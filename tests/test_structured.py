"""READINESS R2: the derived tier — JSON-LD + llms.txt from the
verified bundle, and the report command."""

import json

from okf_web.cli import main as cli_main
from okf_web.model import load_bundle
from okf_web.publisher import publish
from okf_web.report import ReportError, build_report, write_report
from okf_web.structured import LLMS_PRODUCT_CAP, jsonld_for, write_llms_txt


def _publish(example_bundle, tmp_path):
    # The library publish takes `site` explicitly (only the CLI
    # auto-resolves it from the index — a documented gotcha).
    result = publish(
        example_bundle,
        tmp_path / "dist",
        site="https://www.alpinepeakoutfitters.example",
    )
    return result, tmp_path / "dist"


def test_jsonld_only_for_human_verified_concepts(example_bundle, tmp_path):
    result, dist = _publish(example_bundle, tmp_path)
    emitted = {rel for rel in result.structured if rel.endswith(".json")}
    # Human-reviewed → restated as the merchant's own markup.
    assert "jsonld/catalog/products/alpine-2-tent.json" in emitted
    # Machine-confirmed publishes in the bundle but is NOT restated.
    assert "jsonld/catalog/products/ridgeline-20-sleeping-bag.json" not in emitted
    bundle = load_bundle(example_bundle)
    assert bundle.concepts[
        "catalog/products/ridgeline-20-sleeping-bag.md"
    ].trust_tier == "machine-confirmed"
    # Drafts never got this far (withheld before emission).
    assert "jsonld/policies/warranty.json" not in emitted


