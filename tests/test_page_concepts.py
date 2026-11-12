"""A surveyed page can yield several concepts, and the write gate keeps
each of them. From 2026-08-12 to 2026-11-12 it did not: path stability
sent every draft of a URL to the first concept that URL owned, so a
page kept only the last concept it yielded, under the first one's path
(a Product Collection in `store.md`). No test page had ever yielded
more than one concept; the first real surveys did (2026-11-11: six
pages, nineteen drafts written, six concepts left). Path stability is
per concept: a draft is written in place, takes over a concept the
producer renamed, or is a further concept from the same page."""

from __future__ import annotations

import pytest

from okf_web import surveyor
from okf_web.model import load_bundle

URL = "https://shop.test/"
OTHER = "https://shop.test/help"


def _block(path, kind, title, url=URL):
    return (f'<<<CONCEPT path="{path}">>>\n---\ntype: {kind}\ntitle: {title}\n'
            f"resource: {url}\n---\n\nBody for {title}.\n<<<END>>>\n")


STORE = ("store.md", "Store Identity", "The store")
FAQ = ("faq/general.md", "FAQ", "Common questions")
OVENS = ("catalog/ovens.md", "Product Collection", "Ovens")


class Scripted:
    """One reply a call, in order; a call past the script fails the test."""

    model = "static/pages"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system, user, max_tokens=0):
        self.calls += 1
        return self.replies.pop(0)


def _reply(*blocks, url=URL):
    return "".join(_block(path, kind, title, url) for path, kind, title in blocks)


def _survey(root, text, *blocks, url=URL):
    result = surveyor.SurveyResult()
    surveyor.survey_page(url, text, root, Scripted(_reply(*blocks, url=url)), result)
    assert result.quarantined == [] and result.errors == []
    return result


def _shape(root):
    return {rel: (c.type, c.title) for rel, c in load_bundle(root).concepts.items()}


def test_a_page_keeps_every_concept_it_yields(tmp_path):
    result = _survey(tmp_path, "v1", STORE, FAQ, OVENS)
    assert result.written == ["store.md", "faq/general.md", "catalog/ovens.md"]
    assert result.collisions == [] and result.proposed == []
    assert _shape(tmp_path) == {
        "store.md": ("Store Identity", "The store"),
        "faq/general.md": ("FAQ", "Common questions"),
        "catalog/ovens.md": ("Product Collection", "Ovens"),
    }
    # Every one of them names the page as its source and carries its text's hash.
    hashes = {c.source_hash for c in load_bundle(tmp_path).concepts.values()}
    assert hashes == {surveyor.stable_page_hash("v1")}
    assert {c.resource for c in load_bundle(tmp_path).concepts.values()} == {URL}


def test_the_whole_survey_keeps_them_and_a_second_page_still_collides_by_name(tmp_path):
    replies = {URL: _reply(STORE, FAQ), OTHER: _reply(FAQ, ("policies/returns.md", "Policy", "Returns"),
                                                      url=OTHER)}

    class ByPage:
        model = "static/pages"

        def complete(self, system, user, max_tokens=0):
            return replies[user.split("\n", 1)[0].split(": ", 1)[1].strip()]

    result = surveyor.survey([URL, OTHER], tmp_path, ByPage(), fetcher=lambda url: f"text of {url}")
    assert result.written == ["store.md", "faq/general.md", "faq/general-help.md",
                              "policies/returns.md"]
    assert result.collisions == [
        f"faq/general.md already belongs to {URL}; wrote faq/general-help.md instead"]
    bundle = load_bundle(tmp_path)
    assert bundle.get("faq/general.md").resource == URL
    assert bundle.get("faq/general-help.md").resource == OTHER
    assert bundle.get("policies/returns.md").resource == OTHER


