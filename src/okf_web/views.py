"""What a publish ships and what it holds back (review 2026-10-21,
A-U7: the rules the publisher, the bridge, the mirror and the viewer
all consult, in a module that imports only the model). The publisher
re-exports them, so ``okf_web.publisher.published_view`` still works.
"""

from __future__ import annotations

import datetime as _dt

from .model import Bundle

__all__ = ["select_publishable", "withhold_reason", "published_view"]


def select_publishable(
    bundle: Bundle,
    include_machine_confirmed: bool = False,
    today: _dt.date | None = None,
    freshness: str = "warn",
) -> tuple[set[str], list[str]]:
    """Split the bundle's concepts into (publishable, withheld).

    Expired promotions are withheld even when stable and approved —
    ``x_geo.ends_at`` is machine-readable, so this is the one content
    class where auto-retirement is unambiguous: a publish after the
    end date can never ship a dead sale.

    ``freshness="withhold"`` extends that retirement to any concept
    past its ``stale_after``: the merchant told consumers "do not
    trust this after date X", so a publish after X stops shipping it.
    The default ("warn") keeps shipping and warns — withholding a
    stale returns policy may be worse than serving it a week late, so
    strict retirement is opt-in.
    """
    include: set[str] = set()
    withheld: list[str] = []
    for rel, concept in bundle.concepts.items():
        if concept.type == "Promotion" and concept.promo_expired(today):
            withheld.append(rel)
        elif freshness == "withhold" and concept.is_stale(today):
            withheld.append(rel)
        elif concept.status == "stable":
            include.add(rel)
        elif (include_machine_confirmed and concept.status == "draft"
              and not concept.is_high_risk):
            # A low-risk draft, on request; a deprecated or unknown status
            # never ships (review 2026-10-21, L-U4).
            include.add(rel)
        else:
            withheld.append(rel)
    return include, withheld


def withhold_reason(
    concept,
    today: _dt.date | None = None,
    freshness: str = "warn",
    include_machine_confirmed: bool = False,
) -> str:
    """Why ``select_publishable`` withholds ``concept``, in the words the
    operator needs (EDGE-CASES U9): the actual status, never a generic
    "drafts or stale"."""
    if concept.type == "Promotion" and concept.promo_expired(today):
        return "expired promotion"
    if freshness == "withhold" and concept.is_stale(today):
        return "stale (--freshness withhold)"
    if concept.status == "stable":
        return "published"
    if concept.status == "draft":
        if concept.is_high_risk:
            return "draft, high-risk: needs `okf-web review approve`"
        if include_machine_confirmed:
            return "draft"
        return "draft (low-risk; --include-machine-confirmed would ship it)"
    return f"status {concept.status!r}: only stable concepts publish"


def published_view(
    bundle: Bundle,
    include_machine_confirmed: bool = False,
    today: _dt.date | None = None,
    freshness: str = "warn",
) -> Bundle:
    """The bundle as consumers see it: withheld concepts removed.

    Evaluating this view instead of the working bundle keeps the
    scorecard honest — a full evaluation over the working copy would
    happily answer questions from drafts the publisher withholds.
    """
    include, _ = select_publishable(bundle, include_machine_confirmed, today, freshness)
    view = Bundle(root=bundle.root)
    view.concepts = {rel: c for rel, c in bundle.concepts.items() if rel in include}
    view.indexes = dict(bundle.indexes)
    view.logs = dict(bundle.logs)
    return view
