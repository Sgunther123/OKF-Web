"""Human-in-the-loop verification queue.

LLM-drafted concepts enter the bundle as ``status: draft`` with a
machine ``generated.by`` actor and no ``verified`` entries. This module
implements the reviewer side:

* ``pending()`` — what needs human eyes, highest risk first.
* ``approve()`` — stamps ``verified: [{by: human:<id>, at: now}]``, flips
  ``status`` to ``stable``, and records the event in ``log.md``. That
  stamp is what moves the concept into the spec's *human-reviewed* trust
  tier, which is the signal generative engines key off.
* ``reject()`` — keeps the concept in ``draft``, records the reason in
  ``x_geo.review`` so the surveyor's next pass can react to it.

The queue is plain files in git, so the same flow works as a pull
request review: surveyor pushes a branch, humans approve concepts, CI
lints, merge publishes.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .model import (
    Bundle,
    Concept,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    TRUST_MACHINE,
    TRUST_UNVERIFIED,
    load_bundle,
)

_RISK_ORDER = {RISK_HIGH: 0, RISK_MEDIUM: 1}


@dataclass
class ReviewItem:
    concept: Concept
    reasons: list[str]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def pending(bundle: Bundle) -> list[ReviewItem]:
    """Concepts awaiting human review, highest risk first.

    Lack of verification only queues risk ``a``/``b`` concepts: stable
    risk-``c`` machine artifacts (indexes, scorecards) don't need human
    attention. Drafts and stale concepts always queue.
    """
    items: list[ReviewItem] = []
    for concept in bundle.concepts.values():
        reasons = []
        if concept.status == "draft":
            reasons.append("status is draft")
        if concept.trust_tier == TRUST_UNVERIFIED and concept.risk in (
            RISK_HIGH,
            RISK_MEDIUM,
        ):
            reasons.append("no verification events")
        if concept.is_stale():
            reasons.append("stale_after has passed")
        if reasons:
            items.append(ReviewItem(concept, reasons))
    items.sort(key=lambda i: (_RISK_ORDER.get(i.concept.risk, 2), i.concept.rel_path))
    return items


def approve(bundle: Bundle, rel_path: str, reviewer: str) -> Concept:
    """Record a human verification event and promote the concept to stable."""
    concept = bundle.get(rel_path)
    if concept is None:
        raise KeyError(f"no such concept in bundle: {rel_path}")
    actor = reviewer if reviewer.startswith("human:") else f"human:{reviewer}"
    entry = {"by": actor, "at": _now_iso()}

    existing = concept.frontmatter.get("verified")
    if existing is None:
        concept.frontmatter["verified"] = [entry]
    elif isinstance(existing, dict):
        concept.frontmatter["verified"] = [existing, entry]
    elif isinstance(existing, list):
        existing.append(entry)

    concept.frontmatter["status"] = "stable"
    x_geo = concept.frontmatter.get("x_geo")
    if isinstance(x_geo, dict):
        x_geo.pop("review", None)
    concept.save()
    append_log(
        bundle.root,
        f"**Verify**: [{concept.title}](/{concept.rel_path}) approved by {actor}.",
    )
    return concept


def batch_approve(
    bundle: Bundle,
    reviewer: str,
    risks: tuple[str, ...] = (RISK_MEDIUM, RISK_LOW),
    only_machine_confirmed: bool = False,
) -> list[Concept]:
    """Approve every pending *draft* in the given risk tiers at once.

    This thins the low-stakes tail of the queue after a skim — the
    descriptive-facts tier the profile says may flow at machine speed.
    Risk ``a`` is deliberately not batchable: E010 exists so that
    money/legal/safety claims get individual human eyes, and a batch
    command must not become the way around it.

    ``only_machine_confirmed`` narrows further to drafts that already
    carry a machine verification event (e.g. a faithfulness check),
    leaving wholly unverified drafts in the queue.
    """
    if RISK_HIGH in risks:
        raise ValueError("risk-a concepts cannot be batch-approved; review them individually")
    approved: list[Concept] = []
    for item in pending(bundle):
        concept = item.concept
        if concept.status != "draft" or concept.risk not in risks:
            continue
        if only_machine_confirmed and concept.trust_tier != TRUST_MACHINE:
            continue
        approved.append(approve(bundle, concept.rel_path, reviewer))
    return approved


def reject(bundle: Bundle, rel_path: str, reviewer: str, reason: str) -> Concept:
    """Keep the concept in draft and record why it was not approved."""
    concept = bundle.get(rel_path)
    if concept is None:
        raise KeyError(f"no such concept in bundle: {rel_path}")
    actor = reviewer if reviewer.startswith("human:") else f"human:{reviewer}"
    concept.frontmatter["status"] = "draft"
    x_geo = concept.frontmatter.setdefault("x_geo", {})
    x_geo["review"] = {"rejected_by": actor, "at": _now_iso(), "reason": reason}
    concept.save()
    append_log(
        bundle.root,
        f"**Reject**: [{concept.title}](/{concept.rel_path}) sent back by {actor}: {reason}",
    )
    return concept


def append_log(root: Path, message: str, today: _dt.date | None = None) -> None:
    """Insert a bullet under today's heading in ``log.md`` (newest first)."""
    log_path = Path(root) / "log.md"
    day = (today or _dt.date.today()).isoformat()
    heading = f"## {day}"
    bullet = f"* {message}"

    if not log_path.exists():
        log_path.write_text(
            f"# Directory Update Log\n\n{heading}\n\n{bullet}\n", encoding="utf-8"
        )
        return

    lines = log_path.read_text(encoding="utf-8").splitlines()
    if heading in lines:
        idx = lines.index(heading) + 1
        while idx < len(lines) and lines[idx].strip() == "":
            idx += 1
        lines.insert(idx, bullet)
    else:
        # Insert a fresh day section after the title (newest first).
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("## "):
                insert_at = i
                break
            if line.startswith("# "):
                insert_at = i + 1
        else:
            insert_at = len(lines)
        while insert_at < len(lines) and lines[insert_at].strip() == "":
            insert_at += 1
        lines[insert_at:insert_at] = [heading, "", bullet, ""]
    log_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load(root: Path | str) -> Bundle:
    return load_bundle(root)
