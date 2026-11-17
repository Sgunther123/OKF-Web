"""Answer blocks: the vouched concepts as plain text a page can show.

The third derived output, beside JSON-LD and llms.txt. It restates, so
it holds the JSON-LD gate (a named human vouched for the concept) and
adds two of its own: a concept past its ``stale_after`` is never
printed on a page, and a capability is executed, never printed.
"""

import datetime as dt
import json

import pytest

from okf_web import review
from okf_web.model import load_bundle
from okf_web.publisher import publish
from okf_web.structured import ANSWER_SCHEMA, ANSWERS_INDEX, answer_for, write_answers

SITE = "https://www.alpinepeakoutfitters.example"
BASE = SITE + "/.well-known/okf"


def _publish(example_bundle, tmp_path, **kwargs):
    result = publish(example_bundle, tmp_path / "dist", site=SITE, **kwargs)
    return result, tmp_path / "dist"


def _answers(dist):
    """Every answer file in a dist, by its path under the dist."""
    return {
        str(path.relative_to(dist)): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((dist / "answers").rglob("*.json"))
        if path.name != "index.json"
    }


def _concept(tmp_path, name="policies/returns.md", *, body=None, resource=None,
             kind="Policy", extra=""):
    """A one-concept bundle in draft, ready for a review to stamp."""
    root = tmp_path / "bundle"
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    resource = resource or "https://shop.example/returns"
    target.write_text(
        "---\n"
        f"type: {kind}\n"
        "title: Returns\n"
        "description: Returns are accepted within 30 days.\n"
        f"resource: {resource}\n"
        "status: draft\n"
        "sources:\n"
        f"  - id: page\n    resource: {resource}\n"
        f"{extra}"
        "x_geo:\n"
        "  risk: b\n"
        "---\n\n"
        + (body or "Opening line.[^page]\n\n# Window\n\nThirty days from delivery.[^page]\n\n"
                   "[^page]: the returns page.\n"),
        encoding="utf-8",
    )
    return root


# --- what is restated, and what is not ------------------------------------

def test_the_example_restates_only_what_a_named_human_vouched_for(example_bundle, tmp_path):
    result, dist = _publish(example_bundle, tmp_path)
    written = set(_answers(dist))
    bundle = load_bundle(example_bundle)
    vouched = {
        "answers/" + rel[:-3] + ".json"
        for rel, concept in bundle.concepts.items()
        if concept.trust_tier in ("human-reviewed", "human-attested")
        and concept.type not in ("Attested Computation", "GEO Scorecard")
        and not rel.startswith("l10n/")
        and concept.frontmatter.get("status") == "stable"
    }
    assert written == vouched and len(written) == 11
    # Published in the bundle, but only machine-checked: not restated.
    assert "answers/catalog/products/ridgeline-20-sleeping-bag.json" not in written
    # A draft never got this far.
    assert "answers/policies/warranty.json" not in written
    # Every file is in the result, with the index last.
    assert set(result.structured) >= written | {ANSWERS_INDEX}
    assert result.structured[-1] == ANSWERS_INDEX


