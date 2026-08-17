"""Phase F1–F3 acceptance tests (docs/FIDELITY.md): trust-invariant
integrity, consumer-surface correctness, and scale/determinism."""

import datetime as dt
import json

from okf_web import discover, feed, retrieval, review, surveyor
from okf_web.cli import main as cli_main
from okf_web.linter import lint_concept
from okf_web.mcp_bridge import build_state, handle_message
from okf_web.model import Concept, load_bundle, localized_view
from okf_web.publisher import publish, select_publishable

_MONEY_CSV = (
    "id,title,description,link,brand,cost_of_goods_sold,installment,"
    "subscription_cost,loyalty_points,auto_pricing_min_price,wholesale_price_usd\n"
    "SKU-1,Trail Stove,A compact canister stove. Boils fast.,"
    "https://shop.example/p/trail-stove,Alpine Peak,23.10 USD,6x 9.99 USD,"
    "4.99 USD,240 pts,39.99 USD,18.00 USD\n"
)


# --- F1: trust-invariant integrity ------------------------------------------

def test_money_fields_never_reach_the_concept(tmp_path):
    feed_path = tmp_path / "feed.csv"
    feed_path.write_text(_MONEY_CSV)
    items = feed.parse_feed(feed_path)
    assert items[0].extras == {}  # every money-bearing field dropped
    # Backstop catches (not on the documented list) are recorded per name.
    assert items[0].dropped == ("wholesale_price_usd",)

    root = tmp_path / "bundle"
    result = feed.ingest_feed(feed_path, root)
    assert result.dropped_live_fields == ["wholesale_price_usd"]
    text = (root / "catalog/products/trail-stove.md").read_text()
    for leak in ("23.10", "9.99", "4.99", "240 pts", "39.99", "18.00",
                 "cost_of_goods_sold", "wholesale"):
        assert leak not in text, leak


def test_taxonomy_is_not_a_tax_field(tmp_path):
    csv_text = (
        "id,title,description,link,google_product_taxonomy\n"
        "S1,Mug,An enamel mug.,https://shop.example/p/mug,Home > Kitchen\n"
    )
    path = tmp_path / "f.csv"
    path.write_text(csv_text)
    item = feed.parse_feed(path)[0]
    assert item.extras == {"google_product_taxonomy": "Home > Kitchen"}
    assert item.dropped == ()


def test_risk_floor_warning_for_money_legal_types():
    def draft(type_, risk):
        return Concept(
            "x.md",
            {"type": type_, "title": "t", "description": "d", "tags": ["t"],
             "status": "draft", "x_geo": {"risk": risk}},
            "Body.\n",
        )

    for type_ in ("Policy", "Promotion", "Store Identity"):
        assert "W034" in {f.code for f in lint_concept(draft(type_, "b"))}, type_
        assert "W034" not in {f.code for f in lint_concept(draft(type_, "a"))}, type_
    # Other types are not floored.
    assert "W034" not in {f.code for f in lint_concept(draft("FAQ", "b"))}


def test_stale_on_the_stale_date_itself(bundle_copy):
    day = dt.date(2026, 9, 23)
    concept = Concept("x.md", {"type": "FAQ", "stale_after": "2026-09-23"}, "b\n")
    assert concept.is_stale(day)
    assert not concept.is_stale(day - dt.timedelta(days=1))

    # The publisher's withhold policy agrees on the boundary day.
    bundle = load_bundle(bundle_copy)
    target = bundle.concepts["faq/general.md"]
    target.frontmatter["stale_after"] = "2026-09-23"
    publishable, withheld = select_publishable(bundle, today=day, freshness="withhold")
    assert "faq/general.md" not in publishable
    assert any("faq/general.md" in note for note in withheld)


def test_review_triage_uses_effective_risk(bundle_copy, capsys):
    (bundle_copy / "trade").mkdir(exist_ok=True)
    (bundle_copy / "trade" / "mis.md").write_text(
        "---\n"
        "type: Trade Program\n"
        "title: Mis-declared trade terms\n"
        "description: Declares b; gates as a.\n"
        "tags: [trade]\n"
        "status: draft\n"
        "x_geo:\n"
        "  risk: b\n"
        "  trade: {payment_terms: Net 30, min_order: 100 USD}\n"
        "---\n\nBody.\n"
    )
    items = review.pending(load_bundle(bundle_copy))
    a_tier = [i.concept.rel_path for i in items if i.concept.effective_risk == "a"]
    assert "trade/mis.md" in a_tier

    assert cli_main(["review", "list", str(bundle_copy), "--risk", "a"]) == 0
    out = capsys.readouterr().out
    assert "trade/mis.md" in out
    assert "(a: 2, b: 0, c: 0)" in out


