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
import difflib
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
    utc_instant,
)

STATUSES = ("draft", "stable", "deprecated")


class ReviewError(KeyError, ValueError):
    """A review action that cannot proceed, with the reason in plain
    words (a KeyError for callers that looked concepts up by path, a
    ValueError for callers that validated arguments; EDGE-CASES U5/U7)."""

    def __str__(self) -> str:  # KeyError would quote the message
        return str(self.args[0]) if self.args else ""


def resolve_path(bundle: Bundle, path: str) -> str:
    """The bundle-relative path a reviewer meant: accepts the exact rel
    path, ``./``-prefixed and bundle-prefixed spellings (what a shell's
    tab completion produces), and absolute paths inside the bundle;
    anything else raises :class:`ReviewError` with the closest matches."""
    given = str(path).replace("\\", "/")
    candidates = [given, given.removeprefix("./")]
    p = Path(given)
    for base in (bundle.root, Path(bundle.root.name)):
        try:
            candidates.append(p.relative_to(base).as_posix())
        except ValueError:
            pass
    try:
        candidates.append(p.resolve().relative_to(bundle.root.resolve()).as_posix())
    except (ValueError, OSError):
        pass
    for candidate in candidates:
        if candidate in bundle.concepts:
            return candidate
    matches = difflib.get_close_matches(candidates[-1], list(bundle.concepts), n=3, cutoff=0.5)
    hint = f"; did you mean {', '.join(matches)}?" if matches else ""
    raise ReviewError(f"no such concept in bundle: {path}{hint}")


def _actor_for(reviewer: str, actor_prefix: str) -> str:
    return (
        reviewer
        if reviewer.startswith(("human:", "human-batch:"))
        else f"{actor_prefix}{reviewer}"
    )


def _verified_entries(concept: Concept) -> list[dict]:
    existing = concept.frontmatter.get("verified")
    if isinstance(existing, dict):
        return [existing]
    if isinstance(existing, list):
        return [e for e in existing if isinstance(e, dict)]
    return []


def approval_state(concept: Concept, reviewer: str, actor_prefix: str = "human:") -> str | None:
    """Why approving ``concept`` again would change nothing, or ``None``
    when an approval is due: a stable, fresh concept already verified by
    this actor is a no-op (EDGE-CASES U5)."""
    actor = _actor_for(reviewer, actor_prefix)
    if concept.status == "stable" and not concept.is_stale():
        for entry in _verified_entries(concept):
            if entry.get("by") == actor:
                return f"already approved by {actor} on {entry.get('at', '?')} (no change)"
    return None

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

    Lack of verification only queues effective-risk ``a``/``b`` concepts: stable
    risk-``c`` machine artifacts (indexes, scorecards) don't need human
    attention. Drafts and stale concepts always queue.
    """
    items: list[ReviewItem] = []
    for concept in bundle.concepts.values():
        reasons = []
        if concept.status == "draft":
            reasons.append("status is draft")
        if concept.trust_tier == TRUST_UNVERIFIED and concept.effective_risk in (
            RISK_HIGH,
            RISK_MEDIUM,
        ):
            reasons.append("no verification events")
        if concept.is_stale():
            reasons.append("stale_after has passed")
        if reasons:
            items.append(ReviewItem(concept, reasons))
    # Triage on *effective* risk so the queue agrees with the gates: a
    # Trade Program declaring `b` sorts — and counts — as `a`.
    items.sort(
        key=lambda i: (_RISK_ORDER.get(i.concept.effective_risk, 2), i.concept.rel_path)
    )
    return items


def approve(
    bundle: Bundle,
    rel_path: str,
    reviewer: str,
    actor_prefix: str = "human:",
    stale_after: str | None = None,
) -> Concept:
    """Record a human verification event and promote the concept to stable.

    ``actor_prefix`` distinguishes per-item review (``human:``, the
    default — the only tier E010 accepts for high-risk concepts) from
    wholesale attestation (``human-batch:``, stamped by batch-approve):
    both name an accountable person, but only one means each item was
    read.

    A concept past its ``stale_after`` is queued for exactly that reason,
    so approving it needs a new freshness date (``stale_after``,
    ``YYYY-MM-DD``, in the future); without one the call refuses rather
    than leave the concept in the queue. Approving a stable, fresh
    concept again by the same actor changes nothing (EDGE-CASES U5).
    """
    rel_path = resolve_path(bundle, rel_path)
    concept = bundle.get(rel_path)
    if approval_state(concept, reviewer, actor_prefix) is not None:
        return concept
    actor = _actor_for(reviewer, actor_prefix)
    if concept.is_stale():
        if not stale_after:
            raise ReviewError(
                f"{rel_path} is past its stale_after "
                f"({concept.frontmatter.get('stale_after')}); approving it "
                "needs a new freshness date: pass --stale-after YYYY-MM-DD "
                "after re-checking the fact against the source"
            )
        try:
            new_date = _dt.date.fromisoformat(str(stale_after))
        except ValueError as exc:
            raise ReviewError(f"--stale-after must be YYYY-MM-DD, got {stale_after!r}") from exc
        if new_date <= _dt.date.today():
            raise ReviewError(f"--stale-after must be a future date, got {stale_after}")
        concept.frontmatter["stale_after"] = utc_instant(
            _dt.datetime(new_date.year, new_date.month, new_date.day, tzinfo=_dt.timezone.utc)
        )
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


def batch_candidates(
    bundle: Bundle,
    risks: tuple[str, ...] = (RISK_MEDIUM, RISK_LOW),
    only_machine_confirmed: bool = False,
) -> tuple[list[Concept], list[tuple[Concept, str]]]:
    """What ``batch_approve`` would approve, and what it skips with the
    reason: a draft a reviewer already rejected stays rejected until
    someone reads it again (EDGE-CASES U4). Raises :class:`ReviewError`
    for risk ``a``."""
    if RISK_HIGH in risks:
        raise ReviewError("risk-a concepts cannot be batch-approved; review them individually")
    candidates: list[Concept] = []
    skipped: list[tuple[Concept, str]] = []
    for item in pending(bundle):
        concept = item.concept
        if concept.status != "draft" or concept.risk not in risks:
            continue
        # Declared risk is not the last word: types that are high-risk
        # by definition (Product Passports) never batch, whatever
        # their frontmatter claims.
        if concept.is_high_risk:
            continue
        if only_machine_confirmed and concept.trust_tier != TRUST_MACHINE:
            continue
        marker = concept.x_geo.get("review")
        if isinstance(marker, dict) and marker.get("rejected_by"):
            reason = str(marker.get("reason") or "").strip()
            skipped.append((
                concept,
                f"rejected by {marker['rejected_by']}" + (f": {reason}" if reason else ""),
            ))
            continue
        candidates.append(concept)
    return candidates, skipped


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
    candidates, _skipped = batch_candidates(bundle, risks, only_machine_confirmed)
    approved: list[Concept] = []
    for concept in candidates:
        # Wholesale attestation, not per-item review: the stamp says so
        # (`human-batch:` → trust tier "human-attested"), so a reader of
        # the published concept — or of the scorecard's trust mix — can
        # tell the difference (READINESS R3).
        approved.append(
            approve(bundle, concept.rel_path, reviewer, actor_prefix="human-batch:")
        )
    return approved


def reject(bundle: Bundle, rel_path: str, reviewer: str, reason: str) -> Concept:
    """Keep the concept in draft and record why it was not approved."""
    rel_path = resolve_path(bundle, rel_path)
    concept = bundle.get(rel_path)
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
