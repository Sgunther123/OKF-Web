"""A survey that cannot read every page (`survey --limit`) and the
question set written from what it read. The first real capped survey
(2026-11-11: a 218-page dealer's site, six pages) read the home page
twice, the about page, an HTML site map, the contact page and a links
page, and then lost its whole question set to one line of the model's
reply that was not YAML. Two rules: the pages a limit keeps are the
useful ones, and a question set is read line by line before it is
called empty."""

from __future__ import annotations

import pytest

from okf_web import cli as cli_mod
from okf_web import evaluator, surveyor
from okf_web.model import Bundle, Concept
from okf_web.surveyor import rank_pages

BASE = "https://dealer.test"

# The shape of the sitemap that failed: a generator's walk of an old
# site, navigation first, 0.80-priority product pages next, then
# galleries, picture frames and PDFs.
DEALER = [f"{BASE}{path}" for path in (
    "/", "/about.shtml", "/index.shtml", "/sitemap.shtml", "/contact.shtml", "/links.shtml",
    "/ie10_compatibility_view.shtml", "/oven_spacesaver.shtml", "/trade_shows.shtml",
    "/ovens.shtml", "/oven_rack.shtml", "/mixers.shtml", "/mixer_spiral.shtml",
    "/terms.shtml", "/termsofuse.shtml", "/Artisan%20Oven%20Gallery.shtml",
    "/Volta%20Gallery%202/ThumbnailFrame.htm",
    "/Volta%20Gallery%202/pages/COMBINATION%20RACK%20AND%20DECK%20OVEN%20(1).htm",
    "/specs/two%20pan%20deck%20spec.pdf", "/images/oven.JPG",
)]


def test_a_small_limit_reaches_each_kind_of_page_on_the_site_that_failed():
    ranked = rank_pages(DEALER)
    assert [url[len(BASE):] for url in ranked[:6]] == [
        "/", "/terms.shtml", "/ovens.shtml", "/contact.shtml", "/mixers.shtml",
        "/termsofuse.shtml"]
    # What the first six used to be, and where those pages are now.
    assert [url[len(BASE):] for url in DEALER[:6]] == [
        "/", "/about.shtml", "/index.shtml", "/sitemap.shtml", "/contact.shtml", "/links.shtml"]
    # The whole order: each kind in its turn, then picture pages, then
    # the second home page, the site maps and what is not a page at all.
    assert [url[len(BASE):] for url in ranked] == [
        "/", "/terms.shtml", "/ovens.shtml", "/contact.shtml", "/mixers.shtml",
        "/termsofuse.shtml", "/oven_rack.shtml", "/about.shtml", "/trade_shows.shtml",
        "/mixer_spiral.shtml", "/oven_spacesaver.shtml",
        "/Artisan%20Oven%20Gallery.shtml", "/Volta%20Gallery%202/ThumbnailFrame.htm",
        "/Volta%20Gallery%202/pages/COMBINATION%20RACK%20AND%20DECK%20OVEN%20(1).htm",
        "/index.shtml", "/sitemap.shtml", "/links.shtml", "/ie10_compatibility_view.shtml",
        "/specs/two%20pan%20deck%20spec.pdf", "/images/oven.JPG"]


def test_ranking_only_reorders():
    for listed in (DEALER, DEALER[::-1], DEALER + DEALER[:3], []):
        ranked = rank_pages(listed)
        assert sorted(ranked) == sorted(set(listed))  # every distinct address, once
        assert rank_pages(ranked) == ranked            # and ranking twice changes nothing
    # Within the catalog a shallower address comes first, however long its name.
    assert rank_pages([f"{BASE}/a/b/c", f"{BASE}/a-long-section-name"]) == [
        f"{BASE}/a-long-section-name", f"{BASE}/a/b/c"]
    # An address is judged by its words: nothing is fetched, nothing raises.
    assert sorted(rank_pages(["not a url", "http://[bad", f"{BASE}/a"])) == sorted(
        ["not a url", "http://[bad", f"{BASE}/a"])


