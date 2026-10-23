"""Review 2026-10-21, phase U3 (operator-loop correctness): the
documented remedies and the daily commands do what their words say.
Each test drives one finding."""

from __future__ import annotations

import datetime as dt
import json

import pytest
import yaml

from okf_web import cli as cli_mod
from okf_web import drift, feed, surveyor
from okf_web.evaluator import generate_questions
from okf_web.linter import lint_concept
from okf_web.llm import StaticClient
from okf_web.model import Concept, load_bundle, localized_view
from okf_web.publisher import select_publishable, withhold_reason
from okf_web.retrieval import EmbeddingIndex, HashingEmbedder
from okf_web.structured import write_llms_txt
from okf_web.viewer import build_viewer

TODAY = dt.date(2026, 8, 5)

_FEED_XML = """<?xml version="1.0"?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0"><channel>
<item>
  <g:id>SKU-9</g:id>
  <g:title>Camp Mug</g:title>
  <g:description>An enamel camp mug for the trail.</g:description>
  <g:link>https://shop.example/p/camp-mug</g:link>
  <g:brand>Alpine Peak</g:brand>
  <g:price>12.00 USD</g:price>
  <g:availability>in_stock</g:availability>
</item>
</channel></rss>
"""


def _concept(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- L-U2: the W041 remedy is never a silent no-op ---------------------------------

def test_approve_with_a_new_stale_after_is_a_change_even_when_already_approved(bundle_copy, capsys):
    rel = "faq/general.md"
    concept = load_bundle(bundle_copy).concepts[rel]
    reviewer = str(concept.frontmatter["verified"][0]["by"]).split(":", 1)[1]
    before = str(concept.frontmatter.get("stale_after"))
    # The same reviewer again, without a date: nothing changes, as documented.
    assert cli_mod.main(["review", "approve", str(bundle_copy), rel, "--by", reviewer]) == 0
    assert "already approved" in capsys.readouterr().out
    assert str(load_bundle(bundle_copy, use_cache=False).concepts[rel].frontmatter["stale_after"]) == before
    # With a date, the date lands (the remedy USER-GUIDE gives for W041).
    assert cli_mod.main(["review", "approve", str(bundle_copy), rel, "--by", reviewer,
                         "--stale-after", "2029-03-01"]) == 0
    after = load_bundle(bundle_copy, use_cache=False).concepts[rel]
    assert str(after.frontmatter["stale_after"]).startswith("2029-03-01")
    assert after.status == "stable"


# --- L-U3: drift is defined against pages; feed rows have none -------------------------

def test_drift_leaves_feed_derived_concepts_to_the_next_ingest(tmp_path, capsys):
    root = tmp_path / "b"
    root.mkdir()
    feed_path = tmp_path / "products.xml"
    feed_path.write_text(_FEED_XML, encoding="utf-8")
    result = feed.ingest_feed(feed_path, root, today=TODAY)
    assert result.written == ["catalog/products/camp-mug.md"]
    concept = load_bundle(root, use_cache=False).concepts["catalog/products/camp-mug.md"]
    assert concept.generated_by == feed.FEED_ACTOR and concept.source_hash

    fetched = []

    def fetch_text(url):
        fetched.append(url)
        return "a product page that never hashes like a feed row"

    report = drift.check_bundle(root, fetch_text=fetch_text)
    assert report.feed_derived == ["catalog/products/camp-mug.md"]
    assert report.drifted == [] and report.clean and fetched == []
    # The CLI says so and exits clean.
    code = cli_mod.main(["drift", str(root)])
    out = capsys.readouterr().out
    assert code == 0 and "1 feed-derived" in out


# --- L-U4: --include-machine-confirmed ships low-risk drafts, nothing else --------------

def test_include_machine_confirmed_never_ships_a_deprecated_concept(bundle_copy):
    bundle = load_bundle(bundle_copy)
    rel = next(r for r, c in bundle.concepts.items() if c.status == "stable" and not c.is_high_risk)
    path = bundle_copy / rel
    path.write_text(path.read_text(encoding="utf-8").replace("status: stable", "status: deprecated", 1),
                    encoding="utf-8")
    bundle = load_bundle(bundle_copy, use_cache=False)
    concept = bundle.concepts[rel]
    assert concept.status == "deprecated"
    include, withheld = select_publishable(bundle, True, TODAY, "warn")
    assert rel in withheld and rel not in include
    assert withhold_reason(concept, TODAY, "warn", True).startswith("status 'deprecated'")
    # The viewer names the status instead of calling it a draft.
    html = build_viewer(bundle, today=TODAY)
    assert "status deprecated: only stable concepts publish" in html


# --- L-U6: a generated question set keeps its paraphrases -------------------------------

def test_generated_questions_keep_the_paraphrase_and_the_cli_writes_it(bundle_copy):
    response = (
        "questions:\n"
        "  - id: g1\n    archetype: policy\n    question: What is the return window?\n"
        "    paraphrase: How long do I have to send something back?\n"
        "  - id: g2\n    archetype: discovery\n    question: Which tents fit two people?\n"
    )
    bundle = load_bundle(bundle_copy)
    questions = generate_questions(bundle, StaticClient([response]), per_archetype=1)
    assert [q.paraphrase for q in questions] == ["How long do I have to send something back?", ""]

    out = bundle_copy / "evaluations" / "questions.yaml"
    out.unlink()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli_mod, "_llm", lambda args: StaticClient([response]))
        assert cli_mod.main(["questions", str(bundle_copy), "--per-archetype", "1"]) == 0
    written = yaml.safe_load(out.read_text(encoding="utf-8"))["questions"]
    assert written[0]["paraphrase"] == "How long do I have to send something back?"
    assert "paraphrase" not in written[1]


