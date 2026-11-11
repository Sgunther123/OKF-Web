"""The "before": the same questions put to the store's own pages
(`okf_web.baseline`, `evaluate --baseline`). A comparison is on a
scorecard only when a run measured it, the evaluator's own harness
grades both sides, and a store whose pages cannot be read has no
baseline rather than a zero."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from okf_web import baseline, evaluator, linter
from okf_web import cli as cli_mod
from okf_web.baseline import Baseline, BaselineError
from okf_web.evaluator import Question
from okf_web.model import Bundle, Concept, load_bundle, parse_document, render_document
from okf_web.report import build_report, reading_tile

REPO = Path(__file__).resolve().parents[1]
#: A multiple stated as fact: "22 times less", "17× cheaper".
TYPED_COMPARISON = re.compile(
    r"(?i)\b\d+(?:[.,]\d+)?\s*(?:×|x|times)\s+(?:less|cheaper|fewer|smaller|more efficient)\b"
)

RETURNS = "https://shop.test/pages/returns"
TENT = "https://shop.test/products/tent"
ABOUT = "https://shop.test/about"

PAGES = {
    RETURNS: "Returns\nUnused gear can be returned within 30 days for a refund.",
    TENT: "Trail Tent\nA two person tent that weighs 1.4 kilograms.",
    ABOUT: "About us\nA small outdoor shop founded in Boulder.",
}

QUESTIONS = [
    Question(id="pol-1", archetype="policy", question="How many days do I have to return unused gear?"),
    Question(id="fact-1", archetype="product_fact", question="How much does the two person tent weigh?"),
    Question(id="cap-1", archetype="capability", question="Is the stove in stock today?"),
]


def _bundle(tmp_path: Path) -> Bundle:
    """Three concepts citing three pages; one question nothing answers."""
    def concept(rel, type_, title, url, body):
        return Concept(rel, {"type": type_, "title": title, "resource": url}, body)

    return Bundle(root=tmp_path, concepts={
        "policies/returns.md": concept(
            "policies/returns.md", "Policy", "Returns", RETURNS,
            "Unused gear can be returned within 30 days."),
        "catalog/tent.md": concept(
            "catalog/tent.md", "Product", "Trail Tent", TENT,
            "A two person tent. It weighs 1.4 kilograms."),
        "store.md": concept(
            "store.md", "Store Identity", "The shop", ABOUT, "An outdoor shop in Boulder."),
    })


def _fetch(pages=PAGES):
    def fetch_text(url):
        if url not in pages:
            raise OSError("HTTP 404")
        return pages[url]
    return fetch_text


# --- which pages -------------------------------------------------------------

def test_the_pages_are_the_ones_the_bundle_cites_its_answers_first(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.concepts["faq.md"] = Concept("faq.md", {"type": "FAQ", "resource": RETURNS}, "x")
    bundle.concepts["feed.md"] = Concept("feed.md", {"type": "Product", "resource": "feed://row/7"}, "x")
    bundle.concepts["hand.md"] = Concept("hand.md", {"type": "FAQ"}, "x")
    bundle.concepts["l10n/es/store.md"] = Concept(
        "l10n/es/store.md", {"type": "Store Identity", "resource": "https://shop.test/es"}, "x")
    bundle.concepts["evaluations/geo-scorecard.md"] = Concept(
        "evaluations/geo-scorecard.md",
        {"type": "GEO Scorecard", "resource": "https://shop.test/score"}, "x")
    # Distinct http(s) pages only, by URL: no feed row, no translation,
    # no scorecard, and a page two concepts cite once.
    assert baseline.source_pages(bundle) == [ABOUT, RETURNS, TENT]
    # The pages behind the named concepts lead, in that order; a path
    # the bundle does not hold is skipped.
    assert baseline.source_pages(bundle, ["catalog/tent.md", "gone.md", "faq.md"]) == [
        TENT, RETURNS, ABOUT]


def test_a_limit_keeps_the_pages_behind_the_bundles_own_answers(tmp_path):
    bundle = _bundle(tmp_path)
    measured = baseline.measure(bundle, QUESTIONS[1:2], limit=1, fetch_text=_fetch())
    # The tent question retrieves the tent concept, so its page is the
    # one read although it sorts last; the record says what was left.
    assert measured.pages == [TENT]
    assert measured.record["pages"] == 1 and measured.record["pages_available"] == 3
    assert measured.record["condition"] == "store pages as text (1 page, same questions)"
    with pytest.raises(BaselineError, match="at least one page"):
        baseline.measure(bundle, QUESTIONS, limit=0, fetch_text=_fetch())


def test_named_pages_replace_the_cited_ones(tmp_path):
    urls = tmp_path / "pages.txt"
    urls.write_text(f"# the store's policy pages\n\n{RETURNS}\n{RETURNS}\n{ABOUT}\n", encoding="utf-8")
    assert baseline.read_urls(urls) == [RETURNS, ABOUT]
    measured = baseline.measure(
        _bundle(tmp_path), QUESTIONS, urls=baseline.read_urls(urls), fetch_text=_fetch())
    assert measured.pages == [RETURNS, ABOUT]
    urls.write_text("https://shop.test/a\nfile:///etc/passwd\n", encoding="utf-8")
    with pytest.raises(BaselineError, match=r"line 2: 'file:///etc/passwd' is not an http\(s\) page"):
        baseline.read_urls(urls)


# --- the measurement ---------------------------------------------------------

def test_a_dry_baseline_is_the_evaluators_retrieval_check_over_the_pages(tmp_path):
    bundle = _bundle(tmp_path)
    measured = baseline.measure(bundle, QUESTIONS, fetch_text=_fetch())
    record = measured.record
    # The evaluator's own harness ran over the pages view: what it
    # reports is what the record carries.
    view = baseline.pages_view(bundle, {url: PAGES[url] for url in measured.pages})
    expected = evaluator.evaluate(view, QUESTIONS).metrics(view)
    assert record["questions"] == 3
    assert record["retrieval_hit_rate"] == expected["retrieval_hit_rate"] == 0.667
    assert record["context_tokens_mean"] == expected["context_tokens_mean"] > 0
    assert record["by_archetype"] == expected["by_archetype"]
    assert record["pages"] == 3 and record["top_k"] == 4 and record["retriever"] == "lexical"
    # A dry run records no verdict for the pages either.
    assert "coverage" not in record and "groundedness" not in record
    assert all("answered" not in slot for slot in record["by_archetype"].values())
    assert measured.report.dry_run
    # Each page is a stand-in concept: its address kept, its trust unverified.
    stand_in = next(iter(view.concepts.values()))
    assert stand_in.rel_path.startswith("pages/001-") and stand_in.type == baseline.PAGE_TYPE
    assert stand_in.trust_tier == "unverified" and stand_in.resource in PAGES


def test_unreadable_pages_are_counted_and_no_page_is_a_refusal_not_a_zero(tmp_path):
    bundle = _bundle(tmp_path)
    pages = {RETURNS: PAGES[RETURNS], ABOUT: "   \n"}  # the tent page is gone, one page is blank
    measured = baseline.measure(bundle, QUESTIONS, fetch_text=_fetch(pages))
    assert measured.pages == [RETURNS]
    assert measured.record["pages"] == 1 and measured.record["pages_unreadable"] == 2
    assert dict(measured.unreadable) == {
        TENT: "HTTP 404", ABOUT: "the page carries no readable text"}
    with pytest.raises(BaselineError, match=r"none of the 3 store page\(s\) could be read "
                       r"\(first: https://shop\.test/pages/returns: HTTP 404\)"):
        baseline.measure(bundle, QUESTIONS, fetch_text=_fetch({}))
    # A bundle that cites no page at all says what to do instead.
    for concept in bundle.concepts.values():
        concept.frontmatter.pop("resource")
    with pytest.raises(BaselineError, match="no concept in this bundle cites an http"):
        baseline.measure(bundle, QUESTIONS, fetch_text=_fetch())


def test_a_long_page_is_cut_and_the_record_says_so(tmp_path):
    bundle = _bundle(tmp_path)
    long_page = "tent " * (baseline.PAGE_CHARS_MAX // 5 + 50)
    measured = baseline.measure(bundle, QUESTIONS, fetch_text=_fetch({**PAGES, TENT: long_page}))
    assert measured.record["pages_cut"] == 1
    assert measured.record["page_chars_max"] == baseline.PAGE_CHARS_MAX
    view = baseline.pages_view(bundle, {TENT: long_page[:baseline.PAGE_CHARS_MAX]})
    assert len(next(iter(view.concepts.values())).body) == baseline.PAGE_CHARS_MAX
    uncut = baseline.measure(bundle, QUESTIONS, fetch_text=_fetch())
    assert "pages_cut" not in uncut.record and "page_chars_max" not in uncut.record


def test_a_raised_relevance_floor_holds_for_the_pages_too(tmp_path):
    bundle = _bundle(tmp_path)
    loose = baseline.measure(bundle, QUESTIONS[:2], fetch_text=_fetch())
    strict = baseline.measure(bundle, QUESTIONS[:2], fetch_text=_fetch(), min_relevance=0.99)
    # The same floor on both sides: a page that shares only part of a
    # question's words stops counting as a match when the bundle's own
    # run asked for nearly all of them.
    assert loose.record["retrieval_hit_rate"] == 1.0
    assert strict.record["retrieval_hit_rate"] < 1.0
    assert strict.record["retriever"] == "lexical"


class _Model:
    """An answerer and judge that read only the CONTEXT they are given:
    answered when the context holds the question's key fact."""

    FACTS = {"return unused gear": "30 days", "tent weigh": "1.4 kilograms", "stove": "in stock: yes"}

    def __init__(self, model="answerer-1"):
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, max_tokens=0):
        self.calls.append((system, user))
        question = user.split("\n", 1)[0]
        fact = next(v for k, v in self.FACTS.items() if k in question)
        found = fact in user.split("CONTEXT:", 1)[1]
        if system == evaluator._prompt("evaluator_judge.md"):
            return json.dumps({"answered": found, "grounded": found, "cited": [], "notes": ""})
        return f"It is {fact}." if found else "CANNOT_ANSWER: the context does not say."


