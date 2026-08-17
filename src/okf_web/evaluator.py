"""Answerability evaluation: measure how well the bundle serves an AI buyer.

The evaluator role-plays the consumer the bundle exists for — a
generative engine answering shopper questions — and measures instead of
guessing:

* A **question set** spans the thirteen question archetypes in
  ``ARCHETYPES`` (discovery and product facts through compliance, local
  availability, and procurement), either curated in
  ``evaluations/questions.yaml`` or LLM-generated from the bundle's own
  index.
* For each question the harness **retrieves** concepts (progressive
  disclosure, same as a real agent), **answers** only from that context,
  and a **judge** scores the answer: was it answerable, grounded, and
  cited?
* Output is a **GEO scorecard** — coverage, citability, freshness, and
  token cost — written back into the bundle as a concept, plus a gap
  list that feeds the next survey/verify cycle.

``dry_run`` gives a retrieval-only coverage signal with no LLM at all,
which is what CI runs.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .llm import estimate_tokens
from .model import (
    Bundle,
    Concept,
    TRUST_UNVERIFIED,
    render_document,
    split_l10n,
)

ARCHETYPES = [
    "discovery",      # does this store sell something for my need?
    "product_fact",   # a concrete attribute of a specific product
    "comparison",     # product A vs product B
    "policy",         # returns, warranty, privacy
    "fulfillment",    # shipping destinations, costs, timelines
    "trust",          # legitimacy, guarantees, contact, provenance
    "capability",     # what can an agent *do* against the store (live price/stock)
    "promotion",      # current sales, discount codes, when a deal ends
    "fit_compatibility",  # will it fit me / work with what I own
    "ownership",      # I own it: setup, care, troubleshooting, warranty process
    "compliance",     # materials, origin, certifications, repairability — passport facts
    "local_availability",  # stores near me, hours, pickup today, on the shelf now
    "procurement",    # B2B: wholesale eligibility, MOQs, payment terms, lead times, RFQ
]

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
    "are", "do", "does", "can", "i", "my", "you", "your", "what", "how",
    "much", "many", "with", "it", "this", "that", "be", "will",
}


@dataclass
class Question:
    id: str
    archetype: str
    question: str


@dataclass
class QuestionResult:
    question: Question
    retrieved: list[str]
    context_tokens: int
    answered: bool | None = None
    grounded: bool | None = None
    cited_paths: list[str] = field(default_factory=list)
    answer: str = ""
    notes: str = ""


@dataclass
class Report:
    results: list[QuestionResult]
    generated_by: str
    dry_run: bool

    def _fraction(self, predicate) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if predicate(r)) / len(self.results)

    def metrics(self, bundle: Bundle) -> dict:
        def cited_ok(r: QuestionResult) -> bool:
            if not (r.answered and r.cited_paths):
                return False
            concepts = [bundle.get(p) for p in r.cited_paths]
            concepts = [c for c in concepts if c is not None]
            return bool(concepts) and all(
                c.trust_tier != TRUST_UNVERIFIED for c in concepts
            )

        def fresh_ok(r: QuestionResult) -> bool:
            concepts = [bundle.get(p) for p in r.cited_paths]
            return all(c is None or not c.is_stale() for c in concepts)

        metrics: dict = {
            "questions": len(self.results),
            "retrieval_hit_rate": round(
                self._fraction(lambda r: bool(r.retrieved)), 3
            ),
            "context_tokens_mean": (
                round(
                    sum(r.context_tokens for r in self.results) / len(self.results)
                )
                if self.results
                else 0
            ),
        }
        if not self.dry_run:
            metrics.update(
                {
                    "coverage": round(self._fraction(lambda r: bool(r.answered)), 3),
                    "groundedness": round(
                        self._fraction(lambda r: bool(r.answered and r.grounded)), 3
                    ),
                    "citability": round(self._fraction(cited_ok), 3),
                    "freshness": round(self._fraction(fresh_ok), 3),
                }
            )
        by_archetype: dict[str, dict[str, int]] = {}
        for r in self.results:
            slot = by_archetype.setdefault(
                r.question.archetype, {"questions": 0, "answered": 0}
            )
            slot["questions"] += 1
            if r.answered:
                slot["answered"] += 1
        metrics["by_archetype"] = by_archetype
        return metrics

    def gaps(self) -> list[QuestionResult]:
        if self.dry_run:
            return [r for r in self.results if not r.retrieved]
        return [r for r in self.results if not r.answered]


# ---------------------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------------------

def load_questions(path: Path | str) -> list[Question]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for i, item in enumerate(data.get("questions", []), start=1):
        out.append(
            Question(
                id=str(item.get("id") or f"q{i}"),
                archetype=str(item.get("archetype") or "discovery"),
                question=str(item.get("question") or "").strip(),
            )
        )
    return [q for q in out if q.question]


def generate_questions(bundle: Bundle, llm, per_archetype: int = 3) -> list[Question]:
    """Ask the LLM to derive a question set from the bundle's own index."""
    system = _prompt("evaluator_questions.md")
    outline = []
    for concept in bundle.concepts.values():
        desc = str(concept.frontmatter.get("description") or "")
        outline.append(f"- {concept.rel_path} [{concept.type}] {concept.title}: {desc}")
    user = (
        f"PER_ARCHETYPE: {per_archetype}\n"
        f"ARCHETYPES: {', '.join(ARCHETYPES)}\n\n"
        "BUNDLE OUTLINE:\n" + "\n".join(sorted(outline))
    )
    response = llm.complete(system, user, max_tokens=4096)
    payload = _extract_yaml(response)
    questions = []
    for i, item in enumerate(payload.get("questions", []), start=1):
        questions.append(
            Question(
                id=str(item.get("id") or f"gen{i}"),
                archetype=str(item.get("archetype") or "discovery"),
                question=str(item.get("question") or "").strip(),
            )
        )
    return [q for q in questions if q.question]


