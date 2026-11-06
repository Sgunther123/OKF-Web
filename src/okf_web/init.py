"""The guided first run (READINESS R3) as a library: feed → lint →
attest → questions → dry-run scorecard → publish → report, one call, no
LLM required (review 2026-10-21, A-U3).

``okf-web init`` used to carry the whole pipeline inside the command,
and the hosted edition re-implemented it to build a store's first
bundle. :func:`run_init` is now the one pipeline: it returns an
:class:`InitResult` with every step's outcome and the exact lines the
command prints, and takes optional ``emit``/``warn`` sinks so a caller
that wants progress as it happens (the CLI) gets it, while one that
does not (a service) reads the result. Every skipped step says why and
names the command that runs it later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import OKF_VERSION, evaluator, feed, linter, packs, publisher, report, review
from .linter import Finding
from .model import Concept, load_bundle, render_document, write_atomic
from .publisher import PublishResult
from .surveyor import SurveyResult

__all__ = ["InitResult", "run_init"]


@dataclass
class InitResult:
    """What the first run did, step by step."""

    ingest: SurveyResult | None = None
    index_written: bool = False
    findings: list[Finding] = field(default_factory=list)
    approved: list[Concept] = field(default_factory=list)
    #: ``written`` (a starter pack), ``kept`` (a set was there), ``skipped``
    #: (no pack asked for) or ``unknown-pack``.
    questions: str = "skipped"
    metrics: dict | None = None
    publish: PublishResult | None = None
    report_path: Path | None = None
    #: Steps not taken, each with how to take it later.
    skipped: list[str] = field(default_factory=list)
    #: Why the run stopped early (``"nothing drafted"``, ``"lint errors"``), or None.
    stopped: str | None = None
    #: Every line the command prints, in order, and every stderr line.
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.stopped else 0


def run_init(
    bundle_root: Path | str,
    dist: Path | str,
    feed_path: Path | str,
    *,
    title: str | None = None,
    site: str | None = None,
    by: str | None = None,
    pack: str | None = None,
    force: bool = False,
    emit: Callable[[str], None] | None = None,
    warn: Callable[[str], None] | None = None,
) -> InitResult:
    """Build a bundle from a product feed and take it through its first
    publish. ``by`` batch-attests the low-risk drafts, ``pack`` seeds a
    starter question set, ``site`` goes on the root index when one is
    written. The run stops, with ``stopped`` set, when the feed drafted
    nothing or the lint found errors; nothing is published then."""
    bundle_root = Path(bundle_root)
    dist = Path(dist)
    result = InitResult()

    def say(line: str) -> None:
        result.lines.append(line)
        if emit is not None:
            emit(line)

    def complain(line: str) -> None:
        result.errors.append(line)
        if warn is not None:
            warn(line)

    say(f"[1/7] ingesting {feed_path} (no LLM — feed rows become draft concepts)")
    ingest = feed.ingest_feed(feed_path, bundle_root)
    result.ingest = ingest
    say(
        f"      {len(ingest.written)} drafted, "
        f"{len(ingest.skipped_unchanged)} unchanged, {len(ingest.errors)} error(s)"
    )
    if ingest.dropped_live_fields:
        say(
            "      live-value fields dropped (never static claims): "
            + ", ".join(ingest.dropped_live_fields)
        )
    for line in ingest.errors[:5]:
        complain(f"      error: {line}")
    for line in ingest.collisions[:5]:
        say(f"      note: {line}")
    if not ingest.written and not ingest.skipped_unchanged:
        complain(
            "      nothing was drafted from the feed; fix the errors above and "
            "re-run (nothing was published)"
        )
        result.stopped = "nothing drafted"
        return result

    index_path = bundle_root / "index.md"
    if not index_path.exists():
        fm: dict = {"okf_version": OKF_VERSION}
        name = title or bundle_root.name
        fm["title"] = name
        if site:
            fm["x_geo"] = {"site": site.rstrip("/")}
        write_atomic(
            index_path,
            render_document(fm, "\n# " + name + "\n\nCatalog concepts live under /catalog/.\n"),
        )
        result.index_written = True
        say(f"[2/7] wrote {index_path} (okf_version 0.2"
            + (f", site {site})" if site else ")"))
    else:
        say(f"[2/7] {index_path} already exists — kept")

    _, findings = linter.lint_bundle(bundle_root)
    result.findings = findings
    errors = [f for f in findings if f.severity == linter.ERROR]
    say(f"[3/7] lint: {len(errors)} error(s), "
        f"{len(findings) - len(errors)} warning(s)")
    if errors:
        for f in errors[:5]:
            say(f"      {f}")
        complain("      fix the errors above, then re-run — publish refuses errors")
        result.stopped = "lint errors"
        return result

    if by:
        bundle = load_bundle(bundle_root)
        result.approved = review.batch_approve(bundle, by)
        say(
            f"[4/7] attested {len(result.approved)} low-risk draft(s) as "
            f"human-batch:{by} — a named bulk sign-off, deliberately "
            "distinct from per-item review; high-risk drafts (if any) still "
            "need `okf-web review approve`"
        )
    else:
        result.skipped.append(
            "attestation (pass --by you@store.com to batch-attest the "
            "low-risk drafts; until then everything stays draft and "
            "publishes nothing)"
        )
        say("[4/7] skipped attestation — no --by given")

    questions_path = bundle_root / "evaluations" / "questions.yaml"
    if not questions_path.exists() and pack:
        available = packs.available()
        if pack in available:
            questions_path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(questions_path, evaluator.stamp_pack(available[pack], pack))
            result.questions = "written"
            say(f"[5/7] wrote starter questions ({pack} pack)")
        else:
            result.questions = "unknown-pack"
            say(f"[5/7] unknown pack {pack!r}; skipped questions")
    elif questions_path.exists():
        result.questions = "kept"
        say("[5/7] questions.yaml already present — kept")
    else:
        result.skipped.append(
            "questions/scorecard/report (pass --pack "
            f"{'|'.join(sorted(packs.available()))} for a starter set)"
        )
        say("[5/7] skipped questions — no --pack given")

    if questions_path.exists():
        bundle = load_bundle(bundle_root)
        questions = evaluator.load_questions(questions_path)
        eval_report = evaluator.evaluate(bundle, questions)
        evaluator.write_scorecard(bundle, eval_report)
        result.metrics = eval_report.metrics(bundle)
        say(
            f"[6/7] dry-run scorecard: {result.metrics['questions']} questions, "
            f"retrieval hit rate {result.metrics['retrieval_hit_rate']} "
            "(retrieval-only; run `okf-web evaluate ... --write-scorecard` "
            "with an LLM for graded coverage)"
        )
    else:
        say("[6/7] skipped scorecard — no question set")

    site_for_publish = site or load_bundle(bundle_root).site
    pub = publisher.publish(bundle_root, dist, site=site_for_publish, force=force)
    result.publish = pub
    say(
        f"[7/7] published {len(pub.published)} file(s) to {dist} "
        f"({len(pub.withheld)} withheld"
        + (f"; derived tier: {max(0, len(pub.structured) - 1)} JSON-LD + llms.txt)"
           if pub.structured else ")")
    )

    if questions_path.exists():
        result.report_path = report.write_report(bundle_root)
        say(f"      report: {result.report_path}")

    say("\ndone. what you have now:")
    say(f"  bundle:  {bundle_root}  (facts, provenance, review queue)")
    say(f"  publish: {dist}  (serve at /.well-known/okf/ — includes jsonld/ + llms.txt)")
    if result.report_path:
        say(f"  report:  {result.report_path}  (open in a browser, share as-is)")
    say("\nserve it to Claude Desktop/Code right now — add to the MCP config:")
    # An absolute path: a desktop client does not share this shell's
    # working directory (EDGE-CASES, "not counted").
    say(
        '  {"mcpServers": {"my-store": {"command": "okf-web", '
        '"args": ["mcp", "' + str(bundle_root.resolve()) + '"]}}}'
    )
    if result.skipped:
        say("\nskipped (and how to run them):")
        for line in result.skipped:
            say(f"  - {line}")
    say(
        "\nnext: review drafts (`okf-web review list`), run the full "
        "LLM evaluation, and see docs/USER-GUIDE.md for the loop."
    )
    return result
