"""The "before": the same questions put to the store's own pages.

A scorecard says how answerable the bundle is. It says nothing about
what an assistant has without it, and a lift nobody measured is a
claim, not a number. This module measures the other side: the pages
the bundle's knowledge was surveyed from, read as the text a visitor
sees, searched by the same retriever, and in a judged run answered and
graded by the same prompts.

The condition is deliberately generous to the pages:

* they are the pages the bundle's own concepts cite (``resource``), so
  the right pages are already chosen, and the ones behind the concepts
  the bundle retrieved for these questions come first when the limit
  applies;
* each page is reduced to its readable text
  (:func:`okf_web.surveyor.html_to_text`), never counted as markup;
* retrieval, ``top_k``, the answer prompt and the judge are the
  evaluation's own: :func:`okf_web.evaluator.evaluate` runs unchanged
  over a view whose concepts are the pages.

What the pages cannot offer is what the comparison then shows: facts
that live on no page, live values a page states without a date, and
the reading cost of a whole page where one concept would do.

Nothing is written here. :func:`measure` returns a :class:`Baseline`;
:meth:`Baseline.attach` puts its record on the evaluation's report,
and :func:`okf_web.evaluator.write_scorecard` stores it under
``x_geo.baseline``. A store none of whose pages can be read has no
baseline: that is a refusal (:class:`BaselineError`), never a zero.
"""

from __future__ import annotations

import functools
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import evaluator
from .errors import Refusal
from .model import Bundle, Concept, slug, split_l10n
from .surveyor import fetch, html_to_text

__all__ = [
    "Baseline",
    "BaselineError",
    "PAGE_CHARS_MAX",
    "PAGE_LIMIT",
    "PAGE_TYPE",
    "measure",
    "pages_view",
    "read_urls",
    "source_pages",
]

#: How many pages one baseline reads unless the caller says otherwise.
#: The pages behind the bundle's own answers are taken first, so the
#: limit costs the pages nothing the questions needed.
PAGE_LIMIT = 50

#: A page's text beyond this many characters is cut (about 10,000
#: tokens): an assistant reading a page stops somewhere too, and four
#: uncut pages of a megabyte each would be no context at all. The
#: record says how many pages were cut.
PAGE_CHARS_MAX = 40_000

#: The type the page stand-ins carry. Not a profile type: the view
#: exists only for the length of one measurement and is never written.
PAGE_TYPE = "Web Page"


class BaselineError(ValueError, Refusal):
    """No baseline can be measured: the bundle cites no page, or none
    of the pages it cites could be read."""


@dataclass
class Baseline:
    """One measurement of the store's own pages.

    ``record`` is what the scorecard stores; ``pages`` are the URLs
    read, in the order they were taken; ``unreadable`` are the ones that
    could not be read, each with its reason; ``report`` is the
    evaluator's own report over the pages view."""

    record: dict
    pages: list[str] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    report: evaluator.Report | None = None

    def attach(self, report: evaluator.Report) -> evaluator.Report:
        """Put this measurement on the bundle's own report, where
        :func:`okf_web.evaluator.write_scorecard` reads it."""
        report.baseline = dict(self.record)
        report.baseline_pages = list(self.pages)
        report.baseline_unreadable = [f"{url}: {why}" for url, why in self.unreadable]
        return report


def _is_page(url: str | None) -> bool:
    return bool(url) and url.startswith(("http://", "https://"))


def source_pages(bundle: Bundle, preferred: list[str] | None = None) -> list[str]:
    """The distinct ``http(s)`` pages the bundle's concepts cite as
    their ``resource``: the ``preferred`` concept paths' pages first, in
    that order, then the rest by URL. Scorecards and translations cite
    no page of their own (the same exclusion retrieval makes)."""
    cited: dict[str, str] = {}
    for rel, concept in bundle.concepts.items():
        if concept.type in evaluator.META_TYPES or split_l10n(rel) is not None:
            continue
        if _is_page(concept.resource):
            cited[rel] = concept.resource
    ordered: list[str] = []
    for rel in preferred or []:
        url = cited.get(rel)
        if url and url not in ordered:
            ordered.append(url)
    for url in sorted(set(cited.values())):
        if url not in ordered:
            ordered.append(url)
    return ordered


def read_urls(path: Path | str) -> list[str]:
    """Page addresses from a file, one per line; blank lines and lines
    starting with ``#`` are skipped, anything that is not ``http(s)``
    is refused by name."""
    urls: list[str] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not _is_page(line):
            raise BaselineError(
                f"{path} line {number}: {line!r} is not an http(s) page address"
            )
        if line not in urls:
            urls.append(line)
    return urls