# ---------------------------------------------------------------------------
# Retrieval (progressive disclosure, lexical)
# ---------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


# Meta-knowledge about the bundle itself (scorecards) never
# participates in retrieval: it describes the evaluation, not the
# store, and its tables are dense with concept paths that would
# pollute ranking. Shared with the embedding retriever.
META_TYPES = {"GEO Scorecard"}


def retrieve(bundle: Bundle, question: str, top_k: int = 4) -> list[Concept]:
    """Rank concepts by overlap with the question (tf * idf-lite).

    Translation trees (``l10n/<lang>/``) are excluded by key: in the
    default view they would duplicate their sources in another
    language, while in a ``localized_view`` the active translation
    sits under its source key and participates normally.
    """
    query = set(_tokens(question))
    if not query:
        return []
    candidates = [
        c
        for rel, c in bundle.concepts.items()
        if c.type not in META_TYPES and split_l10n(rel) is None
    ]
    docs = {c.rel_path: _tokens(c.retrieval_text()) for c in candidates}
    doc_freq = {term: sum(1 for toks in docs.values() if term in toks) for term in query}
    n_docs = max(1, len(docs))
    scored: list[tuple[float, Concept]] = []
    for concept in candidates:
        toks = docs[concept.rel_path]
        if not toks:
            continue
        counts = {t: toks.count(t) for t in query}
        score = 0.0
        for term, count in counts.items():
            if count == 0:
                continue
            idf = math.log(1 + n_docs / (1 + doc_freq.get(term, 0)))
            score += (1 + math.log(count)) * idf
        # Small boost when the concept declares an intent matching words
        # in the question (e.g. "return" → policy concepts).
        score *= 1.0 + 0.1 * len(query & set(_tokens(" ".join(concept.intents))))
        if score > 0:
            scored.append((score, concept))
    scored.sort(key=lambda pair: (-pair[0], pair[1].rel_path))
    return [c for _, c in scored[:top_k]]


