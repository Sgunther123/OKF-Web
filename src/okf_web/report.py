"""The answerability report: the scorecard as a shareable artifact.

The evaluation already answers the question every merchant actually
asks — *can an AI answer my shoppers' questions?* — and already
carries the raw-HTML baseline quantifying the lift. This module
renders that measurement as a single self-contained HTML page a
non-technical owner can read and forward (READINESS R2): headline
numbers, per-topic coverage, the measured gaps, and the trust posture,
with no dependency beyond the stdlib and no LLM call (it reads the
scorecard the evaluator already wrote).

The report never invents numbers: everything shown is read from the
GEO Scorecard concept and the bundle itself. A dry-run scorecard
renders honestly as retrieval-only coverage with a pointer to the
full evaluation.

Beneath the summary the report carries a detail tier: per-question
rows recomputed at render time by the evaluator's deterministic
retrieval pass over the bundle's committed question pack — the exact
question, the knowledge file it finds, the reading cost, and how the
shopper-vocabulary paraphrase fared. No LLM is involved and no grade
is displayed that was not measured: judged verdicts exist only as the
recorded aggregates.
"""

from __future__ import annotations

import datetime as _dt
import html
import re
from pathlib import Path

from .evaluator import evaluate as _dry_evaluate, load_questions
from .model import (
    Bundle,
    Concept,
    TRUST_HUMAN,
    TRUST_HUMAN_BATCH,
    load_bundle,
    split_l10n,
)

# Archetype → the question a shopper would recognize.
ARCHETYPE_LABELS = {
    "discovery": "Finding the right product",
    "product_fact": "Product facts",
    "comparison": "Comparing products",
    "policy": "Returns, warranty and policies",
    "fulfillment": "Shipping and delivery",
    "trust": "Trust and legitimacy",
    "capability": "Live price and stock",
    "promotion": "Sales and promotions",
    "fit_compatibility": "Fit and compatibility",
    "ownership": "After the purchase",
    "compliance": "Materials and compliance",
    "local_availability": "In-store and local",
    "procurement": "Wholesale and B2B",
}


class ReportError(RuntimeError):
    pass


def _scorecard(bundle: Bundle) -> Concept:
    for rel in sorted(bundle.concepts):
        if bundle.concepts[rel].type == "GEO Scorecard":
            return bundle.concepts[rel]
    raise ReportError(
        "no GEO Scorecard concept in the bundle; run "
        "`okf-web evaluate <bundle> --write-scorecard` (full, LLM-backed) "
        "or author one, then re-run `okf-web report`"
    )


def _gaps(scorecard: Concept) -> list[str]:
    lines: list[str] = []
    in_section = False
    for line in scorecard.body.splitlines():
        if line.startswith("#"):
            in_section = line.strip("# ").lower().startswith("knowledge gaps")
            continue
        if in_section and line.lstrip().startswith("*"):
            lines.append(line.lstrip("* ").strip())
        elif in_section and line.strip() and lines and lines[-1]:
            # continuation of a wrapped bullet
            lines[-1] += " " + line.strip()
    cleaned = [re.sub(r"\s+", " ", g).replace("`", "") for g in lines if g]
    return [g for g in cleaned if not g.lower().startswith("none found")]


def _pct(value) -> str:
    return f"{round(float(value) * 100)}%"


_GAP_ID = re.compile(r"^\*\s*`([^`]+)`")


def _judged_verdicts(scorecard: Concept) -> dict[str, bool]:
    """Per-question judged verdicts, read only from what the recorded
    scorecard states: the results table's ``answered`` column (located
    by header, so older five-column tables parse too), plus the gap
    bullets' question ids, since a recorded gap is a recorded
    non-answer. Nothing is inferred; a question the scorecard does not
    pronounce on stays absent."""
    verdicts: dict[str, bool] = {}
    answered_col: int | None = None
    in_gaps = False
    for line in scorecard.body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_gaps = stripped.strip("# ").lower().startswith("knowledge gaps")
            answered_col = None
            continue
        if in_gaps:
            match = _GAP_ID.match(stripped)
            if match:
                verdicts.setdefault(match.group(1), False)
            continue
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if "answered" in cells:
            answered_col = cells.index("answered")
            continue
        if answered_col is None or len(cells) <= answered_col:
            continue
        verdict = cells[answered_col].lower()
        if verdict in ("yes", "no"):
            verdicts[cells[0].strip("`")] = verdict == "yes"
    return verdicts


