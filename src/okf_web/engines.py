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
question) by the evaluation's judge, and three things are read off it
without a model: whether the provider declined, whether the answer
names the store, and whether it cites a page on the store's address.

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

#: Room for the assistant's answer and whatever reasoning precedes it.
_ANSWER_MAX_TOKENS = 8000
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
    cites, how many searches it ran, and whether the provider declined
    to answer."""

    text: str
    cited: list[str] = field(default_factory=list)
    searched: int = 0
    declined: bool = False


class Engine(Protocol):
    """A live assistant: a name for the record and one question in, one
    answer out."""

    name: str

    def ask(self, prompt: str) -> EngineAnswer:
        ...


class AnthropicSearch:
    """Claude through the Messages API with the web search server tool.

    The request is the shopper's message and nothing else: no system
    prompt, so the assistant behaves as the provider ships it. A turn
    the provider pauses is sent back to continue; a declined turn is
    recorded as declined, not as an answer."""

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
        text: list[str] = []
        cited: list[str] = []
        searched = 0
        reason = ""
        for _ in range(_MAX_RESUMES + 1):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=_ANSWER_MAX_TOKENS,
                tools=[{"type": self.tool_type, "name": "web_search",
                        "max_uses": self.max_searches}],
                messages=messages,
            )
            for block in response.content:
                kind = getattr(block, "type", "")
                if kind == "text":
                    text.append(getattr(block, "text", "") or "")
                    for citation in getattr(block, "citations", None) or []:
                        url = getattr(citation, "url", None)
                        if url and url not in cited:
                            cited.append(str(url))
                elif kind == "server_tool_use" and getattr(block, "name", "") == "web_search":
                    searched += 1
            reason = getattr(response, "stop_reason", "") or ""
            if reason != "pause_turn":
                break
            # The provider's own loop paused: send the turn back as it
            # stands and it resumes where it stopped.
            messages.append({"role": "assistant", "content": response.content})
        return EngineAnswer(
            text="".join(text).strip(), cited=cited, searched=searched,
            declined=reason == "refusal",
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
    ``checked``, ``contradicted``, ``named``, ``cited``, ``notes``)."""

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
    searches = 0
    by_archetype: dict[str, dict[str, int]] = {}
    first_error = ""
    for question in questions:
        if question.archetype in declared:
            continue
        verified = evaluator.render_context(retrieve_fn(bundle, question.question, top_k))
        row = {"id": question.id, "archetype": question.archetype, "asked": 0,
               "answered": 0, "checked": 0, "contradicted": 0, "named": 0,
               "cited": 0, "notes": ""}
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
    if checked:
        record["agrees"] = _share(checked - contradicted, checked)
    if declined:
        record["declined"] = declined
    if errors:
        record["errors"] = errors
    return Probe(record=record, rows=rows)