PLATFORM = [f"https://shop.test{path}" for path in (
    "/products/alpine-tent-2p", "/products/down-bag-20f", "/blogs/news/spring-sale",
    "/collections/tents", "/collections", "/pages/about-us", "/pages/shipping-returns",
    "/policies/refund-policy", "/pages/contact", "/cart", "/account/login", "/search",
    "/pages/faq", "/", "/product-category/stoves/", "/blogs/news",
)]


def test_a_platform_stores_listing_and_policy_pages_come_before_single_products():
    ranked = [url[len("https://shop.test"):] for url in rank_pages(PLATFORM)]
    assert ranked[:10] == [
        "/", "/pages/shipping-returns", "/collections", "/pages/contact", "/collections/tents",
        "/policies/refund-policy", "/product-category/stoves/", "/pages/about-us",
        "/products/down-bag-20f", "/pages/faq"]
    # Section pages before the products under them.
    assert ranked.index("/collections/tents") < ranked.index("/products/alpine-tent-2p")
    assert ranked.index("/product-category/stoves/") < ranked.index("/products/down-bag-20f")
    # The contact page before the about page; news after the catalog; the cart last.
    assert ranked.index("/pages/contact") < ranked.index("/pages/about-us")
    assert ranked.index("/products/down-bag-20f") < ranked.index("/blogs/news/spring-sale")
    assert set(ranked[-3:]) == {"/cart", "/account/login", "/search"}


@pytest.mark.parametrize("url,kind", [
    (f"{BASE}", "home"), (f"{BASE}/", "home"), (f"{BASE}/index.php", "home"),
    (f"{BASE}/Default.aspx", "home"), (f"{BASE}/shop/index.html", "catalog"),
    (f"{BASE}/returns", "policy"), (f"{BASE}/Shipping-Policy", "policy"),
    (f"{BASE}/pages/warranty-information", "policy"), (f"{BASE}/termsofuse.shtml", "policy"),
    (f"{BASE}/financing", "policy"), (f"{BASE}/store-locator", "where"),
    (f"{BASE}/our-story", "where"), (f"{BASE}/showcases.shtml", "catalog"),
    (f"{BASE}/trade_shows.shtml", "catalog"), (f"{BASE}/gallery/2", "aside"),
    (f"{BASE}/blog/how-to-proof", "aside"), (f"{BASE}/privacy-policy", "last"),
    (f"{BASE}/sitemap.html", "last"), (f"{BASE}/brochure.PDF", "last"),
    (f"{BASE}/checkout", "last"), ("http://[bad", "last"),
])
def test_an_address_is_judged_by_its_words(url, kind):
    assert surveyor._page_kind(url)[0] == kind


def test_the_survey_command_ranks_a_sitemaps_pages_only_under_a_limit(tmp_path, monkeypatch, capsys):
    read: list[list[str]] = []
    monkeypatch.setattr(surveyor, "discover_sitemap", lambda base, **kwargs: list(DEALER))
    monkeypatch.setattr(surveyor, "survey",
                        lambda urls, bundle, llm, **kwargs: read.append(list(urls))
                        or surveyor.SurveyResult())
    monkeypatch.setattr(cli_mod, "_llm", lambda args, model=None: object())
    (tmp_path / "pages.txt").write_text(f"{BASE}/hand-picked\n", encoding="utf-8")
    argv = ["survey", str(tmp_path / "bundle"), "--sitemap", BASE]
    assert cli_mod.main(argv + ["--limit", "4"]) == 0
    assert read[-1] == [BASE + path for path in ("/", "/terms.shtml", "/ovens.shtml", "/contact.shtml")]
    # Without a limit every page is read, in the sitemap's own order.
    assert cli_mod.main(argv) == 0
    assert read[-1] == DEALER
    # A hand-written list keeps its place after the sitemap's pages.
    assert cli_mod.main(argv + ["--limit", "3", "--urls", str(tmp_path / "pages.txt")]) == 0
    assert read[-1] == [BASE + "/", BASE + "/terms.shtml", BASE + "/ovens.shtml"]
    assert cli_mod.main(["survey", str(tmp_path / "bundle"), "--urls", str(tmp_path / "pages.txt"),
                         "--limit", "1"]) == 0
    assert read[-1] == [f"{BASE}/hand-picked"]
    capsys.readouterr()


