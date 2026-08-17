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

from . import drift as drift_mod
from . import evaluator, linter, publisher, review, signing, surveyor
from .model import load_bundle


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


def _bundle_site(bundle_root) -> str | None:
    """The store origin declared on the root index.md (x_geo.site)."""
    root_index = load_bundle(bundle_root).indexes.get("index.md")
    x_geo = (root_index.frontmatter.get("x_geo") or {}) if root_index else {}
    site = x_geo.get("site") if isinstance(x_geo, dict) else None
    return str(site) if site else None


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
        shown = [i for i in items if not args.risk or i.concept.risk == args.risk]
        if not items:
            print("review queue is empty")
        for item in shown:
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
        # Machine-greppable summary so CI can surface a rotting queue.
        by_risk = {"a": 0, "b": 0, "c": 0}
        for item in items:
            by_risk[item.concept.risk] = by_risk.get(item.concept.risk, 0) + 1
        print(
            f"\npending: {len(items)} (a: {by_risk['a']}, b: {by_risk['b']}, "
            f"c: {by_risk['c']}); drift proposals: {len(proposed)}"
        )
        if args.fail_nonempty and (items or proposed):
            return 1
        return 0
    if args.action == "batch-approve":
        if not args.by:
            print("batch-approve needs --by <reviewer-id>", file=sys.stderr)
            return 2
        approved = review.batch_approve(
            bundle, args.by, only_machine_confirmed=args.only_machine_confirmed
        )
        for concept in approved:
            print(f"approved {concept.rel_path} -> {concept.trust_tier}, status {concept.status}")
        print(
            f"{len(approved)} concept(s) batch-approved (risk b/c drafts only; "
            "risk a always needs individual review)"
        )
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

        feed_result = feed_mod.ingest_feed(args.feed, args.bundle)
        for attr in ("written", "proposed", "skipped_unchanged",
                     "quarantined", "collisions", "errors"):
            getattr(result, attr).extend(getattr(feed_result, attr))
    if urls:
        if args.limit:
            urls = urls[: args.limit]
        page_result = surveyor.survey(urls, args.bundle, _llm(args))
        for attr in ("written", "proposed", "skipped_unchanged",
                     "quarantined", "collisions", "errors"):
            getattr(result, attr).extend(getattr(page_result, attr))
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


