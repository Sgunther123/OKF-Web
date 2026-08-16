from okf_web import evaluator
from okf_web.linter import lint_bundle
from okf_web.model import Concept, load_bundle

_PRODUCT = (
    "---\n"
    "type: Product\n"
    "title: Widget\n"
    "description: A widget.\n"
    "tags: [w]\n"
    "status: stable\n"
    "resource: https://shop.example/p/widget\n"
    "x_geo:\n"
    "  risk: b\n"
    "  entity: sku:WIDGET-1\n"
    "---\n\nA widget.\n"
)

_COMPAT = (
    "---\n"
    "type: Compatibility\n"
    "title: Widget Fit Chart\n"
    "description: Which widget fits what.\n"
    "tags: [fit]\n"
    "status: {status}\n"
    "x_geo:\n"
    "  risk: {risk}\n"
    "{refs}"
    "---\n\nSize chart.\n"
)


def _bundle(tmp_path, status="stable", risk="b", refs="  fits: [sku:WIDGET-1]\n"):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "widget.md").write_text(_PRODUCT)
    (root / "fit.md").write_text(_COMPAT.format(status=status, risk=risk, refs=refs))
    return root


# --- model accessors --------------------------------------------------------

def test_fit_accessors_and_entity_map(tmp_path):
    bundle = load_bundle(_bundle(tmp_path, refs="  fits: [sku:WIDGET-1]\n  works_with: [sku:WIDGET-1]\n"))
    fit = bundle.concepts["fit.md"]
    assert fit.fits == ["sku:WIDGET-1"]
    assert fit.works_with == ["sku:WIDGET-1"]
    assert bundle.concepts["widget.md"].entity == "sku:WIDGET-1"
    assert bundle.entities() == {"sku:WIDGET-1": "widget.md"}


def test_accessors_tolerate_missing_keys():
    concept = Concept("x.md", {"type": "Compatibility"}, "")
    assert concept.fits == [] and concept.works_with == [] and concept.entity is None


# --- lint gates -------------------------------------------------------------

def test_stable_compatibility_without_refs_is_error(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, refs=""))
    assert any(f.code == "E015" for f in findings)


def test_draft_compatibility_without_refs_warns_only(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, status="draft", refs=""))
    assert not any(f.code == "E015" for f in findings)
    assert any(f.code == "W032" for f in findings)


def test_unresolved_entity_reference_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, refs="  fits: [sku:GHOST-9]\n"))
    hits = [f for f in findings if f.code == "W032"]
    assert hits and "sku:GHOST-9" in hits[0].message


def test_risk_c_compatibility_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, risk="c"))
    assert any(f.code == "W033" for f in findings)


def test_resolving_risk_b_compatibility_is_clean(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path))
    assert findings == []


# --- example bundle + retrieval --------------------------------------------

def test_example_fit_concept_resolves_and_retrieves(example_bundle):
    bundle = load_bundle(example_bundle)
    fit = bundle.concepts["compatibility/fit-and-pairing.md"]
    entities = bundle.entities()
    for ref in fit.fits + fit.works_with:
        assert ref in entities

    hits = evaluator.retrieve(
        bundle, "I'm 6 foot 4 — which length of your sleeping bag do I need?", 4
    )
    assert "compatibility/fit-and-pairing.md" in [c.rel_path for c in hits]


def test_fit_compatibility_is_an_archetype():
    assert "fit_compatibility" in evaluator.ARCHETYPES
    assert len(evaluator.ARCHETYPES) == 11