def test_a_judged_baseline_is_graded_by_the_same_prompts_as_the_bundle(tmp_path):
    bundle = _bundle(tmp_path)
    answerer, judge = _Model("answerer-1"), _Model("judge-1")
    measured = baseline.measure(bundle, QUESTIONS, llm=answerer, judge=judge, fetch_text=_fetch())
    # Two of the three questions are answerable from the pages; the
    # stock question is not, on the pages or anywhere.
    assert measured.record["coverage"] == 0.667 and measured.record["groundedness"] == 0.667
    assert measured.record["by_archetype"]["capability"] == {"questions": 1, "found": 0, "answered": 0}
    assert measured.report.generated_by == "okf-web-evaluator/answerer-1+judge/judge-1"
    # The evaluator's own prompts, and the pages as inert concept blocks.
    assert {system for system, _ in answerer.calls} == {evaluator._prompt("evaluator_answer.md")}
    assert {system for system, _ in judge.calls} == {evaluator._prompt("evaluator_judge.md")}
    context = answerer.calls[0][1]
    assert '<concept path="/pages/00' in context and 'trust="unverified"' in context
    assert "Unused gear can be returned within 30 days for a refund." in context


def test_the_pages_view_keeps_the_bundles_language_and_declarations(tmp_path):
    bundle = _bundle(tmp_path)
    bundle.indexes["index.md"] = Concept(
        "index.md", {"x_geo": {"language": "es", "not_applicable": ["capability"]}}, "")
    measured = baseline.measure(bundle, QUESTIONS, fetch_text=_fetch())
    view = baseline.pages_view(bundle, PAGES)
    assert view.language == bundle.language == "es"
    # The archetype the store declared not applicable is set aside on
    # both sides: the same questions, never one more for the pages.
    assert measured.record["questions"] == 2
    assert "capability" not in measured.record["by_archetype"]


