"""``okf-web`` command line interface.

Subcommands mirror the lifecycle: survey → review → lint → evaluate →
publish. LLM-backed commands (survey, questions, evaluate without
--dry-run) take ``--llm`` to choose how calls are billed and
authenticated:

* ``--llm api`` (default) — the Anthropic SDK; needs ``pip install
  okf-web[llm]`` plus either ``ANTHROPIC_API_KEY`` or a keyless
  ``ant auth login`` OAuth profile. Use this for anything scheduled or
  unattended.
* ``--llm claude-code`` — routes calls through a locally installed,
  logged-in Claude Code in print mode, drawing on your existing Claude
  subscription. Interactive, human-initiated runs only; no extra
  Python dependency.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import evaluator, linter, publisher, review, signing, surveyor
from .model import load_bundle


def _llm(args):
    if getattr(args, "llm", "api") == "claude-code":
        from .llm import claude_code_client

        return claude_code_client(model=args.model)
    from .llm import AnthropicClient

    return AnthropicClient(model=args.model)


def _add_llm_args(parser) -> None:
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument(
        "--llm",
        choices=["api", "claude-code"],
        default="api",
        help="api: Anthropic SDK (API key or `ant auth login` profile); "
        "claude-code: your Claude subscription via a local `claude -p` "
        "(interactive runs only)",
    )


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
    result = surveyor.survey(urls, args.bundle, _llm(args))
    print(
        f"written: {len(result.written)}  proposed: {len(result.proposed)}  "
        f"unchanged: {len(result.skipped_unchanged)}  "
        f"quarantined: {len(result.quarantined)}  errors: {len(result.errors)}"
    )
    for rel in result.written:
        print(f"  draft: {rel}")
    for rel in result.proposed:
        print(f"  drift proposal: _review/proposed/{rel}")
    for note in result.collisions:
        print(f"  path collision: {note}")
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
        bundle, _llm(args), per_archetype=args.per_archetype
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
    if args.published:
        bundle = publisher.published_view(
            bundle, include_machine_confirmed=args.include_machine_confirmed
        )
        print(f"evaluating the published view ({len(bundle.concepts)} concept(s); drafts excluded)")
    questions_path = Path(args.questions or Path(args.bundle) / "evaluations" / "questions.yaml")
    if not questions_path.exists():
        print(f"question set not found: {questions_path}", file=sys.stderr)
        return 2
    questions = evaluator.load_questions(questions_path)
    retriever = None
    if args.retriever != "lexical":
        from .retrieval import CACHE_NAME, EmbeddingIndex, HashingEmbedder

        cache = Path(args.bundle) / CACHE_NAME
        if args.retriever == "embedding":
            from .retrieval import VoyageClient

            embedder = VoyageClient(model=args.embed_model)
        else:
            embedder = HashingEmbedder()
        retriever = EmbeddingIndex(embedder, cache_path=cache)
    llm = None if args.dry_run else _llm(args)
    report = evaluator.evaluate(
        bundle, questions, llm=llm, top_k=args.top_k, retriever=retriever
    )
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
    for warning in result.warnings:
        print(f"warning: {warning}")
    if args.sign:
        try:
            out = signing.sign_manifest(
                args.dist, sigstore_bin=args.sigstore_bin, staging=args.staging
            )
        except signing.SigningError as exc:
            print(f"signing failed: {exc}", file=sys.stderr)
            return 1
        print(f"signed: {out} (verify with `okf-web verify {args.dist} "
              "--cert-identity <id> --cert-oidc-issuer <issuer>`)")
    if args.check_robots:
        site = args.site
        if not site:
            root_index = load_bundle(args.bundle).indexes.get("index.md")
            x_geo = (root_index.frontmatter.get("x_geo") or {}) if root_index else {}
            site = x_geo.get("site") if isinstance(x_geo, dict) else None
        if not site:
            print(
                "warning: --check-robots needs a site URL (pass --site or set "
                "x_geo.site on the root index.md)"
            )
        else:
            blocked, error = publisher.check_robots(str(site), args.base_path)
            if error:
                print(f"warning: robots check inconclusive — {error}")
            elif blocked:
                print(
                    "warning: robots.txt blocks these AI agents from the bundle "
                    f"path ({args.base_path}): {', '.join(blocked)} — the bundle "
                    "is published but unreachable for them"
                )
            else:
                print("robots.txt: all checked AI agents may fetch the bundle")
    return 0


def cmd_sign(args) -> int:
    try:
        out = signing.sign_manifest(
            args.dist, sigstore_bin=args.sigstore_bin, staging=args.staging
        )
    except signing.SigningError as exc:
        print(f"signing failed: {exc}", file=sys.stderr)
        return 1
    print(f"signed: {out}")
    print(
        "consumers verify with: okf-web verify "
        f"{args.dist} --cert-identity <your-oidc-identity> "
        "--cert-oidc-issuer <issuer-url>"
    )
    return 0


def cmd_verify(args) -> int:
    errors, warnings = signing.verify_integrity(args.dist)
    for err in errors:
        print(f"integrity error: {err}")
    for warning in warnings:
        print(f"integrity warning: {warning}")
    if not errors:
        print("integrity: all manifest hashes match")

    failed = bool(errors)
    has_sig = signing.signature_path(args.dist).exists()
    if args.cert_identity or args.cert_oidc_issuer:
        if not (args.cert_identity and args.cert_oidc_issuer):
            print(
                "signature check needs both --cert-identity and "
                "--cert-oidc-issuer",
                file=sys.stderr,
            )
            return 2
        try:
            signing.verify_signature(
                args.dist,
                cert_identity=args.cert_identity,
                cert_oidc_issuer=args.cert_oidc_issuer,
                sigstore_bin=args.sigstore_bin,
                staging=args.staging,
            )
            print(f"signature: valid for {args.cert_identity} ({args.cert_oidc_issuer})")
        except signing.SigningError as exc:
            print(f"signature: {exc}", file=sys.stderr)
            failed = True
    elif has_sig:
        print(
            "signature present but not checked — pass --cert-identity and "
            "--cert-oidc-issuer to verify it"
        )
    else:
        print("no signature found (bundle is unsigned)")
    return 1 if failed else 0


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
    _add_llm_args(p)
    p.set_defaults(func=cmd_survey)

    p = sub.add_parser("index", help="rebuild index.md from bundle contents")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("questions", help="LLM-generate an evaluation question set")
    p.add_argument("bundle")
    p.add_argument("--per-archetype", type=int, default=3)
    _add_llm_args(p)
    p.set_defaults(func=cmd_questions)

    p = sub.add_parser("evaluate", help="run the answerability evaluation")
    p.add_argument("bundle")
    p.add_argument("--questions", help="question set YAML (default: bundle/evaluations/questions.yaml)")
    p.add_argument("--dry-run", action="store_true", help="retrieval-only, no LLM")
    p.add_argument(
        "--published",
        action="store_true",
        help="evaluate the published view (drafts excluded) — what engines "
        "actually see, not the working copy",
    )
    p.add_argument(
        "--include-machine-confirmed",
        action="store_true",
        help="with --published: mirror a publish that includes non-high-risk drafts",
    )
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument(
        "--retriever",
        choices=["lexical", "embedding", "hashing"],
        default="lexical",
        help="lexical: tf-idf (default); embedding: Voyage semantic "
        "embeddings with an on-disk cache (`pip install okf-web[embed]`, "
        "VOYAGE_API_KEY); hashing: dependency-free local embedder",
    )
    p.add_argument("--embed-model", default="voyage-3.5")
    _add_llm_args(p)
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
    p.add_argument(
        "--check-robots",
        action="store_true",
        help="fetch the live site's robots.txt and warn if AI agents are "
        "blocked from the bundle path",
    )
    p.add_argument(
        "--site",
        help="site origin for --check-robots (default: x_geo.site from the "
        "bundle's root index.md)",
    )
    p.add_argument(
        "--sign",
        action="store_true",
        help="sigstore-sign manifest.json after publishing (needs "
        "`pip install okf-web[sign]`; OIDC login or CI ambient identity)",
    )
    p.add_argument("--sigstore-bin", default="sigstore", help="signing tool executable")
    p.add_argument(
        "--staging", action="store_true", help="use sigstore's staging infrastructure"
    )
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("sign", help="sigstore-sign a published bundle's manifest.json")
    p.add_argument("dist", help="published bundle directory (from `okf-web publish`)")
    p.add_argument("--sigstore-bin", default="sigstore")
    p.add_argument("--staging", action="store_true")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser(
        "verify",
        help="consumer-side check of a published bundle: manifest↔file "
        "integrity, plus signature identity when requested",
    )
    p.add_argument("dist", help="published bundle directory")
    p.add_argument("--cert-identity", help="expected signer identity (email or CI workflow URI)")
    p.add_argument("--cert-oidc-issuer", help="expected OIDC issuer URL")
    p.add_argument("--sigstore-bin", default="sigstore")
    p.add_argument("--staging", action="store_true")
    p.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
