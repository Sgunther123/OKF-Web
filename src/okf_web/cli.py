"""``okf-web`` command line interface.

Subcommands mirror the lifecycle: survey → review → lint → evaluate →
publish. LLM-backed commands (survey, questions, evaluate without
--dry-run) need ``pip install okf-web[llm]`` and ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import evaluator, linter, publisher, review, surveyor
from .model import load_bundle


def _llm(model: str):
    from .llm import AnthropicClient

    return AnthropicClient(model=model)


def cmd_lint(args) -> int:
    _, findings = linter.lint_bundle(args.bundle)
    for finding in findings:
        print(finding)
    errors = [f for f in findings if f.severity == linter.ERROR]
    warnings = [f for f in findings if f.severity == linter.WARNING]
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    return 0


def cmd_review(args) -> int:
    bundle = load_bundle(args.bundle)
    if args.action == "list":
        items = review.pending(bundle)
        if not items:
            print("review queue is empty")
            return 0
        for item in items:
            c = item.concept
            print(
                f"[risk {c.risk}] {c.rel_path} ({c.type}, {c.trust_tier}) — "
                + "; ".join(item.reasons)
            )
        proposed = sorted((Path(args.bundle) / "_review" / "proposed").rglob("*.md"))
        if proposed:
            print("\ndrift proposals (surveyor found changes to human-reviewed concepts):")
            for path in proposed:
                print(f"  {path}")
        return 0
    if not args.path or not args.by:
        print("approve/reject need a concept path and --by <reviewer-id>", file=sys.stderr)
        return 2
    if args.action == "approve":
        concept = review.approve(bundle, args.path, args.by)
        print(f"approved {concept.rel_path} -> {concept.trust_tier}, status {concept.status}")
    else:
        concept = review.reject(bundle, args.path, args.by, args.reason or "no reason given")
        print(f"rejected {concept.rel_path}; kept as draft")
    return 0


def cmd_survey(args) -> int:
    urls: list[str] = []
    if args.sitemap:
        urls.extend(surveyor.discover_sitemap(args.sitemap))
    if args.urls:
        urls.extend(
            line.strip()
            for line in Path(args.urls).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    if not urls:
        print("no URLs: pass --sitemap BASE_URL and/or --urls FILE", file=sys.stderr)
        return 2
    if args.limit:
        urls = urls[: args.limit]
    result = surveyor.survey(urls, args.bundle, _llm(args.model))
    print(
        f"written: {len(result.written)}  proposed: {len(result.proposed)}  "
        f"unchanged: {len(result.skipped_unchanged)}  "
        f"quarantined: {len(result.quarantined)}  errors: {len(result.errors)}"
    )
    for rel in result.written:
        print(f"  draft: {rel}")
    for rel in result.proposed:
        print(f"  drift proposal: _review/proposed/{rel}")
    for err in result.errors:
        print(f"  error: {err}", file=sys.stderr)
    return 0 if not result.errors else 1


def cmd_index(args) -> int:
    surveyor.rebuild_index(args.bundle)
    print("index.md rebuilt")
    return 0


def cmd_questions(args) -> int:
    bundle = load_bundle(args.bundle)
    questions = evaluator.generate_questions(
        bundle, _llm(args.model), per_archetype=args.per_archetype
    )
    out = Path(args.bundle) / "evaluations" / "questions.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    out.write_text(
        yaml.safe_dump(
            {
                "questions": [
                    {"id": q.id, "archetype": q.archetype, "question": q.question}
                    for q in questions
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(questions)} questions to {out}")
    return 0


def cmd_evaluate(args) -> int:
    bundle = load_bundle(args.bundle)
    questions_path = Path(args.questions or Path(args.bundle) / "evaluations" / "questions.yaml")
    if not questions_path.exists():
        print(f"question set not found: {questions_path}", file=sys.stderr)
        return 2
    questions = evaluator.load_questions(questions_path)
    llm = None if args.dry_run else _llm(args.model)
    report = evaluator.evaluate(bundle, questions, llm=llm, top_k=args.top_k)
    metrics = report.metrics(bundle)
    for key, value in metrics.items():
        if key != "by_archetype":
            print(f"{key}: {value}")
    gaps = report.gaps()
    if gaps:
        print(f"\nknowledge gaps ({len(gaps)}):")
        for r in gaps:
            print(f"  {r.question.id} [{r.question.archetype}] {r.question.question}")
    if args.write_scorecard:
        out = evaluator.write_scorecard(bundle, report)
        print(f"\nscorecard written to {out}")
    return 0


def cmd_publish(args) -> int:
    try:
        result = publisher.publish(
            args.bundle,
            args.dist,
            include_machine_confirmed=args.include_machine_confirmed,
            base_path=args.base_path,
        )
    except publisher.PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"published {len(result.published)} file(s) to {result.dist}")
    if result.withheld:
        print(f"withheld {len(result.withheld)} unapproved draft(s):")
        for rel in result.withheld:
            print(f"  {rel}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="okf-web",
        description="Survey, verify, evaluate, and publish an OKF companion bundle "
        "for an ecommerce site.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("lint", help="check spec conformance + profile rules")
    p.add_argument("bundle")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("review", help="human-in-the-loop verification queue")
    p.add_argument("action", choices=["list", "approve", "reject"])
    p.add_argument("bundle")
    p.add_argument("path", nargs="?", help="concept path within the bundle")
    p.add_argument("--by", help="reviewer id (becomes human:<id>)")
    p.add_argument("--reason", help="rejection reason")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("survey", help="LLM-populate draft concepts from site pages")
    p.add_argument("bundle")
    p.add_argument("--sitemap", help="site base URL; reads <base>/sitemap.xml")
    p.add_argument("--urls", help="file with one URL per line")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="claude-sonnet-5")
    p.set_defaults(func=cmd_survey)

    p = sub.add_parser("index", help="rebuild index.md from bundle contents")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("questions", help="LLM-generate an evaluation question set")
    p.add_argument("bundle")
    p.add_argument("--per-archetype", type=int, default=3)
    p.add_argument("--model", default="claude-sonnet-5")
    p.set_defaults(func=cmd_questions)

    p = sub.add_parser("evaluate", help="run the answerability evaluation")
    p.add_argument("bundle")
    p.add_argument("--questions", help="question set YAML (default: bundle/evaluations/questions.yaml)")
    p.add_argument("--dry-run", action="store_true", help="retrieval-only, no LLM")
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--model", default="claude-sonnet-5")
    p.add_argument("--write-scorecard", action="store_true")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("publish", help="build the static companion bundle")
    p.add_argument("bundle")
    p.add_argument("dist")
    p.add_argument(
        "--include-machine-confirmed",
        action="store_true",
        help="also publish non-high-risk drafts (they surface as unverified/machine-confirmed)",
    )
    p.add_argument("--base-path", default="/.well-known/okf")
    p.set_defaults(func=cmd_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
