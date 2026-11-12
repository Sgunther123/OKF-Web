"""What a shopper is told today: the store's questions put to a live
assistant with web search on.

The scorecard measures the bundle, and :mod:`okf_web.baseline` measures
the store's own pages. Neither says what an assistant answers when a
shopper asks it about the store today, which is the one thing a
merchant can check for themselves and the thing a published bundle is
meant to change. This module asks.

Each question is sent the way a shopper would send it: one message
naming the store and its address, no system prompt, the provider's web
search switched on. The answer is then compared with the store's own
verified knowledge (the concepts the bundle retrieves for that
question) by the evaluation's judge, and four things are read off the
reply without a model: whether the provider declined, whether the
answer names the store, whether it cites a page on the store's
address, and whether the searches behind it returned such a page at
all (an answer cannot cite a store its searches never found).

What this is not, recorded with every measurement:

* an API with search is a provider's assistant without its consumer
  app around it; the two are close, not identical;
* an answer is one draw: ``repeats`` asks each question more than once
  and the record gives shares, never a single anecdote;
* ``agrees`` is agreement with the store's verified knowledge, not with
  the world; an answer that knowledge does not cover is unchecked, and
  is never counted for or against.

Nothing is written here. :func:`probe` returns a :class:`Probe`;
:meth:`Probe.attach` puts it on the evaluation's report, and
:func:`okf_web.evaluator.write_scorecard` stores it under
``x_geo.live``. An assistant that cannot be reached at all is a
refusal (:class:`ProbeError`), never a column of zeros.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from importlib import resources
from typing import Protocol

from . import evaluator
from .config import DEFAULT_MODEL
from .errors import Refusal
from .llm import LLMTruncated
from .model import Bundle

__all__ = [
    "ANTHROPIC_SEARCH_TOOL",
    "AnthropicSearch",
    "Engine",
    "EngineAnswer",
    "Probe",
    "ProbeError",
    "judge_prompt",
    "probe",
    "shopper_prompt",
    "store_of",
]

#: The provider's web search server tool this adapter declares. Dated:
#: a model that predates it needs the version it knows.
ANTHROPIC_SEARCH_TOOL = "web_search_20260209"

#: The searches are asked for directly. On this tool version the
#: provider's default runs them inside its own code execution (a
#: filtering step), and a reply made that way carries no citations:
#: the first run on a real store (2026-11-12) recorded "cites the
#: store: 0" for answers that could not cite anything, at more than
#: twice the tokens of the same question asked directly.
_SEARCH_CALLERS = ("direct",)

#: Room for the assistant's answer and whatever reasoning precedes it.
#: A reply cut at this limit is a failed ask, not an answer.
_ANSWER_MAX_TOKENS = 16000
#: How many times a turn the provider paused is sent back to continue.
_MAX_RESUMES = 3
#: Asks that may fail in a row, from the first, before the probe stops:
#: an unreachable assistant is found out in three calls, not thirty-nine.
_FAILURES_BEFORE_STOP = 3
_NOTE_CHARS = 240


class ProbeError(RuntimeError, Refusal):
    """The live check cannot be made: the bundle names no store address,
    or the assistant could not be reached at all."""


@dataclass
class EngineAnswer:
    """One answer from a live assistant: its text, the page addresses it
    cites, how many searches it ran, whether the provider declined to
    answer, and the page addresses its searches returned (None from an
    assistant that does not say)."""

    text: str
    cited: list[str] = field(default_factory=list)
    searched: int = 0
    declined: bool = False
    found: list[str] | None = None


class Engine(Protocol):
    """A live assistant: a name for the record and one question in, one
    answer out."""

    name: str

    def ask(self, prompt: str) -> EngineAnswer:
        ...


class AnthropicSearch:
    """Claude through the Messages API with the web search server tool.

    The request is the shopper's message and nothing else: no system
    prompt, so the assistant behaves as the provider ships it. The
    searches are made directly (``_SEARCH_CALLERS``), which is the form
    whose answers carry citations. A turn the provider pauses is sent
    back to continue; a declined turn is recorded as declined, not as
    an answer. What the assistant said before a search and after it are
    two paragraphs of one answer."""

    def __init__(self, model: str = DEFAULT_MODEL, max_searches: int = 3,
                 client=None, tool_type: str = ANTHROPIC_SEARCH_TOOL):
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise ProbeError(
                    "the live check asks the Anthropic API with web search and "
                    "needs the `anthropic` package: `pip install okf-web[llm]`"
                ) from exc
            client = anthropic.Anthropic()
        self.model = model
        self.max_searches = max_searches
        self.tool_type = tool_type
        self.name = f"anthropic/{model}"
        self._client = client

    def ask(self, prompt: str) -> EngineAnswer:
        messages: list[dict] = [{"role": "user", "content": prompt}]
        text = ""
        cited: list[str] = []
        found: list[str] = []
        searched = 0
        apart = False  # a tool ran since the last words
        reason = ""
        for _ in range(_MAX_RESUMES + 1):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=_ANSWER_MAX_TOKENS,
                tools=[{"type": self.tool_type, "name": "web_search",
                        "max_uses": self.max_searches,
                        "allowed_callers": list(_SEARCH_CALLERS)}],
                messages=messages,
            )
            for block in response.content:
                kind = getattr(block, "type", "")
                if kind == "text":
                    piece = getattr(block, "text", "") or ""
                    # A cited answer arrives in pieces that join as they
                    # stand; words either side of a tool's work do not.
                    if apart and text.strip() and piece.strip():
                        text = text.rstrip() + "\n\n" + piece.lstrip()
                    else:
                        text += piece
                    apart = False
                    for citation in getattr(block, "citations", None) or []:
                        url = getattr(citation, "url", None)
                        if url and str(url) not in cited:
                            cited.append(str(url))
                elif kind == "server_tool_use":
                    apart = True
                    if getattr(block, "name", "") == "web_search":
                        searched += 1
                elif kind == "web_search_tool_result":
                    results = getattr(block, "content", None)
                    # A failed search carries one error object, not a list.
                    for item in results if isinstance(results, list) else []:
                        url = (item.get("url") if isinstance(item, dict)
                               else getattr(item, "url", None))
                        if url and str(url) not in found:
                            found.append(str(url))
            reason = getattr(response, "stop_reason", "") or ""
            if reason != "pause_turn":
                break
            # The provider's own loop paused: send the turn back as it
            # stands and it resumes where it stopped.
            messages.append({"role": "assistant", "content": response.content})
        if reason == "max_tokens":
            raise LLMTruncated(
                f"{self.name} was cut off at its output limit ({_ANSWER_MAX_TOKENS} "
                "tokens) before it finished its answer; a cut-off answer is not graded"
            )
        return EngineAnswer(
            text=text.strip(), cited=cited, searched=searched,
            declined=reason == "refusal", found=found,
        )


def judge_prompt() -> str:
    return resources.files("okf_web").joinpath("prompts/probe_judge.md").read_text("utf-8")


def store_of(bundle: Bundle) -> tuple[str, str]:
    """The store as a shopper would name it: ``(name, host)``. The name
    is the Store Identity's title, or the host when the bundle has
    none; a bundle whose root index names no site cannot be asked
    about."""
    try:
        host = urllib.parse.urlsplit(bundle.site or "").hostname or ""
    except ValueError:
        host = ""
    if not host:
        raise ProbeError(
            "the live check needs the store's address: set `x_geo.site` on the "
            "bundle's root index (an assistant cannot be asked about a store "
            "with no name to find it by)"
        )
    identity = next(
        (c for c in bundle.concepts.values() if c.type == "Store Identity"), None
    )
    return (identity.title if identity else host), host


def shopper_prompt(store: str, host: str, question: str) -> str:
    """The one message the assistant receives."""
    named = store if store == host else f"{store} ({host})"
    return f"I have a question about the online store {named}. {question}"


def _on_store(url: str, host: str) -> bool:
    try:
        cited = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    bare = host.lower().removeprefix("www.")
    return bool(cited) and (cited == bare or cited.endswith("." + bare))


def _inert_answer(text: str) -> str:
    """The assistant's answer as the judge receives it: whatever a web
    page put into it, it cannot close its own ``<answer>`` block or
    open a ``<concept>`` block that would pass for the store's verified
    knowledge (the rule `evaluator.render_context` holds for bodies)."""
    for tag in ("answer", "concept"):
        text = text.replace(f"<{tag}", f"&lt;{tag}").replace(f"</{tag}", f"&lt;/{tag}")
    return text


def _agrees(value) -> bool | None:
    """The judge's three-valued verdict: a JSON boolean or yes/true and
    no/false in any case; anything else, null included, is unchecked."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("yes", "true"):
            return True
        if word in ("no", "false"):
            return False
    return None


