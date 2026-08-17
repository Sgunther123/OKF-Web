import io
import json

from okf_web.mcp_bridge import BridgeState, build_state, handle_message, serve_stdio


def _rpc(method, params=None, msg_id=1):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def _call(state, name, arguments=None):
    resp = handle_message(
        state, _rpc("tools/call", {"name": name, "arguments": arguments or {}})
    )
    result = resp["result"]
    return result, result["content"][0]["text"]


def test_initialize_handshake(example_bundle):
    state = build_state(example_bundle)
    resp = handle_message(
        state, _rpc("initialize", {"protocolVersion": "2025-06-18"})
    )
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "okf-web"
    assert "tools" in result["capabilities"]
    # Client's initialized notification gets no response.
    assert handle_message(state, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list(example_bundle):
    state = build_state(example_bundle)
    resp = handle_message(state, _rpc("tools/list"))
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["okf_info", "okf_search", "okf_get", "okf_capabilities", "okf_execute"]
    assert all("description" in t and "inputSchema" in t for t in resp["result"]["tools"])


def test_unknown_method_errors(example_bundle):
    state = build_state(example_bundle)
    resp = handle_message(state, _rpc("resources/list"))
    assert resp["error"]["code"] == -32601


def test_info_reports_store_and_scorecard(example_bundle):
    state = build_state(example_bundle)
    _, text = _call(state, "okf_info")
    payload = json.loads(text)
    assert payload["store"]["path"] == "store.md"
    assert payload["concepts_by_type"]["Product"] == 2
    assert payload["scorecard_metrics"]["questions"] == 39


def test_search_returns_trust_annotated_hits(example_bundle):
    state = build_state(example_bundle)
    _, text = _call(state, "okf_search", {"question": "How much does the Alpine 2 tent weigh?"})
    payload = json.loads(text)
    paths = [r["path"] for r in payload["results"]]
    assert "catalog/products/alpine-2-tent.md" in paths
    top = payload["results"][0]
    assert {"trust_tier", "risk", "stale", "body"} <= set(top)


def test_published_view_hides_drafts_working_shows_them(example_bundle):
    published = build_state(example_bundle)
    result, text = _call(published, "okf_get", {"path": "policies/warranty.md"})
    assert result["isError"]
    assert "no published concept" in text

    working = build_state(example_bundle, working=True)
    result, text = _call(working, "okf_get", {"path": "policies/warranty.md"})
    assert not result.get("isError")
    assert "warranty" in text.lower()


def test_get_full_concept(example_bundle):
    state = build_state(example_bundle)
    result, text = _call(state, "okf_get", {"path": "/catalog/products/alpine-2-tent.md"})
    assert not result.get("isError")
    assert text.startswith("---")
    assert "Alpine" in text


def test_capabilities_listing(example_bundle):
    state = build_state(example_bundle)
    _, text = _call(state, "okf_capabilities")
    payload = json.loads(text)
    by_path = {c["path"]: c for c in payload["capabilities"]}
    price = by_path["capabilities/price-check.md"]
    assert price["runtime"] == "http"
    assert any(p["name"] == "sku" and p["required"] for p in price["parameters"])
    assert price["executor"]["resource"].startswith("https://")


def test_execute_capability(example_bundle):
    seen = {}

    def fake_get(url):
        seen["url"] = url
        return 200, '{"sku": "APO-TENT-A2", "price": "329.00"}'

    state = build_state(example_bundle, http_get=fake_get)
    result, text = _call(
        state,
        "okf_execute",
        {"path": "capabilities/price-check.md", "arguments": {"sku": "APO-TENT-A2"}},
    )
    assert not result.get("isError")
    payload = json.loads(text)
    assert payload["status"] == 200
    assert "sku=APO-TENT-A2" in seen["url"]
    assert "signature" in payload["receipt_fields"]


def test_execute_requires_declared_parameters(example_bundle):
    state = build_state(example_bundle, http_get=lambda url: (200, "{}"))
    result, text = _call(state, "okf_execute", {"path": "capabilities/price-check.md"})
    assert result["isError"]
    assert "missing required parameter" in text

    result, text = _call(
        state, "okf_execute", {"path": "faq/general.md", "arguments": {"q": "x"}}
    )
    assert result["isError"]
    assert "not an http-runtime" in text


def test_execute_ignores_undeclared_arguments(example_bundle):
    seen = {}

    def fake_get(url):
        seen["url"] = url
        return 200, "{}"

    state = build_state(example_bundle, http_get=fake_get)
    _call(
        state,
        "okf_execute",
        {
            "path": "capabilities/price-check.md",
            "arguments": {"sku": "X1", "evil": "https://attacker.example"},
        },
    )
    assert "attacker" not in seen["url"]


def test_serve_stdio_round_trip(example_bundle):
    state = build_state(example_bundle)
    stdin = io.StringIO(
        json.dumps(_rpc("initialize", {"protocolVersion": "2025-03-26"})) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + "not json\n"
        + json.dumps(_rpc("tools/list", msg_id=2)) + "\n"
    )
    stdout = io.StringIO()
    serve_stdio(state, stdin=stdin, stdout=stdout)
    lines = [json.loads(l) for l in stdout.getvalue().splitlines()]
    # init response, parse error, tools/list response — notification silent.
    assert lines[0]["id"] == 1 and "result" in lines[0]
    assert lines[1]["error"]["code"] == -32700
    assert lines[2]["id"] == 2 and len(lines[2]["result"]["tools"]) == 5
