"""Review 2026-10-21, phase U1 (rendered truth): the report, the viewer
and `okf_info` read the scorecard only at its own path, render its
numbers as numbers or as escaped text, never present a retrieval-only
run as judged, parse judge verdicts strictly, measure freshness over
citations, and keep a localized view's scorecard apart from the
store's own."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from okf_web import cli as cli_mod
from okf_web.evaluator import (
    ARCHETYPES,
    SCORECARD_PATH,
    Question,
    QuestionResult,
    Report,
    evaluate,
    load_questions,
    write_scorecard,
)
from okf_web.linter import lint_bundle
from okf_web.llm import StaticClient
from okf_web.mcp_bridge import _tool_info, build_state
from okf_web.model import load_bundle, localized_view, parse_document, render_document
from okf_web.report import build_report
from okf_web.viewer import build_viewer

TODAY = _dt.date(2026, 8, 5)
HOSTILE = "<img src=x onerror=alert(1)>"


def _scorecard_text(metrics: dict, status: str = "stable") -> str:
    fm = {
        "type": "GEO Scorecard",
        "title": "Answerability evaluation — 2026-08-01",
        "status": status,
        "stale_after": "2026-12-31T00:00:00Z",
        "x_geo": {"risk": "c", "metrics": metrics},
    }
    return render_document(fm, "\n# Results\n\n# Knowledge gaps\n\nNone found in this run.\n")


def _questions(bundle_dir: Path):
    return load_questions(bundle_dir / "evaluations" / "questions.yaml")


# --- S-U1: numbers are numbers, and the scorecard has one address -----------

def test_hostile_scorecard_metrics_never_render_as_markup(bundle_copy):
    (bundle_copy / SCORECARD_PATH).write_text(
        _scorecard_text({
            "questions": 3,
            "coverage": 0.5,
            "retrieval_hit_rate": 1.0,
            "context_tokens_mean": 100,
            "by_archetype": {
                "discovery": {"questions": HOSTILE, "answered": "<script>alert(2)</script>"},
                "policy": {"questions": 3, "answered": 2},
            },
        }),
        encoding="utf-8",
    )
    bundle = load_bundle(bundle_copy)
    for page in (build_report(bundle, today=TODAY), build_viewer(bundle, today=TODAY)):
        assert "<img" not in page and "<script" not in page
    report = build_report(bundle, today=TODAY)
    # The hostile value is still visible to the operator, as text.
    assert "&lt;img src=x onerror=alert(1)&gt;" in report
    # A sound slot beside it renders as a count.
    assert "2 / 3 answered" in report


def test_a_scorecard_outside_evaluations_or_in_draft_is_a_lint_error_and_never_read(bundle_copy):
    fake_metrics = {
        "questions": 1,
        "coverage": 0.01,
        "retrieval_hit_rate": 1.0,
        "context_tokens_mean": 1,
        "by_archetype": {"discovery": {"questions": HOSTILE, "answered": HOSTILE}},
    }
    (bundle_copy / "aaa").mkdir()
    (bundle_copy / "aaa" / "fake.md").write_text(
        _scorecard_text(fake_metrics, status="draft"), encoding="utf-8"
    )
    (bundle_copy / "evaluations" / "other.md").write_text(
        _scorecard_text(fake_metrics), encoding="utf-8"
    )
    bundle, findings = lint_bundle(bundle_copy, today=TODAY)
    flagged = {f.rel_path for f in findings if f.code == "E022"}
    # Outside evaluations/ is an error; a non-draft under evaluations/ is
    # allowed to exist (a kept older record) but is not what is read.
    assert flagged == {"aaa/fake.md"}

    report = build_report(bundle, today=TODAY)
    assert "<img" not in report
    assert '<div class="value">1%</div>' not in report
    assert '<div class="value">95%</div>' in report  # the example's own record
    info = _tool_info(build_state(bundle_copy, working=True), {})
    assert info["scorecard_judged"] is True
    assert info["scorecard_metrics"]["coverage"] == 0.949

    # And a draft at the one address is refused too.
    (bundle_copy / SCORECARD_PATH).write_text(
        _scorecard_text(fake_metrics, status="draft"), encoding="utf-8"
    )
    codes = {f.rel_path for f in lint_bundle(bundle_copy, today=TODAY)[1] if f.code == "E022"}
    assert SCORECARD_PATH in codes


# --- L-U1: a dry run is not a verdict ----------------------------------------

def test_dry_run_scorecard_renders_as_not_judged(bundle_copy):
    bundle = load_bundle(bundle_copy)
    report = evaluate(bundle, _questions(bundle_copy))
    assert report.dry_run
    metrics = report.metrics(bundle)
    assert "coverage" not in metrics
    for slot in metrics["by_archetype"].values():
        assert "answered" not in slot and slot["found"] == slot["questions"]
    write_scorecard(bundle, report, force=True)

    bundle = load_bundle(bundle_copy)
    text = build_report(bundle, today=TODAY)
    assert "Knowledge found by topic (not judged)" in text
    assert "judged answers" not in text
    assert "judged not answered" not in text
    assert "retrieval-only measurement" in text
    assert "LLM-based" not in text
    assert "over the working copy" in text
    assert "<script" not in text
    assert text == build_report(bundle, today=TODAY)

    page = build_viewer(bundle, today=TODAY)
    assert "answered</span>" not in page
    assert page.count("not judged</span>") == len(ARCHETYPES)
    assert "judged not answered" not in page

    info = _tool_info(build_state(bundle_copy, working=True), {})
    assert info["scorecard_judged"] is False
    assert "coverage" not in info["scorecard_metrics"]


# --- T-U2: judge verdicts parse strictly -------------------------------------

def test_judge_verdicts_parse_strictly(bundle_copy):
    bundle = load_bundle(bundle_copy)
    questions = _questions(bundle_copy)[:3]
    answerer = StaticClient(["an answer"] * 3, model="static/answer")
    judge = StaticClient(
        [
            '{"answered": "false", "grounded": "no", "cited": []}',
            'Sure.\n```json\n{"answered": "yes", "grounded": true, "cited": []}\n```',
            '{"answered": 1, "grounded": "TRUE", "cited": []}',
        ],
        model="static/judge",
    )
    report = evaluate(bundle, questions, llm=answerer, judge=judge)
    assert [r.answered for r in report.results] == [False, True, False]
    assert [r.grounded for r in report.results] == [False, True, True]
    assert report.metrics(bundle)["coverage"] == 0.333
    assert report.generated_by == "okf-web-evaluator/static/answer+judge/static/judge"


# --- L-U9: freshness is a property of citations ------------------------------

def test_freshness_is_measured_over_cited_answers_only(bundle_copy):
    (bundle_copy / "faq" / "old.md").write_text(
        render_document(
            {
                "type": "FAQ",
                "title": "An old answer",
                "status": "stable",
                "stale_after": "2020-01-01T00:00:00Z",
                "x_geo": {"risk": "c"},
            },
            "\nOld.\n",
        ),
        encoding="utf-8",
    )
    bundle = load_bundle(bundle_copy)
    q = Question(id="q", archetype="policy", question="?")

    def result(answered: bool, cited: list[str]) -> QuestionResult:
        return QuestionResult(
            question=q, retrieved=["policies/returns.md"], context_tokens=10,
            answered=answered, grounded=answered, cited_paths=cited,
        )

    def metrics(*results):
        return Report(results=list(results), generated_by="t", dry_run=False).metrics(bundle)

    # An unanswered, uncited question no longer counts as fresh.
    assert metrics(result(True, ["policies/returns.md"]), result(False, []))["freshness"] == 1.0
    assert "freshness" not in metrics(result(False, []), result(False, []))
    stale = metrics(result(True, ["faq/old.md"]), result(True, ["policies/returns.md"]), result(False, []))
    assert stale["freshness"] == 0.5


# --- A-U9: a localized view's scorecard is its own record --------------------

def test_a_localized_view_writes_its_own_scorecard(bundle_copy):
    before = (bundle_copy / SCORECARD_PATH).read_bytes()
    base = load_bundle(bundle_copy)
    view = localized_view(base, "es")
    out = write_scorecard(view, evaluate(view, _questions(bundle_copy)))
    assert out == bundle_copy / "evaluations" / "geo-scorecard.es.md"
    fm, _ = parse_document(out.read_text(encoding="utf-8"))
    assert fm["x_geo"]["evaluated"] == {
        "view": "working", "retriever": "lexical", "top_k": 4, "language": "es",
    }
    assert (bundle_copy / SCORECARD_PATH).read_bytes() == before

    bundle, findings = lint_bundle(bundle_copy, today=TODAY)
    assert not [f for f in findings if f.code == "E022"]
    # The report still reads the store's own record.
    assert '<div class="value">95%</div>' in build_report(bundle, today=TODAY)


def test_the_scorecard_records_what_was_evaluated(bundle_copy):
    rc = cli_mod.main([
        "evaluate", str(bundle_copy), "--dry-run", "--published",
        "--write-scorecard", "--force",
    ])
    assert rc == 0
    fm, _ = parse_document((bundle_copy / SCORECARD_PATH).read_text(encoding="utf-8"))
    assert fm["x_geo"]["evaluated"] == {"view": "published", "retriever": "lexical", "top_k": 4}
    text = build_report(load_bundle(bundle_copy), today=TODAY)
    assert "over the published view" in text and "retrieval-only measurement" in text

    rc = cli_mod.main([
        "evaluate", str(bundle_copy), "--dry-run", "--retriever", "hashing",
        "--top-k", "6", "--write-scorecard", "--force",
    ])
    assert rc == 0
    fm, _ = parse_document((bundle_copy / SCORECARD_PATH).read_text(encoding="utf-8"))
    evaluated = fm["x_geo"]["evaluated"]
    assert evaluated["view"] == "working" and evaluated["top_k"] == 6
    assert evaluated["retriever"].startswith("embedding/hashing-")


# --- the store's name: what names it, else its site, never its folder --------

def test_the_report_names_the_store_by_its_identity_else_by_its_site(bundle_copy):
    """A bundle's folder is often just ``bundle`` (every hosted store's
    is), so a report titled after it names nobody: the Store Identity's
    title first, then the host of the site the index declares, and the
    folder only when neither exists."""
    assert bundle_copy.name == "bundle"
    page = build_report(load_bundle(bundle_copy), today=TODAY)
    assert "<title>AI answerability — Alpine Peak Outfitters</title>" in page
    (bundle_copy / "store.md").unlink()
    page = build_report(load_bundle(bundle_copy), today=TODAY)
    assert "<title>AI answerability — www.alpinepeakoutfitters.example</title>" in page
    assert '<p class="sub">www.alpinepeakoutfitters.example &middot;' in page
    index = bundle_copy / "index.md"
    frontmatter, body = parse_document(index.read_text(encoding="utf-8"))
    del frontmatter["x_geo"]["site"]
    index.write_text(render_document(frontmatter, body), encoding="utf-8")
    page = build_report(load_bundle(bundle_copy), today=TODAY)
    assert "<title>AI answerability — bundle</title>" in page
