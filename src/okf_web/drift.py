"""LLM-free drift detection: which concepts' source pages changed?

The surveyor stamps every extracted concept with
``x_geo.source_hash`` — a sha256 over the *stabilized* text of the
page it came from (volatile chrome lines removed). That hash powers
incremental re-survey; here it powers the other direction: a cheap,
scheduled check that re-fetches each concept's ``resource`` and
reports whether the underlying page still matches what the bundle
claims to describe.

This is the mechanical half of the faithfulness story, and it costs
zero LLM tokens — cheap enough to run nightly in CI:

* ``drifted`` — the page's stable text no longer matches the hash the
  concept was extracted from. The bundle may now be asserting facts
  the site has changed; re-survey those URLs.
* ``unreachable`` — the page could not be fetched. A concept whose
  source is gone is unverifiable; investigate.
* ``unchanged`` — the page still matches; the concept's claims are as
  grounded as the day they were reviewed.

Concepts without a ``resource`` + ``source_hash`` pair (hand-authored
concepts, scorecards) are skipped — drift is defined against a
surveyed source, and there is nothing to compare otherwise. The
semantic half (does the *claim* still hold, not just the page bytes)
stays with the LLM re-survey this check tells you to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .feed import FEED_ACTOR
from .model import load_bundle
from .surveyor import fetch, html_to_text, stable_page_hash

__all__ = [
    "DriftReport",
    "check_bundle",
]


def _fetch_page_text(
    url: str, timeout: float = 30.0, allow_private: bool = False, policy=None
) -> str:
    return html_to_text(fetch(url, timeout=timeout, allow_private=allow_private, policy=policy))


@dataclass
class DriftReport:
    unchanged: list[str] = field(default_factory=list)
    drifted: list[tuple[str, str]] = field(default_factory=list)      # (rel, url)
    unreachable: list[tuple[str, str]] = field(default_factory=list)  # (rel, error)
    skipped: list[str] = field(default_factory=list)
    # Concepts a feed produced: their hash is the row's, not a page's, so
    # a page fetch can only ever disagree (review 2026-10-21, L-U3). The
    # next feed ingest is their drift check.
    feed_derived: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.drifted and not self.unreachable


def check_bundle(
    bundle_root: Path | str,
    fetch_text=None,
    timeout: float = 30.0,
    allow_private: bool = False,
    policy=None,
) -> DriftReport:
    """Compare every surveyed concept's source page against its hash.

    Pages are fetched once per URL even when several concepts were
    extracted from the same page. Fetches run under the page policy
    (private hosts refused unless ``allow_private``) or an explicit
    ``policy``.
    """
    if fetch_text is None:
        if policy is not None:
            fetch_text = lambda url: _fetch_page_text(url, policy=policy)  # noqa: E731
        else:
            extra = {"allow_private": True} if allow_private else {}
            fetch_text = lambda url: _fetch_page_text(url, timeout=timeout, **extra)  # noqa: E731
    bundle = load_bundle(bundle_root)
    report = DriftReport()

    pages: dict[str, str | Exception] = {}
    for rel, concept in sorted(bundle.concepts.items()):
        url = concept.resource
        if not url or not concept.source_hash or not url.startswith(("http://", "https://")):
            report.skipped.append(rel)
            continue
        if concept.generated_by == FEED_ACTOR:
            report.feed_derived.append(rel)
            continue
        if url not in pages:
            try:
                pages[url] = fetch_text(url)
            except Exception as exc:  # noqa: BLE001 — any fetch failure is the same signal
                pages[url] = exc
        page = pages[url]
        if isinstance(page, Exception):
            report.unreachable.append((rel, f"{url}: {page}"))
        elif stable_page_hash(page) == concept.source_hash:
            report.unchanged.append(rel)
        else:
            report.drifted.append((rel, url))
    return report
