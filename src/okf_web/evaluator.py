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
    trust_mix,
    utc_instant,
    parse_document,
    write_atomic,
    language_primary,
)
from .text import words

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

# Stop words per language, in the tokenizer's folded spelling (accents
# stripped, lowercase): function words a shopper's question and a
# concept share without meaning anything. Keyed by the primary subtag of
# the bundle's (or view's) language — `stopwords_for`. The English list is
# the historical one and stays byte-identical so an undeclared bundle
# ranks exactly as before.
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset({
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
        "are", "do", "does", "can", "i", "my", "you", "your", "what", "how",
        "much", "many", "with", "it", "this", "that", "be", "will",
    }),
    "es": frozenset({
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
        "al", "a", "en", "por", "para", "con", "sin", "sobre", "y", "o", "u",
        "que", "es", "son", "esta", "estan", "ser", "estar", "hay", "tiene",
        "tienen", "teneis", "tengo", "tenemos", "puedo", "puede", "pueden",
        "podeis", "podemos", "se", "su", "sus", "mi", "mis", "tu", "tus",
        "nuestro", "nuestra", "vuestro", "vuestra", "lo", "le", "les", "me",
        "te", "nos", "os", "yo", "usted", "ustedes", "como", "cual", "cuales",
        "cuanto", "cuanta", "cuantos", "cuantas", "donde", "cuando", "quien",
        "si", "este", "estos", "estas", "ese", "esa", "esos", "esas", "esto",
        "eso",
    }),
    "de": frozenset({
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen",
        "einem", "einer", "eines", "und", "oder", "aber", "in", "im", "an",
        "am", "auf", "aus", "bei", "fur", "mit", "nach", "von", "vom", "zu",
        "zum", "zur", "uber", "unter", "ist", "sind", "war", "waren", "sein",
        "bin", "bist", "seid", "hat", "haben", "habe", "habt", "wird",
        "werden", "kann", "konnen", "konnt", "kannst", "ich", "du", "er",
        "sie", "es", "wir", "ihr", "mein", "meine", "meinen", "meinem",
        "meiner", "dein", "deine", "euer", "eure", "ihre", "ihren", "ihrem",
        "unser", "unsere", "was", "wie", "wo", "wann", "welche", "welcher",
        "welches", "wer", "ob", "dass",
    }),
    "fr": frozenset({
        "le", "la", "les", "l", "un", "une", "des", "de", "du", "d", "a",
        "au", "aux", "en", "dans", "sur", "pour", "par", "avec", "sans", "et",
        "ou", "que", "qui", "quoi", "qu", "est", "sont", "etre", "ete",
        "etes", "avons", "avez", "ont", "ai", "as", "il", "elle", "ils",
        "elles", "je", "j", "tu", "nous", "vous", "on", "mon", "ma", "mes",
        "ton", "ta", "tes", "son", "sa", "ses", "notre", "nos", "votre",
        "vos", "leur", "leurs", "ce", "c", "cet", "cette", "ces", "ca", "y",
        "ne", "n", "s", "m", "t", "quel", "quelle", "quels", "quelles",
        "comment", "combien", "quand", "puis", "peut", "peuvent", "pouvez",
        "pouvons",
    }),
    "pt": frozenset({
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da",
        "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "pelo",
        "pela", "com", "sem", "sobre", "e", "ou", "que", "sao", "esta",
        "estao", "ser", "estar", "ha", "tem", "tenho", "temos", "pode",
        "posso", "podem", "podemos", "se", "seu", "sua", "seus", "suas",
        "meu", "minha", "meus", "minhas", "nosso", "nossa", "vosso", "vossa",
        "eu", "tu", "voce", "voces", "ele", "ela", "eles", "elas", "como",
        "qual", "quais", "quanto", "quanta", "quantos", "quantas", "onde",
        "quando", "quem", "este", "estes", "estas", "esse", "essa", "esses",
        "essas", "isto", "isso", "ao", "aos",
    }),
    "it": frozenset({
        "il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una", "di",
        "del", "dello", "della", "dei", "degli", "delle", "a", "al", "allo",
        "alla", "ai", "agli", "alle", "da", "dal", "dallo", "dalla", "dai",
        "dagli", "dalle", "in", "nel", "nello", "nella", "nei", "negli",
        "nelle", "su", "sul", "sullo", "sulla", "sui", "sugli", "sulle",
        "per", "con", "tra", "fra", "e", "o", "che", "chi", "cui", "sono",
        "essere", "ho", "hai", "ha", "abbiamo", "avete", "hanno", "posso",
        "puo", "possono", "potete", "possiamo", "si", "mi", "ti", "ci", "vi",
        "li", "ne", "mio", "mia", "miei", "mie", "tuo", "tua", "tuoi", "tue",
        "suo", "sua", "suoi", "sue", "nostro", "nostra", "vostro", "vostra",
        "loro", "come", "quale", "quali", "quanto", "quanta", "quanti",
        "quante", "dove", "quando", "questo", "questa", "questi", "queste",
        "quello", "quella", "quelli", "quelle", "io", "tu", "lui", "lei",
        "noi", "voi",
    }),
    "nl": frozenset({
        "de", "het", "een", "en", "of", "van", "in", "op", "voor", "met",
        "aan", "bij", "naar", "uit", "over", "tot", "om", "is", "zijn", "ben",
        "bent", "was", "waren", "heb", "hebt", "heeft", "hebben", "kan",
        "kunnen", "kunt", "wordt", "worden", "ik", "je", "jij", "u", "hij",
        "zij", "ze", "we", "wij", "jullie", "mijn", "mij", "me", "jouw",
        "jou", "uw", "haar", "ons", "onze", "hun", "hen", "wat", "hoe",
        "waar", "wanneer", "welke", "welk", "wie", "dat", "die", "dit",
        "deze", "er",
    }),
}
_STOPWORDS = STOPWORDS["en"]  # the historical name, the historical list