# --- L-U7: the view's language is one normalized tag ----------------------------------------

def test_localized_view_normalizes_the_language_tag(bundle_copy):
    bundle = load_bundle(bundle_copy)
    lower = localized_view(bundle, "es")
    for spelling in ("ES", "es_ES", " es "):
        view = localized_view(bundle, spelling)
        assert view.language == lower.language
        assert {rel: c.title for rel, c in view.concepts.items()} == {
            rel: c.title for rel, c in lower.concepts.items()}
        assert view.indexes["index.md"].title == lower.indexes["index.md"].title
    # The es view really carries the translation, whatever the spelling.
    assert localized_view(bundle, "ES").concepts["faq/general.md"].title != \
        bundle.concepts["faq/general.md"].title


# --- L-U8: a sale is valid through ends_at ---------------------------------------------------

_PROMO = (
    "---\ntype: Promotion\ntitle: Flash sale\ndescription: Ten percent off everything.\n"
    "tags: [sale]\nstatus: stable\nstale_after: {stale}\n"
    "verified:\n  - by: human:owner@shop.example\n    at: 2026-08-01T00:00:00Z\n"
    "sources:\n  - id: s\n    resource: https://shop.example/sale\n"
    "x_geo:\n  risk: b\n  intents: [promotion]\n  starts_at: 2026-08-01\n  ends_at: 2026-08-31\n"
    "  code: TEN\n---\n\nTen percent off.[^s]\n\n[^s]: s.\n"
)


def test_a_promotion_is_valid_through_its_last_day(tmp_path):
    root = tmp_path / "b"
    _concept(root, "promotions/flash.md", _PROMO.format(stale="2026-09-01T00:00:00Z"))
    concept = load_bundle(root, use_cache=False).concepts["promotions/flash.md"]
    last_day, day_after = dt.date(2026, 8, 31), dt.date(2026, 9, 1)
    assert not concept.promo_expired(last_day) and not concept.is_stale(last_day)
    assert concept.promo_expired(day_after) and concept.is_stale(day_after)
    # The surveyor's stamp lints clean; a day later is W027; the sale's
    # last day publishes under the strictest freshness.
    assert not any(f.code == "W027" for f in lint_concept(concept, today=TODAY))
    include, _ = select_publishable(load_bundle(root, use_cache=False), False, last_day, "withhold")
    assert include == {"promotions/flash.md"}
    _concept(root, "promotions/flash.md", _PROMO.format(stale="2026-09-02T00:00:00Z"))
    late = load_bundle(root, use_cache=False).concepts["promotions/flash.md"]
    assert any(f.code == "W027" for f in lint_concept(late, today=TODAY))


