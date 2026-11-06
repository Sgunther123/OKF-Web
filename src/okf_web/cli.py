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
import functools
import shlex
import sys
from pathlib import Path

import yaml

from . import drift as drift_mod
from . import report as report_mod
from . import evaluator, init, linter, packs, publisher, review, signing, surveyor
from .config import WELL_KNOWN_PATH
from .errors import OkfWebError, exit_code
from .llm import add_llm_args, client_from_args
from .model import (
    RISK_LOW,
    RISK_MEDIUM,
    bundle_lock,
    load_bundle,
    write_atomic,
)

__all__ = [
    "cmd_lint",
    "cmd_review",
    "cmd_survey",
    "cmd_index",
    "cmd_questions",
    "cmd_evaluate",
    "cmd_publish",
    "cmd_drift",
    "cmd_discover",
    "cmd_logscan",
    "cmd_init",
    "cmd_report",
    "cmd_view",
    "cmd_mcp",
    "cmd_sign",
    "cmd_verify",
    "build_parser",
    "main",
]


def _build_retriever(args, bundle_dir):
    """Retriever callable from --retriever/--embed-model, or None for lexical."""
    if args.retriever == "lexical":
        return None
    from .retrieval import CACHE_NAME, EmbeddingIndex, HashingEmbedder

    cache = Path(bundle_dir) / CACHE_NAME
    if args.retriever == "embedding":
        from .retrieval import VoyageClient

        embedder = VoyageClient(model=args.embed_model)
    else:
        embedder = HashingEmbedder()
    return EmbeddingIndex(embedder, cache_path=cache)


def _add_retriever_args(parser) -> None:
    parser.add_argument(
        "--retriever",
        choices=["lexical", "embedding", "hashing"],
        default="lexical",
        help="lexical: tf-idf (default); embedding: Voyage semantic "
        "embeddings with an on-disk cache (`pip install okf-web[embed]`, "
        "VOYAGE_API_KEY); hashing: dependency-free local embedder",
    )
    parser.add_argument("--embed-model", default="voyage-3.5")
    parser.add_argument(
        "--min-relevance",
        type=float,
        default=evaluator.RELEVANCE_FLOOR,
        help="lexical retriever: drop hits carrying less than this share of "
        f"the question's informative weight (default {evaluator.RELEVANCE_FLOOR})",
    )


def _bundle_site(bundle_root) -> str | None:
    """The store origin declared on the root index.md (x_geo.site)."""
    return load_bundle(bundle_root).site


# The wiring lives in `llm` and `packs` now (review 2026-10-21, A-U2);
# these names stay for the hosted edition until its adapter lands.
_llm = client_from_args
_add_llm_args = add_llm_args
_question_packs = packs.available


def _add_network_args(parser) -> None:
    parser.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="also fetch loopback, private and link-local hosts — for a "
        "local dev or staging host only; never the default, because page, "
        "sitemap and pointer URLs are untrusted input",
    )


def cmd_lint(args) -> int:
    _, findings = linter.lint_bundle(args.bundle, strict_okf=args.strict_okf)
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
        queue = review.queue_summary(bundle)
        items = queue.items
        shown = [i for i in items if not args.risk or i.concept.effective_risk == args.risk]
        if not items:
            print("review queue is empty")
        for item in shown:
            c = item.concept
            print(
                f"[risk {c.risk}] {c.rel_path} ({c.type}, {c.trust_tier}) — "
                + "; ".join(item.reasons)
            )
        proposed = queue.proposed
        if proposed:
            print("\ndrift proposals (surveyor found changes to human-reviewed concepts):")
            for path in proposed:
                print(f"  {path}")
        # Machine-greppable summary so CI can surface a rotting queue.
        print("\n" + queue.line)
        if args.fail_nonempty and (items or proposed):
            return 1
        return 0
    if args.action == "batch-approve":
        if not args.by and not args.dry_run:
            print("batch-approve needs --by <reviewer-id>", file=sys.stderr)
            return 2
        risks = (args.risk,) if args.risk else (RISK_MEDIUM, RISK_LOW)
        candidates, skipped = review.batch_candidates(
            bundle, risks, only_machine_confirmed=args.only_machine_confirmed
        )
        for concept, why in skipped:
            print(f"skipped {concept.rel_path}: {why}")
        if args.dry_run:
            for concept in candidates:
                print(f"would approve {concept.rel_path} (risk {concept.risk}, {concept.trust_tier})")
            print(
                f"dry run: {len(candidates)} concept(s) would be batch-approved, "
                f"{len(skipped)} skipped; nothing written"
            )
            return 0
        approved = review.batch_approve(
            bundle, args.by, risks=risks, only_machine_confirmed=args.only_machine_confirmed
        )
        for concept in approved:
            print(f"approved {concept.rel_path} -> {concept.trust_tier}, status {concept.status}")
        tiers = "/".join(risks)
        print(
            f"{len(approved)} concept(s) batch-approved (risk {tiers} drafts only; "
            f"{len(skipped)} rejected draft(s) skipped; "
            "risk a always needs individual review)"
        )
        return 0
    if not args.path or not args.by:
        print("approve/reject need a concept path and --by <reviewer-id>", file=sys.stderr)
        return 2
    if args.action == "approve":
        rel = review.resolve_path(bundle, args.path)
        note = review.approval_state(bundle.get(rel), args.by)
        if note and not args.stale_after:
            # A new freshness date is a change even for an approved
            # concept (the W041 remedy, review 2026-10-21 L-U2).
            print(f"{rel}: {note}")
            return 0
        concept = review.approve(bundle, rel, args.by, stale_after=args.stale_after)
        print(f"approved {concept.rel_path} -> {concept.trust_tier}, status {concept.status}")
    else:
        concept = review.reject(bundle, args.path, args.by, args.reason or "no reason given")
        print(f"rejected {concept.rel_path}; kept as draft")
    return 0