# --- F2: consumer-surface correctness ---------------------------------------

def test_localized_view_paths_round_trip(bundle_copy):
    view = localized_view(load_bundle(bundle_copy), "es")
    es = view.concepts["faq/general.md"]
    assert es.rel_path == "faq/general.md"
    assert view.get(es.rel_path) is es
    assert all(view.get(c.rel_path) is not None for c in view.concepts.values())
    assert view.indexes["index.md"].rel_path == "index.md"


def test_discover_resolves_relative_href_like_a_browser():
    manifest = json.dumps({"files": {"index.md": {}}, "site": "https://store.example"})
    page = '<html><head><link rel="okf-bundle" href="bundle/okf"></head></html>'

    def fake_fetch(url):
        if url == "https://store.example/bundle/okf/manifest.json":
            return 200, manifest
        if url == "https://store.example/home.html":
            return 200, page
        return 404, ""

    report = discover.discover("https://store.example/home.html", fetch=fake_fetch)
    assert report.bundle_url == "https://store.example/bundle/okf"
    assert report.ok


def test_execute_rejects_placeholder_anywhere_in_url(bundle_copy):
    (bundle_copy / "capabilities" / "regional.md").write_text(
        "---\n"
        "type: Attested Computation\n"
        "title: Regional stock\n"
        "description: Stock by region.\n"
        "tags: [capability]\n"
        "status: draft\n"
        "runtime: http\n"
        "parameters:\n"
        "  - { name: sku, type: string, required: true }\n"
        "executor:\n"
        "  resource: https://{region}.api.example.com/stock?sku={sku}\n"
        "  receipt: [sku, status]\n"
        "x_geo: {risk: a, intents: [capability]}\n"
        "---\n\nBody.\n"
    )
    state = build_state(bundle_copy, working=True, http_get=lambda url: (200, "{}"))
    resp = handle_message(state, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "okf_execute", "arguments": {
            "path": "capabilities/regional.md", "arguments": {"sku": "S1"},
        }},
    })
    result = resp["result"]
    assert result["isError"]
    assert "undeclared placeholders" in result["content"][0]["text"]


def test_rebuild_index_pluralizes_properly(tmp_path):
    root = tmp_path / "b"
    root.mkdir()

    def put(rel, type_):
        (root / rel).write_text(
            f"---\ntype: {type_}\ntitle: T {rel}\ndescription: d\n"
            "status: stable\n---\n\nB.\n"
        )

    put("a.md", "Policy")
    put("b.md", "Compatibility")
    put("c.md", "Store Identity")
    put("d.md", "FAQ")
    text = surveyor.rebuild_index(root)
    for heading in ("## Policies", "## Compatibilities", "## Store Identities", "## FAQs"):
        assert heading in text, heading
    assert "Policys" not in text and "Identitys" not in text and "Compatibilitys" not in text


def test_verify_rejects_invalid_label_cleanly(bundle_copy, tmp_path, capsys):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    assert cli_main(
        ["verify", str(dist), "--countersignature", "Bad Label!"]
    ) == 2
    err = capsys.readouterr().err
    assert "invalid countersignature label" in err


# --- F3: scale and determinism ----------------------------------------------

def test_ingest_loads_the_bundle_once(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = feed.load_bundle

    def counting(root, *args, **kwargs):
        calls["n"] += 1
        return real(root, *args, **kwargs)

    monkeypatch.setattr(feed, "load_bundle", counting)
    monkeypatch.setattr(surveyor, "load_bundle", counting)

    rows = "".join(
        f"SKU-{i},Item {i},Solid item number {i}.,https://shop.example/p/item-{i}\n"
        for i in range(12)
    )
    feed_path = tmp_path / "f.csv"
    feed_path.write_text("id,title,description,link\n" + rows)
    result = feed.ingest_feed(feed_path, tmp_path / "b")
    assert len(result.written) == 12
    assert calls["n"] == 1  # one load per ingest, not per row


def test_embedding_index_is_content_addressed(bundle_copy):
    index = retrieval.EmbeddingIndex(retrieval.HashingEmbedder(dim=128))
    bundle = load_bundle(bundle_copy)
    index(bundle, "sleeping bag temperature rating", top_k=3)

    # Same object, mutated content: a content-addressed index re-embeds;
    # the old id()-keyed check would have served stale vectors.
    target = bundle.concepts["catalog/products/alpine-2-tent.md"]
    target.body = "Completely different text about kayaks and paddles.\n"
    results = index(bundle, "kayaks paddles", top_k=3)
    assert any(c.rel_path == "catalog/products/alpine-2-tent.md" for c in results)