def test_the_surveyor_stamps_the_midnight_after_the_sale(tmp_path):
    response = (
        '<<<CONCEPT path="promotions/flash.md">>>\n'
        "---\ntype: Promotion\ntitle: Flash sale\ndescription: Ten percent off everything.\n"
        "tags: [sale]\nsources:\n  - id: s\n    resource: https://shop.example/sale\n"
        "x_geo:\n  risk: b\n  intents: [promotion]\n  starts_at: 2027-01-01\n"
        "  ends_at: 2027-03-01\n  code: TEN\n---\n\nTen percent off.[^s]\n\n[^s]: s.\n"
        "<<<END>>>\n"
    )
    result = surveyor.SurveyResult()
    surveyor.survey_page("https://shop.example/sale", "page text", tmp_path,
                         StaticClient([response]), result)
    concept = load_bundle(tmp_path, use_cache=False).concepts["promotions/flash.md"]
    assert str(concept.frontmatter["stale_after"]) == "2027-03-02T00:00:00Z"
    assert not concept.is_stale(dt.date(2027, 3, 1)) and concept.is_stale(dt.date(2027, 3, 2))


# --- L-U10: a torn embeddings cache entry is a miss, never an exception ------------------------

def test_malformed_embedding_cache_entries_are_re_embedded(bundle_copy):
    bundle = load_bundle(bundle_copy)
    EmbeddingIndex(HashingEmbedder(), cache_path=bundle_copy / ".embeddings.json").build(bundle)
    cache = json.loads((bundle_copy / ".embeddings.json").read_text(encoding="utf-8"))
    entries = cache["entries"]
    rels = sorted(entries)[:5]
    entries[rels[0]]["vector"] = None
    entries[rels[1]] = "not a dict"
    entries[rels[2]]["vector"] = entries[rels[2]]["vector"][:3]  # wrong dimension
    entries[rels[3]]["vector"] = ["x"] * len(entries[rels[3]]["vector"])
    entries[rels[4]]["vector"] = []
    (bundle_copy / ".embeddings.json").write_text(json.dumps(cache), encoding="utf-8")
    again = EmbeddingIndex(HashingEmbedder(), cache_path=bundle_copy / ".embeddings.json")
    fresh = again.build(bundle)
    assert fresh == 5
    assert again(bundle, "return window", top_k=3)
    repaired = json.loads((bundle_copy / ".embeddings.json").read_text(encoding="utf-8"))["entries"]
    assert all(isinstance(repaired[rel]["vector"], list) and repaired[rel]["vector"] for rel in rels)


# --- L-U11: llms.txt lists the guides the profile defines ---------------------------------------

def test_llms_txt_lists_guides_under_guides_and_compatibility(bundle_copy, tmp_path):
    bundle = load_bundle(bundle_copy)
    guides = {rel for rel, c in bundle.concepts.items() if c.type in ("Buying Guide", "Ownership Guide")}
    assert guides, "the example carries guides"
    published = {rel for rel, c in bundle.concepts.items() if c.status == "stable"}
    dist = tmp_path / "dist"
    rel = write_llms_txt(dist, bundle, published, "https://shop.example/.well-known/okf")
    text = (dist / rel).read_text(encoding="utf-8")
    section = text.split("## Guides and compatibility", 1)[1].split("\n## ", 1)[0]
    assert any(guide in section for guide in guides & published)


# --- A-U9: report writes into the bundle, so it holds the lock ----------------------------------

def test_report_holds_the_bundle_lock():
    parser = cli_mod.build_parser()
    args = parser.parse_args(["report", "b"])
    assert cli_mod._lock_for(args) == (True, False)
