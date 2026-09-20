from okf_web import evaluator, review
from okf_web.linter import lint_bundle
from okf_web.model import Concept, load_bundle
from okf_web.publisher import select_publishable

_TRADE = (
    "---\n"
    "type: Trade Program\n"
    "title: Wholesale Program\n"
    "description: Trade terms for business buyers.\n"
    "tags: [wholesale]\n"
    "status: {status}\n"
    "stale_after: 2030-01-01T00:00:00Z\n"
    "{verified}"
    "{sources}"
    "x_geo:\n"
    "  risk: {risk}\n"
    "{trade}"
    "---\n\n{body}"
)

_HUMAN = "verified:\n  - by: human:sales@shop.example\n    at: 2026-08-17T10:00:00Z\n"
_SOURCES = (
    "sources:\n"
    "  - id: trade\n"
    "    resource: https://shop.example/trade\n"
    "    title: Trade page\n"
)
_FULL_TRADE = (
    "  trade:\n"
    "    payment_terms: Net 30 after credit approval\n"
    "    min_order: USD 1,000 opening order\n"
    "    lead_time: 2-4 weeks\n"
)
_BODY = "Net 30 after approval.[^trade]\n\n[^trade]: Trade page.\n"


def _bundle(tmp_path, status="stable", risk="a", trade=_FULL_TRADE,
            verified=_HUMAN, sources=_SOURCES, body=_BODY):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "trade.md").write_text(_TRADE.format(
        status=status, risk=risk, trade=trade,
        verified=verified, sources=sources, body=body,
    ))
    return root


# --- model ------------------------------------------------------------------

def test_trade_and_procurement_accessors_and_effective_risk():
    program = Concept(
        "t.md",
        {"type": "Trade Program",
         "x_geo": {"risk": "b", "trade": {"payment_terms": "Net 30", "min_order": "10 units"}}},
        "",
    )
    assert program.trade["payment_terms"] == "Net 30"
    assert program.risk == "b"       # declared
    assert program.is_high_risk      # effective: trade terms gate as a

    product = Concept(
        "p.md",
        {"type": "Product", "x_geo": {"risk": "b", "procurement": {"moq": "6", "case_pack": 6}}},
        "",
    )
    assert product.procurement["case_pack"] == 6
    assert not product.is_high_risk  # procurement data doesn't escalate products


# --- lint gates -------------------------------------------------------------

def test_clean_trade_program_lints_clean(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path))
    assert findings == []


def test_stable_trade_program_missing_terms_is_error(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, trade=""))
    e019 = [f for f in findings if f.code == "E019"]
    assert e019 and "payment_terms" in e019[0].message and "min_order" in e019[0].message


def test_draft_trade_program_missing_terms_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, status="draft", trade="", verified=""))
    assert not any(f.code == "E019" for f in findings)
    assert any(f.code == "W032" and "Trade Program draft" in f.message for f in findings)


def test_declared_low_risk_cannot_dodge_the_gates(tmp_path):
    _, findings = lint_bundle(
        _bundle(tmp_path, risk="b", verified="", sources="", body="Net 30.\n")
    )
    codes = {f.code for f in findings}
    assert "E010" in codes and "E013" in codes
    assert any(f.code == "W033" and "declares risk `b`" in f.message for f in findings)


# --- publisher and batch-approve exclusion ----------------------------------

def test_draft_trade_program_never_ships_machine_confirmed(tmp_path):
    root = _bundle(tmp_path, status="draft", risk="b", verified="")
    bundle = load_bundle(root)
    include, withheld = select_publishable(bundle, include_machine_confirmed=True)
    assert "trade.md" in withheld and "trade.md" not in include


def test_batch_approve_skips_trade_programs(tmp_path):
    root = _bundle(tmp_path, status="draft", risk="b", verified="")
    approved = review.batch_approve(load_bundle(root), "ops@shop.example")
    assert approved == []
    assert load_bundle(root).concepts["trade.md"].status == "draft"


# --- example bundle ---------------------------------------------------------

def test_example_trade_program_retrieves(example_bundle):
    bundle = load_bundle(example_bundle)
    program = bundle.concepts["trade/wholesale-program.md"]
    assert program.is_high_risk and program.risk == "a"
    assert "Net 30" in program.trade["payment_terms"]

    hits = evaluator.retrieve(
        bundle, "What are your payment terms for business accounts?", 4
    )
    assert "trade/wholesale-program.md" in [c.rel_path for c in hits]


def test_example_product_carries_procurement_facts(example_bundle):
    bundle = load_bundle(example_bundle)
    product = bundle.concepts["catalog/products/ridgeline-20-sleeping-bag.md"]
    assert product.procurement["case_pack"] == 6
    assert "6 units" in str(product.procurement["moq"])


def test_procurement_is_an_archetype():
    assert "procurement" in evaluator.ARCHETYPES
    assert len(evaluator.ARCHETYPES) == 13