def _question_detail(bundle: Bundle, by_archetype: dict | None,
                     verdicts: dict[str, bool] | None = None,
                     gap_ids: set[str] | None = None) -> str:
    """The detail tier: one row per question in the committed pack,
    recomputed by the evaluator's deterministic retrieval pass at
    render time. Shows facts that can be measured without an LLM —
    which knowledge file the question finds, the reading cost, the
    paraphrase's fate — and displays no per-question grade, because
    none is recorded. Each block's summary carries both counts where a
    full evaluation was recorded: knowledge found (this pass) beside
    judged answers (the scorecard), so the two measurements cannot be
    mistaken for one another when they differ."""
    pack = bundle.root / "evaluations" / "questions.yaml"
    if not pack.exists():
        return ""
    questions = load_questions(pack)
    if not questions:
        return ""
    dry = _dry_evaluate(bundle, questions)
    e = html.escape

    grouped: dict[str, list] = {}
    for result in dry.results:
        grouped.setdefault(result.question.archetype, []).append(result)

    blocks: list[str] = []
    for archetype, results in grouped.items():
        label = ARCHETYPE_LABELS.get(archetype, archetype)
        found = sum(1 for r in results if r.retrieved)
        rows = []
        for r in results:
            cell = e(r.question.question)
            if (verdicts or {}).get(r.question.id) is False:
                # The pointer is a working link: to this question's own
                # gap bullet when the scorecard recorded one, else to
                # the gaps section itself.
                if r.question.id in (gap_ids or set()):
                    where = (f'<a href="#gap-{e(r.question.id)}">'
                             "see the gap above</a>")
                else:
                    where = '<a href="#gaps">see the gaps above</a>'
                cell += (
                    '<div class="judged">judged not answered in the '
                    f"recorded evaluation ({where})</div>"
                )
            if r.retrieved_paraphrase is not None:
                if set(r.retrieved_paraphrase) & set(r.retrieved):
                    para = "the same knowledge was found"
                elif r.retrieved_paraphrase:
                    para = "different knowledge was found"
                else:
                    para = "nothing was found"
                cell += (
                    '<div class="para">asked in a shopper\'s own words: '
                    f"{para}</div>"
                )
            if r.retrieved:
                top = r.retrieved[0]
                concept = bundle.get(top)
                title = f" &middot; {e(concept.title)}" if concept else ""
                more = (
                    f' <span class="more">+{len(r.retrieved) - 1} more</span>'
                    if len(r.retrieved) > 1 else ""
                )
                found_cell = f"<code>/{e(top)}</code>{title}{more}"
            else:
                found_cell = '<span class="miss">no matching knowledge</span>'
            rows.append(
                f"<tr><td>{cell}</td><td>{found_cell}</td>"
                f'<td class="num">{r.context_tokens:,}</td></tr>'
            )
        recorded = (by_archetype or {}).get(archetype) or {}
        judged = (
            f' &middot; judged answers {recorded.get("answered", 0)} / '
            f'{recorded["questions"]} (recorded)'
            if recorded.get("questions") else ""
        )
        blocks.append(
            f'<details class="arch"><summary>{e(label)} '
            f'<span class="count">knowledge found for {found} / '
            f"{len(results)}{judged}</span></summary>"
            '<table class="qtable"><thead><tr><th>Question</th>'
            "<th>Knowledge found (top match)</th><th>Tokens</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></details>"
        )
    return (
        "<h2>The detail behind the numbers</h2>"
        '<p class="meaning">Each row below is recomputed from the committed '
        "bundle and its question pack every time this report renders: the "
        "exact question asked, the knowledge file it finds, and the reading "
        "cost in tokens. This pass is deterministic and involves no AI "
        "model. Judged verdicts (answered, grounded, cited) are recorded "
        "only as the aggregates above, so no per-question grade is shown "
        "that was not measured. Finding knowledge is necessary, not "
        "sufficient: a question can find the right file and still lose "
        "its point from the judge, which is why each topic shows both "
        "counts; where the recorded scorecard names the question that "
        "lost its point, its row is marked, and the knowledge gaps above "
        "say what was missing.</p>" + "".join(blocks)
    )