def stopwords_for(lang: str) -> frozenset[str]:
    """The stop-word list for a language tag: the English list for an
    undeclared bundle (the historical default), the language's own list
    when one ships, and none for a declared language without one — an
    English list applied to Japanese bigrams or Swedish words would be
    noise, not signal."""
    if not lang:
        return STOPWORDS["en"]
    return STOPWORDS.get(language_primary(lang), frozenset())


@dataclass
class Question:
    id: str
    archetype: str
    question: str
    # The same question in a shopper's own words — synonyms, no product
    # names (READINESS R3): the curated phrasing shares vocabulary with
    # the bundle, so its hit rate flatters lexical retrieval; the
    # paraphrase measures what a merchant's customers will experience.
    paraphrase: str = ""


@dataclass
class QuestionResult:
    question: Question
    retrieved: list[str]
    context_tokens: int
    retrieved_paraphrase: list[str] | None = None
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
        # The phrasing-gap columns (READINESS R3): retrieval measured on
        # the shopper-vocabulary paraphrases, where the question set
        # carries them. `paraphrase_hit_rate` mirrors the primary metric
        # (anything retrieved at all — saturates on small bundles);
        # `paraphrase_agreement` is the honest one: the paraphrase found
        # at least one of the same concepts the curated phrasing found.
        # A drop is the finding — it is what customers will experience.
        with_para = [r for r in self.results if r.retrieved_paraphrase is not None]
        if with_para:
            metrics["paraphrase_questions"] = len(with_para)
            metrics["paraphrase_hit_rate"] = round(
                sum(1 for r in with_para if r.retrieved_paraphrase) / len(with_para),
                3,
            )
            metrics["paraphrase_agreement"] = round(
                sum(
                    1
                    for r in with_para
                    if set(r.retrieved_paraphrase) & set(r.retrieved)
                )
                / len(with_para),
                3,
            )
        metrics["trust_mix"] = trust_mix(bundle)
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

class QuestionSetError(ValueError):
    """The question set cannot be evaluated as it stands (EDGE-CASES A3)."""