def _page_rel(number: int, url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    name = slug(f"{parts.netloc} {parts.path}") or "page"
    return f"pages/{number:03d}-{name[:60]}.md"


def _page_title(text: str, url: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first[:120] or url


def pages_view(bundle: Bundle, pages: dict[str, str]) -> Bundle:
    """The pages as a bundle the evaluator can run over unchanged: one
    stand-in concept per page (its text as the body, its address as the
    ``resource``, no verifier, so its trust reads ``unverified``), under
    the bundle's own indexes, so its language and the archetypes it
    declares not applicable hold for both sides of the comparison."""
    concepts: dict[str, Concept] = {}
    for number, (url, text) in enumerate(pages.items(), 1):
        rel = _page_rel(number, url)
        concepts[rel] = Concept(
            rel_path=rel,
            frontmatter={"type": PAGE_TYPE, "title": _page_title(text, url), "resource": url},
            body=text,
        )
    return Bundle(
        root=bundle.root,
        concepts=concepts,
        indexes=bundle.indexes,
        language_override=bundle.language_override,
    )


def _fetch_page_text(url: str, timeout: float, allow_private: bool, policy) -> str:
    return html_to_text(fetch(url, timeout=timeout, allow_private=allow_private, policy=policy))


def _retrieved_first(bundle: Bundle, questions, top_k: int, retriever) -> list[str]:
    """The concept paths the bundle's own retrieval returns for the
    questions, first seen first: the pages behind them are the ones a
    limited baseline must not lose."""
    retrieve_fn = retriever or evaluator.retrieve
    seen: list[str] = []
    for question in questions:
        for concept in retrieve_fn(bundle, question.question, top_k):
            if concept.rel_path not in seen:
                seen.append(concept.rel_path)
    return seen


def measure(
    bundle: Bundle,
    questions: list[evaluator.Question],
    llm=None,
    judge=None,
    top_k: int = 4,
    urls: list[str] | None = None,
    limit: int = PAGE_LIMIT,
    retriever=None,
    min_relevance: float = evaluator.RELEVANCE_FLOOR,
    fetch_text=None,
    timeout: float = 30.0,
    allow_private: bool = False,
    policy=None,
) -> Baseline:
    """Put ``questions`` to the store's own pages.

    ``urls`` names the pages; without it they are the pages the
    bundle's concepts cite (:func:`source_pages`), those behind the
    concepts ``retriever`` (the bundle's own, the lexical default) finds
    for the questions first. At most ``limit`` pages are read, through
    the page policy (private hosts refused unless ``allow_private``) or
    an explicit ``policy``; ``fetch_text`` replaces the fetch for tests.

    Without ``llm`` this is the retrieval half only, as in a dry run:
    how often a page matched and what reading it costs. With ``llm``
    (and ``judge``, when grading is decoupled) the same prompts answer
    and grade from the pages, and the record carries ``coverage`` and
    ``groundedness``. The pages are always searched by the lexical
    retriever, under the caller's ``min_relevance`` when the bundle's
    run raised the floor: an embedding index belongs to the bundle it
    was built from, a floor belongs to both sides.
    """
    if limit < 1:
        raise BaselineError("the baseline needs at least one page (limit must be 1 or more)")
    if urls is None:
        urls = source_pages(bundle, _retrieved_first(bundle, questions, top_k, retriever))
        if not urls:
            raise BaselineError(
                "no baseline: no concept in this bundle cites an http(s) page as "
                "its resource; name the store's pages with --baseline-urls FILE"
            )
    available = len(urls)
    taken = urls[:limit]
    if fetch_text is None:
        fetch_text = lambda url: _fetch_page_text(url, timeout, allow_private, policy)  # noqa: E731

    pages: dict[str, str] = {}
    unreadable: list[tuple[str, str]] = []
    cut = 0
    for url in taken:
        try:
            text = fetch_text(url)
        except Exception as exc:  # noqa: BLE001 — any fetch failure is the same finding
            unreadable.append((url, str(exc) or type(exc).__name__))
            continue
        text = (text or "").strip()
        if not text:
            unreadable.append((url, "the page carries no readable text"))
            continue
        if len(text) > PAGE_CHARS_MAX:
            text = text[:PAGE_CHARS_MAX]
            cut += 1
        pages[url] = text
    if not pages:
        first = f" (first: {unreadable[0][0]}: {unreadable[0][1]})" if unreadable else ""
        raise BaselineError(
            f"no baseline: none of the {len(taken)} store page(s) could be read{first}"
        )

    view = pages_view(bundle, pages)
    pages_retriever = None
    if min_relevance != evaluator.RELEVANCE_FLOOR:
        pages_retriever = functools.partial(evaluator.retrieve, min_relevance=min_relevance)
    report = evaluator.evaluate(
        view, questions, llm=llm, top_k=top_k, retriever=pages_retriever, judge=judge
    )
    metrics = report.metrics(view)
    record: dict = {
        "condition": (
            f"store pages as text ({len(pages)} page{'s' if len(pages) != 1 else ''}, "
            "same questions)"
        ),
        "pages": len(pages),
        "top_k": top_k,
        "retriever": report.retriever,
        "questions": metrics["questions"],
        "retrieval_hit_rate": metrics["retrieval_hit_rate"],
        "context_tokens_mean": metrics["context_tokens_mean"],
    }
    if not report.dry_run:
        record["coverage"] = metrics["coverage"]
        record["groundedness"] = metrics["groundedness"]
    record["by_archetype"] = metrics["by_archetype"]
    if unreadable:
        record["pages_unreadable"] = len(unreadable)
    if available > len(taken):
        record["pages_available"] = available
    if cut:
        record["pages_cut"] = cut
        record["page_chars_max"] = PAGE_CHARS_MAX
    return Baseline(record=record, pages=list(pages), unreadable=unreadable, report=report)
