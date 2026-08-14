import json

from okf_web import cli as cli_mod
from okf_web import evaluator, logscan, review
from okf_web.model import load_bundle

_DRAFT = (
    "---\n"
    "type: {type}\n"
    "title: {title}\n"
    "description: A draft.\n"
    "tags: [t]\n"
    "status: draft\n"
    "{verified}"
    "x_geo:\n"
    "  risk: {risk}\n"
    "---\n\nBody.\n"
)

_MACHINE_VERIFIED = (
    "verified:\n"
    "  - by: process:okf-web-faithfulness-check\n"
    "    at: 2026-08-10T00:00:00Z\n"
)


def _write_draft(root, rel, risk, machine_confirmed=False):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _DRAFT.format(
            type="FAQ",
            title=rel,
            risk=risk,
            verified=_MACHINE_VERIFIED if machine_confirmed else "",
        )
    )


# --- review ergonomics ------------------------------------------------------

def test_batch_approve_clears_bc_but_never_a(bundle_copy):
    _write_draft(bundle_copy, "faq/b-draft.md", "b")
    _write_draft(bundle_copy, "faq/c-draft.md", "c")
    bundle = load_bundle(bundle_copy)
    approved = review.batch_approve(bundle, "ops@shop.example")
    paths = {c.rel_path for c in approved}
    assert paths == {"faq/b-draft.md", "faq/c-draft.md"}
    # The high-risk warranty draft is untouched — E010 stays individual.
    fresh = load_bundle(bundle_copy)
    assert fresh.concepts["policies/warranty.md"].status == "draft"
    assert fresh.concepts["faq/b-draft.md"].status == "stable"
    assert fresh.concepts["faq/b-draft.md"].trust_tier == "human-reviewed"


def test_batch_approve_only_machine_confirmed(bundle_copy):
    _write_draft(bundle_copy, "faq/unverified.md", "b")
    _write_draft(bundle_copy, "faq/confirmed.md", "b", machine_confirmed=True)
    bundle = load_bundle(bundle_copy)
    approved = review.batch_approve(
        bundle, "ops@shop.example", only_machine_confirmed=True
    )
    assert [c.rel_path for c in approved] == ["faq/confirmed.md"]


def test_batch_approve_refuses_risk_a(bundle_copy):
    import pytest

    bundle = load_bundle(bundle_copy)
    with pytest.raises(ValueError):
        review.batch_approve(bundle, "ops@shop.example", risks=("a", "b"))


def test_review_list_summary_filter_and_ci_gate(bundle_copy, capsys):
    # Example bundle has one pending item: the risk-a warranty draft.
    assert cli_mod.main(["review", "list", str(bundle_copy)]) == 0
    out = capsys.readouterr().out
    assert "pending: 1 (a: 1, b: 0, c: 0)" in out

    assert cli_mod.main(["review", "list", str(bundle_copy), "--risk", "b"]) == 0
    out = capsys.readouterr().out
    assert "warranty" not in out.split("pending:")[0]  # filtered from listing

    assert cli_mod.main(["review", "list", str(bundle_copy), "--fail-nonempty"]) == 1


def test_cli_batch_approve_requires_by(bundle_copy):
    assert cli_mod.main(["review", "batch-approve", str(bundle_copy)]) == 2


# --- starter question packs -------------------------------------------------

def test_all_packs_load_and_cover_all_archetypes(tmp_path):
    packs = cli_mod._question_packs()
    assert set(packs) == {"outdoor", "apparel", "electronics", "grocery"}
    for name, text in packs.items():
        path = tmp_path / f"{name}.yaml"
        path.write_text(text)
        questions = evaluator.load_questions(path)
        assert len(questions) == 24, name
        archetypes = {q.archetype for q in questions}
        assert archetypes == set(evaluator.ARCHETYPES), name


def test_questions_pack_cli(bundle_copy, capsys):
    # Example bundle already has a question set: refuse without --force.
    assert cli_mod.main(["questions", str(bundle_copy), "--pack", "outdoor"]) == 2
    assert cli_mod.main(
        ["questions", str(bundle_copy), "--pack", "outdoor", "--force"]
    ) == 0
    questions = evaluator.load_questions(
        bundle_copy / "evaluations" / "questions.yaml"
    )
    assert len(questions) == 24

    assert cli_mod.main(["questions", str(bundle_copy), "--pack", "nope"]) == 2
    assert cli_mod.main(["questions", str(bundle_copy), "--list-packs"]) == 0
    assert "outdoor" in capsys.readouterr().out


# --- logscan ----------------------------------------------------------------

_CLF = (
    '203.0.113.7 - - [10/Aug/2026:13:55:36 +0000] "GET /.well-known/okf/index.md HTTP/1.1" 200 2357 "-" "Mozilla/5.0 (compatible; GPTBot/1.1)"\n'
    '203.0.113.8 - - [10/Aug/2026:14:00:00 +0000] "GET /.well-known/okf/policies/returns.md HTTP/1.1" 200 1800 "-" "Mozilla/5.0"\n'
    '203.0.113.9 - - [10/Aug/2026:14:05:00 +0000] "GET /products/tent HTTP/1.1" 200 51000 "-" "GPTBot/1.1"\n'
    "garbage line that parses as nothing\n"
)
_JSONL = (
    json.dumps({
        "path": "/.well-known/okf/manifest.json",
        "user_agent": "ClaudeBot/1.0 (+https://anthropic.com)",
        "time": "2026-08-11T09:00:00Z",
    }) + "\n"
)


def test_logscan_counts_and_window():
    report = logscan.scan_lines((_CLF + _JSONL).splitlines())
    assert report.ai_hits == 2  # GPTBot index + ClaudeBot manifest
    assert report.other_hits == 1  # plain Mozilla on a bundle path
    assert report.by_agent == {"GPTBot": 1, "ClaudeBot": 1}
    assert report.by_file["index.md"] == 1
    assert report.by_file["manifest.json"] == 1
    assert report.first_seen.day == 10 and report.last_seen.day == 11


def test_logscan_cli_and_fail_empty(tmp_path, capsys):
    log = tmp_path / "access.log"
    log.write_text(_CLF + _JSONL)
    assert cli_mod.main(["logscan", str(log)]) == 0
    assert "GPTBot: 1" in capsys.readouterr().out

    quiet = tmp_path / "quiet.log"
    quiet.write_text(_CLF.splitlines()[1] + "\n")  # only the Mozilla hit
    assert cli_mod.main(["logscan", str(quiet)]) == 0
    assert cli_mod.main(["logscan", str(quiet), "--fail-empty"]) == 1
