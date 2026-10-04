"""EDGE-CASES phase E5: automation hygiene.

Covers A4 (one bad page aborts a survey; an HTML sitemap reads as "no
inputs"), A5 (local dates against UTC stamps), A6 (nothing is atomic and
nothing locks) and A7 (CI blind spots), plus the absolute MCP path
`init` prints.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import time
from email.message import Message
from pathlib import Path

import pytest

import okf_web
from okf_web import cli as cli_mod
from okf_web import model, review, surveyor
from okf_web.llm import StaticClient
from okf_web.model import BundleLocked, bundle_lock, load_bundle, write_atomic
from okf_web.net import FetchResult

REPO = Path(__file__).resolve().parent.parent


def _faq_block(rel: str, body: str = "# Q\n\nA.[^faq]\n\n[^faq]: FAQ page.\n") -> str:
    return (
        f'<<<CONCEPT path="{rel}">>>\n---\ntype: FAQ\ntitle: FAQ\ndescription: Answers.\n'
        "resource: https://shop.example/faq\ntags: [faq]\n"
        "sources:\n  - id: faq\n    resource: https://shop.example/faq\n    title: FAQ page\n"
        "x_geo:\n  profile: ecommerce-geo/1.12\n  risk: b\n  intents: [trust]\n---\n\n"
        f"{body}<<<END>>>\n"
    )


# --- A4: one bad page never aborts the run ---------------------------------------------

def test_a_page_raising_a_non_os_error_is_recorded_and_the_rest_proceed(tmp_path):
    def fetcher(url: str) -> str:
        if url.endswith("/bad"):
            raise LookupError("unknown encoding: bogus")
        return "page text"

    llm = StaticClient([_faq_block("faq/good.md")])
    result = surveyor.survey(
        ["https://shop.example/bad", "https://shop.example/good"], tmp_path / "b", llm, fetcher=fetcher
    )
    assert result.errors == ["https://shop.example/bad: fetch failed: unknown encoding: bogus"]
    assert result.written == ["faq/good.md"]


def test_a_bogus_charset_falls_back_to_utf8():
    headers = Message()
    headers["Content-Type"] = "text/html; charset=bogus-9"
    result = FetchResult(url="https://shop.example/", status=200, headers=headers, body="café".encode("utf-8"))
    assert result.text == "café"


def test_an_html_sitemap_is_named_not_reported_as_no_inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(surveyor, "fetch", lambda url, **kwargs: "<!doctype html><html><body>app</body></html>")
    with pytest.raises(surveyor.SitemapError, match="sitemap unparseable: https://shop.example/sitemap.xml"):
        surveyor.discover_sitemap("https://shop.example")
    assert cli_mod.main(["survey", str(tmp_path / "b"), "--sitemap", "https://shop.example"]) == 2
    err = capsys.readouterr().err
    assert "sitemap unparseable" in err and "no inputs" not in err

    monkeypatch.setattr(surveyor, "fetch", lambda url, **kwargs: '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>')
    with pytest.raises(surveyor.SitemapError, match="sitemap empty"):
        surveyor.discover_sitemap("https://shop.example")


# --- A5: every clock is UTC -----------------------------------------------------------------

def test_staleness_uses_the_utc_instant_not_the_local_date(tmp_path, monkeypatch):
    concept = model.Concept("faq/a.md", {"type": "FAQ", "stale_after": "2026-09-16T00:00:00Z"}, "body")
    monkeypatch.setattr(model, "utc_now", lambda: _dt.datetime(2026, 9, 15, 23, 30, tzinfo=_dt.timezone.utc))
    assert concept.is_stale() is False
    monkeypatch.setattr(model, "utc_now", lambda: _dt.datetime(2026, 9, 16, 0, 0, tzinfo=_dt.timezone.utc))
    assert concept.is_stale() is True
    # An explicit date clock keeps the documented date-granular reading.
    assert concept.is_stale(_dt.date(2026, 9, 16)) is True
    assert concept.is_stale(_dt.date(2026, 9, 15)) is False


def test_the_log_day_is_the_utc_date_whatever_the_host_zone(tmp_path, monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("tzset is POSIX-only")
    monkeypatch.setenv("TZ", "Etc/GMT-14")  # UTC+14: the host's calendar runs ahead of UTC
    time.tzset()
    try:
        assert model.utc_today() == _dt.datetime.now(_dt.timezone.utc).date()
        root = tmp_path / "b"
        root.mkdir()
        review.append_log(root, "**Verify**: something")
        heading = re.search(r"^## (\d{4}-\d{2}-\d{2})$", (root / "log.md").read_text(encoding="utf-8"), re.M)
        assert heading and heading.group(1) == model.utc_today().isoformat()
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


# --- A6: atomic writes, the lock, unique quarantine names -----------------------------------

def test_a_failed_write_leaves_the_original_intact(tmp_path, monkeypatch):
    target = tmp_path / "policy.md"
    target.write_text("---\ntype: Policy\n---\n\noriginal\n", encoding="utf-8")

    def half_then_fail(path, data):
        with open(path, "wb") as fh:
            fh.write(data[: len(data) // 2])
        raise OSError("disk full")

    monkeypatch.setattr(model, "_write_bytes", half_then_fail)
    with pytest.raises(OSError, match="disk full"):
        write_atomic(target, "---\ntype: Policy\n---\n\nreplacement that never lands\n")
    assert target.read_text(encoding="utf-8").endswith("original\n")
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]  # no temp file left behind


def test_concept_save_is_atomic_and_leaves_no_temp_files(bundle_copy):
    concept = load_bundle(bundle_copy).get("policies/shipping.md")
    concept.frontmatter["description"] = "Rewritten."
    concept.save()
    assert load_bundle(bundle_copy).get("policies/shipping.md").frontmatter["description"] == "Rewritten."
    assert not list((bundle_copy / "policies").glob(".*.tmp"))


def test_the_bundle_lock_refuses_a_second_mutating_run(bundle_copy, capsys):
    with bundle_lock(bundle_copy) as lock:
        assert lock.exists()
        with pytest.raises(BundleLocked, match="locked by process"):
            with bundle_lock(bundle_copy):
                pass
        code = cli_mod.main(["review", "approve", str(bundle_copy), "policies/warranty.md", "--by", "x@shop.example"])
        assert code == 2 and "is locked by process" in capsys.readouterr().err
        # Read-only commands are not held up by the lock.
        assert cli_mod.main(["review", "list", str(bundle_copy)]) == 0
    assert not lock.exists()
    assert load_bundle(bundle_copy).get("policies/warranty.md").status == "draft"


def test_a_stale_lock_from_a_dead_process_is_taken_over(bundle_copy):
    (bundle_copy / model.LOCK_NAME).write_text("999999999 2026-09-16T00:00:00Z\n", encoding="utf-8")
    with bundle_lock(bundle_copy) as lock:
        assert lock.read_text(encoding="utf-8").startswith(str(os.getpid()))
    assert not lock.exists()


def test_a_refused_survey_leaves_no_bundle_directory_behind(tmp_path, capsys):
    root = tmp_path / "fresh"
    assert cli_mod.main(["survey", str(root), "--urls", str(tmp_path / "missing.txt")]) == 2
    assert "missing.txt" in capsys.readouterr().err
    assert not root.exists()
    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / "note.txt").write_text("mine", encoding="utf-8")
    assert cli_mod.main(["survey", str(keep), "--urls", str(tmp_path / "missing.txt")]) == 2
    assert (keep / "note.txt").exists() and not (keep / ".okf-lock").exists()


def test_the_lock_never_creates_a_bundle_for_commands_that_expect_one(tmp_path, capsys):
    missing = tmp_path / "typo"
    assert cli_mod.main(["review", "approve", str(missing), "x.md", "--by", "a@b"]) == 2
    assert not missing.exists() and "bundle directory not found" in capsys.readouterr().err


def test_two_bad_blocks_in_one_second_are_two_quarantine_files(tmp_path):
    root = tmp_path / "b"
    response = _faq_block("../one.md", "# One\n\nx.[^faq]\n\n[^faq]: FAQ page.\n") + _faq_block("../two.md", "# Two\n\ny.[^faq]\n\n[^faq]: FAQ page.\n")
    result = surveyor.SurveyResult()
    root.mkdir()
    surveyor.survey_page("https://shop.example/p", "text", root, StaticClient([response]), result)
    files = sorted((root / "_quarantine").glob("*.txt"))
    assert len(result.quarantined) == 2 and len(files) == 2
    # Identical payloads twice in one second still get two files.
    surveyor._quarantine(root, "https://shop.example/p", "same", "dup")
    surveyor._quarantine(root, "https://shop.example/p", "same", "dup")
    assert len(list((root / "_quarantine").glob("*.txt"))) == 4


# --- A7: CI blind spots -----------------------------------------------------------------------

def test_package_version_matches_pyproject():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert okf_web.__version__ == declared


def test_ci_tests_every_supported_python_and_keeps_the_required_check_name():
    workflow = (REPO / ".github" / "workflows" / "okf-ci.yml").read_text(encoding="utf-8")
    assert '"3.10"' in workflow and '"3.12"' in workflow
    assert "\n  test-and-lint:\n" in workflow and "needs: tests" in workflow
    release = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "okf_web.__version__" in release


# --- init prints a path a desktop client can use --------------------------------------------

def test_init_prints_an_absolute_mcp_path(tmp_path, monkeypatch, capsys):
    feed = tmp_path / "products.csv"
    feed.write_text(
        "id,title,description,link\nSKU-1,Trail Stove,A stove.,https://shop.example/p/stove\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert cli_mod.main(["init", "store", "--feed", "products.csv", "--dist", "dist"]) == 0
    out = capsys.readouterr().out
    assert f'"args": ["mcp", "{(tmp_path / "store").resolve()}"]' in out