def test_a_capability_and_a_scorecard_are_never_printed(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    assert not (dist / "answers" / "capabilities").exists()
    assert not (dist / "answers" / "evaluations").exists()
    bundle = load_bundle(example_bundle)
    for rel, concept in bundle.concepts.items():
        if concept.type in ("Attested Computation", "GEO Scorecard"):
            assert answer_for(concept, BASE) is None, rel


def test_a_translation_is_not_restated(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    assert (dist / "l10n" / "es" / "faq" / "general.md").exists()
    assert not (dist / "answers" / "l10n").exists()


def test_a_draft_and_a_machine_checked_concept_have_no_answer(example_bundle):
    bundle = load_bundle(example_bundle)
    assert answer_for(bundle.concepts["policies/warranty.md"], BASE) is None
    assert answer_for(
        bundle.concepts["catalog/products/ridgeline-20-sleeping-bag.md"], BASE
    ) is None


def test_a_wholesale_sign_off_is_restated_under_its_own_label(tmp_path):
    root = _concept(tmp_path, "catalog/pack.md", kind="Product")
    review.batch_approve(load_bundle(root), "owner@shop.example")
    publish(root, tmp_path / "dist")
    answer = json.loads((tmp_path / "dist/answers/catalog/pack.json").read_text())
    assert answer["verified"]["tier"] == "human-attested"


# --- the shape of one answer ----------------------------------------------

def test_an_answer_is_the_concept_as_plain_text(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    answer = _answers(dist)["answers/policies/returns.json"]
    assert answer["schema"] == ANSWER_SCHEMA == "okf-web/answer/1"
    assert answer["type"] == "Policy"
    assert answer["title"] == "Return & Exchange Policy"
    assert answer["summary"].startswith("Items may be returned within 60 days")
    headings = [section["heading"] for section in answer["sections"]]
    assert headings == ["Window and condition", "Exclusions",
                        "Refunds and exchanges", "How to start a return"]
    assert answer["verified"] == {"tier": "human-reviewed", "at": "2026-08-05T15:11:38Z"}
    assert answer["subjectOf"] == BASE + "/policies/returns.md"
    assert answer["page"] == SITE + "/policies/returns"
    assert answer["expires"] == "2028-02-01T00:00:00Z"
    assert answer["inLanguage"] == "en"
    assert set(answer) == {"schema", "type", "title", "summary", "sections",
                           "verified", "subjectOf", "page", "expires", "inLanguage"}


def test_the_text_carries_no_markdown_and_no_footnote(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    for rel, answer in _answers(dist).items():
        text = " ".join([answer["title"], answer["summary"]]
                        + [s["heading"] + " " + s["text"] for s in answer["sections"]])
        assert "[^" not in text and "](" not in text and "**" not in text, rel
        assert "\n" not in text and "  " not in text, rel
        assert all(section["text"] for section in answer["sections"]), rel


def test_text_before_the_first_heading_is_kept(tmp_path):
    root = _concept(tmp_path)
    review.approve(load_bundle(root), "policies/returns.md", "owner@shop.example")
    answer = answer_for(load_bundle(root).concepts["policies/returns.md"], "/.well-known/okf")
    assert answer["sections"] == [
        {"heading": "", "text": "Opening line."},
        {"heading": "Window", "text": "Thirty days from delivery."},
    ]
    # An undeclared bundle speaks no language and names none.
    assert "inLanguage" not in answer


def test_no_reviewer_is_named_in_any_answer(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    bundle = load_bundle(example_bundle)
    reviewers = {
        str(entry.get("by", "")).split(":", 1)[-1]
        for concept in bundle.concepts.values()
        for entry in concept.verified_entries
        if str(entry.get("by", "")).startswith(("human:", "human-batch:"))
    }
    assert len(reviewers) >= 4
    for path in (dist / "answers").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        for reviewer in reviewers:
            assert reviewer not in text, (path.name, reviewer)


def test_a_live_value_is_never_an_answer(example_bundle, tmp_path):
    """The live-values rule survives this surface too: what is printed
    is concept text, and a price or a stock level is not concept text."""
    _, dist = _publish(example_bundle, tmp_path)
    product = _answers(dist)["answers/catalog/products/alpine-2-tent.json"]
    assert "offers" not in product and "price" not in product
    assert "availability" not in product and "stock" not in product


# --- freshness ------------------------------------------------------------

def test_a_stale_concept_is_published_under_a_warning_but_never_printed(example_bundle, tmp_path):
    future = dt.date(2028, 12, 1)  # past every stale_after in the example
    result, dist = _publish(example_bundle, tmp_path, today=future)
    # The default policy ships stale concepts with a warning ...
    assert "policies/returns.md" in result.published
    assert any(rel.startswith("jsonld/") for rel in result.structured)
    # ... and a page still shows none of them, nor an empty index.
    assert not (dist / "answers").exists()
    assert not any(rel.startswith("answers/") for rel in result.structured)


def test_the_publishers_clock_decides_not_the_wall_clock(example_bundle):
    concept = load_bundle(example_bundle).concepts["promotions/fall-clearance.md"]
    assert concept.stale_after_iso == "2028-01-01T00:00:00Z"
    assert answer_for(concept, BASE, today=dt.date(2027, 12, 31)) is not None
    # SPEC §5.5: stale from the instant itself.
    assert answer_for(concept, BASE, today=dt.date(2028, 1, 1)) is None


# --- the index ------------------------------------------------------------

def test_the_index_names_every_answer_by_its_page(example_bundle, tmp_path):
    _, dist = _publish(example_bundle, tmp_path)
    index = json.loads((dist / ANSWERS_INDEX).read_text(encoding="utf-8"))
    answers = _answers(dist)
    assert index["schema"] == "okf-web/answers-index/1"
    assert index["answers"] == sorted(answers)
    assert index["pages"][SITE + "/faq"] == ["answers/faq/general.json"]
    listed = [rel for rels in index["pages"].values() for rel in rels]
    assert sorted(listed) == sorted(answers)
    for page, rels in index["pages"].items():
        for rel in rels:
            assert answers[rel]["page"] == page
    assert list(index["pages"]) == sorted(index["pages"])


def test_two_concepts_about_one_page_are_both_listed_in_order(tmp_path):
    root = _concept(tmp_path, "policies/returns.md")
    _concept(tmp_path, "faq/returns.md", kind="FAQ",
             body="# Can I return it?\n\nYes, within thirty days.[^page]\n\n[^page]: the page.\n")
    for rel in ("faq/returns.md", "policies/returns.md"):
        review.approve(load_bundle(root), rel, "owner@shop.example")
    publish(root, tmp_path / "dist")
    index = json.loads((tmp_path / "dist" / ANSWERS_INDEX).read_text())
    assert index["pages"] == {"https://shop.example/returns": [
        "answers/faq/returns.json", "answers/policies/returns.json"]}


def test_a_concept_about_no_web_page_has_an_answer_and_no_page(tmp_path):
    root = _concept(tmp_path)
    review.approve(load_bundle(root), "policies/returns.md", "owner@shop.example")
    bundle = load_bundle(root)
    concept = bundle.concepts["policies/returns.md"]
    for address in ("javascript:alert(1)", "ftp://shop.example/returns", "/returns", ""):
        concept.frontmatter["resource"] = address
        answer = answer_for(concept, "/.well-known/okf")
        assert answer is not None and "page" not in answer, address
    dist = tmp_path / "out"
    dist.mkdir()
    written = write_answers(dist, bundle, set(bundle.concepts), "/.well-known/okf")
    assert written == ["answers/policies/returns.json", ANSWERS_INDEX]
    assert json.loads((dist / ANSWERS_INDEX).read_text())["pages"] == {}


def test_a_dist_with_no_answer_has_no_index(tmp_path):
    root = _concept(tmp_path)  # a draft: nothing vouched
    bundle = load_bundle(root)
    dist = tmp_path / "out"
    dist.mkdir()
    assert write_answers(dist, bundle, set(bundle.concepts), "/.well-known/okf") == []
    assert not (dist / "answers").exists()


def test_only_published_concepts_are_restated(example_bundle, tmp_path):
    bundle = load_bundle(example_bundle)
    dist = tmp_path / "out"
    dist.mkdir()
    written = write_answers(dist, bundle, {"faq/general.md", "no/such.md"}, BASE)
    assert written == ["answers/faq/general.json", ANSWERS_INDEX]


# --- the files in a dist --------------------------------------------------

def test_the_manifest_covers_every_answer_file(example_bundle, tmp_path):
    result, dist = _publish(example_bundle, tmp_path)
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    for rel in result.structured:
        if rel.startswith("answers/"):
            assert rel in manifest["files"], rel


def test_no_structured_flag_writes_no_answer(example_bundle, tmp_path):
    result, dist = _publish(example_bundle, tmp_path, structured=False)
    assert result.structured == [] and not (dist / "answers").exists()


def test_publishing_twice_writes_the_same_bytes(example_bundle, tmp_path):
    first = publish(example_bundle, tmp_path / "a", site=SITE)
    second = publish(example_bundle, tmp_path / "b", site=SITE)
    assert first.structured == second.structured
    for rel in first.structured:
        if rel.startswith("answers/"):
            assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()


@pytest.mark.parametrize("hostile", [
    "</script><script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "Tom & Jerry   line",
])
def test_an_answer_file_is_inert_whatever_the_concept_says(tmp_path, hostile):
    """A reader prints these strings; the file itself must stay inert
    wherever it is pasted (EDGE-CASES E3), and say exactly what the
    concept said once parsed."""
    root = _concept(tmp_path, body=f"# Note\n\n{hostile}[^page]\n\n[^page]: the page.\n")
    review.approve(load_bundle(root), "policies/returns.md", "owner@shop.example")
    publish(root, tmp_path / "dist")
    raw = (tmp_path / "dist/answers/policies/returns.json").read_text(encoding="utf-8")
    assert "<" not in raw and ">" not in raw and "&" not in raw
    assert " " not in raw
    answer = json.loads(raw)
    assert answer["sections"][0]["text"] == " ".join(hostile.split())