def test_a_second_reading_updates_each_concept_where_it_is(tmp_path):
    _survey(tmp_path, "v1", STORE, FAQ, OVENS)
    result = _survey(tmp_path, "v2", ("store.md", "Store Identity", "The store, renamed"),
                     FAQ, ("catalog/ovens.md", "Product Collection", "Ovens and proofers"))
    assert result.written == ["store.md", "faq/general.md", "catalog/ovens.md"]
    assert _shape(tmp_path) == {
        "store.md": ("Store Identity", "The store, renamed"),
        "faq/general.md": ("FAQ", "Common questions"),
        "catalog/ovens.md": ("Product Collection", "Ovens and proofers"),
    }


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_a_renamed_concept_keeps_its_path_whatever_the_order(tmp_path, order):
    _survey(tmp_path, "v1", STORE, FAQ, OVENS)
    blocks = [STORE, ("faq/questions-and-answers.md", "FAQ", "Questions and answers"), OVENS]
    result = _survey(tmp_path, "v2", *(blocks[i] for i in order))
    assert sorted(result.written) == ["catalog/ovens.md", "faq/general.md", "store.md"]
    assert _shape(tmp_path) == {
        "store.md": ("Store Identity", "The store"),
        "faq/general.md": ("FAQ", "Questions and answers"),  # the old path, the new text
        "catalog/ovens.md": ("Product Collection", "Ovens"),
    }


def test_a_further_concept_of_a_type_the_page_already_has_is_new(tmp_path):
    _survey(tmp_path, "v1", STORE, FAQ)
    shipping = ("faq/shipping.md", "FAQ", "Shipping questions")
    result = _survey(tmp_path, "v2", STORE, shipping, FAQ)
    assert result.written == ["store.md", "faq/shipping.md", "faq/general.md"]
    assert _shape(tmp_path)["faq/general.md"] == ("FAQ", "Common questions")
    assert _shape(tmp_path)["faq/shipping.md"] == ("FAQ", "Shipping questions")
    # Two new names for one old concept: the first takes its place, the second is new.
    returns = ("faq/returns.md", "FAQ", "Returns questions")
    _survey(tmp_path, "v3", STORE, FAQ, ("faq/delivery.md", "FAQ", "Delivery questions"), returns)
    assert _shape(tmp_path) == {
        "store.md": ("Store Identity", "The store"),
        "faq/general.md": ("FAQ", "Common questions"),
        "faq/shipping.md": ("FAQ", "Delivery questions"),
        "faq/returns.md": ("FAQ", "Returns questions"),
    }


def test_a_pages_only_concept_renamed_and_retyped_leaves_no_twin(tmp_path):
    _survey(tmp_path, "v1", ("faq/shipping.md", "FAQ", "Shipping"))
    result = _survey(tmp_path, "v2", ("policies/shipping.md", "Policy", "Shipping policy"))
    assert result.written == ["faq/shipping.md"]
    assert _shape(tmp_path) == {"faq/shipping.md": ("Policy", "Shipping policy")}
    # With a second concept beside it the retyped one is told apart: both are kept.
    _survey(tmp_path, "v3", ("policies/shipping.md", "Policy", "Shipping policy"),
            ("guides/packing.md", "Buying Guide", "Packing"))
    assert _shape(tmp_path) == {
        "faq/shipping.md": ("Policy", "Shipping policy"),
        "guides/packing.md": ("Buying Guide", "Packing"),
    }


def test_two_blocks_under_one_path_are_two_concepts(tmp_path):
    first = ("faq/general.md", "FAQ", "Ordering")
    second = ("faq/general.md", "FAQ", "Delivery")
    result = _survey(tmp_path, "v1", first, second)
    assert result.written == ["faq/general.md", "faq/general-2.md"]
    assert _shape(tmp_path) == {"faq/general.md": ("FAQ", "Ordering"),
                                "faq/general-2.md": ("FAQ", "Delivery")}
    # The same reply again lands on the same two paths, and a third takes the next number
    # that no block of the reply uses.
    result = _survey(tmp_path, "v2", first, ("faq/general-2.md", "FAQ", "Delivery, as named"),
                     second, ("faq/general.md", "FAQ", "Payment"))
    assert result.written == ["faq/general.md", "faq/general-2.md", "faq/general-3.md",
                              "faq/general-4.md"]
    assert _shape(tmp_path) == {
        "faq/general.md": ("FAQ", "Ordering"),
        "faq/general-2.md": ("FAQ", "Delivery, as named"),
        "faq/general-3.md": ("FAQ", "Delivery"),
        "faq/general-4.md": ("FAQ", "Payment"),
    }


