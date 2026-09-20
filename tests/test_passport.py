from okf_web import evaluator, review
from okf_web.linter import lint_bundle
from okf_web.model import Concept, load_bundle
from okf_web.publisher import publish, select_publishable

_PRODUCT = (
    "---\n"
    "type: Product\n"
    "title: Widget\n"
    "description: A widget.\n"
    "tags: [w]\n"
    "status: stable\n"
    "stale_after: 2030-01-01T00:00:00Z\n"
    "resource: https://shop.example/p/widget\n"
    "x_geo:\n"
    "  risk: b\n"
    "  entity: sku:WIDGET-1\n"
    "---\n\nA widget.\n"
)

_PASSPORT = (
    "---\n"
    "type: Product Passport\n"
    "title: Widget Passport\n"
    "description: Materials and origin for the widget.\n"
    "tags: [passport]\n"
    "status: {status}\n"
    "stale_after: 2030-01-01T00:00:00Z\n"
    "{verified}"
    "{sources}"
    "x_geo:\n"
    "  risk: {risk}\n"
    "{binding}"
    "{passport}"
    "---\n\n{body}"
)

_HUMAN = "verified:\n  - by: human:compliance@shop.example\n    at: 2026-08-16T10:00:00Z\n"
_SOURCES = (
    "sources:\n"
    "  - id: decl\n"
    "    resource: https://shop.example/certs/widget.pdf\n"
    "    title: Declaration\n"
)
_FULL_PASSPORT = (
    "  passport:\n"
    "    materials: [\"100% recycled steel\"]\n"
    "    origin: DE\n"
)
_BODY = "Made of recycled steel.[^decl]\n\n[^decl]: Declaration.\n"


def _bundle(tmp_path, status="stable", risk="a", binding="  passport_for: sku:WIDGET-1\n",
            passport=_FULL_PASSPORT, verified=_HUMAN, sources=_SOURCES, body=_BODY):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "widget.md").write_text(_PRODUCT)
    (root / "passport.md").write_text(_PASSPORT.format(
        status=status, risk=risk, binding=binding, passport=passport,
        verified=verified, sources=sources, body=body,
    ))
    return root


# --- model ------------------------------------------------------------------

def test_passport_accessors_and_effective_risk():
    concept = Concept(
        "p.md",
        {"type": "Product Passport",
         "x_geo": {"risk": "b", "passport_for": "sku:A",
                   "passport": {"materials": ["steel"], "origin": "DE"}}},
        "",
    )
    assert concept.passport_for == "sku:A"
    assert concept.passport["origin"] == "DE"
    assert concept.risk == "b"          # declared
    assert concept.is_high_risk         # effective: passports always gate as a
    assert "sku:A" in concept.entity_refs

    plain = Concept("x.md", {"type": "FAQ", "x_geo": {"risk": "b"}}, "")
    assert not plain.is_high_risk


# --- lint gates -------------------------------------------------------------

def test_clean_passport_lints_clean(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path))
    assert findings == []


def test_stable_passport_missing_contract_is_error(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, binding="", passport=""))
    e017 = [f for f in findings if f.code == "E017"]
    assert e017 and "passport_for" in e017[0].message
    assert "materials" in e017[0].message


def test_draft_passport_missing_contract_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, status="draft", passport="", verified=""))
    assert not any(f.code == "E017" for f in findings)
    assert any(f.code == "W032" and "Passport draft" in f.message for f in findings)


def test_declared_low_risk_cannot_dodge_the_gates(tmp_path):
    # risk: b declared, stable, no human verifier → E010 fires anyway,
    # E013 fires without sources, and W033 flags the declaration.
    _, findings = lint_bundle(
        _bundle(tmp_path, risk="b", verified="", sources="", body="Steel.\n")
    )
    codes = {f.code for f in findings}
    assert "E010" in codes
    assert "E013" in codes
    assert any(f.code == "W033" and "declares risk `b`" in f.message for f in findings)


def test_unresolved_passport_for_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, binding="  passport_for: sku:GHOST\n"))
    assert any(f.code == "W032" and "sku:GHOST" in f.message for f in findings)


# --- publisher and batch-approve loopholes ----------------------------------

def test_draft_passport_declaring_b_never_ships_machine_confirmed(tmp_path):
    root = _bundle(tmp_path, status="draft", risk="b", verified="")
    bundle = load_bundle(root)
    include, withheld = select_publishable(bundle, include_machine_confirmed=True)
    assert "passport.md" in withheld
    assert "passport.md" not in include


def test_batch_approve_skips_passports_whatever_they_declare(tmp_path):
    root = _bundle(tmp_path, status="draft", risk="b", verified="")
    bundle = load_bundle(root)
    approved = review.batch_approve(bundle, "ops@shop.example")
    assert approved == []
    assert load_bundle(root).concepts["passport.md"].status == "draft"


# --- example bundle ---------------------------------------------------------

def test_example_passport_resolves_and_retrieves(example_bundle):
    bundle = load_bundle(example_bundle)
    passport = bundle.concepts["passports/ridgeline-20.md"]
    assert passport.passport_for == "sku:APO-BAG-R20"
    assert passport.passport_for in bundle.entities()
    assert passport.risk == "a" and passport.is_high_risk
    assert passport.passport["certifications"][0]["issuer"] == "Control Union"

    hits = evaluator.retrieve(
        bundle, "Is the down in your sleeping bags responsibly sourced — can you prove it?", 4
    )
    assert "passports/ridgeline-20.md" in [c.rel_path for c in hits]


def test_compliance_is_an_archetype():
    assert "compliance" in evaluator.ARCHETYPES
    assert len(evaluator.ARCHETYPES) == 13