def cmd_survey(args) -> int:
    for label, name in (("--urls", args.urls), ("--feed", args.feed)):
        if name and not Path(name).is_file():
            print(f"error: {label} file not found: {name}", file=sys.stderr)
            return 2
    urls: list[str] = []
    if args.sitemap:
        urls.extend(
            surveyor.discover_sitemap(args.sitemap, allow_private=args.allow_private_hosts)
        )
    if args.urls:
        urls.extend(
            line.strip()
            for line in Path(args.urls).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    if not urls and not args.feed:
        print(
            "no inputs: pass --sitemap BASE_URL, --urls FILE, and/or --feed FILE",
            file=sys.stderr,
        )
        return 2

    result = surveyor.SurveyResult()
    if args.feed:
        # Feed ingestion is deterministic — no LLM, no credentials.
        from . import feed as feed_mod

        result.extend(feed_mod.ingest_feed(args.feed, args.bundle))
    if urls:
        if args.limit:
            urls = urls[: args.limit]
        result.extend(surveyor.survey(
            urls, args.bundle, _llm(args), allow_private=args.allow_private_hosts
        ))
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
    if result.dropped_live_fields:
        print(
            "  dropped live-value fields (never published): "
            + ", ".join(sorted(set(result.dropped_live_fields)))
        )
    for err in result.errors:
        print(f"  error: {err}", file=sys.stderr)
    return 0 if not result.errors else 1


def cmd_index(args) -> int:
    surveyor.rebuild_index(args.bundle)
    print("index.md rebuilt")
    return 0


def cmd_questions(args) -> int:
    out = Path(args.bundle) / "evaluations" / "questions.yaml"
    if args.list_packs:
        for name in sorted(_question_packs()):
            print(name)
        return 0
    if args.pack:
        packs = _question_packs()
        if args.pack not in packs:
            print(
                f"unknown pack {args.pack!r}; available: {', '.join(sorted(packs))}",
                file=sys.stderr,
            )
            return 2
        if out.exists() and not args.force:
            print(
                f"{out} already exists; pass --force to replace it with the "
                f"{args.pack} starter pack",
                file=sys.stderr,
            )
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(out, packs[args.pack])
        count = len(evaluator.load_questions(out))
        print(
            f"wrote {count} starter questions ({args.pack}) to {out} — "
            "customize the nouns to your catalog, then curate"
        )
        return 0
    if out.exists() and not args.force:
        print(
            f"{out} already exists; pass --force to replace it with a freshly "
            "generated set (curated questions are lost when you do)",
            file=sys.stderr,
        )
        return 2
    bundle = load_bundle(args.bundle)
    questions = evaluator.generate_questions(
        bundle, _llm(args), per_archetype=args.per_archetype
    )
    if not questions:
        print(
            "the model returned no parsable questions (expected a YAML "
            f"`questions:` list); nothing written, {out} unchanged",
            file=sys.stderr,
        )
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(
        out,
        yaml.safe_dump(
            {
                "questions": [
                    {"id": q.id, "archetype": q.archetype, "question": q.question,
                     **({"paraphrase": q.paraphrase} if q.paraphrase else {})}
                    for q in questions
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
    )
    print(f"wrote {len(questions)} questions to {out}")
    return 0


def cmd_evaluate(args) -> int:
    bundle = load_bundle(args.bundle)
    if args.lang:
        from .model import localized_view

        bundle = localized_view(bundle, args.lang)
        print(f"evaluating the {args.lang} localized view")
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
    problems = evaluator.validate_questions(questions)
    if problems:
        print(f"question set {questions_path} cannot be evaluated:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 2
    if args.min_coverage is not None and args.dry_run:
        print(
            "--min-coverage needs a judged run: coverage is not measured in a "
            "dry run (drop --dry-run and pass --llm)",
            file=sys.stderr,
        )
        return 2
    retriever = _build_retriever(args, args.bundle)
    if retriever is None and args.min_relevance != evaluator.RELEVANCE_FLOOR:
        retriever = functools.partial(evaluator.retrieve, min_relevance=args.min_relevance)
    llm = None if args.dry_run else _llm(args)
    judge = None
    if llm is not None and args.judge_model and args.judge_model != args.model:
        judge = _llm(args, model=args.judge_model)
    report = evaluator.evaluate(
        bundle, questions, llm=llm, top_k=args.top_k, retriever=retriever,
        judge=judge,
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
        report.view = "published" if args.published else "working"
        out = evaluator.write_scorecard(bundle, report, force=args.force)
        print(f"\nscorecard written to {out}")
    failed = False
    if args.min_hit_rate is not None and metrics["retrieval_hit_rate"] < args.min_hit_rate:
        print(
            f"retrieval hit rate {metrics['retrieval_hit_rate']} is below "
            f"--min-hit-rate {args.min_hit_rate}",
            file=sys.stderr,
        )
        failed = True
    if args.min_coverage is not None and metrics.get("coverage", 0.0) < args.min_coverage:
        print(
            f"coverage {metrics.get('coverage')} is below --min-coverage {args.min_coverage}",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


def cmd_publish(args) -> int:
    site = args.site or _bundle_site(args.bundle)
    result = publisher.publish(
        args.bundle,
        args.dist,
        include_machine_confirmed=args.include_machine_confirmed,
        base_path=args.base_path,
        freshness=args.freshness,
        site=site,
        bundle_url=args.bundle_url,
        structured=not args.no_structured,
        force=args.force,
    )
    print(f"published {len(result.published)} file(s) to {result.dist}")
    if result.assets:
        print(
            f"shipped {len(result.assets)} non-concept asset(s): "
            + ", ".join(result.assets)
        )
    if result.structured:
        print(
            f"derived tier: {len(result.structured) - 1} JSON-LD file(s) "
            "(jsonld/, human-verified concepts only) + llms.txt — "
            "structured data engines read today, generated from the bundle"
        )
    if result.withheld:
        working = load_bundle(args.bundle)
        print(f"withheld {len(result.withheld)} concept(s):")
        for rel in result.withheld:
            concept = working.get(rel)
            reason = (
                publisher.withhold_reason(
                    concept,
                    freshness=args.freshness,
                    include_machine_confirmed=args.include_machine_confirmed,
                )
                if concept is not None
                else "not in the bundle"
            )
            print(f"  {rel}: {reason}")
    warnings = list(result.warnings)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.bundle_url:
        print(
            "delegated hosting: serve the dist at "
            f"{args.bundle_url.rstrip('/')}/ and paste the <link rel=\"okf-bundle\"> "
            "tag from llms-snippet.txt into the storefront's <head>"
        )
    if args.sign:
        out = signing.sign_manifest(
            args.dist, sigstore_bin=args.sigstore_bin, staging=args.staging
        )
        print(f"signed: {out} (verify with `okf-web verify {args.dist} "
              "--cert-identity <id> --cert-oidc-issuer <issuer>`)")
    if args.check_robots:
        if not site:
            warnings.append(
                "--check-robots needs a site URL (pass --site or set "
                "x_geo.site on the root index.md)"
            )
            print(f"warning: {warnings[-1]}", file=sys.stderr)
        else:
            blocked, error = publisher.check_robots(
                str(site), args.base_path, allow_private=args.allow_private_hosts
            )
            if error:
                warnings.append(f"robots check inconclusive — {error}")
                print(f"warning: {warnings[-1]}", file=sys.stderr)
            elif blocked:
                warnings.append(
                    "robots.txt blocks these AI agents from the bundle "
                    f"path ({args.base_path}): {', '.join(blocked)} — the bundle "
                    "is published but unreachable for them"
                )
                print(f"warning: {warnings[-1]}", file=sys.stderr)
            else:
                print("robots.txt: all checked AI agents may fetch the bundle")
    if warnings and args.fail_on_warnings:
        print(
            f"{len(warnings)} warning(s) and --fail-on-warnings is set",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_drift(args) -> int:
    report = drift_mod.check_bundle(
        args.bundle, timeout=args.timeout, allow_private=args.allow_private_hosts
    )
    for rel, url in report.drifted:
        print(f"drifted: {rel} ({url})")
    for rel, err in report.unreachable:
        print(f"unreachable: {rel} ({err})")
    print(
        f"\n{len(report.unchanged)} unchanged, {len(report.drifted)} drifted, "
        f"{len(report.unreachable)} unreachable, {len(report.skipped)} skipped "
        f"(no surveyed source), {len(report.feed_derived)} feed-derived "
        "(checked by the next feed ingest, not by a page fetch)"
    )
    if report.drifted:
        print("re-survey the drifted URLs to refresh those concepts")
        return 1
    if report.unreachable:
        print(
            "some source pages could not be fetched; nothing is known to have "
            "changed — retry later (exit 3)",
            file=sys.stderr,
        )
        return 3
    return 0


def cmd_discover(args) -> int:
    from . import discover as discover_mod

    report = discover_mod.discover(
        args.store_url, timeout=args.timeout, allow_private=args.allow_private_hosts
    )
    print(f"store origin: {report.store_origin}")
    print(f"routes found: {', '.join(report.routes) or 'none'}")
    if report.bundle_url:
        print(f"bundle: {report.bundle_url} ({report.files} file(s), "
              f"profile {report.manifest.get('profile', '?')})")
        print(f"signature: {'present' if report.signed else 'absent'}"
              + (" — verify identity with `okf-web verify`" if report.signed else ""))
    print(f"binding: {report.binding}")
    for problem in report.problems:
        print(f"problem: {problem}")
    if report.ok:
        print("OK: the bundle is discoverable and speaks for this store")
        return 0
    return 1


def cmd_logscan(args) -> int:
    from . import logscan

    def _lines():
        for name in args.logfile:
            if name == "-":
                yield from sys.stdin
            else:
                with open(name, "r", encoding="utf-8", errors="replace") as fh:
                    yield from fh

    report = logscan.scan_lines(_lines(), base_path=args.base_path)
    print(
        f"scanned {report.lines} line(s): {report.ai_hits} AI-agent bundle "
        f"fetch(es), {report.other_hits} other bundle fetch(es)"
    )
    for agent, count in report.by_agent.most_common():
        print(f"  {agent}: {count}")
    if report.by_file:
        print("top files:")
        for path, count in report.by_file.most_common(5):
            print(f"  {path}: {count}")
    if report.first_seen and report.last_seen:
        print(f"window: {report.first_seen.isoformat()} … {report.last_seen.isoformat()}")
    if report.ai_hits == 0:
        print(
            "no AI-agent fetches found — check robots.txt reachability "
            "(`okf-web publish --check-robots`) and discovery "
            "(llms.txt / <link rel=\"okf-bundle\">)"
        )
        if args.fail_empty:
            return 1
    return 0


def cmd_init(args) -> int:
    """The guided first run (READINESS R3): feed → lint → attest →
    questions → dry-run scorecard → publish → report, one command, no
    LLM required. The pipeline is `init.run_init` (review 2026-10-21,
    A-U3); this command checks the arguments and prints as it goes."""
    if not args.feed:
        print(
            "okf-web init needs --feed PRODUCTS.csv for the no-LLM first "
            "run (a sitemap survey needs an LLM — run `okf-web survey "
            f"{args.bundle} --sitemap URL --llm ...` and then the steps "
            "init would have chained: lint, review, publish, report)",
            file=sys.stderr,
        )
        return 2
    result = init.run_init(
        args.bundle, args.dist, args.feed, title=args.title, site=args.site,
        by=args.by, pack=args.pack, force=args.force,
        emit=print, warn=functools.partial(print, file=sys.stderr),
    )
    return result.exit_code


def cmd_report(args) -> int:
    out = report_mod.write_report(args.bundle, out=args.out)
    print(f"report written to {out}")
    print(
        "open it in a browser, or send it as-is — it is a single "
        "self-contained HTML file"
    )
    return 0


def cmd_view(args) -> int:
    from . import viewer as viewer_mod

    logs = None
    if args.access_log:
        from . import logscan

        def _lines():
            for name in args.access_log:
                with open(name, "r", encoding="utf-8", errors="replace") as fh:
                    yield from fh

        logs = logscan.scan_lines(_lines(), base_path=args.base_path)
    out = viewer_mod.write_viewer(
        args.bundle,
        out=args.out,
        access_logs=logs,
        log_sources=list(args.access_log or []),
        base_path=args.base_path,
    )
    print(f"viewer written to {out}")
    print(
        "it is a single self-contained HTML file, kept outside the bundle "
        "on purpose: it shows drafts and read logs meant for you"
    )
    if logs is None:
        print(
            "no access log given — the read-activity panel explains how to "
            "add one (--access-log access.log)"
        )
    elif logs.ai_hits == 0:
        print("access log read, but no fetch of the bundle by a named AI agent")
    else:
        print(
            f"read activity: {logs.ai_hits} AI-agent fetch(es) by "
            f"{len(logs.by_agent)} agent(s)"
        )
    return 0


def cmd_mcp(args) -> int:
    from . import mcp_bridge

    if args.url and args.bundle:
        print("give a bundle directory or --url, not both", file=sys.stderr)
        return 2
    if not args.url and not args.bundle:
        print("mcp needs a bundle directory or --url <published bundle>", file=sys.stderr)
        return 2
    if args.url:
        # A published bundle anywhere on the web, mirrored locally and
        # verified against its manifest (GAPS item 10). The dist is the
        # published view already; --working has nothing to show here.
        from .remote import RemoteSource, cache_dir_for, default_policy

        source = RemoteSource(
            args.url,
            Path(args.cache_dir) if args.cache_dir else cache_dir_for(args.url),
            policy=default_policy(allow_private=args.allow_private_hosts),
            refresh_seconds=args.refresh_seconds,
            lang=args.lang,
        )
        synced = source.sync()
        retriever = _build_retriever(args, source.cache_dir)
        state = mcp_bridge.build_state(
            None,
            retriever=retriever,
            top_k=args.top_k,
            allow_private_hosts=args.allow_private_hosts,
            min_relevance=args.min_relevance,
            source=source,
        )
        print(
            f"okf-web mcp: serving {len(state.bundle.concepts)} concept(s) from "
            f"{source.base_url} [published view; {synced['fetched']} file(s) mirrored "
            f"at {source.cache_dir}, re-checked every {args.refresh_seconds:g}s] over stdio",
            file=sys.stderr,
        )
        mcp_bridge.serve_stdio(state)
        return 0

    retriever = _build_retriever(args, args.bundle)
    state = mcp_bridge.build_state(
        args.bundle,
        working=args.working,
        include_machine_confirmed=args.include_machine_confirmed,
        retriever=retriever,
        top_k=args.top_k,
        lang=args.lang,
        allow_private_hosts=args.allow_private_hosts,
        min_relevance=args.min_relevance,
    )
    view = "working copy (drafts included)" if args.working else "published view"
    print(
        f"okf-web mcp: serving {len(state.bundle.concepts)} concept(s) "
        f"[{view}] over stdio",
        file=sys.stderr,
    )
    mcp_bridge.serve_stdio(state)
    return 0


def cmd_sign(args) -> int:
    out = signing.sign_manifest(
        args.dist,
        sigstore_bin=args.sigstore_bin,
        staging=args.staging,
        label=args.label,
    )
    print(f"signed: {out}")
    # The identity and issuer the new certificate names, so the command
    # consumers are given is complete; a placeholder only when the
    # bundle holds no certificate this can read.
    named = signing.signer(out)
    if named:
        identity, issuer = (shlex.quote(part) for part in named)
    else:
        identity = "<attester-identity>" if args.label else "<your-oidc-identity>"
        issuer = "<issuer-url>"
    if args.label:
        print(
            f"countersignature as {args.label!r} — consumers verify with: "
            f"okf-web verify {args.dist} --countersignature {args.label} "
            f"--cert-identity {identity} --cert-oidc-issuer {issuer}"
        )
    else:
        print(
            "consumers verify with: okf-web verify "
            f"{args.dist} --cert-identity {identity} "
            f"--cert-oidc-issuer {issuer}"
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
    has_sig = signing.signature_path(args.dist, args.countersignature).exists()
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
                label=args.countersignature,
            )
            kind = (
                f"countersignature ({args.countersignature})"
                if args.countersignature
                else "signature"
            )
            print(f"{kind}: valid for {args.cert_identity} ({args.cert_oidc_issuer})")
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


def _add_lint_parser(sub) -> None:
    p = sub.add_parser("lint", help="check spec conformance + profile rules")
    p.add_argument("bundle")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument(
        "--strict-okf",
        action="store_true",
        help="also report the base-OKF-spec deviations the profile makes "
        "deliberately (W040; see GEO-PROFILE §7)",
    )
    p.set_defaults(func=cmd_lint)


def _add_review_parser(sub) -> None:
    p = sub.add_parser("review", help="human-in-the-loop verification queue")
    p.add_argument("action", choices=["list", "approve", "reject", "batch-approve"])
    p.add_argument("bundle")
    p.add_argument("path", nargs="?", help="concept path within the bundle")
    p.add_argument(
        "--by",
        help="reviewer id (approve stamps human:<id>, batch-approve "
        "human-batch:<id>; a prefix typed here is ignored); when index.md "
        "lists x_geo.reviewers it must be one of them",
    )
    p.add_argument("--reason", help="rejection reason")
    p.add_argument(
        "--risk",
        choices=["a", "b", "c"],
        help="list: only show this risk tier; batch-approve: only this tier "
        "(a is never batchable)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="batch-approve: show what would be approved and what is skipped, "
        "without writing",
    )
    p.add_argument(
        "--stale-after",
        help="approve: the new freshness date (YYYY-MM-DD) for a concept past "
        "its stale_after — required to approve a stale concept",
    )
    p.add_argument(
        "--fail-nonempty",
        action="store_true",
        help="list: exit 1 when anything is pending — CI visibility for a "
        "rotting queue",
    )
    p.add_argument(
        "--only-machine-confirmed",
        action="store_true",
        help="batch-approve: only drafts that already carry a machine "
        "verification event",
    )
    p.set_defaults(func=cmd_review)


def _add_survey_parser(sub) -> None:
    p = sub.add_parser(
        "survey",
        help="populate draft concepts: LLM extraction from site pages, "
        "and/or a mechanical (LLM-free) product feed import",
    )
    p.add_argument("bundle")
    p.add_argument("--sitemap", help="site base URL; reads <base>/sitemap.xml")
    p.add_argument("--urls", help="file with one URL per line")
    p.add_argument(
        "--feed",
        help="product feed file (Google Merchant XML/TSV or CSV): each row "
        "becomes a draft Product concept deterministically — no LLM, no "
        "credentials; price/availability fields are dropped per the "
        "live-values rule",
    )
    p.add_argument("--limit", type=int, default=0)
    _add_network_args(p)
    _add_llm_args(p)
    p.set_defaults(func=cmd_survey)


def _add_index_parser(sub) -> None:
    p = sub.add_parser("index", help="rebuild index.md from bundle contents")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_index)


def _add_questions_parser(sub) -> None:
    p = sub.add_parser(
        "questions",
        help="write an evaluation question set: --pack for a no-LLM vertical "
        "starter, or LLM-generate from the bundle outline",
    )
    p.add_argument("bundle")
    p.add_argument("--per-archetype", type=int, default=3)
    p.add_argument(
        "--pack",
        help="start from a vertical starter pack instead of LLM generation "
        "(see --list-packs); no credentials needed",
    )
    p.add_argument("--list-packs", action="store_true", help="print available starter packs")
    p.add_argument("--force", action="store_true", help="replace an existing questions.yaml")
    _add_llm_args(p)
    p.set_defaults(func=cmd_questions)


def _add_evaluate_parser(sub) -> None:
    p = sub.add_parser("evaluate", help="run the answerability evaluation")
    p.add_argument("bundle")
    p.add_argument("--questions", help="question set YAML (default: bundle/evaluations/questions.yaml)")
    p.add_argument("--dry-run", action="store_true", help="retrieval-only, no LLM")
    p.add_argument(
        "--judge-model",
        help="grade answers with a different model than the answerer, so "
        "coverage is not self-graded; both identities are recorded in the "
        "scorecard's generated.by",
    )
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
        "--lang",
        help="evaluate the localized view: l10n/<lang>/ translations "
        "overlaid on the default language",
    )
    _add_retriever_args(p)
    _add_llm_args(p)
    p.add_argument("--write-scorecard", action="store_true")
    p.add_argument(
        "--force",
        action="store_true",
        help="with --write-scorecard --dry-run: replace a judged scorecard "
        "with the dry-run one (its graded numbers are lost)",
    )
    p.add_argument(
        "--min-hit-rate",
        type=float,
        help="exit 1 when retrieval_hit_rate is below this (CI gate)",
    )
    p.add_argument(
        "--min-coverage",
        type=float,
        help="exit 1 when judged coverage is below this (needs an LLM run)",
    )
    p.set_defaults(func=cmd_evaluate)


def _add_publish_parser(sub) -> None:
    p = sub.add_parser("publish", help="build the static companion bundle")
    p.add_argument("bundle")
    p.add_argument("dist")
    p.add_argument(
        "--include-machine-confirmed",
        action="store_true",
        help="also publish non-high-risk drafts (they surface as unverified/machine-confirmed)",
    )
    p.add_argument("--base-path", default=WELL_KNOWN_PATH)
    p.add_argument(
        "--freshness",
        choices=["warn", "withhold"],
        default="warn",
        help="what to do with concepts past stale_after: warn (default) "
        "ships them with a warning; withhold retires them from the "
        "published set (expired promotions are always withheld)",
    )
    p.add_argument(
        "--check-robots",
        action="store_true",
        help="fetch the live site's robots.txt and warn if AI agents are "
        "blocked from the bundle path",
    )
    p.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="exit 1 when the publish produced any warning (withheld links, "
        "off-origin resources, robots blocks) — for unattended runs",
    )
    _add_network_args(p)
    p.add_argument(
        "--site",
        help="storefront origin the bundle speaks for; recorded in "
        "manifest.json and used for --check-robots (default: x_geo.site "
        "from the bundle's root index.md)",
    )
    p.add_argument(
        "--bundle-url",
        help="absolute base URL where the bundle will be served, when that "
        "is NOT <site>/.well-known/okf (platform-hosted stores that cannot "
        "serve root paths); enables the delegated-discovery artifacts",
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
    p.add_argument(
        "--no-structured",
        action="store_true",
        help="skip the derived tier (jsonld/ + llms.txt) — bundle-only publish",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="empty a non-empty dist directory that is not a previous publish "
        "(the bundle itself, and any directory containing it, are always refused)",
    )
    p.set_defaults(func=cmd_publish)


def _add_init_parser(sub) -> None:
    p = sub.add_parser(
        "init",
        help="guided first run, no LLM: feed → lint → attest → questions → "
        "dry-run scorecard → publish → report, in one command",
    )
    p.add_argument("bundle", help="bundle directory to create/extend")
    p.add_argument("--feed", required=False, help="product feed export (CSV/TSV/Merchant XML)")
    p.add_argument("--site", help="storefront origin (recorded in index.md and manifest)")
    p.add_argument("--title", help="store name for the bundle index (default: directory name)")
    p.add_argument(
        "--by",
        help="your email/id: batch-attests the low-risk drafts as "
        "human-batch:<id> (a named bulk sign-off, not per-item review)",
    )
    p.add_argument(
        "--pack",
        help="starter question pack (outdoor/apparel/electronics/grocery/"
        "machinery, + .es variants) for the dry-run scorecard and report",
    )
    p.add_argument("--dist", default="dist", help="publish output directory (default: dist)")
    p.add_argument(
        "--force",
        action="store_true",
        help="empty a non-empty --dist directory that is not a previous publish",
    )
    p.set_defaults(func=cmd_init)


def _add_report_parser(sub) -> None:
    p = sub.add_parser(
        "report",
        help="render the scorecard as a shareable HTML answerability report "
        "(no LLM; reads the scorecard the evaluator wrote)",
    )
    p.add_argument("bundle")
    p.add_argument(
        "--out",
        help="output path (default: <bundle>/evaluations/geo-report.html)",
    )
    p.set_defaults(func=cmd_report)


def _add_view_parser(sub) -> None:
    p = sub.add_parser(
        "view",
        help="render the bundle viewer: what is inside, how AI engines "
        "discover, interpret and surface it, and (with --access-log) who "
        "has read it (no LLM)",
    )
    p.add_argument("bundle")
    p.add_argument(
        "--out",
        help="output path (default: ./bundle-viewer.html — outside the "
        "bundle, since the page shows drafts and read logs)",
    )
    p.add_argument(
        "--access-log",
        nargs="+",
        metavar="FILE",
        help="server/CDN access log(s) to draw the read-activity panel from "
        "(Combined Log Format or JSON lines, as for `okf-web logscan`)",
    )
    p.add_argument("--base-path", default=WELL_KNOWN_PATH)
    p.set_defaults(func=cmd_view)


def _add_sign_parser(sub) -> None:
    p = sub.add_parser("sign", help="sigstore-sign a published bundle's manifest.json")
    p.add_argument("dist", help="published bundle directory (from `okf-web publish`)")
    p.add_argument(
        "--as",
        dest="label",
        metavar="LABEL",
        help="write a countersignature (manifest.json.<LABEL>.sigstore.json) "
        "instead of the primary signature — for third-party attesters "
        "signing with their own identity (e.g. --as auditor-acme)",
    )
    p.add_argument("--sigstore-bin", default="sigstore")
    p.add_argument("--staging", action="store_true")
    p.set_defaults(func=cmd_sign)


def _add_drift_parser(sub) -> None:
    p = sub.add_parser(
        "drift",
        help="LLM-free check: re-fetch each surveyed concept's source page "
        "and report which ones changed (cheap enough for nightly CI)",
    )
    p.add_argument("bundle")
    p.add_argument("--timeout", type=float, default=30.0)
    _add_network_args(p)
    p.set_defaults(func=cmd_drift)


def _add_discover_parser(sub) -> None:
    p = sub.add_parser(
        "discover",
        help="consumer-side check of a live store: find its bundle "
        "(well-known or <link rel=\"okf-bundle\">) and verify the "
        "store↔bundle binding",
    )
    p.add_argument("store_url", help="storefront URL, e.g. https://www.example-store.com")
    p.add_argument("--timeout", type=float, default=15.0)
    _add_network_args(p)
    p.set_defaults(func=cmd_discover)


def _add_logscan_parser(sub) -> None:
    p = sub.add_parser(
        "logscan",
        help="scan server/CDN access logs for AI agents fetching the bundle "
        "— the consumption feedback loop (see docs/MEASUREMENT.md)",
    )
    p.add_argument("logfile", nargs="+", help="access log file(s), or - for stdin")
    p.add_argument("--base-path", default=WELL_KNOWN_PATH)
    p.add_argument(
        "--fail-empty",
        action="store_true",
        help="exit 1 when no AI-agent fetches are found (CI signal)",
    )
    p.set_defaults(func=cmd_logscan)


def _add_mcp_parser(sub) -> None:
    p = sub.add_parser(
        "mcp",
        help="serve the bundle to MCP clients (Claude Desktop/Code, other "
        "assistants) over stdio: retrieval, concept reads, capability calls",
    )
    p.add_argument("bundle", nargs="?", help="bundle directory (or use --url)")
    p.add_argument(
        "--url",
        help="serve a published bundle from its URL (the directory holding "
        "manifest.json, e.g. https://store.example/.well-known/okf): mirrored "
        "locally, every file verified against the manifest, re-checked on "
        "a schedule",
    )
    p.add_argument(
        "--cache-dir",
        help="with --url: where to keep the mirror (default: "
        "~/.cache/okf-web/remote/<digest of the URL>)",
    )
    p.add_argument(
        "--refresh-seconds",
        type=float,
        default=300.0,
        help="with --url: how often the manifest is re-checked with a "
        "conditional request (default 300, the hosting recipes' max-age)",
    )
    p.add_argument(
        "--working",
        action="store_true",
        help="serve the working copy (drafts included) instead of the "
        "published view — for merchant self-testing only",
    )
    p.add_argument(
        "--include-machine-confirmed",
        action="store_true",
        help="published view mirrors a publish that includes non-high-risk drafts",
    )
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument(
        "--lang",
        help="serve the localized view (l10n/<lang>/ overlaid on the default)",
    )
    p.add_argument(
        "--allow-private-hosts",
        action="store_true",
        help="let okf_execute fetch loopback/private/link-local hosts — "
        "for testing capabilities against a local dev server only",
    )
    _add_retriever_args(p)
    p.set_defaults(func=cmd_mcp)


def _add_verify_parser(sub) -> None:
    p = sub.add_parser(
        "verify",
        help="consumer-side check of a published bundle: manifest↔file "
        "integrity, plus signature identity when requested",
    )
    p.add_argument("dist", help="published bundle directory")
    p.add_argument("--cert-identity", help="expected signer identity (email or CI workflow URI)")
    p.add_argument("--cert-oidc-issuer", help="expected OIDC issuer URL")
    p.add_argument(
        "--countersignature",
        metavar="LABEL",
        help="verify the countersignature written by `sign --as LABEL` "
        "(pass the attester's identity/issuer, not the merchant's)",
    )
    p.add_argument("--sigstore-bin", default="sigstore")
    p.add_argument("--staging", action="store_true")
    p.set_defaults(func=cmd_verify)


def build_parser() -> argparse.ArgumentParser:
    """The command line: one `_add_<command>_parser` per verb, in the
    order the help lists them (review 2026-10-21, A-U4)."""
    parser = argparse.ArgumentParser(
        prog="okf-web",
        description="Survey, verify, evaluate, and publish an OKF companion bundle "
        "for an ecommerce site.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_lint_parser(sub)
    _add_review_parser(sub)
    _add_survey_parser(sub)
    _add_index_parser(sub)
    _add_questions_parser(sub)
    _add_evaluate_parser(sub)
    _add_publish_parser(sub)
    _add_init_parser(sub)
    _add_report_parser(sub)
    _add_view_parser(sub)
    _add_sign_parser(sub)
    _add_drift_parser(sub)
    _add_discover_parser(sub)
    _add_logscan_parser(sub)
    _add_mcp_parser(sub)
    _add_verify_parser(sub)
    return parser


# Commands that write into a bundle hold its lock for the run; the value
# says whether the command may create the bundle directory.
# `report` writes the page into the bundle (review 2026-10-21, A-U9).
_MUTATING: dict[str, bool] = {"survey": True, "init": True, "index": False,
                              "report": False}


def _lock_for(args) -> tuple[bool, bool]:
    """(hold the bundle lock?, may create the bundle?) for this invocation."""
    command = getattr(args, "command", None)
    if command in _MUTATING:
        return True, _MUTATING[command]
    if command == "review":
        return args.action != "list", False
    if command == "questions":
        return not args.list_packs, False
    if command == "evaluate":
        return bool(args.write_scorecard), False
    return False, False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        hold, create = _lock_for(args)
        if hold:
            with bundle_lock(args.bundle, create=create):
                return args.func(args)
        return args.func(args)
    except OkfWebError as exc:
        # Every error the toolchain raises on purpose carries its verdict
        # (errors.py): a refusal exits 2, a failure 1 (review 2026-10-21,
        # A-U1).
        print(f"error: {exc}", file=sys.stderr)
        return exit_code(exc)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError) as exc:
        detail = exc.strerror or exc.__class__.__name__
        target = f": {exc.filename}" if exc.filename else ""
        print(f"error: {detail}{target}", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML: {exc}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        # The loader records a non-UTF-8 concept as broken (E001); this is
        # the backstop for any other file read (review 2026-10-21, L-U5).
        print(f"error: a file is not valid UTF-8: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