class ScorecardGuard(ValueError):
    """A dry-run scorecard would replace a judged one (EDGE-CASES A3)."""


def validate_questions(questions: list[Question]) -> list[str]:
    """Problems that make a question set unfit to gate on: empty,
    duplicate ids, archetypes outside ``ARCHETYPES``. Empty when fine."""
    problems: list[str] = []
    if not questions:
        problems.append("the question set is empty")
    seen: set[str] = set()
    for q in questions:
        if q.id in seen:
            problems.append(f"duplicate question id {q.id!r}")
        seen.add(q.id)
        if q.archetype not in ARCHETYPES:
            problems.append(
                f"question {q.id!r}: unknown archetype {q.archetype!r} "
                f"(known: {', '.join(ARCHETYPES)})"
            )
    return problems


def load_questions(path: Path | str) -> list[Question]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for i, item in enumerate(data.get("questions", []), start=1):
        out.append(
            Question(
                id=str(item.get("id") or f"q{i}"),
                archetype=str(item.get("archetype") or "discovery"),
                question=str(item.get("question") or "").strip(),
                paraphrase=str(item.get("paraphrase") or "").strip(),
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
        f"ARCHETYPES: {', '.join(ARCHETYPES)}\n"
        f"LANGUAGE: {bundle.language or 'undeclared'}\n\n"
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

def _tokens(text: str, lang: str = "") -> list[str]:
    """The informative tokens of ``text`` in ``lang`` (the bundle's or
    view's language; empty means undeclared, English stop words)."""
    stop = stopwords_for(lang)
    return [t for t in words(text) if t not in stop]


# The share of a question's informative weight (idf mass) a concept
# must carry to count as a hit. Lexical overlap cannot tell an
# off-topic question from a terse one — "quantum flux capacitor lunar
# warranty" legitimately matches the warranty policy — so the floor
# only removes the noise tail: a concept sharing one common word with
# a long question. Every hit carries its relevance so callers (the MCP
# bridge) can label weak matches instead of pretending a threshold is
# truth (GAPS item 2). Callers may raise it (`--min-relevance`).
RELEVANCE_FLOOR = 0.05


# Meta-knowledge about the bundle itself (scorecards) never
# participates in retrieval: it describes the evaluation, not the
# store, and its tables are dense with concept paths that would
# pollute ranking. Shared with the embedding retriever.
META_TYPES = {"GEO Scorecard"}


def _lexical_index(bundle: Bundle) -> tuple[dict, dict, dict, int]:
    """Inverted index over the bundle's retrievable concepts, built once
    per :class:`Bundle` instance and cached on it (READINESS R4): the
    old per-query re-tokenization of every concept made each query
    O(bundle); with postings, a query touches only the concepts that
    share a term with it. The index snapshots the instance at first
    retrieval — consumers treat a loaded Bundle as an immutable view
    (the evaluator, the MCP bridge); reload after in-place edits.

    Returns ``(postings, intent_tokens, by_rel, n_docs)`` where
    ``postings[term][rel]`` is the term count and ``n_docs`` counts every
    candidate (including token-less ones), preserving the exact idf of
    the pre-index implementation.
    """
    cached = getattr(bundle, "_lexical_cache", None)
    if cached is not None:
        return cached
    lang = bundle.language  # the view's language picks the stop words
    postings: dict[str, dict[str, int]] = {}
    intent_tokens: dict[str, set[str]] = {}
    by_rel: dict[str, Concept] = {}
    n_docs = 0
    for rel, concept in bundle.concepts.items():
        if concept.type in META_TYPES or split_l10n(rel) is not None:
            continue
        n_docs += 1
        toks = _tokens(concept.retrieval_text(), lang)
        if not toks:
            continue
        by_rel[rel] = concept
        intent_tokens[rel] = set(_tokens(" ".join(concept.intents), lang))
        counts: dict[str, int] = {}
        for tok in toks:
            counts[tok] = counts.get(tok, 0) + 1
        for tok, count in counts.items():
            postings.setdefault(tok, {})[rel] = count
    index = (postings, intent_tokens, by_rel, max(1, n_docs))
    bundle._lexical_cache = index
    return index


def retrieve_scored(
    bundle: Bundle,
    question: str,
    top_k: int = 4,
    min_relevance: float = RELEVANCE_FLOOR,
) -> list[tuple[Concept, float]]:
    """Rank concepts by overlap with the question (tf * idf-lite) and
    return ``(concept, relevance)`` pairs, best first.

    ``relevance`` is the share of the question's idf mass the concept
    matched (0..1): 1.0 means every informative word of the question
    occurs in the concept, 0.1 that only a sliver does. Hits below
    ``min_relevance`` are dropped.

    Translation trees (``l10n/<lang>/``) are excluded by key: in the
    default view they would duplicate their sources in another
    language, while in a ``localized_view`` the active translation
    sits under its source key and participates normally.
    """
    query = set(_tokens(question, bundle.language))
    if not query:
        return []
    postings, intent_tokens, by_rel, n_docs = _lexical_index(bundle)
    idf = {
        term: math.log(1 + n_docs / (1 + len(postings.get(term, {}))))
        for term in query
    }
    total = sum(idf.values()) or 1.0
    hit_rels: set[str] = set()
    for term in query:
        hit_rels.update(postings.get(term, ()))
    scored: list[tuple[float, float, Concept]] = []
    for rel in hit_rels:
        score = 0.0
        matched = 0.0
        for term in query:
            count = postings.get(term, {}).get(rel, 0)
            if count == 0:
                continue
            score += (1 + math.log(count)) * idf[term]
            matched += idf[term]
        # Small boost when the concept declares an intent matching words
        # in the question (e.g. "return" → policy concepts).
        score *= 1.0 + 0.1 * len(query & intent_tokens[rel])
        relevance = matched / total
        if score > 0 and relevance >= min_relevance:
            scored.append((score, relevance, by_rel[rel]))
    scored.sort(key=lambda t: (-t[0], t[2].rel_path))
    return [(c, round(r, 3)) for _, r, c in scored[:top_k]]


def retrieve(
    bundle: Bundle,
    question: str,
    top_k: int = 4,
    min_relevance: float = RELEVANCE_FLOOR,
) -> list[Concept]:
    """The default retriever: :func:`retrieve_scored` without the scores
    (the evaluator's retriever contract is ``(bundle, question, top_k)
    -> [Concept]``)."""
    return [c for c, _ in retrieve_scored(bundle, question, top_k, min_relevance)]


# ---------------------------------------------------------------------------
# Answer + judge
# ---------------------------------------------------------------------------

def _prompt(name: str) -> str:
    return resources.files("okf_web").joinpath(f"prompts/{name}").read_text("utf-8")


def _safe_body(text: str) -> str:
    """A rendered concept with any block delimiter it carries
    neutralized: a body may say anything, but it cannot open or close a
    ``<concept>`` block of its own (EDGE-CASES S11)."""
    return text.replace("<concept", "&lt;concept").replace("</concept", "&lt;/concept")


def render_context(retrieved: list[Concept]) -> str:
    """The CONTEXT the answerer and the judge see: one ``<concept>``
    block per retrieved concept, path and trust written by the harness,
    the body inert."""
    return "\n\n".join(
        f"<concept path=\"/{c.rel_path}\" trust=\"{c.trust_tier}\">\n"
        f"{_safe_body(c.render())}\n</concept>"
        for c in retrieved
    )


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
    judge=None,
) -> Report:
    """Run the harness. ``retriever`` is any callable with the
    signature ``(bundle, question, top_k) -> [Concept]`` — the lexical
    default, an :class:`okf_web.retrieval.EmbeddingIndex`, or an
    engine-specific stand-in; the metric contract doesn't change.

    ``judge`` decouples grading from answering (READINESS R3): a
    distinct LLM client for the judge calls, so coverage/groundedness
    are not a model grading its own family's work. Defaults to ``llm``
    (self-graded — the scorecard's recorded identities say so either
    way)."""
    retrieve_fn = retriever or retrieve
    dry_run = llm is None
    judge_llm = judge or llm
    results: list[QuestionResult] = []
    for question in questions:
        retrieved = retrieve_fn(bundle, question.question, top_k)
        context = render_context(retrieved)
        result = QuestionResult(
            question=question,
            retrieved=[c.rel_path for c in retrieved],
            context_tokens=estimate_tokens(context),
        )
        if question.paraphrase:
            result.retrieved_paraphrase = [
                c.rel_path for c in retrieve_fn(bundle, question.paraphrase, top_k)
            ]
        if not dry_run:
            answer = llm.complete(
                _prompt("evaluator_answer.md"),
                f"QUESTION: {question.question}\n\nCONTEXT:\n{context}",
                max_tokens=1024,
            )
            verdict = _extract_json(
                judge_llm.complete(
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
    if llm is None:
        generated_by = "okf-web-evaluator/dry-run"
    elif judge_llm is not llm and getattr(judge_llm, "model", None) != llm.model:
        # Both identities on the record: a reader can see the grading
        # was independent — or, absent this suffix, that it was not.
        generated_by = f"okf-web-evaluator/{llm.model}+judge/{judge_llm.model}"
    else:
        generated_by = f"okf-web-evaluator/{llm.model}"
    return Report(results=results, generated_by=generated_by, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def _is_judged_scorecard(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        fm, _ = parse_document(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — an unreadable scorecard guards nothing
        return False
    x_geo = fm.get("x_geo") if isinstance(fm, dict) else None
    metrics = x_geo.get("metrics") if isinstance(x_geo, dict) else None
    return isinstance(metrics, dict) and "coverage" in metrics


def write_scorecard(
    bundle: Bundle,
    report: Report,
    rel_path: str = "evaluations/geo-scorecard.md",
    force: bool = False,
) -> Path:
    """Write the scorecard concept. A dry-run report never silently
    replaces a judged scorecard (one carrying ``coverage``): that would
    erase the graded numbers the report and the viewer show; pass
    ``force`` to do it on purpose (EDGE-CASES A3)."""
    out = bundle.root / rel_path
    if report.dry_run and not force and _is_judged_scorecard(out):
        raise ScorecardGuard(
            f"refusing to replace the judged scorecard {out} with a dry-run "
            "one (its coverage, groundedness and citability would be lost); "
            "run the full evaluation with an LLM, or pass --force to overwrite "
            "it deliberately"
        )
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
        # The evaluation SLA made real (EVALUATION.md; F5): a scorecard
        # is a snapshot, and 30 days is how long it may claim freshness
        # before the freshness machinery retires it — re-evaluate to
        # renew. Stamped at the spec's instant precision.
        "stale_after": utc_instant(now + _dt.timedelta(days=30)),
        "generated": {"by": report.generated_by, "at": now.isoformat().replace("+00:00", "Z")},
        "x_geo": {"risk": "c", "metrics": metrics},
    }
    lines = ["# Results", ""]
    lines.append("| id | archetype | retrieved | paraphrase | answered | cited |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in report.results:
        answered = "—" if r.answered is None else ("yes" if r.answered else "no")
        cited = ", ".join(f"/{p}" for p in r.cited_paths) or "—"
        if r.retrieved_paraphrase is None:
            para = "—"
        elif set(r.retrieved_paraphrase) & set(r.retrieved):
            para = "hit"
        elif r.retrieved_paraphrase:
            para = "diverged"  # found *something*, but not the same knowledge
        else:
            para = "miss"
        lines.append(
            f"| {r.question.id} | {r.question.archetype} | "
            f"{len(r.retrieved)} | {para} | {answered} | {cited} |"
        )
    gaps = report.gaps()
    lines += ["", "# Knowledge gaps", ""]
    if gaps:
        for r in gaps:
            lines.append(f"* `{r.question.id}` ({r.question.archetype}): {r.question.question}")
    else:
        lines.append("None found in this run.")
    body = "\n" + "\n".join(lines) + "\n"

    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(out, render_document(fm, body))
    return out