def build_report(bundle: Bundle, today: _dt.date | None = None) -> str:
    """Render the bundle's scorecard as a self-contained HTML page."""
    scorecard = _scorecard(bundle)
    metrics = scorecard.x_geo.get("metrics") or {}
    baseline = scorecard.x_geo.get("baseline") or {}
    identity = next(
        (c for c in bundle.concepts.values() if c.type == "Store Identity"), None
    )
    store = identity.title if identity else bundle.root.name
    full_run = "coverage" in metrics

    concepts = [
        c for rel, c in bundle.concepts.items() if split_l10n(rel) is None
    ]
    human = sum(1 for c in concepts if c.trust_tier == TRUST_HUMAN)
    attested = sum(1 for c in concepts if c.trust_tier == TRUST_HUMAN_BATCH)
    capabilities = sum(1 for c in concepts if c.type == "Attested Computation")
    stale = sum(1 for c in concepts if c.is_stale(today))

    e = html.escape

    def tile(value: str, label: str, detail: str = "") -> str:
        detail_html = f'<div class="detail">{e(detail)}</div>' if detail else ""
        return (
            f'<div class="tile"><div class="value">{e(value)}</div>'
            f'<div class="label">{e(label)}</div>{detail_html}</div>'
        )

    tiles = []
    questions = metrics.get("questions", 0)
    if full_run:
        tiles.append(
            tile(
                _pct(metrics["coverage"]),
                "shopper questions answered",
                f"of {questions} measured questions",
            )
        )
        if baseline.get("coverage") is not None:
            tiles.append(
                tile(
                    _pct(baseline["coverage"]),
                    "answered from the site alone",
                    str(baseline.get("condition") or "raw site pages"),
                )
            )
        if metrics.get("citability") is not None:
            tiles.append(
                tile(
                    _pct(metrics["citability"]),
                    "answers citing verified facts",
                    "every citation names its concept",
                )
            )
    else:
        tiles.append(
            tile(
                _pct(metrics.get("retrieval_hit_rate", 0)),
                "questions with matching knowledge",
                f"retrieval-only dry run over {questions} questions",
            )
        )
    if metrics.get("paraphrase_agreement") is not None:
        tiles.append(
            tile(
                _pct(metrics["paraphrase_agreement"]),
                "asked in shoppers' own words",
                f"same knowledge found across "
                f"{metrics.get('paraphrase_questions', 0)} paraphrased questions",
            )
        )
    if metrics.get("context_tokens_mean") and baseline.get("context_tokens_mean"):
        ratio = baseline["context_tokens_mean"] / max(1, metrics["context_tokens_mean"])
        tiles.append(
            tile(
                f"{ratio:.0f}× less",
                "reading for the same answers",
                f"{metrics['context_tokens_mean']:,} vs "
                f"{baseline['context_tokens_mean']:,} tokens per question",
            )
        )

    rows = []
    for archetype, slot in (metrics.get("by_archetype") or {}).items():
        label = ARCHETYPE_LABELS.get(archetype, archetype)
        answered, total = slot.get("answered", 0), slot.get("questions", 0)
        state = "ok" if answered == total else ("warn" if answered else "gap")
        rows.append(
            f'<tr class="{state}"><td>{e(label)}</td>'
            f"<td>{answered} / {total}</td></tr>"
        )

    gaps = _gaps(scorecard)
    # Gap bullets open with the question id (write_scorecard's format),
    # so each list item can carry an anchor the detail rows link to.
    gap_ids: set[str] = set()

    def gap_li(gap: str) -> str:
        match = re.match(r"([A-Za-z0-9_-]+)\s*\(", gap)
        if match:
            gap_ids.add(match.group(1))
            return f'<li id="gap-{e(match.group(1))}">{e(gap)}</li>'
        return f"<li>{e(gap)}</li>"

    gaps_html = (
        "".join(gap_li(g) for g in gaps)
        if gaps
        else "<li>None found in the last evaluation.</li>"
    )

    generated_by = str((scorecard.frontmatter.get("generated") or {}).get("by") or "okf-web")
    evaluated_on = str(scorecard.title).rsplit("—", 1)[-1].strip()

    if full_run:
        meaning = (
            "An AI assistant given this store's knowledge bundle answered "
            f"{_pct(metrics['coverage'])} of a fixed set of realistic shopper "
            "questions"
            + (
                f", against {_pct(baseline['coverage'])} when reading the "
                "website the way engines otherwise do"
                if baseline.get("coverage") is not None
                else ""
            )
            + ". Answers cite the exact verified fact they came from, and "
            "live values like price and stock are fetched from the store's "
            "own systems instead of quoted from stale text."
        )
    else:
        meaning = (
            "This is a retrieval-only dry run: it measures whether matching "
            "knowledge exists for each question, without an AI writing "
            "answers. Run the full evaluation for answer coverage and "
            "citation numbers."
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI answerability — {e(store)}</title>
<style>
  body {{ font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
         color: #1c2733; margin: 0; background: #f5f7f9; }}
  main {{ max-width: 780px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; }}
  h2 {{ font-size: 1.1rem; margin: 2.2rem 0 .6rem; }}
  .sub {{ color: #5b6b7a; margin: 0 0 1.8rem; }}
  .tiles {{ display: flex; flex-wrap: wrap; gap: .8rem; }}
  .tile {{ flex: 1 1 160px; background: #fff; border: 1px solid #e1e7ec;
           border-radius: 10px; padding: 1rem 1.1rem; }}
  .tile .value {{ font-size: 1.7rem; font-weight: 700; }}
  .tile .label {{ color: #33424f; margin-top: .15rem; }}
  .tile .detail {{ color: #7a8894; font-size: .85rem; margin-top: .3rem; }}
  p.meaning {{ background: #fff; border: 1px solid #e1e7ec; border-radius: 10px;
               padding: 1rem 1.1rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border: 1px solid #e1e7ec; border-radius: 10px; overflow: hidden; }}
  td {{ padding: .55rem .9rem; border-top: 1px solid #eef2f5; }}
  tr:first-child td {{ border-top: none; }}
  td:last-child {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  tr.warn td:last-child {{ color: #9a6b00; }}
  tr.gap td:last-child {{ color: #b3261e; }}
  ul {{ background: #fff; border: 1px solid #e1e7ec; border-radius: 10px;
        margin: 0; padding: .8rem 1.1rem .8rem 2.2rem; }}
  li {{ margin: .3rem 0; }}
  details.arch {{ background: #fff; border: 1px solid #e1e7ec;
                  border-radius: 10px; margin: .6rem 0; }}
  details.arch summary {{ cursor: pointer; padding: .65rem 1rem;
                          font-weight: 600; }}
  details.arch summary .count {{ color: #7a8894; font-weight: 400;
                                 font-size: .88rem; }}
  details.arch .qtable {{ border: none; border-top: 1px solid #eef2f5;
                          border-radius: 0; }}
  .qtable th {{ text-align: left; color: #7a8894; font-weight: 600;
                font-size: .85rem; padding: .45rem .9rem; border-top: none; }}
  .qtable td {{ vertical-align: top; }}
  .qtable .para {{ color: #7a8894; font-size: .82rem; margin-top: .15rem; }}
  .qtable .more {{ color: #7a8894; font-size: .82rem; white-space: nowrap; }}
  .qtable .miss {{ color: #b3261e; }}
  .qtable .judged {{ color: #b3261e; font-size: .82rem; font-weight: 600;
                     margin-top: .15rem; }}
  .qtable .judged a {{ color: inherit; }}
  li:target, tr:target td {{ background: #fdf3d7; }}
  footer {{ color: #7a8894; font-size: .85rem; margin-top: 2.5rem; }}
</style>
</head>
<body>
<main>
  <h1>Can an AI answer your shoppers?</h1>
  <p class="sub">{e(store)} &middot; measured {e(evaluated_on)}</p>
  <div class="tiles">{''.join(tiles)}</div>
  <h2>What this means</h2>
  <p class="meaning">{e(meaning)}</p>
  <h2>Coverage by topic</h2>
  <table>{''.join(rows) or '<tr><td>No per-topic data in this scorecard.</td><td>—</td></tr>'}</table>
  <h2 id="gaps">What the store still can't answer</h2>
  <ul>{gaps_html}</ul>
  {_question_detail(bundle, metrics.get("by_archetype"),
                    _judged_verdicts(scorecard), gap_ids)}
  <h2>Why these answers can be trusted</h2>
  <p class="meaning">Of {len(concepts)} knowledge entries: {human} were
  read and approved individually by a named person, and {attested} were
  published under a named person's bulk sign-off (mechanical facts, like
  a product feed — the label says which is which); {capabilities}
  live-value lookups (price, stock, order status) execute against the
  store's own systems instead of quoting stored numbers; {stale} entries
  are past their freshness date. High-risk facts — prices, policies,
  safety — cannot be published without an individual human review.</p>
  <footer>Measured by the okf-web evaluation harness
  ({e(generated_by)}) over the published bundle — an LLM-based
  measurement; method in docs/EVALUATION.md. Regenerate with
  <code>okf-web report &lt;bundle&gt;</code>.</footer>
</main>
</body>
</html>
"""


def write_report(
    bundle_root: Path | str,
    out: Path | str | None = None,
    today: _dt.date | None = None,
) -> Path:
    bundle_root = Path(bundle_root)
    bundle = load_bundle(bundle_root)
    target = Path(out) if out else bundle_root / "evaluations" / "geo-report.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(bundle, today=today), encoding="utf-8")
    return target
