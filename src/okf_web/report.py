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
"""

from __future__ import annotations

import datetime as _dt
import html
import re
from pathlib import Path

from .model import Bundle, Concept, TRUST_HUMAN, load_bundle, split_l10n

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
    gaps_html = (
        "".join(f"<li>{e(g)}</li>" for g in gaps)
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
  <h2>What the store still can't answer</h2>
  <ul>{gaps_html}</ul>
  <h2>Why these answers can be trusted</h2>
  <p class="meaning">{human} of {len(concepts)} knowledge entries were
  approved by a named human reviewer before publication; {capabilities}
  live-value lookups (price, stock, order status) execute against the
  store's own systems instead of quoting stored numbers; {stale} entries
  are past their freshness date. High-risk facts — prices, policies,
  safety — cannot be published here without a human sign-off.</p>
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
