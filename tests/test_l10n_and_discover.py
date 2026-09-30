import json

from okf_web import cli as cli_mod
from okf_web import discover as discover_mod
from okf_web.evaluator import retrieve
from okf_web.linter import lint_bundle
from okf_web.model import concept_content_hash, load_bundle, localized_view

_EN = (
    "---\n"
    "type: FAQ\n"
    "title: Shipping FAQ\n"
    "description: Shipping answers.\n"
    "tags: [faq]\n"
    "status: stable\n"
    "x_geo:\n"
    "  risk: b\n"
    "---\n\nWe ship worldwide by courier.\n"
)

_ES = (
    "---\n"
    "type: FAQ\n"
    "title: Preguntas de envío\n"
    "description: Respuestas de envío.\n"
    "tags: [faq]\n"
    "status: stable\n"
    "x_geo:\n"
    "  risk: b\n"
    "{pin}"
    "---\n\nEnviamos a todo el mundo por mensajería.\n"
)


def _mini(tmp_path, pin=True, orphan=False):
    root = tmp_path / "bundle"
    (root / "faq").mkdir(parents=True)
    (root / "faq" / "shipping.md").write_text(_EN)
    bundle = load_bundle(root)
    pin_line = (
        f"  l10n_source_hash: {concept_content_hash(bundle.concepts['faq/shipping.md'])}\n"
        if pin
        else ""
    )
    target = "faq/orphan.md" if orphan else "faq/shipping.md"
    es = root / "l10n" / "es" / target
    es.parent.mkdir(parents=True, exist_ok=True)
    es.write_text(_ES.format(pin=pin_line))
    return root


# --- localized view ---------------------------------------------------------

def test_localized_view_overlays_and_drops_other_langs(tmp_path):
    root = _mini(tmp_path)
    fr = root / "l10n" / "fr" / "faq" / "shipping.md"
    fr.parent.mkdir(parents=True)
    fr.write_text(_ES.format(pin=""))

    bundle = load_bundle(root)
    assert set(bundle.concepts) == {
        "faq/shipping.md", "l10n/es/faq/shipping.md", "l10n/fr/faq/shipping.md",
    }
    view = localized_view(bundle, "es")
    assert set(view.concepts) == {"faq/shipping.md"}
    assert view.concepts["faq/shipping.md"].title == "Preguntas de envío"
    # A language with no translations falls back to the default entirely.
    view_de = localized_view(bundle, "de")
    assert view_de.concepts["faq/shipping.md"].title == "Shipping FAQ"


def test_retrieval_excludes_l10n_but_localized_view_uses_it(tmp_path):
    root = _mini(tmp_path)
    bundle = load_bundle(root)
    hits = retrieve(bundle, "mensajería envío mundo", top_k=4)
    assert all(not c.rel_path.startswith("l10n/") for c in hits)

    view = localized_view(bundle, "es")
    hits = retrieve(view, "mensajería envío mundo", top_k=4)
    assert [c.title for c in hits] == ["Preguntas de envío"]


# --- lint parity ------------------------------------------------------------

def test_lint_translation_clean_when_pinned(tmp_path):
    _, findings = lint_bundle(_mini(tmp_path))
    assert not [f for f in findings if f.code in ("W030", "W031")]


def test_lint_orphan_translation(tmp_path):
    _, findings = lint_bundle(_mini(tmp_path, orphan=True))
    assert any(f.code == "W030" for f in findings)


def test_lint_unpinned_and_outdated_translation(tmp_path):
    root = _mini(tmp_path, pin=False)
    _, findings = lint_bundle(root)
    assert any(f.code == "W031" and "not pinned" in f.message for f in findings)

    root2 = _mini(tmp_path / "second")
    (root2 / "faq" / "shipping.md").write_text(_EN.replace("courier", "drone"))
    _, findings = lint_bundle(root2)
    assert any(f.code == "W031" and "out of date" in f.message for f in findings)


