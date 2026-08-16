from okf_web import evaluator
from okf_web.linter import lint_bundle
from okf_web.mcp_bridge import build_state, handle_message
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

_GUIDE = (
    "---\n"
    "type: Ownership Guide\n"
    "title: Widget Care\n"
    "description: Caring for your widget.\n"
    "tags: [care]\n"
    "status: {status}\n"
    "x_geo:\n"
    "  risk: {risk}\n"
    "{refs}"
    "---\n\nWipe with a damp cloth.\n"
)


def _bundle(tmp_path, status="stable", risk="b", refs="  covers: [sku:WIDGET-1]\n"):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "widget.md").write_text(_PRODUCT)
    (root / "care.md").write_text(_GUIDE.format(status=status, risk=risk, refs=refs))
    return root


# --- model ------------------------------------------------------------------

def test_covers_accessor_and_entity_refs():
    concept = Concept(
        "g.md",
        {"type": "Ownership Guide", "x_geo": {"covers": ["sku:A"], "fits": ["sku:B"]}},
        "",
    )
    assert concept.covers == ["sku:A"]
    assert concept.entity_refs == ["sku:B", "sku:A"]  # fits + works_with + covers
    assert Concept("g.md", {"type": "Ownership Guide"}, "").covers == []


# --- lint gates -------------------------------------------------------------

def test_stable_guide_without_covers_is_error(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, refs=""))
    assert any(f.code == "E016" for f in findings)


def test_draft_guide_without_covers_warns_only(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, status="draft", refs=""))
    assert not any(f.code == "E016" for f in findings)
    assert any(f.code == "W032" for f in findings)


def test_unresolved_covers_reference_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, refs="  covers: [sku:GHOST-9]\n"))
    hits = [f for f in findings if f.code == "W032"]
    assert hits and "sku:GHOST-9" in hits[0].message


def test_risk_c_guide_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, risk="c"))
    assert any(f.code == "W033" for f in findings)


def test_resolving_risk_b_guide_is_clean(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path))
    assert findings == []


# --- example bundle ---------------------------------------------------------

def test_example_care_guide_resolves_and_retrieves(example_bundle):
    bundle = load_bundle(example_bundle)
    guide = bundle.concepts["ownership/ridgeline-20-care.md"]
    assert guide.covers == ["sku:APO-BAG-R20"]
    assert set(guide.covers) <= set(bundle.entities())

    hits = evaluator.retrieve(
        bundle, "How should I store my down sleeping bag between trips?", 4
    )
    assert "ownership/ridgeline-20-care.md" in [c.rel_path for c in hits]


def test_claim_status_capability_is_exposed_but_get_only(example_bundle):
    state = build_state(example_bundle, http_get=lambda url: (200, "{}"))
    resp = handle_message(
        state,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "okf_capabilities", "arguments": {}}},
    )
    import json

    payload = json.loads(resp["result"]["content"][0]["text"])
    by_path = {c["path"]: c for c in payload["capabilities"]}
    claim = by_path["capabilities/warranty-claim-status.md"]
    assert claim["runtime"] == "http"
    assert {p["name"] for p in claim["parameters"]} == {"claim_id", "token"}

    resp = handle_message(
        state,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "okf_execute",
                    "arguments": {"path": "capabilities/warranty-claim-status.md",
                                  "arguments": {"claim_id": "WC-1", "token": "t0k"}}}},
    )
    assert not resp["result"].get("isError")


def test_ownership_is_an_archetype():
    assert "ownership" in evaluator.ARCHETYPES
    assert len(evaluator.ARCHETYPES) == 12