def test_a_page_whose_text_did_not_change_is_not_read_again(tmp_path):
    _survey(tmp_path, "v1", STORE, FAQ)
    silent = Scripted()  # a call would fail: the script is empty
    result = surveyor.SurveyResult()
    surveyor.survey_page(URL, "v1", tmp_path, silent, result)
    assert result.skipped_unchanged == [URL] and silent.calls == 0
    # The page changes and yields one concept fewer: the one it dropped keeps its old
    # text and hash, and the page still counts as read at the new text.
    _survey(tmp_path, "v2", ("store.md", "Store Identity", "The store, renamed"))
    bundle = load_bundle(tmp_path)
    assert bundle.get("faq/general.md").source_hash == surveyor.stable_page_hash("v1")
    assert bundle.get("store.md").source_hash == surveyor.stable_page_hash("v2")
    for _ in range(2):
        result = surveyor.SurveyResult()
        surveyor.survey_page(URL, "v2", tmp_path, silent, result)
        assert result.skipped_unchanged == [URL] and silent.calls == 0


def test_an_approved_concept_among_a_pages_several_gets_a_proposal_of_its_own(tmp_path):
    _survey(tmp_path, "v1", STORE, FAQ, OVENS)
    approved = tmp_path / "faq" / "general.md"
    approved.write_text(approved.read_text(encoding="utf-8").replace(
        "status: draft", "status: stable"), encoding="utf-8")
    kept = approved.read_text(encoding="utf-8")
    result = _survey(tmp_path, "v2", STORE, ("faq/general.md", "FAQ", "Common questions, revised"),
                     ("catalog/ovens.md", "Product Collection", "Ovens and proofers"))
    assert result.written == ["store.md", "catalog/ovens.md"]
    assert result.proposed == ["faq/general.md"]
    assert approved.read_text(encoding="utf-8") == kept  # never machine-overwritten
    proposal = tmp_path / "_review" / "proposed" / "faq" / "general.md"
    assert "Common questions, revised" in proposal.read_text(encoding="utf-8")
    assert _shape(tmp_path)["catalog/ovens.md"] == ("Product Collection", "Ovens and proofers")
    assert sorted(p.name for p in (tmp_path / "_review" / "proposed").rglob("*.md")) == ["general.md"]


def test_the_gate_alone_keeps_a_urls_second_concept_and_follows_a_rename(tmp_path):
    def place(rel, kind, title, **kwargs):
        result = surveyor.SurveyResult()
        fm = {"type": kind, "title": title, "resource": URL, "status": "draft"}
        return surveyor.place_draft(tmp_path, URL, rel, fm, f"Body for {title}.\n", result, **kwargs)

    # A producer that says nothing about the page's other drafts: one draft a call.
    assert place("store.md", "Store Identity", "The store") == "store.md"
    assert place("faq/general.md", "FAQ", "Common questions") == "faq/general.md"  # not store.md
    assert place("faq/questions.md", "FAQ", "Questions") == "faq/general.md"       # a rename
    assert place("store.md", "Store Identity", "The store, again") == "store.md"   # in place
    assert _shape(tmp_path) == {"store.md": ("Store Identity", "The store, again"),
                                "faq/general.md": ("FAQ", "Questions")}
    # With the page's paths declared, the gate adds where each draft landed, and a
    # later draft never takes a place an earlier one of the same page was given.
    claimed = {"faq/a.md", "faq/b.md"}
    assert place("faq/a.md", "FAQ", "A", claimed=claimed) == "faq/general.md"
    assert place("faq/b.md", "FAQ", "B", claimed=claimed) == "faq/b.md"
    assert claimed == {"faq/a.md", "faq/b.md", "faq/general.md"}
    assert _shape(tmp_path)["faq/general.md"] == ("FAQ", "A")
    assert _shape(tmp_path)["faq/b.md"] == ("FAQ", "B")
