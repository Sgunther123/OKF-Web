import datetime as dt
import json

from okf_web import drift
from okf_web.model import load_bundle
from okf_web.publisher import publish, published_view, select_publishable
from okf_web.surveyor import stable_page_hash

TODAY = dt.date(2026, 8, 5)
FUTURE = dt.date(2027, 6, 1)  # past every stale_after in the example bundle
SITE = "https://www.alpinepeakoutfitters.example"

_STALE_FAQ = (
    "---\n"
    "type: FAQ\n"
    "title: Old FAQ\n"
    "description: A stale low-risk concept.\n"
    "tags: [faq]\n"
    "status: stable\n"
    "stale_after: 2026-01-01\n"
    "x_geo:\n"
    "  risk: c\n"
    "---\n\nOld answers.\n"
)


def _write_stale(root):
    (root / "faq" / "old.md").write_text(_STALE_FAQ)
    return "faq/old.md"


# --- freshness publish policy ----------------------------------------------

def test_default_publish_ships_stale_with_warning(bundle_copy, tmp_path):
    rel = _write_stale(bundle_copy)
    result = publish(bundle_copy, tmp_path / "dist", today=TODAY)
    assert rel in result.published
    assert any(rel in w and "stale_after" in w for w in result.warnings)


def test_withhold_retires_stale_concepts(bundle_copy, tmp_path):
    rel = _write_stale(bundle_copy)
    result = publish(bundle_copy, tmp_path / "dist", freshness="withhold", today=TODAY)
    assert rel in result.withheld
    assert not (tmp_path / "dist" / rel).exists()
    # And no warning for it — withheld, not shipped-stale.
    assert not any(rel in w for w in result.warnings)


def test_withhold_is_clock_dependent_and_view_mirrors_it(example_bundle):
    bundle = load_bundle(example_bundle)
    fresh_include, _ = select_publishable(bundle, today=TODAY, freshness="withhold")
    assert "policies/returns.md" in fresh_include

    _, stale_withheld = select_publishable(bundle, today=FUTURE, freshness="withhold")
    assert "policies/returns.md" in stale_withheld
    view = published_view(bundle, today=FUTURE, freshness="withhold")
    assert "policies/returns.md" not in view.concepts
    # Default policy at the same clock still ships (warn is publish-side).
    default_view = published_view(bundle, today=FUTURE)
    assert "policies/returns.md" in default_view.concepts


# --- discovery / delegation -------------------------------------------------

def test_publish_records_site_binding(example_bundle, tmp_path):
    result = publish(example_bundle, tmp_path / "dist", site=SITE)
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    assert manifest["site"] == SITE
    assert manifest["bundle_url"] == SITE + "/.well-known/okf"

    snippet = (tmp_path / "dist" / "llms-snippet.txt").read_text()
    assert f'<link rel="okf-bundle" href="{SITE}/.well-known/okf/">' in snippet

    linkmap = json.loads((tmp_path / "dist" / "linkmap.json").read_text())
    assert linkmap and all(v.startswith(SITE) for v in linkmap.values())
    # Example bundle resources are all on the store origin: no warnings.
    assert not any("origin" in w for w in result.warnings)


def test_publish_delegated_bundle_url(example_bundle, tmp_path):
    cdn = "https://cdn.example.net/apo-okf"
    publish(example_bundle, tmp_path / "dist", site=SITE, bundle_url=cdn)
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    assert manifest["site"] == SITE
    assert manifest["bundle_url"] == cdn

    snippet = (tmp_path / "dist" / "llms-snippet.txt").read_text()
    assert f'<link rel="okf-bundle" href="{cdn}/">' in snippet

    linkmap = json.loads((tmp_path / "dist" / "linkmap.json").read_text())
    assert all(v.startswith(cdn + "/") for v in linkmap.values())