@dataclass
class Probe:
    """One live check: the record the scorecard stores and one row per
    question (``id``, ``archetype``, ``asked``, ``answered``,
    ``checked``, ``contradicted``, ``named``, ``cited``, ``found``,
    ``notes``)."""

    record: dict
    rows: list[dict] = field(default_factory=list)

    def attach(self, report: evaluator.Report) -> evaluator.Report:
        """Put this check on the bundle's own report, where
        :func:`okf_web.evaluator.write_scorecard` reads it."""
        report.live = [*report.live, dict(self.record)]
        report.live_rows = [*report.live_rows, *({**row} for row in self.rows)]
        return report


def _share(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def probe(
    bundle: Bundle,
    questions: list[evaluator.Question],
    engine: Engine,
    judge,
    top_k: int = 4,
    repeats: int = 1,
    retriever=None,
) -> Probe:
    """Ask ``engine`` every question about the bundle's store and grade
    what it says against the bundle.

    ``judge`` is the evaluation's judge (an LLM client): it reads the
    question, the assistant's answer and the concepts the bundle
    retrieves for that question, and says whether the answer is a
    substantive answer about this store and whether it agrees with the
    store's verified knowledge. An ask that fails (the provider's error)
    is counted as an error and left out of every share; three failures
    in a row from the first ask stop the probe as unreachable.
    """
    if repeats < 1:
        raise ProbeError("the live check asks each question at least once")
    store, host = store_of(bundle)
    retrieve_fn = retriever or evaluator.retrieve
    declared = set(a for a in (bundle.not_applicable or []) if a in evaluator.ARCHETYPES)
    system = judge_prompt()

    rows: list[dict] = []
    asked = errors = answered = checked = contradicted = named = cited = declined = 0
    searches = found = 0
    reported = False  # the assistant says which pages its searches returned
    by_archetype: dict[str, dict[str, int]] = {}
    first_error = ""
    for question in questions:
        if question.archetype in declared:
            continue
        verified = evaluator.render_context(retrieve_fn(bundle, question.question, top_k))
        row = {"id": question.id, "archetype": question.archetype, "asked": 0,
               "answered": 0, "checked": 0, "contradicted": 0, "named": 0,
               "cited": 0, "found": 0, "notes": ""}
        for _ in range(repeats):
            try:
                answer = engine.ask(shopper_prompt(store, host, question.question))
            except Exception as exc:  # noqa: BLE001 — any provider failure is the same finding
                errors += 1
                first_error = first_error or (str(exc) or type(exc).__name__)
                if asked == 0 and errors >= _FAILURES_BEFORE_STOP:
                    raise ProbeError(
                        f"the live check could not reach {engine.name}: "
                        f"{first_error}"
                    ) from exc
                continue
            asked += 1
            row["asked"] += 1
            searches += answer.searched
            if answer.found is not None:
                reported = True
                if any(_on_store(url, host) for url in answer.found):
                    found += 1
                    row["found"] += 1
            if answer.declined or not answer.text:
                declined += 1 if answer.declined else 0
                continue
            lowered = answer.text.lower()
            if store.lower() in lowered or host.lower().removeprefix("www.") in lowered:
                named += 1
                row["named"] += 1
            if any(_on_store(url, host) for url in answer.cited):
                cited += 1
                row["cited"] += 1
            verdict = evaluator._extract_json(judge.complete(
                system,
                f"STORE: {store} ({host})\n\nQUESTION: {question.question}\n\n"
                f"VERIFIED:\n{verified}\n\n"
                f"ANSWER:\n<answer>\n{_inert_answer(answer.text)}\n</answer>",
                max_tokens=1024,
            ))
            if not evaluator._verdict_flag(verdict.get("answered")):
                continue
            answered += 1
            row["answered"] += 1
            agrees = _agrees(verdict.get("agrees"))
            if agrees is None:
                continue
            checked += 1
            row["checked"] += 1
            if not agrees:
                contradicted += 1
                row["contradicted"] += 1
                row["notes"] = row["notes"] or str(verdict.get("notes") or "")[:_NOTE_CHARS]
        slot = by_archetype.setdefault(
            question.archetype, {"asked": 0, "answered": 0, "contradicted": 0})
        slot["asked"] += row["asked"]
        slot["answered"] += row["answered"]
        slot["contradicted"] += row["contradicted"]
        rows.append(row)
    if asked == 0:
        detail = f": {first_error}" if first_error else ""
        raise ProbeError(f"the live check put no question to {engine.name}{detail}")

    record: dict = {
        "engine": engine.name,
        "asked_as": shopper_prompt(store, host, "<the question>"),
        "questions": len(rows),
        "repeats": repeats,
        "asked": asked,
        "answered": _share(answered, asked),
        "checked": checked,
        "contradicted": contradicted,
        "names_store": _share(named, asked),
        "cites_store": _share(cited, asked),
        "searches_mean": round(searches / asked, 2),
        "judged_by": getattr(judge, "model", "unknown"),
        "by_archetype": by_archetype,
    }
    search = getattr(engine, "tool_type", "")
    if search:
        record["search"] = search
    if reported:
        # The share of replies whose searches returned a page on the
        # store's address: what `cites_store` can at most be.
        record["finds_store"] = _share(found, asked)
    if checked:
        record["agrees"] = _share(checked - contradicted, checked)
    if declined:
        record["declined"] = declined
    if errors:
        record["errors"] = errors
    return Probe(record=record, rows=rows)