def test_product_jsonld_carries_identity_never_price(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    obj = json.loads(
        (dist / "jsonld/catalog/products/alpine-2-tent.json").read_text()
    )
    assert obj["@type"] == "Product"
    assert obj["sku"] == "APO-TENT-A2"
    assert obj["brand"]["name"] == "Alpine Peak"
    assert "offers" not in obj and "price" not in json.dumps(obj).lower()
    # Provenance stays one hop away.
    assert obj["subjectOf"]["url"].endswith(
        "/.well-known/okf/catalog/products/alpine-2-tent.md"
    )


def test_faq_jsonld_sections_with_footnotes_stripped(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    obj = json.loads((dist / "jsonld/faq/general.json").read_text())
    assert obj["@type"] == "FAQPage"
    names = [q["name"] for q in obj["mainEntity"]]
    assert "Payments" in names and "Gift cards" in names
    text = json.dumps(obj)
    assert "[^" not in text  # footnote apparatus never leaks
    gift = next(q for q in obj["mainEntity"] if q["name"] == "Gift cards")
    # Markdown links unwrap to their text.
    assert "Return & Exchange Policy" in gift["acceptedAnswer"]["text"]
    assert "](" not in gift["acceptedAnswer"]["text"]


def test_store_location_and_return_policy_jsonld(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    org = json.loads((dist / "jsonld/store.json").read_text())
    assert org["@type"] == "Organization"
    assert org["url"] == "https://www.alpinepeakoutfitters.example"
    loc = json.loads((dist / "jsonld/locations/denver-flagship.json").read_text())
    assert loc["@type"] == "LocalBusiness"
    assert "1420 Larimer" in loc["address"]["streetAddress"]
    assert "Mo-Fr 10:00-19:00" in loc["openingHours"]
    pol = json.loads((dist / "jsonld/policies/returns.json").read_text())
    assert pol["@type"] == "MerchantReturnPolicy"
    assert "60 days" in pol["description"]


def test_jsonld_files_are_in_the_manifest(example_bundle, tmp_path):
    result, dist = _publish(example_bundle, tmp_path)
    manifest = json.loads((dist / "manifest.json").read_text())
    for rel in result.structured:
        assert rel in manifest["files"], rel


def test_llms_txt_links_into_the_bundle(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    text = (dist / "llms.txt").read_text()
    assert text.startswith("# Alpine Peak Outfitters")
    assert "/.well-known/okf/policies/returns.md" in text
    assert "## Live values (executable)" in text
    # The withheld draft is not advertised.
    assert "warranty.md" not in text
    # The pointer snippet for existing llms.txt files still ships too.
    assert (dist / "llms-snippet.txt").exists()


def test_llms_txt_caps_products(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "catalog").mkdir()
    for i in range(LLMS_PRODUCT_CAP + 7):
        (bundle_dir / "catalog" / f"p{i:03d}.md").write_text(
            "---\n"
            "type: Product\n"
            f"title: Product {i:03d}\n"
            f"description: Item number {i:03d}.\n"
            f"resource: https://shop.example/p/{i:03d}\n"
            "status: stable\n"
            "sources:\n"
            f"  - id: pdp\n    resource: https://shop.example/p/{i:03d}\n"
            "---\n\nBody.[^pdp]\n\n[^pdp]: pdp.\n"
        )
    bundle = load_bundle(bundle_dir)
    rel = write_llms_txt(tmp_path / "out", bundle, set(bundle.concepts), "/.well-known/okf")
    text = (tmp_path / "out" / "llms.txt").read_text()
    assert rel == "llms.txt"
    assert text.count("- [Product ") == LLMS_PRODUCT_CAP
    assert "and 7 more products" in text


def test_no_structured_flag_skips_the_derived_tier(example_bundle, tmp_path):
    result = publish(example_bundle, tmp_path / "dist", structured=False)
    assert result.structured == []
    assert not (tmp_path / "dist" / "jsonld").exists()
    assert not (tmp_path / "dist" / "llms.txt").exists()


def test_withheld_stale_concepts_get_no_jsonld(example_bundle, tmp_path):
    import datetime as dt

    future = dt.date(2028, 12, 1)  # past every stale_after in the example
    result = publish(
        example_bundle, tmp_path / "dist", freshness="withhold", today=future
    )
    assert not any(rel.endswith(".json") for rel in result.structured)


def test_unmapped_types_emit_nothing(example_bundle):
    bundle = load_bundle(example_bundle)
    scorecard = bundle.concepts["evaluations/geo-scorecard.md"]
    assert jsonld_for(scorecard, "/.well-known/okf") is None
    shipping = bundle.concepts["policies/shipping.md"]  # policy, not returns
    assert jsonld_for(shipping, "/.well-known/okf") is None


# --- the report -----------------------------------------------------------

def test_report_renders_scorecard_and_trust_posture(example_bundle, tmp_path):
    out = write_report(example_bundle, out=tmp_path / "report.html")
    text = out.read_text()
    assert "Alpine Peak Outfitters" in text
    assert "95%" in text          # coverage 0.949
    assert "62%" in text          # baseline 0.615
    assert "18× less" in text     # 41,780 / 2,380
    assert "Returns, warranty and policies" in text
    assert "named human reviewer" in text
    assert "warranty" in text     # the measured gap surfaces
    assert text.lstrip().startswith("<!DOCTYPE html>")


def test_report_cli_and_missing_scorecard(example_bundle, tmp_path):
    assert cli_main(
        ["report", str(example_bundle), "--out", str(tmp_path / "r.html")]
    ) == 0
    assert (tmp_path / "r.html").exists()

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "c.md").write_text("---\ntype: FAQ\ntitle: X\n---\n\nbody\n")
    assert cli_main(["report", str(empty)]) == 2


def test_report_handles_dry_run_scorecards(tmp_path):
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "evaluations").mkdir(parents=True)
    (bundle_dir / "evaluations" / "geo-scorecard.md").write_text(
        "---\n"
        "type: GEO Scorecard\n"
        "title: Answerability evaluation — 2026-08-27\n"
        "status: stable\n"
        "x_geo:\n"
        "  risk: c\n"
        "  metrics:\n"
        "    questions: 39\n"
        "    retrieval_hit_rate: 1.0\n"
        "    context_tokens_mean: 2380\n"
        "---\n\n# Results\n\n# Knowledge gaps\n\nNone found in this run.\n"
    )
    html = build_report(load_bundle(bundle_dir))
    assert "retrieval-only dry run" in html
    assert "100%" in html
    assert "None found in the last evaluation." in html