def test_publish_without_site_stays_relative(example_bundle, tmp_path):
    publish(example_bundle, tmp_path / "dist")
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    assert "site" not in manifest and "bundle_url" not in manifest
    linkmap = json.loads((tmp_path / "dist" / "linkmap.json").read_text())
    assert all(v.startswith("/.well-known/okf/") for v in linkmap.values())


def test_off_origin_resource_warns(bundle_copy, tmp_path):
    (bundle_copy / "faq" / "offsite.md").write_text(
        "---\n"
        "type: FAQ\n"
        "title: Offsite FAQ\n"
        "description: Cites a page on some other origin.\n"
        "tags: [faq]\n"
        "status: stable\n"
        "stale_after: 2027-12-31\n"
        "resource: https://other-host.example/page\n"
        "x_geo:\n"
        "  risk: c\n"
        "---\n\nAnswers.\n"
    )
    result = publish(bundle_copy, tmp_path / "dist", site=SITE)
    assert any(
        "faq/offsite.md" in w and "not on the declared site origin" in w
        for w in result.warnings
    )


# --- drift ------------------------------------------------------------------

_PAGE = "Alpine 2 Tent\nPacked weight 1.9 kg\n"


def _concept(resource=None, source_hash=None):
    lines = [
        "---",
        "type: Product",
        "title: Alpine 2 Tent",
        "description: A tent.",
        "tags: [tent]",
        "status: draft",
    ]
    if resource:
        lines.append(f"resource: {resource}")
    lines += ["x_geo:", "  risk: b"]
    if source_hash:
        lines.append(f"  source_hash: {source_hash}")
    lines += ["---", "", "A two-person tent.", ""]
    return "\n".join(lines)


def _mini_bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "catalog").mkdir(parents=True)
    url = "https://shop.example/p/alpine"
    good = stable_page_hash(_PAGE)
    (root / "catalog" / "a.md").write_text(_concept(url, good))
    (root / "catalog" / "b.md").write_text(_concept(url, good))  # same page
    (root / "catalog" / "hand-authored.md").write_text(_concept())
    return root, url


def test_drift_unchanged_and_fetch_deduped(tmp_path):
    root, url = _mini_bundle(tmp_path)
    calls = []

    def fake(u):
        calls.append(u)
        return _PAGE

    report = drift.check_bundle(root, fetch_text=fake)
    assert sorted(report.unchanged) == ["catalog/a.md", "catalog/b.md"]
    assert report.skipped == ["catalog/hand-authored.md"]
    assert report.clean
    assert calls == [url]  # one fetch for two concepts


def test_drift_detects_changed_page(tmp_path):
    root, url = _mini_bundle(tmp_path)
    report = drift.check_bundle(root, fetch_text=lambda u: _PAGE + "Now 30% lighter!\n")
    assert [rel for rel, _ in report.drifted] == ["catalog/a.md", "catalog/b.md"]
    assert not report.clean


def test_drift_volatile_chrome_does_not_trip(tmp_path):
    root, url = _mini_bundle(tmp_path)
    report = drift.check_bundle(
        root, fetch_text=lambda u: _PAGE + "Cart (3 items)\n© 2027 Shop\n"
    )
    assert report.clean  # volatile lines are excluded from the stable hash


def test_drift_unreachable(tmp_path):
    root, url = _mini_bundle(tmp_path)

    def fake(u):
        raise OSError("boom")

    report = drift.check_bundle(root, fetch_text=fake)
    assert [rel for rel, _ in report.unreachable] == ["catalog/a.md", "catalog/b.md"]
    assert not report.clean


def test_cli_drift_exit_codes(tmp_path, monkeypatch):
    from okf_web import cli as cli_mod

    root, url = _mini_bundle(tmp_path)
    monkeypatch.setattr(drift, "_fetch_page_text", lambda u, timeout=30.0: _PAGE)
    assert cli_mod.main(["drift", str(root)]) == 0
    monkeypatch.setattr(drift, "_fetch_page_text", lambda u, timeout=30.0: "changed")
    assert cli_mod.main(["drift", str(root)]) == 1