# --- the scorecard -----------------------------------------------------------

def test_a_scorecard_carries_a_comparison_only_when_its_run_measured_one(bundle_copy):
    bundle = load_bundle(bundle_copy)
    questions = evaluator.load_questions(bundle_copy / "evaluations" / "questions.yaml")
    report = evaluator.evaluate(bundle, questions)
    out = evaluator.write_scorecard(bundle, report, force=True)
    fm, body = parse_document(out.read_text(encoding="utf-8"))
    assert "baseline" not in fm["x_geo"] and "Store pages read" not in body

    pages = {url: f"Alpine Peak Outfitters page {n}: tents, sleeping bags, returns."
             for n, url in enumerate(baseline.source_pages(bundle)[:3])}
    measured = baseline.measure(bundle, questions, urls=[*pages, "https://x.test/a`b\nc"],
                                fetch_text=_fetch(pages))
    assert measured.attach(report) is report
    out = evaluator.write_scorecard(bundle, report, force=True)
    fm, body = parse_document(out.read_text(encoding="utf-8"))
    assert fm["x_geo"]["baseline"] == measured.record
    assert fm["x_geo"]["baseline"]["condition"] == "store pages as text (3 pages, same questions)"
    assert "# Store pages read for the comparison" in body
    assert "a dry run records no verdict for either side" in body
    for url in pages:
        assert f"* `{url}`" in body
    # What could not be read is listed, as one inert line: no backtick,
    # no line break a page address could smuggle into the body.
    assert "Could not be read:" in body
    assert "* `https://x.test/a'b c: HTTP 404`" in body
    # The record survives a reload, and the bundle still lints as it did.
    reloaded = load_bundle(bundle_copy)
    assert reloaded.concepts[evaluator.SCORECARD_PATH].x_geo["baseline"]["pages"] == 3
    _, findings = linter.lint_bundle(bundle_copy)
    assert not [f for f in findings if f.path == evaluator.SCORECARD_PATH]