def _question_packs() -> dict[str, str]:
    """Available starter packs: name -> YAML text."""
    from importlib import resources

    packs = {}
    for entry in resources.files("okf_web").joinpath("questionpacks").iterdir():
        if entry.name.endswith(".yaml"):
            packs[entry.name[: -len(".yaml")]] = entry.read_text("utf-8")
    return packs


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
        out.write_text(packs[args.pack], encoding="utf-8")
        count = len(evaluator.load_questions(out))
        print(
            f"wrote {count} starter questions ({args.pack}) to {out} — "
            "customize the nouns to your catalog, then curate"
        )
        return 0
    bundle = load_bundle(args.bundle)
    questions = evaluator.generate_questions(
        bundle, _llm(args), per_archetype=args.per_archetype
    )
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
    retriever = _build_retriever(args, args.bundle)
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
    site = args.site or _bundle_site(args.bundle)
    try:
        result = publisher.publish(
            args.bundle,
            args.dist,
            include_machine_confirmed=args.include_machine_confirmed,
            base_path=args.base_path,
            freshness=args.freshness,
            site=site,
            bundle_url=args.bundle_url,
        )
    except publisher.PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"published {len(result.published)} file(s) to {result.dist}")
    if result.withheld:
        print(
            f"withheld {len(result.withheld)} concept(s) "
            "(drafts, expired promotions, or stale under --freshness withhold):"
        )
        for rel in result.withheld:
            print(f"  {rel}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if args.bundle_url:
        print(
            "delegated hosting: serve the dist at "
            f"{args.bundle_url.rstrip('/')}/ and paste the <link rel=\"okf-bundle\"> "
            "tag from llms-snippet.txt into the storefront's <head>"
        )
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


def cmd_drift(args) -> int:
    report = drift_mod.check_bundle(args.bundle, timeout=args.timeout)
    for rel, url in report.drifted:
        print(f"drifted: {rel} ({url})")
    for rel, err in report.unreachable:
        print(f"unreachable: {rel} ({err})")
    print(
        f"\n{len(report.unchanged)} unchanged, {len(report.drifted)} drifted, "
        f"{len(report.unreachable)} unreachable, {len(report.skipped)} skipped "
        "(no surveyed source)"
    )
    if report.drifted:
        print("re-survey the drifted URLs to refresh those concepts")
    return 0 if report.clean else 1


def cmd_discover(args) -> int:
    from . import discover as discover_mod

    report = discover_mod.discover(args.store_url, timeout=args.timeout)
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


def cmd_mcp(args) -> int:
    from . import mcp_bridge

    retriever = _build_retriever(args, args.bundle)
    state = mcp_bridge.build_state(
        args.bundle,
        working=args.working,
        include_machine_confirmed=args.include_machine_confirmed,
        retriever=retriever,
        top_k=args.top_k,
        lang=args.lang,
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
    try:
        out = signing.sign_manifest(
            args.dist,
            sigstore_bin=args.sigstore_bin,
            staging=args.staging,
            label=args.label,
        )
    except signing.SigningError as exc:
        print(f"signing failed: {exc}", file=sys.stderr)
        return 1
    print(f"signed: {out}")
    if args.label:
        print(
            f"countersignature as {args.label!r} — consumers verify with: "
            f"okf-web verify {args.dist} --countersignature {args.label} "
            "--cert-identity <attester-identity> --cert-oidc-issuer <issuer-url>"
        )
    else:
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
    p.add_argument("action", choices=["list", "approve", "reject", "batch-approve"])
    p.add_argument("bundle")
    p.add_argument("path", nargs="?", help="concept path within the bundle")
    p.add_argument("--by", help="reviewer id (becomes human:<id>)")
    p.add_argument("--reason", help="rejection reason")
    p.add_argument(
        "--risk", choices=["a", "b", "c"], help="list: only show this risk tier"
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
    _add_llm_args(p)
    p.set_defaults(func=cmd_survey)

    p = sub.add_parser("index", help="rebuild index.md from bundle contents")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_index)

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
        "--lang",
        help="evaluate the localized view: l10n/<lang>/ translations "
        "overlaid on the default language",
    )
    _add_retriever_args(p)
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
    p.set_defaults(func=cmd_publish)

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

    p = sub.add_parser(
        "drift",
        help="LLM-free check: re-fetch each surveyed concept's source page "
        "and report which ones changed (cheap enough for nightly CI)",
    )
    p.add_argument("bundle")
    p.add_argument("--timeout", type=float, default=30.0)
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser(
        "discover",
        help="consumer-side check of a live store: find its bundle "
        "(well-known or <link rel=\"okf-bundle\">) and verify the "
        "store↔bundle binding",
    )
    p.add_argument("store_url", help="storefront URL, e.g. https://www.example-store.com")
    p.add_argument("--timeout", type=float, default=15.0)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser(
        "logscan",
        help="scan server/CDN access logs for AI agents fetching the bundle "
        "— the consumption feedback loop (see docs/MEASUREMENT.md)",
    )
    p.add_argument("logfile", nargs="+", help="access log file(s), or - for stdin")
    p.add_argument("--base-path", default="/.well-known/okf")
    p.add_argument(
        "--fail-empty",
        action="store_true",
        help="exit 1 when no AI-agent fetches are found (CI signal)",
    )
    p.set_defaults(func=cmd_logscan)

    p = sub.add_parser(
        "mcp",
        help="serve the bundle to MCP clients (Claude Desktop/Code, other "
        "assistants) over stdio: retrieval, concept reads, capability calls",
    )
    p.add_argument("bundle")
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
    _add_retriever_args(p)
    p.set_defaults(func=cmd_mcp)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
