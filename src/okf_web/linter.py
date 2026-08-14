"""Conformance + profile linter for companion bundles.

Two layers of checks:

* **Spec conformance** (``E0xx``): the OKF v0.2 rules a bundle must meet —
  parseable frontmatter, a non-empty ``type``, a valid ``okf_version`` on
  the root index when present.
* **Profile rules** (``E01x``/``W0xx``): the ecommerce-geo publishing
  gates. The load-bearing one is E010: a high-risk concept (``x_geo.risk:
  a`` — prices, policies, safety claims) may not be ``stable`` until a
  ``human:`` actor appears in ``verified``. That is the machine-checkable
  form of "human in the loop".

Per the spec, *consumers* must tolerate missing optional fields, unknown
types, and broken links. This linter is a *producer* tool, so it warns
about those anyway — producers should ship clean bundles.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from .model import (
    Bundle,
    Concept,
    RISK_HIGH,
    TRUST_HUMAN,
    _as_date,
    load_bundle,
)

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    severity: str
    code: str
    rel_path: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():7s} {self.code} {self.rel_path}: {self.message}"


def lint_concept(concept: Concept, today: _dt.date | None = None) -> list[Finding]:
    findings: list[Finding] = []
    rel = concept.rel_path

    # -- spec conformance --------------------------------------------------
    if concept.type is None:
        findings.append(Finding(ERROR, "E002", rel, "frontmatter has no non-empty `type`"))
        return findings  # nothing profile-shaped to check without a type

    # -- profile: human-in-the-loop gate -----------------------------------
    if concept.risk == RISK_HIGH:
        if concept.status == "stable" and concept.trust_tier != TRUST_HUMAN:
            findings.append(
                Finding(
                    ERROR,
                    "E010",
                    rel,
                    "high-risk concept (x_geo.risk: a) is `stable` but has no "
                    "`human:` verifier; it must stay `draft` until a human "
                    "approves it",
                )
            )
        if not concept.sources:
            findings.append(
                Finding(
                    ERROR,
                    "E013",
                    rel,
                    "high-risk concept has no `sources`; every high-risk claim "
                    "needs attributable provenance",
                )
            )
        elif not concept.footnote_refs:
            findings.append(
                Finding(
                    WARNING,
                    "W024",
                    rel,
                    "high-risk concept body has no [^footnote] citations; "
                    "reviewers cannot check claims against sources",
                )
            )

    # -- profile: type-specific requirements -------------------------------
    if concept.type == "Attested Computation":
        if not concept.frontmatter.get("runtime"):
            findings.append(
                Finding(ERROR, "E011", rel, "Attested Computation requires `runtime`")
            )
        executor = concept.frontmatter.get("executor")
        if not (isinstance(executor, dict) and executor.get("resource")):
            findings.append(
                Finding(
                    WARNING,
                    "W026",
                    rel,
                    "Attested Computation has no executor.resource; agents "
                    "cannot run it",
                )
            )
    if concept.type == "Promotion":
        ends = concept.promo_ends
        if ends is None:
            if concept.status == "stable":
                findings.append(
                    Finding(
                        ERROR,
                        "E014",
                        rel,
                        "stable Promotion has no `x_geo.ends_at`; unbounded "
                        "promotions are exactly what engines misquote — add "
                        "the end date before publishing",
                    )
                )
            else:
                findings.append(
                    Finding(
                        WARNING,
                        "W027",
                        rel,
                        "Promotion draft has no `x_geo.ends_at`; a reviewer "
                        "must add the end date before it can go stable",
                    )
                )
        else:
            stale_date = _as_date(concept.frontmatter.get("stale_after"))
            if stale_date is None or stale_date > ends:
                findings.append(
                    Finding(
                        WARNING,
                        "W027",
                        rel,
                        "Promotion `stale_after` should equal `x_geo.ends_at` "
                        "so the freshness machinery retires it with the sale",
                    )
                )
            if (today or _dt.date.today()) > ends:
                findings.append(
                    Finding(
                        WARNING,
                        "W028",
                        rel,
                        f"promotion ended {ends.isoformat()}; the publisher "
                        "withholds it automatically, but retire or re-survey "
                        "the concept",
                    )
                )

    if concept.type == "Product" and not concept.resource:
        findings.append(
            Finding(
                ERROR,
                "E012",
                rel,
                "Product concept needs `resource` pointing at its canonical "
                "live URL (the page ↔ concept binding)",
            )
        )

    # -- citations ---------------------------------------------------------
    known = concept.source_ids | concept.footnote_defs
    for ref in sorted(concept.footnote_refs - known):
        findings.append(
            Finding(
                WARNING,
                "W020",
                rel,
                f"footnote [^{ref}] has no matching sources[].id or footnote "
                "definition",
            )
        )

    # -- freshness ---------------------------------------------------------
    if concept.is_stale(today):
        findings.append(
            Finding(
                WARNING,
                "W021",
                rel,
                f"stale: `stale_after` ({concept.frontmatter.get('stale_after')}) "
                "has passed; re-survey or re-verify",
            )
        )

    return findings


def lint_bundle(
    root: Path | str, today: _dt.date | None = None
) -> tuple[Bundle, list[Finding]]:
    bundle = load_bundle(root)
    findings: list[Finding] = []

    for rel, error in sorted(bundle.broken.items()):
        findings.append(Finding(ERROR, "E001", rel, f"unparseable frontmatter: {error}"))

    version = bundle.okf_version
    if version is not None and version != "0.2":
        findings.append(
            Finding(ERROR, "E003", "index.md", f"okf_version is {version!r}, expected '0.2'")
        )

    for concept in bundle.concepts.values():
        findings.extend(lint_concept(concept, today=today))

    # Broken bundle-internal links (concepts and indexes alike).
    known_paths = set(bundle.concepts) | set(bundle.indexes) | set(bundle.logs)
    for doc in bundle.all_documents():
        for target in doc.internal_links():
            resolved = bundle.resolve_link(doc.rel_path, target)
            if resolved.endswith(".md") and resolved not in known_paths:
                findings.append(
                    Finding(
                        WARNING,
                        "W022",
                        doc.rel_path,
                        f"link target not found in bundle: {target}",
                    )
                )

    findings.sort(key=lambda f: (f.severity != ERROR, f.rel_path, f.code))
    return bundle, findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)