def test_example_bundle_spanish_view_cli(example_bundle):
    assert cli_mod.main(
        ["evaluate", str(example_bundle), "--dry-run", "--lang", "es"]
    ) == 0
    view = localized_view(load_bundle(example_bundle), "es")
    assert view.concepts["faq/general.md"].title == "Preguntas frecuentes"


# --- discover ---------------------------------------------------------------

STORE = "https://shop.example"
CDN = "https://cdn.host.example/shop-okf"


def _manifest(site=None):
    manifest = {"okf_version": "0.2", "profile": "ecommerce-geo/1.11",
                "files": {"index.md": {"sha256": "x", "bytes": 1}}}
    if site:
        manifest["site"] = site
    return json.dumps(manifest)


def _fake_fetch(pages):
    def fetch(url):
        if url in pages:
            return pages[url]
        raise OSError(f"no route to {url}")
    return fetch


def test_discover_same_origin_well_known():
    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        f"{STORE}/.well-known/okf/manifest.json": (200, _manifest(site=STORE)),
        STORE: (200, "<html><head></head></html>"),
    }))
    assert report.routes == ["well-known"]
    assert report.binding == "same-origin"
    assert report.ok and report.files == 1 and not report.signed


def test_discover_delegated_bound():
    html = f'<html><head><link rel="okf-bundle" href="{CDN}/"></head></html>'
    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        STORE: (200, html),
        f"{CDN}/manifest.json": (200, _manifest(site=STORE)),
        f"{CDN}/manifest.json.sigstore.json": (200, "{}"),
    }))
    assert report.routes == ["link-tag"]
    assert report.bundle_url == CDN
    assert report.binding == "bound"
    assert report.signed
    assert report.ok


def test_discover_delegated_mismatch_and_missing_site():
    html = f'<html><head><link rel="okf-bundle" href="{CDN}/"></head></html>'
    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        STORE: (200, html),
        f"{CDN}/manifest.json": (200, _manifest(site="https://other.example")),
    }))
    assert report.binding == "mismatch" and not report.ok
    assert any("does not speak for this store" in p for p in report.problems)

    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        STORE: (200, html),
        f"{CDN}/manifest.json": (200, _manifest()),
    }))
    assert report.binding == "missing" and not report.ok


def test_discover_nothing_found():
    report = discover_mod.discover(STORE, fetch=_fake_fetch({}))
    assert not report.ok and report.binding == "none"
    assert any("no bundle found" in p for p in report.problems)
    assert any("could not be fetched" in p for p in report.problems)

    # What the well-known location answered is in the line: a challenge
    # page is told apart from an absent bundle, and a pointer at an HTML
    # fallback from a pointer at nothing.
    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        f"{STORE}/.well-known/okf/manifest.json": (403, "<html>challenge</html>"),
        STORE: (200, "<html><head></head></html>"),
    }))
    (problem,) = report.problems
    assert "answered HTTP 403" in problem and "bot gate" in problem
    html = f'<html><head><link rel="okf-bundle" href="{CDN}/"></head></html>'
    report = discover_mod.discover(STORE, fetch=_fake_fetch({
        f"{STORE}/.well-known/okf/manifest.json": (404, "not here"),
        STORE: (200, html),
        f"{CDN}/manifest.json": (200, "<html>app shell</html>"),
    }))
    assert any("something other than JSON" in p for p in report.problems)
    assert any("answered HTTP 404" in p for p in report.problems)


def test_discover_cli_exit_codes(monkeypatch):
    def _with_timeout(pages):
        fetch = _fake_fetch(pages)
        return lambda url, timeout=15.0: fetch(url)

    monkeypatch.setattr(
        discover_mod, "_fetch",
        _with_timeout({
            f"{STORE}/.well-known/okf/manifest.json": (200, _manifest(site=STORE)),
            STORE: (200, "<html></html>"),
        }),
    )
    assert cli_mod.main(["discover", STORE]) == 0
    monkeypatch.setattr(discover_mod, "_fetch", _with_timeout({}))
    assert cli_mod.main(["discover", STORE]) == 1