def test_the_example_scorecard_carries_no_typed_comparison(example_bundle):
    """The example store is fictional: there are no pages a baseline
    could have read, so its scorecard has none (it carried a hand-kept
    one until 2026-11-10), and it says what its judged figures are."""
    fm, body = parse_document(
        (example_bundle / "evaluations" / "geo-scorecard.md").read_text(encoding="utf-8"))
    assert "baseline" not in fm["x_geo"]
    assert "Baseline comparison" not in body and "41,780" not in body
    assert "not the record of a run" in body
    with pytest.raises(BaselineError, match="none of the"):
        baseline.measure(
            load_bundle(example_bundle),
            evaluator.load_questions(example_bundle / "evaluations" / "questions.yaml"),
            fetch_text=_fetch({}))


def test_no_document_states_a_comparison_as_a_number():
    """A comparison is measured on a store or absent, so the documents
    say how it is measured and never state a multiple. The guide said
    "about 22 times less AI reading effort ... measured on the example
    store" until 2026-11-11, and nothing had ever measured it."""
    hits = []
    for path in [REPO / "README.md", *sorted((REPO / "docs").glob("*.md"))]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if TYPED_COMPARISON.search(line):
                hits.append(f"{path.name}:{number}: {line.strip()}")
    assert not hits, hits
    # The pattern catches the forms that were quoted, bold or plain.
    assert TYPED_COMPARISON.search("used about **22 times less** AI reading effort")
    assert TYPED_COMPARISON.search("17× cheaper in the reference bundle")
    assert not TYPED_COMPARISON.search("the same questions, measured both times")


# --- the report --------------------------------------------------------------

def _with_scorecard(bundle_copy, change) -> Bundle:
    path = bundle_copy / "evaluations" / "geo-scorecard.md"
    fm, body = parse_document(path.read_text(encoding="utf-8"))
    change(fm["x_geo"])
    path.write_text(render_document(fm, body), encoding="utf-8")
    return load_bundle(bundle_copy)


def test_the_report_shows_a_before_and_after_only_when_one_was_measured(bundle_copy):
    plain = build_report(load_bundle(bundle_copy))
    assert "answered from the store" not in plain and "reading than the store" not in plain
    assert "own pages read as text" not in plain

    def measured(x_geo):
        x_geo["baseline"] = {
            "condition": "store pages as text (18 pages, same questions)",
            "pages": 18, "coverage": 0.59, "context_tokens_mean": 9628,
        }
    page = build_report(_with_scorecard(bundle_copy, measured))
    assert ">59%<" in page and "answered from the store&#x27;s own pages" in page
    assert "store pages as text (18 pages, same questions)" in page
    assert "against 59% from the store&#x27;s own pages read as text" in page
    assert ">4.0× less<" in page and "2,407 vs 9,628 tokens per question" in page


def test_the_reading_comparison_is_stated_as_it_came_out():
    assert reading_tile({"context_tokens_mean": 2400}, {"context_tokens_mean": 6000}) == (
        "2.5× less", "reading than the store's own pages", "2,400 vs 6,000 tokens per question")
    # It may go the other way, and then it says so.
    assert reading_tile({"context_tokens_mean": 3000}, {"context_tokens_mean": 2000})[0] == "1.5× more"
    assert reading_tile({"context_tokens_mean": 2400}, {}) is None
    for junk in ("9628", True, 0, -5, None):
        assert reading_tile({"context_tokens_mean": 2400}, {"context_tokens_mean": junk}) is None


