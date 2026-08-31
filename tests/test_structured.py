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
    assert "17× less" in text     # 41,780 / 2,407
    assert "Returns, warranty and policies" in text
    assert "read and approved individually by a named person" in text
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
        "    context_tokens_mean: 2407\n"
        "---\n\n# Results\n\n# Knowledge gaps\n\nNone found in this run.\n"
    )
    html = build_report(load_bundle(bundle_dir))
    assert "retrieval-only dry run" in html
    assert "100%" in html
    assert "None found in the last evaluation." in html
    # No committed question pack → the detail tier is honestly absent.
    assert "The detail behind the numbers" not in html


def test_report_carries_question_detail(example_bundle):
    """The detail tier: per-question retrieval rows recomputed
    deterministically at render time from the committed pack — access
    to the detail, never an invented per-question grade."""
    bundle = load_bundle(example_bundle)
    text = build_report(bundle)
    assert "The detail behind the numbers" in text
    # One collapsible block per archetype in the pack, no scripts.
    assert text.count('<details class="arch"') == 13
    assert "<script" not in text
    # A real question row: top match named by path, tokens shown.
    assert "knowledge found for 3 / 3" in text
    assert "no per-question grade is shown that was not measured" in text
    # The two measurements sit side by side per topic, so the recorded
    # judged score (2/3 on policy and capability) can never be mistaken
    # for the deterministic found-knowledge count (3/3 everywhere).
    assert text.count("judged answers 2 / 3 (recorded)") == 2
    assert text.count("judged answers 3 / 3 (recorded)") == 11
    assert "Finding knowledge is necessary, not sufficient" in text
    # The exact rows that lost their point are marked, read from the
    # recorded results table / gap ids (pol-3, cap-3) — never inferred.
    marker = "judged not answered in the recorded evaluation"
    assert text.count(marker) == 2
    detail = text.split("The detail behind the numbers")[1]
    warranty_row = detail.split("own-brand gear?")[1][:300]
    assert marker in warranty_row
    # The pointer is actionable: each marked row links to its own gap
    # bullet's anchor (and the gaps heading is itself an anchor).
    assert 'id="gaps"' in text
    for qid in ("pol-3", "cap-3"):
        assert f'id="gap-{qid}"' in text
        assert f'href="#gap-{qid}"' in text
    # The paraphrase column reports the phrasing-gap outcome per row.
    assert "asked in a shopper's own words" in text
    # Deterministic: rendering twice is byte-identical.
    assert text == build_report(bundle)


# --- R3: honest defaults --------------------------------------------------

def test_batch_attested_concepts_emit_jsonld(tmp_path):
    """A named bulk sign-off is enough for the derived tier (the person
    took responsibility for publication); the label stays distinct."""
    from okf_web import review

    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "catalog").mkdir(parents=True)
    (bundle_dir / "catalog" / "pack.md").write_text(
        "---\n"
        "type: Product\n"
        "title: Trailhead 35 Pack\n"
        "description: 35 liter hiking backpack.\n"
        "resource: https://shop.example/p/pack\n"
        "status: draft\n"
        "sources:\n"
        "  - id: pdp\n    resource: https://shop.example/p/pack\n"
        "x_geo:\n"
        "  risk: b\n"
        "  entity: sku:PK-35\n"
        "---\n\nBody.[^pdp]\n\n[^pdp]: pdp.\n"
    )
    bundle = load_bundle(bundle_dir)
    review.batch_approve(bundle, "owner@shop.example")
    result = publish(bundle_dir, tmp_path / "dist")
    assert "jsonld/catalog/pack.json" in result.structured
    obj = json.loads((tmp_path / "dist" / "jsonld/catalog/pack.json").read_text())
    assert obj["sku"] == "PK-35"


def test_high_risk_rejects_batch_actor(tmp_path):
    """E010 stays individual: a `human-batch:` stamp on a stable
    high-risk concept is still an error — only `human:` clears it."""
    from okf_web.linter import lint_bundle

    (tmp_path / "policy.md").write_text(
        "---\n"
        "type: Policy\n"
        "title: Warranty\n"
        "status: stable\n"
        "verified:\n"
        "  - by: human-batch:ops@shop.example\n"
        "    at: 2026-08-27T00:00:00Z\n"
        "sources:\n"
        "  - id: p\n    resource: https://shop.example/warranty\n"
        "x_geo:\n"
        "  risk: a\n"
        "---\n\nClaim.[^p]\n\n[^p]: p.\n"
    )
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E010" for f in findings)


def test_paraphrase_metrics_and_scorecard_column(example_bundle):
    from okf_web.evaluator import evaluate, load_questions
    from okf_web.model import load_bundle as _load

    bundle = _load(example_bundle)
    questions = load_questions(example_bundle / "evaluations" / "questions.yaml")
    assert all(q.paraphrase for q in questions)
    report = evaluate(bundle, questions)
    metrics = report.metrics(bundle)
    assert metrics["paraphrase_questions"] == 39
    assert 0 < metrics["paraphrase_agreement"] <= 1
    assert metrics["trust_mix"]["human-reviewed"] > 0


def test_judge_decoupling_records_both_identities(example_bundle):
    from okf_web.evaluator import evaluate, load_questions
    from okf_web.llm import StaticClient
    from okf_web.model import load_bundle as _load

    bundle = _load(example_bundle)
    questions = load_questions(example_bundle / "evaluations" / "questions.yaml")[:2]
    answerer = StaticClient(["answer one", "answer two"], model="static/answer")
    judge = StaticClient(
        ['{"answered": true, "grounded": true, "cited": []}'] * 2,
        model="static/judge",
    )
    report = evaluate(bundle, questions, llm=answerer, judge=judge)
    assert report.generated_by == "okf-web-evaluator/static/answer+judge/static/judge"
    # The judge client graded; the answerer only answered.
    assert len(judge.calls) == 2 and len(answerer.calls) == 2
    # Same client answering and judging keeps the plain identity
    # (self-graded, and the single recorded model says so).
    answerer2 = StaticClient(
        ["a", '{"answered": true, "grounded": true, "cited": []}'],
        model="static/one",
    )
    report2 = evaluate(bundle, questions[:1], llm=answerer2, judge=None)
    assert report2.generated_by == "okf-web-evaluator/static/one"


def test_init_guided_first_run(tmp_path, monkeypatch):
    feed = tmp_path / "feed.csv"
    feed.write_text(
        "id,title,description,link,brand,price\n"
        "T1,Trail Pack,35 liter hiking backpack.,https://shop.example/p/t1,Ridge,129.00\n"
    )
    monkeypatch.chdir(tmp_path)
    rc = cli_main(
        [
            "init", "my-store",
            "--feed", str(feed),
            "--site", "https://shop.example",
            "--by", "owner@shop.example",
            "--pack", "outdoor",
        ]
    )
    assert rc == 0
    bundle = load_bundle(tmp_path / "my-store")
    product = next(c for c in bundle.concepts.values() if c.type == "Product")
    assert product.trust_tier == "human-attested"
    assert product.status == "stable"
    assert (tmp_path / "my-store" / "index.md").exists()
    assert (tmp_path / "my-store" / "evaluations" / "geo-report.html").exists()
    assert (tmp_path / "dist" / "llms.txt").exists()
    assert any((tmp_path / "dist" / "jsonld").rglob("*.json"))
    # Live values never made it in.
    assert "129" not in product.render()