# ---------------------------------------------------------------------------
# Answer + judge
# ---------------------------------------------------------------------------

def _prompt(name: str) -> str:
    return resources.files("okf_web").joinpath(f"prompts/{name}").read_text("utf-8")


def _extract_json(text: str) -> dict:
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return {}


def _extract_yaml(text: str) -> dict:
    fenced = re.search(r"```(?:yaml)?\s*\n(.*?)```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text
    try:
        data = yaml.safe_load(payload)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def evaluate(
    bundle: Bundle,
    questions: list[Question],
    llm=None,
    top_k: int = 4,
    retriever=None,
) -> Report:
    """Run the harness. ``retriever`` is any callable with the
    signature ``(bundle, question, top_k) -> [Concept]`` — the lexical
    default, an :class:`okf_web.retrieval.EmbeddingIndex`, or an
    engine-specific stand-in; the metric contract doesn't change."""
    retrieve_fn = retriever or retrieve
    dry_run = llm is None
    results: list[QuestionResult] = []
    for question in questions:
        retrieved = retrieve_fn(bundle, question.question, top_k)
        context = "\n\n".join(
            f"<concept path=\"/{c.rel_path}\" trust=\"{c.trust_tier}\">\n"
            f"{c.render()}\n</concept>"
            for c in retrieved
        )
        result = QuestionResult(
            question=question,
            retrieved=[c.rel_path for c in retrieved],
            context_tokens=estimate_tokens(context),
        )
        if not dry_run:
            answer = llm.complete(
                _prompt("evaluator_answer.md"),
                f"QUESTION: {question.question}\n\nCONTEXT:\n{context}",
                max_tokens=1024,
            )
            verdict = _extract_json(
                llm.complete(
                    _prompt("evaluator_judge.md"),
                    (
                        f"QUESTION: {question.question}\n\n"
                        f"ANSWER:\n{answer}\n\nCONTEXT:\n{context}"
                    ),
                    max_tokens=1024,
                )
            )
            result.answer = answer.strip()
            result.answered = bool(verdict.get("answered"))
            result.grounded = bool(verdict.get("grounded"))
            result.cited_paths = [
                str(p).lstrip("/") for p in verdict.get("cited", []) if p
            ]
            result.notes = str(verdict.get("notes") or "")
        results.append(result)
    generated_by = f"okf-web-evaluator/{llm.model}" if llm else "okf-web-evaluator/dry-run"
    return Report(results=results, generated_by=generated_by, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def write_scorecard(
    bundle: Bundle,
    report: Report,
    rel_path: str = "evaluations/geo-scorecard.md",
) -> Path:
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    metrics = report.metrics(bundle)
    fm = {
        "type": "GEO Scorecard",
        "title": f"Answerability evaluation — {now.date().isoformat()}",
        "description": (
            "Machine-generated answerability scorecard for this bundle; "
            "see x_geo.metrics for the numbers."
        ),
        "tags": ["evaluation", "geo"],
        "status": "stable",
        "generated": {"by": report.generated_by, "at": now.isoformat().replace("+00:00", "Z")},
        "x_geo": {"risk": "c", "metrics": metrics},
    }
    lines = ["# Results", ""]
    lines.append("| id | archetype | retrieved | answered | cited |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in report.results:
        answered = "—" if r.answered is None else ("yes" if r.answered else "no")
        cited = ", ".join(f"/{p}" for p in r.cited_paths) or "—"
        lines.append(
            f"| {r.question.id} | {r.question.archetype} | "
            f"{len(r.retrieved)} | {answered} | {cited} |"
        )
    gaps = report.gaps()
    lines += ["", "# Knowledge gaps", ""]
    if gaps:
        for r in gaps:
            lines.append(f"* `{r.question.id}` ({r.question.archetype}): {r.question.question}")
    else:
        lines.append("None found in this run.")
    body = "\n" + "\n".join(lines) + "\n"

    out = bundle.root / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_document(fm, body), encoding="utf-8")
    return out