# --- the command, over real HTTP ---------------------------------------------

class _Store(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    PAGES = {
        "/returns": "<html><head><title>Returns</title><script>var cart=1;</script></head>"
                    "<body><nav>Home Shop</nav><h1>Returns</h1>"
                    "<p>Unused gear can be returned within 30 days.</p></body></html>",
        "/tent": "<html><body><h1>Trail Tent</h1><p>A two person tent, 1.4 kilograms.</p>"
                 "<style>p{color:red}</style></body></html>",
    }

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        body = self.PAGES.get(self.path)
        status = 200 if body is not None else 404
        data = (body or "not found").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def store():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Store)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _disk_bundle(root: Path, base: str) -> Path:
    def write(rel, fm, body):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(fm, body), encoding="utf-8")

    write("policies/returns.md",
          {"type": "Policy", "title": "Returns", "resource": f"{base}/returns"},
          "\nUnused gear can be returned within 30 days.\n")
    write("catalog/tent.md",
          {"type": "Product", "title": "Trail Tent", "resource": f"{base}/tent"},
          "\nA two person tent. It weighs 1.4 kilograms.\n")
    write("store.md",
          {"type": "Store Identity", "title": "The shop", "resource": f"{base}/about"},
          "\nAn outdoor shop in Boulder.\n")
    (root / "evaluations").mkdir()
    (root / "evaluations" / "questions.yaml").write_text(
        evaluator.dump_questions(QUESTIONS[:2]), encoding="utf-8")
    return root


def test_evaluate_baseline_reads_the_stores_pages_through_the_fetch_door(store, tmp_path, capsys):
    root = _disk_bundle(tmp_path / "bundle", store)
    scorecard = root / "evaluations" / "geo-scorecard.md"
    # Loopback is refused like any private host: no page, no baseline,
    # nothing written, exit 2.
    assert cli_mod.main(["evaluate", str(root), "--dry-run", "--baseline", "--write-scorecard"]) == 2
    assert "no baseline: none of the 3 store page(s) could be read" in capsys.readouterr().err
    assert not scorecard.exists()

    assert cli_mod.main(["evaluate", str(root), "--dry-run", "--baseline", "--write-scorecard",
                         "--allow-private-hosts"]) == 0
    out = capsys.readouterr().out
    assert "baseline: store pages as text (2 pages, same questions)" in out
    assert "1 page(s) could not be read:" in out and f"{store}/about: " in out
    fm, body = parse_document(scorecard.read_text(encoding="utf-8"))
    record = fm["x_geo"]["baseline"]
    assert record["pages"] == 2 and record["pages_unreadable"] == 1
    assert record["retrieval_hit_rate"] == 1.0 and "coverage" not in record
    assert f"* `{store}/returns`" in body and f"* `{store}/tent`" in body
    # The pages were read as text: the script and the style sheet are
    # not part of what was searched or counted.
    text = baseline._fetch_page_text(f"{store}/returns", 10.0, True, None)
    assert "Unused gear can be returned within 30 days." in text and "var cart" not in text

    # Named pages instead of the cited ones; a missing file is a refusal.
    urls = tmp_path / "pages.txt"
    urls.write_text(f"{store}/tent\n", encoding="utf-8")
    assert cli_mod.main(["evaluate", str(root), "--dry-run", "--baseline-urls", str(urls),
                         "--allow-private-hosts"]) == 0
    assert "baseline: store pages as text (1 page, same questions)" in capsys.readouterr().out
    assert cli_mod.main(["evaluate", str(root), "--dry-run", "--baseline-urls",
                         str(tmp_path / "absent.txt")]) == 2
    # Without the flag nothing is fetched and no comparison is recorded.
    assert cli_mod.main(["evaluate", str(root), "--dry-run", "--write-scorecard", "--force"]) == 0
    fm, _ = parse_document(scorecard.read_text(encoding="utf-8"))
    assert "baseline" not in fm["x_geo"]


def test_an_attached_baseline_is_a_copy(tmp_path):
    measured = Baseline(record={"pages": 1}, pages=["https://shop.test/a"],
                        unreadable=[("https://shop.test/b", "HTTP 500")])
    report = measured.attach(evaluator.Report(results=[], generated_by="x", dry_run=True))
    report.baseline["pages"] = 99
    assert measured.record == {"pages": 1}
    assert report.baseline_unreadable == ["https://shop.test/b: HTTP 500"]
