import json

from okf_web import evaluator
from okf_web.linter import lint_bundle
from okf_web.mcp_bridge import build_state, handle_message
from okf_web.model import Concept, load_bundle

_LOCATION = (
    "---\n"
    "type: Store Location\n"
    "title: Downtown Store\n"
    "description: The physical store.\n"
    "tags: [store]\n"
    "status: {status}\n"
    "x_geo:\n"
    "  risk: {risk}\n"
    "{entity}"
    "{location}"
    "---\n\nVisit us downtown.\n"
)

_FULL_LOCATION = (
    "  location:\n"
    "    address: 1 Main Street, Springfield, US\n"
    "    hours:\n"
    "      mon-fri: \"09:00-18:00\"\n"
)


def _bundle(tmp_path, status="stable", risk="b",
            entity="  entity: loc:MAIN-01\n", location=_FULL_LOCATION):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "store.md").write_text(_LOCATION.format(
        status=status, risk=risk, entity=entity, location=location,
    ))
    return root


# --- model ------------------------------------------------------------------

def test_location_accessor():
    concept = Concept(
        "l.md",
        {"type": "Store Location",
         "x_geo": {"entity": "loc:X", "location": {"address": "1 Main St"}}},
        "",
    )
    assert concept.location["address"] == "1 Main St"
    assert concept.entity == "loc:X"
    assert Concept("l.md", {"type": "Store Location"}, "").location == {}


# --- lint gates -------------------------------------------------------------

def test_clean_location_lints_clean(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path))
    assert findings == []


def test_stable_location_missing_contract_is_error(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, entity="", location=""))
    e018 = [f for f in findings if f.code == "E018"]
    assert e018 and "entity" in e018[0].message and "address" in e018[0].message


def test_draft_location_missing_contract_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, status="draft", location=""))
    assert not any(f.code == "E018" for f in findings)
    assert any(f.code == "W032" and "Location draft" in f.message for f in findings)


def test_risk_c_location_warns(tmp_path):
    _, findings = lint_bundle(_bundle(tmp_path, risk="c"))
    assert any(f.code == "W033" for f in findings)


# --- example bundle ---------------------------------------------------------

def test_example_location_resolves_and_retrieves(example_bundle):
    bundle = load_bundle(example_bundle)
    store = bundle.concepts["locations/denver-flagship.md"]
    assert store.entity == "loc:APO-DEN-01"
    assert store.entity in bundle.entities()
    assert "Larimer" in store.location["address"]
    assert store.location["services"] == ["in-store-pickup", "in-store-returns", "gear-fitting"]

    hits = evaluator.retrieve(
        bundle, "Do you have an actual store I can visit, and when is it open?", 4
    )
    assert "locations/denver-flagship.md" in [c.rel_path for c in hits]


def test_store_stock_capability_takes_location_entity(example_bundle):
    seen = {}

    def fake_get(url):
        seen["url"] = url
        return 200, json.dumps({
            "sku": "APO-TENT-A2", "location": "loc:APO-DEN-01",
            "availability": "in_stock", "as_of": "2026-08-17T00:00:00Z",
        })

    state = build_state(example_bundle, http_get=fake_get)
    resp = handle_message(
        state,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "okf_execute",
                    "arguments": {"path": "capabilities/store-stock-check.md",
                                  "arguments": {"sku": "APO-TENT-A2",
                                                "location": "loc:APO-DEN-01"}}}},
    )
    assert not resp["result"].get("isError")
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["status"] == 200
    assert "location=loc%3AAPO-DEN-01" in seen["url"]
    assert "availability" in payload["receipt_fields"]


def test_local_availability_is_an_archetype():
    assert "local_availability" in evaluator.ARCHETYPES
    assert len(evaluator.ARCHETYPES) == 13