# --- the question set ---------------------------------------------------------

def _bundle(tmp_path) -> Bundle:
    return Bundle(root=tmp_path, concepts={
        "store.md": Concept("store.md", {"type": "Store Identity", "title": "Baker's Best",
                                         "description": "A dealer of bakery equipment."}, "x"),
        "catalog/ovens.md": Concept("catalog/ovens.md", {"type": "Product Collection",
                                                         "title": "Ovens",
                                                         "description": "Deck and rack ovens."}, "x"),
    })


class _Reply:
    model = "static/questions"

    def __init__(self, text):
        self.text = text

    def complete(self, system, user, max_tokens=0):
        return self.text


# What a model writes for a store whose name has an apostrophe: single
# quotes around a sentence that holds one, and a colon in another.
BROKEN = """Here is the set.

```yaml
questions:
  - id: disc-1
    archetype: discovery
    question: 'Does Baker's Best sell an oven for a small bakery?'
    paraphrase: Looking for a compact bakery oven: do they have one?
  - id: trust-1
    archetype: trust
    question: "Is \\"Baker's Best\\" a real company with a showroom?"
    probe: negative
  - archetype: comparison
    question: Which is better for baguettes, a deck oven or a rack oven?
  - id: empty-1
    archetype: discovery
    question:
```
"""


def test_one_malformed_line_no_longer_loses_the_whole_set(tmp_path):
    import yaml
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(BROKEN.split("```yaml\n", 1)[1].split("```", 1)[0])
    questions = evaluator.generate_questions(_bundle(tmp_path), _Reply(BROKEN))
    assert [(q.id, q.archetype) for q in questions] == [
        ("disc-1", "discovery"), ("trust-1", "trust"), ("gen3", "comparison")]
    assert questions[0].question == "Does Baker's Best sell an oven for a small bakery?"
    assert questions[0].paraphrase == "Looking for a compact bakery oven: do they have one?"
    assert questions[1].question == 'Is "Baker\'s Best" a real company with a showroom?'
    assert questions[1].probe == "negative" and questions[2].probe == ""
    # The entry with no question in it is not part of the set.
    assert [item.get("id") for item in evaluator._question_payload(BROKEN)["questions"]] == [
        "disc-1", "trust-1", None]


def test_a_well_formed_set_is_read_as_before(tmp_path):
    good = ("```yaml\nquestions:\n  - id: a-1\n    archetype: discovery\n"
            "    question: Do they sell deck ovens?\n    paraphrase: deck oven for sale\n```\n")
    [question] = evaluator.generate_questions(_bundle(tmp_path), _Reply(good))
    assert (question.id, question.question, question.paraphrase) == (
        "a-1", "Do they sell deck ovens?", "deck oven for sale")
    assert evaluator._question_payload(good) == evaluator._extract_yaml(good)
    # Nothing at all is still nothing, and a list of strings is not a set.
    assert evaluator.generate_questions(_bundle(tmp_path), _Reply("I cannot do that.")) == []
    assert evaluator.generate_questions(
        _bundle(tmp_path), _Reply("questions:\n  - just a sentence\n")) == []


@pytest.mark.parametrize("reply", [
    "reason: not-a-store\nquestions: []\n",
    "```yaml\nreason: 'not-a-store'\nquestions:\n```",
    # The refusal inside a reply whose other line is not YAML.
    "reason: not-a-store\nnote: 'the owner's page says nothing is sold'\n",
])
def test_a_refusal_survives_a_malformed_reply(tmp_path, reply):
    with pytest.raises(evaluator.NotAStore):
        evaluator.generate_questions(_bundle(tmp_path), _Reply(reply))


@pytest.mark.parametrize("value,expected", [
    ("plain words", "plain words"), ("  'it''s quoted'  ", "it's quoted"),
    ("'Baker's Best'", "Baker's Best"), ('"said \\"so\\""', 'said "so"'),
    ("'", "'"), ("", ""), ("\"unclosed", "\"unclosed"),
])
def test_a_values_wrapping_quotes_are_the_models_not_the_sentences(value, expected):
    assert evaluator._plain_scalar(value) == expected
