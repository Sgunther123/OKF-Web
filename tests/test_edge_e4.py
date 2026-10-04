"""EDGE-CASES phase E4: operator clarity.

Covers U3 (`questions --llm` overwrites a curated pack), U4
(`batch-approve` approves rejected drafts and ignores `--risk`), U5
(approving a stale concept, approving twice), U6 (feed importer edge
cases), U7 (common mistakes end in tracebacks), U9 (a misspelled
`status`), A2 (warnings on stdout, drift's exit code) and A3 (`evaluate`
cannot fail, a dry run erases a judged scorecard).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from okf_web import cli as cli_mod
from okf_web import drift, evaluator, feed, linter, publisher, review
from okf_web.drift import DriftReport
from okf_web.llm import StaticClient
from okf_web.model import load_bundle
from okf_web.net import FetchError

CSV = (
    "id,title,description,link,brand,gtin,product_type,price,availability\n"
    "SKU-1,Trail Stove,A compact canister stove. Boils fast.,"
    "https://shop.example/p/trail-stove,Alpine Peak,00012345600012,"
    "Camping > Cooking,49.99 USD,in_stock\n"
    "SKU-2,Titanium Pot,A 750 ml titanium pot with lid.,"
    "https://shop.example/p/titanium-pot,Alpine Peak,,Camping > Cooking,"
    "34.99 USD,out_of_stock\n"
)


def _faq(bundle_dir: Path, rel: str, *, status="draft", risk="b", stale_after=None,
         resource="https://shop.example/faq", extra_fm="") -> Path:
    path = bundle_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = f"stale_after: {stale_after}\n" if stale_after else ""
    path.write_text(
        "---\ntype: FAQ\ntitle: FAQ\ndescription: Answers.\n"
        f"resource: {resource}\nstatus: {status}\n{stale}tags: [faq]\n"
        f"sources:\n  - id: faq\n    resource: {resource}\n    title: FAQ page\n"
        f"x_geo:\n  profile: ecommerce-geo/1.12\n  risk: {risk}\n  intents: [trust]\n{extra_fm}"
        "---\n\n# Q\n\nA.[^faq]\n\n[^faq]: FAQ page.\n",
        encoding="utf-8",
    )
    return path


# --- U3: questions --------------------------------------------------------------

def test_questions_llm_refuses_to_overwrite_and_never_writes_an_empty_pack(bundle_copy, monkeypatch, capsys):
    pack = bundle_copy / "evaluations" / "questions.yaml"
    before = pack.read_bytes()
    assert cli_mod.main(["questions", str(bundle_copy), "--llm", "claude-code"]) == 2
    assert "--force" in capsys.readouterr().err
    assert pack.read_bytes() == before

    monkeypatch.setattr(cli_mod, "_llm", lambda args, model=None: StaticClient(["Sure! Here are some questions in prose."]))
    assert cli_mod.main(["questions", str(bundle_copy), "--llm", "claude-code", "--force"]) == 1
    assert "no parsable questions" in capsys.readouterr().err
    assert pack.read_bytes() == before


# --- U4: batch-approve -----------------------------------------------------------

def test_batch_approve_skips_rejected_drafts_and_honours_risk(tmp_path, capsys):
    root = tmp_path / "bundle"
    _faq(root, "faq/a.md", risk="b")
    _faq(root, "faq/b.md", risk="b", resource="https://shop.example/b")
    _faq(root, "faq/c.md", risk="c", resource="https://shop.example/c")
    review.reject(load_bundle(root), "faq/a.md", "bob@shop.example", "wrong currency")

    candidates, skipped = review.batch_candidates(load_bundle(root))
    assert [c.rel_path for c in candidates] == ["faq/b.md", "faq/c.md"]
    assert [(c.rel_path, why) for c, why in skipped] == [
        ("faq/a.md", "rejected by human:bob@shop.example: wrong currency")
    ]

    # --dry-run writes nothing.
    assert cli_mod.main(["review", "batch-approve", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "skipped faq/a.md: rejected by" in out and "would approve faq/b.md" in out
    assert load_bundle(root).get("faq/b.md").status == "draft"

    # --risk c leaves the risk-b draft alone; the rejected one stays rejected.
    assert cli_mod.main(["review", "batch-approve", str(root), "--by", "ops@shop.example", "--risk", "c"]) == 0
    bundle = load_bundle(root)
    assert bundle.get("faq/c.md").status == "stable" and bundle.get("faq/b.md").status == "draft"
    assert bundle.get("faq/a.md").status == "draft"
    assert bundle.get("faq/a.md").x_geo["review"]["reason"] == "wrong currency"

    # risk a is never batchable, and says so instead of raising.
    assert cli_mod.main(["review", "batch-approve", str(root), "--by", "ops@shop.example", "--risk", "a"]) == 2
    assert "cannot be batch-approved" in capsys.readouterr().err


# --- U5: stale approvals and idempotence -------------------------------------------

def test_approving_a_stale_concept_needs_a_new_date_and_clears_the_queue(tmp_path, capsys):
    root = tmp_path / "bundle"
    _faq(root, "faq/a.md", status="stable", stale_after="2020-01-01T00:00:00Z",
         extra_fm="verified:\n  - by: human:ann@shop.example\n    at: 2019-12-01T00:00:00Z\n")
    assert [i.concept.rel_path for i in review.pending(load_bundle(root))] == ["faq/a.md"]

    with pytest.raises(review.ReviewError, match="--stale-after"):
        review.approve(load_bundle(root), "faq/a.md", "ann@shop.example")
    assert cli_mod.main(["review", "approve", str(root), "faq/a.md", "--by", "ann@shop.example"]) == 2
    assert "--stale-after" in capsys.readouterr().err

    next_year = (_dt.date.today() + _dt.timedelta(days=365)).isoformat()
    assert cli_mod.main([
        "review", "approve", str(root), "faq/a.md", "--by", "ann@shop.example",
        "--stale-after", next_year,
    ]) == 0
    concept = load_bundle(root).get("faq/a.md")
    assert concept.frontmatter["stale_after"] == f"{next_year}T00:00:00Z"
    assert not concept.is_stale()
    assert review.pending(load_bundle(root)) == []


def test_approving_twice_records_one_verification(tmp_path, capsys):
    root = tmp_path / "bundle"
    _faq(root, "faq/a.md")
    assert cli_mod.main(["review", "approve", str(root), "faq/a.md", "--by", "ann@shop.example"]) == 0
    assert cli_mod.main(["review", "approve", str(root), "faq/a.md", "--by", "ann@shop.example"]) == 0
    assert "already approved by human:ann@shop.example" in capsys.readouterr().out
    review.approve(load_bundle(root), "faq/a.md", "ann@shop.example")  # library path, same no-op
    concept = load_bundle(root).get("faq/a.md")
    assert len(concept.frontmatter["verified"]) == 1
    assert (root / "log.md").read_text(encoding="utf-8").count("approved by") == 1


# --- U6: the feed importer --------------------------------------------------------------

def test_bom_csv_and_comma_rich_tsv_parse(tmp_path):
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbf" + CSV.encode("utf-8"))
    items = feed.parse_feed(bom)
    assert [i.id for i in items] == ["SKU-1", "SKU-2"]

    tsv = tmp_path / "products.tsv"
    tsv.write_text(
        "id\ttitle\tdescription\tlink\n"
        "SKU-1\tTrail Stove\tCompact, light, fast, quiet, cheap, blue, red, green\thttps://shop.example/p/stove\n",
        encoding="utf-8",
    )
    items = feed.parse_feed(tsv)
    assert items[0].link == "https://shop.example/p/stove" and items[0].title == "Trail Stove"


def test_missing_column_and_empty_feed_fail_once_up_front(tmp_path, capsys):
    renamed = tmp_path / "renamed.csv"
    renamed.write_text(CSV.replace("link", "url"), encoding="utf-8")
    with pytest.raises(feed.FeedError, match="column 'link' not found"):
        feed.parse_feed(renamed)
    assert cli_mod.main(["survey", str(tmp_path / "b"), "--feed", str(renamed)]) == 2
    assert "column 'link' not found" in capsys.readouterr().err

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(feed.FeedError, match="feed is empty"):
        feed.parse_feed(empty)

    assert cli_mod.main(["survey", str(tmp_path / "b"), "--feed", str(tmp_path / "nope.csv")]) == 2
    assert "nope.csv" in capsys.readouterr().err


def test_rows_sharing_one_link_give_one_file_and_a_note(tmp_path):
    shared = tmp_path / "shared.csv"
    shared.write_text(
        CSV + "SKU-3,Trail Stove Red,Same page but the red variant.,"
        "https://shop.example/p/trail-stove,Alpine Peak,,Camping > Cooking,49.99 USD,in_stock\n",
        encoding="utf-8",
    )
    result = feed.ingest_feed(shared, tmp_path / "bundle")
    assert sorted(result.written) == ["catalog/products/titanium-pot.md", "catalog/products/trail-stove.md"]
    assert len(result.collisions) == 1 and "already used by item SKU-1" in result.collisions[0]
    assert load_bundle(tmp_path / "bundle").get("catalog/products/trail-stove.md").title == "Trail Stove"


def test_init_exits_1_when_nothing_was_drafted(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("id,title,link\nSKU-1,,https://shop.example/p/x\n", encoding="utf-8")
    assert cli_mod.main(["init", str(tmp_path / "store"), "--feed", str(bad), "--dist", str(tmp_path / "dist")]) == 1
    assert "nothing was drafted" in capsys.readouterr().err
    assert not (tmp_path / "dist").exists()


# --- U7: common mistakes ------------------------------------------------------------------

def test_review_accepts_tab_completed_paths_and_suggests_close_matches(bundle_copy, capsys):
    prefixed = str(bundle_copy / "policies" / "warranty.md")
    assert cli_mod.main(["review", "approve", str(bundle_copy), prefixed, "--by", "legal@shop.example"]) == 0
    assert load_bundle(bundle_copy).get("policies/warranty.md").status == "stable"
    assert cli_mod.main(["review", "reject", str(bundle_copy), "./policies/shipping.md",
                         "--by", "legal@shop.example", "--reason", "recheck"]) == 0
    assert cli_mod.main(["review", "approve", str(bundle_copy), "policies/warrantee.md", "--by", "x@shop.example"]) == 2
    err = capsys.readouterr().err
    assert "no such concept" in err and "did you mean policies/warranty.md" in err


def test_missing_inputs_and_fetch_failures_are_one_line_errors(tmp_path, monkeypatch, capsys):
    assert cli_mod.main(["survey", str(tmp_path / "b"), "--urls", str(tmp_path / "urls.txt")]) == 2
    assert "urls.txt" in capsys.readouterr().err

    def boom(base, allow_private=False, **kwargs):
        raise FetchError("HTTP 404 for https://shop.example/sitemap.xml")
    monkeypatch.setattr(cli_mod.surveyor, "discover_sitemap", boom)
    assert cli_mod.main(["survey", str(tmp_path / "b"), "--sitemap", "https://shop.example"]) == 2
    assert "HTTP 404" in capsys.readouterr().err

    bad_yaml = tmp_path / "q.yaml"
    bad_yaml.write_text("questions: [\n", encoding="utf-8")
    (tmp_path / "b").mkdir()
    assert cli_mod.main(["evaluate", str(tmp_path / "b"), "--dry-run", "--questions", str(bad_yaml)]) == 2
    assert "invalid YAML" in capsys.readouterr().err


# --- U9: the status enumeration --------------------------------------------------------------

def test_misspelled_status_is_a_lint_error_and_withheld_lines_name_the_status(tmp_path, capsys):
    root = tmp_path / "bundle"
    _faq(root, "faq/a.md", status="Stable")
    _, findings = linter.lint_bundle(root)
    assert any(f.code == "E021" and "'Stable'" in f.message for f in findings)

    root2 = tmp_path / "bundle2"
    _faq(root2, "faq/old.md", status="deprecated")
    _faq(root2, "faq/new.md", status="draft", resource="https://shop.example/new")
    _faq(root2, "faq/live.md", status="stable", resource="https://shop.example/live")
    assert cli_mod.main(["publish", str(root2), str(tmp_path / "dist")]) == 0
    out = capsys.readouterr().out
    assert "faq/old.md: status 'deprecated'" in out
    assert "faq/new.md: draft (low-risk; --include-machine-confirmed would ship it)" in out


# --- A2: warnings and drift's exit codes ---------------------------------------------------

def test_publish_warnings_go_to_stderr_and_can_fail_the_run(bundle_copy, tmp_path, capsys):
    ship = bundle_copy / "policies" / "shipping.md"
    ship.write_text(ship.read_text(encoding="utf-8").replace("status: stable", "status: draft"), encoding="utf-8")
    assert cli_mod.main(["publish", str(bundle_copy), str(tmp_path / "dist")]) == 0
    captured = capsys.readouterr()
    assert "warning:" in captured.err and "warning:" not in captured.out
    assert cli_mod.main(["publish", str(bundle_copy), str(tmp_path / "dist"), "--fail-on-warnings"]) == 1
    assert "--fail-on-warnings is set" in capsys.readouterr().err


def test_drift_distinguishes_unreachable_from_changed(bundle_copy, monkeypatch, capsys):
    # The library report itself says which state it is in.
    report = drift.check_bundle(bundle_copy, fetch_text=lambda url: (_ for _ in ()).throw(FetchError("down")))
    assert report.unreachable and not report.drifted

    reports = {
        "unreachable": DriftReport(unreachable=[("catalog/x.md", "timed out")]),
        "drifted": DriftReport(drifted=[("catalog/x.md", "https://shop.example/x")]),
        "clean": DriftReport(unchanged=["catalog/x.md"]),
    }
    for name, code in (("unreachable", 3), ("drifted", 1), ("clean", 0)):
        monkeypatch.setattr(cli_mod.drift_mod, "check_bundle", lambda *a, _r=reports[name], **k: _r)
        assert cli_mod.main(["drift", str(bundle_copy)]) == code, name
        capsys.readouterr()


# --- A3: evaluate ----------------------------------------------------------------------------

def test_evaluate_validates_the_pack_and_gates_on_the_hit_rate(bundle_copy, tmp_path, capsys):
    empty = tmp_path / "empty.yaml"
    empty.write_text("questions: []\n", encoding="utf-8")
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--questions", str(empty)]) == 2
    assert "question set is empty" in capsys.readouterr().err

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "questions:\n  - id: q1\n    archetype: policy\n    question: Do you ship?\n"
        "  - id: q1\n    archetype: teleport\n    question: Where is the moon base?\n",
        encoding="utf-8",
    )
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--questions", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "duplicate question id 'q1'" in err and "unknown archetype 'teleport'" in err

    miss = tmp_path / "miss.yaml"
    miss.write_text("questions:\n  - id: q1\n    archetype: discovery\n    question: zzzz qqqq xxxx\n", encoding="utf-8")
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--questions", str(miss), "--min-hit-rate", "0.9"]) == 1
    assert "below --min-hit-rate" in capsys.readouterr().err
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--min-hit-rate", "1.0"]) == 0
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--min-coverage", "0.5"]) == 2


def test_dry_run_never_silently_replaces_a_judged_scorecard(bundle_copy, capsys):
    scorecard = bundle_copy / "evaluations" / "geo-scorecard.md"
    before = scorecard.read_bytes()
    assert "coverage" in before.decode("utf-8")
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--write-scorecard"]) == 2
    assert "judged scorecard" in capsys.readouterr().err
    assert scorecard.read_bytes() == before
    assert cli_mod.main(["evaluate", str(bundle_copy), "--dry-run", "--write-scorecard", "--force"]) == 0
    assert scorecard.read_bytes() != before and "coverage" not in scorecard.read_text(encoding="utf-8")
