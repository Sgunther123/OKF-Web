"""A question set measures the store it was written from (profile 1.13).
Generation is told which archetypes the outline supports and which the
store declares not applicable, marks deliberate negative probes, and
refuses an outline that describes no store; a generated set whose
ungrounded questions outnumber its grounded ones is refused; every set
the toolchain writes records its provenance, which the report states;
and a declared archetype is set aside everywhere instead of counted as
a gap. Found when a two-page site that is not a store was measured
against a set that was the prompt's own examples."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from okf_web import cli as cli_mod
from okf_web import evaluator
from okf_web.evaluator import (
    ARCHETYPES,
    ARCHETYPE_EVIDENCE,
    NotAStore,
    Question,
    UngroundedSet,
    check_grounding,
    dump_questions,
    evaluate,
    generate_questions,
    load_provenance,
    load_questions,
    stamp_pack,
    supported_archetypes,
    validate_questions,
    write_scorecard,
)
from okf_web.linter import lint_bundle
from okf_web.model import load_bundle
from okf_web.report import build_report, provenance_sentence

REPO = Path(__file__).resolve().parents[1]
PROMPT = REPO / "src" / "okf_web" / "prompts" / "evaluator_questions.md"

_INDEX = (
    "---\n"
    'okf_version: "0.2"\n'
    "title: Two Pages\n"
    "x_geo:\n"
    "  profile: ecommerce-geo/1.13\n"
    "  site: https://two.example\n"
    "{extra}"
    "---\n\n# Two Pages\n\n* [Who we are](/store-identity.md)\n"
)
_IDENTITY = (
    "---\n"
    "type: Store Identity\n"
    "title: Data Freshness and Verification Policy\n"
    "description: How this project checks that prices and stock shown anywhere are current.\n"
    "tags: [trust, freshness]\n"
    "status: stable\n"
    "x_geo:\n"
    "  risk: a\n"
    "---\n\n# Data Freshness and Verification Policy\n\n"
    "Every price and stock figure is verified against its source before it is shown.\n"
)

# What the generator wrote for that two-page site: the prompt's own
# examples, almost word for word (the rehearsal of 2026-11-06).
_ECHOED = [
    ("disc-1", "discovery", "Do you have a tent that could handle a winter camping trip in Norway?"),
    ("disc-2", "discovery", "Is there a rain jacket in your lineup good for everyday commuting?"),
    ("fact-1", "product_fact", "What's the weight of your lightest backpack?"),
    ("fact-2", "product_fact", "Does your running shoe come in half sizes?"),
    ("comp-1", "comparison", "Which keeps you warmer, your down jacket or your synthetic one?"),
    ("pol-1", "policy", "Can I send something back if I already opened the box?"),
    ("ful-1", "fulfillment", "How long does it usually take for a package to reach Canada?"),
    ("trust-1", "trust", "How do I know the prices and stock counts on your site are actually current?"),
    ("own-1", "ownership", "Can I machine-wash the jacket I bought from you?"),
    ("proc-1", "procurement", "We need 40 units by October: what's the minimum order size and lead time?"),
]


def _two_pages(tmp_path: Path, extra: str = "") -> Path:
    root = tmp_path / "two"
    root.mkdir()
    (root / "index.md").write_text(_INDEX.format(extra=extra), encoding="utf-8")
    (root / "store-identity.md").write_text(_IDENTITY, encoding="utf-8")
    return root


class _Scripted:
    model = "scripted"

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 0) -> str:
        self.prompts.append((system, user))
        return self.reply


def _reply(items, extra: str = "") -> str:
    body = "\n".join(
        f"  - id: {i}\n    archetype: {a}\n    question: {q!r}\n    paraphrase: {q!r}"
        + (f"\n    probe: {p}" if p else "")
        for i, a, q, p in items
    )
    return f"```yaml\nquestions:\n{body}\n{extra}```"


# --- the prompt ----------------------------------------------------------------------

def test_the_prompt_carries_no_vertical_and_states_the_rules():
    text = " ".join(PROMPT.read_text(encoding="utf-8").split())
    for noun in ("tent", "tents", "jacket", "Norway", "camping", "sleeping", "gear", "down filling"):
        assert not re.search(rf"\b{noun}\b", text), noun
    for rule in ("SUPPORTED", "NOT_APPLICABLE", "probe: negative", "not-a-store",
                 "Never reuse the wording of this prompt", "grounded in the outline"):
        assert rule in text, rule


# --- evidence and support --------------------------------------------------------------

def test_every_archetype_has_evidence_types_and_support_follows_them(tmp_path, example_bundle):
    assert set(ARCHETYPE_EVIDENCE) == set(ARCHETYPES)
    assert supported_archetypes(load_bundle(example_bundle)) == list(ARCHETYPES)
    thin = load_bundle(_two_pages(tmp_path))
    assert supported_archetypes(thin) == ["discovery", "fulfillment", "trust"]


# --- generation ----------------------------------------------------------------------

def test_generation_tells_the_model_what_is_supported_and_declared_and_keeps_probes(tmp_path):
    root = _two_pages(tmp_path, extra="  not_applicable: [procurement]\n")
    reply = _reply([
        ("trust-1", "trust", "How do I know the prices you show are current?", ""),
        ("disc-1", "discovery", "Do you sell anything I can buy?", "negative"),
        ("proc-1", "procurement", "Do you offer wholesale terms?", ""),
    ])
    llm = _Scripted(reply)
    questions = generate_questions(load_bundle(root), llm)
    system, user = llm.prompts[0]
    assert "SUPPORTED: discovery, fulfillment, trust" in user
    assert "NOT_APPLICABLE: procurement" in user
    assert [q.id for q in questions] == ["trust-1", "disc-1"]  # the declared one dropped
    assert questions[1].probe == "negative" and questions[0].probe == ""


def test_an_outline_that_is_not_a_store_is_refused(tmp_path, monkeypatch, capsys):
    root = _two_pages(tmp_path)
    llm = _Scripted("```yaml\nquestions: []\nreason: not-a-store\n```")
    with pytest.raises(NotAStore):
        generate_questions(load_bundle(root), llm)
    monkeypatch.setattr(cli_mod, "_llm", lambda args: llm)
    assert cli_mod.main(["questions", str(root)]) == 2
    assert "describes no store" in capsys.readouterr().err
    assert not (root / "evaluations" / "questions.yaml").exists()


def test_an_echoed_set_is_ungrounded_and_refused_unless_allowed(tmp_path, monkeypatch, capsys):
    root = _two_pages(tmp_path)
    bundle = load_bundle(root)
    questions = [Question(i, a, q) for i, a, q in _ECHOED]
    report = check_grounding(bundle, questions)
    assert report.grounded == ["trust-1"]  # prices, stock, current
    assert len(report.ungrounded) == len(_ECHOED) - 1 and not report.fit
    assert "9 ungrounded" in report.summary()

    llm = _Scripted(_reply([(i, a, q, "") for i, a, q in _ECHOED]))
    monkeypatch.setattr(cli_mod, "_llm", lambda args: llm)
    assert cli_mod.main(["questions", str(root)]) == 2
    err = capsys.readouterr().err
    assert "9 of 10 generated questions share no vocabulary" in err
    out = root / "evaluations" / "questions.yaml"
    assert not out.exists()

    assert cli_mod.main(["questions", str(root), "--allow-ungrounded"]) == 0
    printed = capsys.readouterr().out
    assert "1 grounded, 9 ungrounded" in printed and "--allow-ungrounded" in printed
    meta = load_provenance(out)
    assert meta["source"] == "generated"
    assert meta["generated"]["by"] == "okf-web-evaluator/scripted"
    assert meta["generated"]["from_concepts"] == 1
    assert meta["grounding"] == {"grounded": 1, "ungrounded": 9, "probes": 0}
    assert len(load_questions(out)) == 10
    assert "were generated from 1 knowledge entries by okf-web-evaluator/scripted, not yet curated" in provenance_sentence(load_bundle(root))


def test_the_example_set_is_grounded_with_its_one_probe(example_bundle):
    bundle = load_bundle(example_bundle)
    questions = load_questions(example_bundle / "evaluations" / "questions.yaml")
    report = check_grounding(bundle, questions)
    assert report.fit and report.probes == ["disc-3"] and not report.excess_probes
    assert len(report.grounded) >= 30, report.ungrounded


def test_the_probe_allowance_is_one_per_archetype(tmp_path):
    bundle = load_bundle(_two_pages(tmp_path))
    report = check_grounding(bundle, [
        Question("d1", "discovery", "Anything at all for sale?", probe="negative"),
        Question("d2", "discovery", "Anything else for sale?", probe="negative"),
        Question("t1", "trust", "Are the prices shown current?"),
    ])
    assert report.probes == ["d1"] and report.excess_probes == ["d2"]
    assert report.ungrounded == ["d2"] and report.grounded == ["t1"] and report.fit


# --- declared applicability ------------------------------------------------------------

def _declare(bundle_copy: Path, names: str) -> None:
    index = bundle_copy / "index.md"
    text = index.read_text(encoding="utf-8")
    assert text.count("  language: en\n") == 1
    index.write_text(text.replace("  language: en\n", f"  language: en\n  not_applicable: [{names}]\n"), encoding="utf-8")


def test_a_declared_archetype_is_set_aside_by_evaluation_scorecard_and_report(bundle_copy):
    _declare(bundle_copy, "procurement")
    bundle = load_bundle(bundle_copy)
    assert bundle.not_applicable == ["procurement"]
    questions = load_questions(bundle_copy / "evaluations" / "questions.yaml")
    report = evaluate(bundle, questions)
    assert report.not_applicable == {"procurement": 3}
    assert all(r.question.archetype != "procurement" for r in report.results)
    metrics = report.metrics(bundle)
    assert metrics["questions"] == 36 and metrics["not_applicable"] == {"procurement": 3}
    assert "procurement" not in metrics["by_archetype"]
    write_scorecard(bundle, report, force=True)
    bundle = load_bundle(bundle_copy)
    assert bundle.concepts["evaluations/geo-scorecard.md"].x_geo["metrics"]["not_applicable"] == {"procurement": 3}
    page = build_report(bundle)
    assert '<tr class="na"><td>Wholesale and B2B</td><td>not applicable, declared by the store</td></tr>' in page
    assert page.count("not applicable, declared by the store") == 1


def test_generation_writes_nothing_for_a_declared_archetype_and_lint_checks_the_declaration(bundle_copy):
    _declare(bundle_copy, "procurement, nonsense")
    _, found = lint_bundle(bundle_copy)
    findings = [f for f in found if f.code == "W044"]
    messages = sorted(f.message for f in findings)
    assert len(messages) == 2
    assert any("`nonsense`" in m and "not a question archetype" in m for m in messages)
    assert any("`procurement`" in m and "Trade Program" in m for m in messages)


# --- provenance ----------------------------------------------------------------------

def test_packs_are_stamped_and_the_report_says_so(bundle_copy, capsys):
    assert cli_mod.main(["questions", str(bundle_copy), "--pack", "outdoor", "--force"]) == 0
    out = bundle_copy / "evaluations" / "questions.yaml"
    assert load_provenance(out) == {"source": "pack:outdoor"}
    assert len(load_questions(out)) == 39
    sentence = provenance_sentence(load_bundle(bundle_copy))
    assert sentence == (
        "The 39 questions measured are the outdoor starter pack, a vertical's "
        "generic questions, not this store's, not yet curated by anyone."
    )
    assert stamp_pack("questions: []\n", "apparel").startswith("meta:\n  source: pack:apparel\n")


def test_the_example_report_states_the_curated_provenance(example_bundle):
    bundle = load_bundle(example_bundle)
    sentence = provenance_sentence(bundle)
    assert sentence == (
        "The 39 questions measured were generated from 19 knowledge entries by "
        "okf-web-evaluator/claude-sonnet-5, then curated by "
        "human:merch-lead@alpinepeakoutfitters.example."
    )
    assert sentence in build_report(bundle).replace("&#x27;", "'")


def test_a_set_without_meta_is_said_to_record_none(tmp_path):
    root = _two_pages(tmp_path)
    (root / "evaluations").mkdir()
    (root / "evaluations" / "questions.yaml").write_text(
        "questions:\n  - id: t1\n    archetype: trust\n    question: Are the prices current?\n",
        encoding="utf-8",
    )
    assert load_provenance(root / "evaluations" / "questions.yaml") == {}
    assert provenance_sentence(load_bundle(root)) == (
        "The 1 questions measured are of unrecorded origin, not yet curated by anyone."
    )


def test_dump_and_load_keep_meta_probe_and_paraphrase(tmp_path):
    text = dump_questions(
        [Question("d1", "discovery", "Any tents?", paraphrase="Got shelters?", probe="negative"),
         Question("t1", "trust", "Who are you?")],
        {"source": "generated", "curated_by": "human:me"},
    )
    data = yaml.safe_load(text)
    assert list(data) == ["meta", "questions"]
    assert data["questions"][0] == {"id": "d1", "archetype": "discovery", "question": "Any tents?",
                                    "paraphrase": "Got shelters?", "probe": "negative"}
    assert "probe" not in data["questions"][1] and "paraphrase" not in data["questions"][1]
    path = tmp_path / "q.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_questions(path)
    assert loaded[0].probe == "negative" and loaded[1].probe == ""
    assert load_provenance(path)["curated_by"] == "human:me"


def test_validate_rejects_an_unknown_probe():
    problems = validate_questions([Question("d1", "discovery", "Any?", probe="maybe")])
    assert problems == ["question 'd1': probe 'maybe' is not 'negative'"]


def test_the_two_refusals_are_question_set_errors():
    assert issubclass(NotAStore, evaluator.QuestionSetError)
    assert issubclass(UngroundedSet, evaluator.QuestionSetError)
