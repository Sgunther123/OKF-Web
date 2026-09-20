from okf_web import evaluator, surveyor
from okf_web.llm import StaticClient
from okf_web.model import load_bundle


def test_retrieval_finds_the_right_concepts(example_bundle):
    bundle = load_bundle(example_bundle)
    top = evaluator.retrieve(bundle, "How much does the Alpine 2 tent weigh?")
    assert top and top[0].rel_path == "catalog/products/alpine-2-tent.md"

    top = evaluator.retrieve(bundle, "Can I return an item after 30 days?")
    assert "policies/returns.md" in [c.rel_path for c in top]


def test_dry_run_evaluation_covers_example_questions(example_bundle):
    bundle = load_bundle(example_bundle)
    questions = evaluator.load_questions(
        example_bundle / "evaluations" / "questions.yaml"
    )
    assert len(questions) == 39
    report = evaluator.evaluate(bundle, questions, llm=None)
    metrics = report.metrics(bundle)
    assert metrics["questions"] == 39
    assert metrics["retrieval_hit_rate"] == 1.0
    assert metrics["context_tokens_mean"] > 0
    assert report.dry_run


def test_scorecard_writer_emits_conformant_concept(bundle_copy):
    bundle = load_bundle(bundle_copy)
    questions = evaluator.load_questions(bundle_copy / "evaluations" / "questions.yaml")
    report = evaluator.evaluate(bundle, questions, llm=None)
    out = evaluator.write_scorecard(bundle, report, rel_path="evaluations/test-scorecard.md")
    assert out.exists()
    reloaded = load_bundle(bundle_copy).get("evaluations/test-scorecard.md")
    assert reloaded.type == "GEO Scorecard"
    assert reloaded.x_geo["metrics"]["questions"] == 39


def test_llm_judged_evaluation_with_static_client(example_bundle):
    bundle = load_bundle(example_bundle)
    questions = [
        evaluator.Question(id="q1", archetype="product_fact",
                           question="How much does the Alpine 2 tent weigh?")
    ]
    llm = StaticClient(
        responses=[
            "The Alpine 2 packs at 1.9 kg. [/catalog/products/alpine-2-tent.md]",
            '{"answered": true, "grounded": true, '
            '"cited": ["/catalog/products/alpine-2-tent.md"], "notes": ""}',
        ]
    )
    report = evaluator.evaluate(bundle, questions, llm=llm)
    metrics = report.metrics(bundle)
    assert metrics["coverage"] == 1.0
    assert metrics["citability"] == 1.0  # cited concept is human-reviewed
    assert metrics["freshness"] == 1.0


def test_surveyor_parses_and_gates_llm_output(tmp_path):
    response = (
        '<<<CONCEPT path="faq/payments.md">>>\n'
        "---\n"
        "type: FAQ\n"
        "title: Payments FAQ\n"
        "description: Accepted payment methods.\n"
        "resource: https://shop.example/faq\n"
        "tags: [faq]\n"
        "sources:\n"
        "  - id: faq\n"
        "    resource: https://shop.example/faq\n"
        "    title: FAQ page\n"
        "x_geo:\n"
        "  profile: ecommerce-geo/1.11\n"
        "  risk: b\n"
        "  intents: [trust]\n"
        "---\n"
        "\n"
        "# Payments\n"
        "\n"
        "The store accepts Visa.[^faq]\n"
        "\n"
        "[^faq]: FAQ page.\n"
        "<<<END>>>\n"
        '<<<CONCEPT path="../escape.md">>>\n'
        "---\ntype: FAQ\n---\n\nbad path\n"
        "<<<END>>>\n"
    )
    llm = StaticClient(responses=[response])
    result = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://shop.example/faq", "page text", tmp_path, llm, result
    )
    assert result.written == ["faq/payments.md"]
    assert any("escape.md" in q for q in result.quarantined)

    concept = load_bundle(tmp_path).get("faq/payments.md")
    assert concept.status == "draft"
    assert concept.generated_by == "okf-web-surveyor/static/test"
    assert concept.trust_tier == "unverified"
    assert concept.source_hash and concept.source_hash.startswith("sha256:")


def test_surveyor_skips_unchanged_pages(tmp_path):
    response = (
        '<<<CONCEPT path="faq/payments.md">>>\n'
        "---\ntype: FAQ\ntitle: Payments\nresource: https://shop.example/faq\n---\n\nBody.\n"
        "<<<END>>>\n"
    )
    llm = StaticClient(responses=[response])
    result = surveyor.SurveyResult()
    surveyor.survey_page("https://shop.example/faq", "same text", tmp_path, llm, result)
    assert result.written == ["faq/payments.md"]

    # Second pass with identical page text: no LLM call, no rewrite.
    llm2 = StaticClient(responses=[])  # would raise if called
    result2 = surveyor.SurveyResult()
    surveyor.survey_page("https://shop.example/faq", "same text", tmp_path, llm2, result2)
    assert result2.skipped_unchanged == ["https://shop.example/faq"]
    assert not llm2.calls


def test_surveyor_files_drift_proposal_for_human_reviewed_concept(bundle_copy):
    response = (
        '<<<CONCEPT path="policies/returns.md">>>\n'
        "---\ntype: Policy\ntitle: Returns\n"
        "resource: https://www.alpinepeakoutfitters.example/policies/returns\n"
        "sources:\n  - id: p\n    resource: https://www.alpinepeakoutfitters.example/policies/returns\n"
        "x_geo:\n  risk: a\n---\n\nNew 30-day window.[^p]\n\n[^p]: page.\n"
        "<<<END>>>\n"
    )
    llm = StaticClient(responses=[response])
    result = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://www.alpinepeakoutfitters.example/policies/returns",
        "changed page text",
        bundle_copy,
        llm,
        result,
    )
    assert result.proposed == ["policies/returns.md"]
    assert (bundle_copy / "_review" / "proposed" / "policies" / "returns.md").exists()
    # The human-reviewed original is untouched.
    original = load_bundle(bundle_copy).get("policies/returns.md")
    assert original.trust_tier == "human-reviewed"
    assert "60 days" in original.body


def test_html_to_text_strips_chrome():
    html = (
        "<html><head><script>var x=1;</script><style>.a{}</style></head>"
        "<body><nav><ul><li>Home</li></ul></nav>"
        "<h1>Alpine 2 Tent</h1><p>Packed weight: 1.9 kg.</p></body></html>"
    )
    text = surveyor.html_to_text(html)
    assert "Alpine 2 Tent" in text
    assert "Packed weight: 1.9 kg." in text
    assert "var x=1" not in text
    assert ".a{}" not in text


def test_rebuild_index_lists_only_stable_concepts(bundle_copy):
    surveyor.rebuild_index(bundle_copy)
    text = (bundle_copy / "index.md").read_text()
    assert "/catalog/products/alpine-2-tent.md" in text
    assert "warranty.md" not in text  # draft stays out of the published index
