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
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import OKF_VERSION
from .model import (
    FRESHNESS_SLA_DAYS,
    Bundle,
    Concept,
    RISK_HIGH,
    TRUST_HUMAN,
    as_date,
    concept_content_hash,
    load_bundle,
    split_l10n,
    utc_today,
)

__all__ = [
    "TypeContract",
    "TYPE_CONTRACTS",
    "ERROR",
    "WARNING",
    "Finding",
    "lint_concept",
    "lint_bundle",
    "has_errors",
]

ERROR = "error"
WARNING = "warning"

# Types the profile's type table lists at risk `a`. Not high-risk *by
# definition* (that set is `model.Concept._HIGH_RISK_TYPES`), but a lower
# declared risk contradicts the table — and would unlock batch approval —
# so W034 surfaces the mismatch.
_RISK_FLOOR_TYPES = ("Policy", "Promotion", "Store Identity")


def _valid_usage_window(value) -> bool:
    return (
        isinstance(value, dict)
        and as_date(value.get("from")) is not None
        and as_date(value.get("to")) is not None
    )


def _site_host(bundle: Bundle) -> str:
    """Hostname of the bundle's declared site (`index.md` x_geo.site),
    lowercased; empty when no site is declared (nothing to judge
    endpoint locality against)."""
    site = bundle.site
    if not site:
        return ""
    return (urllib.parse.urlsplit(site).hostname or "").lower()


@dataclass
class Finding:
    severity: str
    code: str
    rel_path: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():7s} {self.code} {self.rel_path}: {self.message}"


@dataclass(frozen=True)
class TypeContract:
    """What a concept type must carry before it goes stable, and the risk
    tier the profile floors it at (GEO-PROFILE's type table): one row per
    type in :data:`TYPE_CONTRACTS`, read by :func:`lint_concept` (review
    2026-10-21, A-U4). ``required`` pairs a label with a predicate; the
    missing labels feed the messages. ``risk_floor`` is ``a`` (anything
    below is flagged) or ``b`` (only ``c`` is)."""

    error_code: str
    required: tuple[tuple[str, Callable[[Concept], bool]], ...]
    stable_message: Callable[[list[str]], str]
    draft_message: Callable[[list[str]], str]
    risk_floor: str
    risk_message: Callable[[Concept], str]


def _missing_stable(type_name: str) -> Callable[[list[str]], str]:
    return lambda missing: f"stable {type_name} is missing " + ", ".join(missing)


def _missing_draft(type_name: str) -> Callable[[list[str]], str]:
    return lambda missing: (
        f"{type_name} draft is missing " + ", ".join(missing)
        + "; a reviewer must complete it before it can go stable"
    )


#: The profile's contract types. A new type that must carry something
#: before it goes stable is a row here (the EXPANSION playbook), never a
#: new block in `lint_concept`.
TYPE_CONTRACTS: dict[str, TypeContract] = {
    "Compatibility": TypeContract(
        # The machine-resolvable applicability is the type's whole point:
        # a fit chart that names no entities cannot be targeted by an
        # agent asking "will this fit mine?".
        error_code="E015",
        required=(("`x_geo.fits` and/or `x_geo.works_with`", lambda c: bool(c.fits or c.works_with)),),
        stable_message=lambda missing: (
            "stable Compatibility concept references no entities — "
            "set `x_geo.fits` and/or `x_geo.works_with`"
        ),
        draft_message=lambda missing: (
            "Compatibility draft references no entities yet; a "
            "reviewer must add `x_geo.fits`/`works_with` before "
            "it can go stable"
        ),
        risk_floor="b",
        risk_message=lambda c: (
            "Compatibility concept classified risk `c`; wrong fit "
            "claims drive returns — classify `b` (or `a` for "
            "safety-relevant fitment)"
        ),
    ),
    "Ownership Guide": TypeContract(
        # Same applicability contract as Compatibility: ownership
        # guidance an agent cannot attach to an owned product is
        # unreachable exactly when the owner asks about it.
        error_code="E016",
        required=(("`x_geo.covers`", lambda c: bool(c.covers)),),
        stable_message=lambda missing: (
            "stable Ownership Guide covers no entities — set "
            "`x_geo.covers` to the product(s) it is guidance for"
        ),
        draft_message=lambda missing: (
            "Ownership Guide draft covers no entities yet; a "
            "reviewer must add `x_geo.covers` before it can go "
            "stable"
        ),
        risk_floor="b",
        risk_message=lambda c: (
            "Ownership Guide classified risk `c`; wrong care or "
            "warranty-process claims damage products and void "
            "warranties — classify `b` (or `a` when care is "
            "safety-relevant)"
        ),
    ),
    "Product Passport": TypeContract(
        # The contract: one product bound by passport_for, and passport
        # data that actually says something — materials and origin at
        # minimum. A vacuous passport is worse than none: it signals
        # compliance without carrying it.
        error_code="E017",
        required=(
            ("`x_geo.passport_for`", lambda c: bool(c.passport_for)),
            ("`x_geo.passport.materials`", lambda c: bool(c.passport.get("materials"))),
            ("`x_geo.passport.origin`", lambda c: bool(c.passport.get("origin"))),
        ),
        stable_message=_missing_stable("Product Passport"),
        draft_message=_missing_draft("Product Passport"),
        risk_floor=RISK_HIGH,
        risk_message=lambda c: (
            f"Product Passport declares risk `{c.risk}`, but "
            "passports are compliance claims and are gated as risk "
            "`a` regardless — declare `a` explicitly"
        ),
    ),
    "Store Location": TypeContract(
        # The contract: an entity id other concepts and stock
        # capabilities can reference, and a real-world address — a
        # location an agent cannot name or place answers nothing.
        error_code="E018",
        required=(
            ("`x_geo.entity` (a stable `loc:` id)", lambda c: bool(c.entity)),
            ("`x_geo.location.address`", lambda c: bool(c.location.get("address"))),
        ),
        stable_message=_missing_stable("Store Location"),
        draft_message=_missing_draft("Store Location"),
        risk_floor="b",
        risk_message=lambda c: (
            "Store Location classified risk `c`; a wrong address or "
            "wrong hours sends someone to a closed door — classify `b`"
        ),
    ),
    "Trade Program": TypeContract(
        # The contract: machine-readable commercial terms. A trade
        # program that states no terms invites the exact guessing
        # (payment terms, minimums) that costs B2B deals.
        error_code="E019",
        required=(
            ("`x_geo.trade.payment_terms`", lambda c: bool(c.trade.get("payment_terms"))),
            ("`x_geo.trade.min_order`", lambda c: bool(c.trade.get("min_order"))),
        ),
        stable_message=_missing_stable("Trade Program"),
        draft_message=_missing_draft("Trade Program"),
        risk_floor=RISK_HIGH,
        risk_message=lambda c: (
            f"Trade Program declares risk `{c.risk}`, but "
            "commercial terms are money/legal claims and are gated "
            "as risk `a` regardless — declare `a` explicitly"
        ),
    ),
}


def _lint_contract(concept: Concept, contract: TypeContract) -> list[Finding]:
    """One contract type's findings: the stable-time error, or the
    draft-time W032, for what is missing; then the W033 risk floor."""
    rel = concept.rel_path
    findings: list[Finding] = []
    missing = [label for label, present in contract.required if not present(concept)]
    if missing:
        if concept.status == "stable":
            findings.append(Finding(ERROR, contract.error_code, rel, contract.stable_message(missing)))
        else:
            findings.append(Finding(WARNING, "W032", rel, contract.draft_message(missing)))
    if contract.risk_floor == RISK_HIGH:
        below_floor = concept.risk != RISK_HIGH
    else:
        below_floor = concept.risk == "c"
    if below_floor:
        findings.append(Finding(WARNING, "W033", rel, contract.risk_message(concept)))
    return findings


def _lint_attested_computation(concept: Concept) -> list[Finding]:
    """An Attested Computation's own rules: a runtime, an attester that
    is code, an executor whose placeholders stay out of the authority."""
    rel = concept.rel_path
    findings: list[Finding] = []
    if not concept.frontmatter.get("runtime"):
        findings.append(
            Finding(ERROR, "E011", rel, "Attested Computation requires `runtime`")
        )
    attester = concept.frontmatter.get("attester")
    if isinstance(attester, dict) and str(
        attester.get("resource") or ""
    ).startswith(("http://", "https://")):
        findings.append(
            Finding(
                WARNING,
                "W036",
                rel,
                "`attester.resource` names an endpoint, not deterministic "
                "verifier code — point it at a bundle artifact "
                "(e.g. `/attesters/http_refetch.py`), per SPEC §10.2",
            )
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
    elif isinstance(executor.get("resource"), str):
        authority = urllib.parse.urlsplit(executor["resource"])
        if "{" in authority.scheme or "{" in authority.netloc:
            findings.append(
                Finding(
                    ERROR,
                    "E023",
                    rel,
                    "executor.resource puts a placeholder in its scheme or "
                    "host; a caller could then choose the target, so "
                    "placeholders belong in the path or query only (the "
                    "bridge refuses such a template)",
                )
            )
    return findings


def _lint_promotion(concept: Concept, today: _dt.date | None) -> list[Finding]:
    """A Promotion's own rules: an end date, a `stale_after` that
    retires it with the sale, and the sale not already over."""
    rel = concept.rel_path
    findings: list[Finding] = []
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
        # The sale is valid through `ends_at`, so `stale_after` may
        # fall anywhere up to the midnight that ends that day (the
        # surveyor stamps exactly that); later outlives the sale.
        stale_date = as_date(concept.frontmatter.get("stale_after"))
        if stale_date is None or stale_date > ends + _dt.timedelta(days=1):
            findings.append(
                Finding(
                    WARNING,
                    "W027",
                    rel,
                    "Promotion `stale_after` should be the midnight after "
                    "`x_geo.ends_at` (or earlier) so the freshness machinery "
                    "retires it with the sale",
                )
            )
        if (today or utc_today()) > ends:
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
    return findings


def lint_concept(concept: Concept, today: _dt.date | None = None) -> list[Finding]:
    findings: list[Finding] = []
    rel = concept.rel_path

    # -- spec conformance --------------------------------------------------
    if concept.type is None:
        findings.append(Finding(ERROR, "E002", rel, "frontmatter has no non-empty `type`"))
        return findings  # nothing profile-shaped to check without a type

    raw_status = concept.frontmatter.get("status")
    if raw_status is not None and str(raw_status) not in ("draft", "stable", "deprecated"):
        findings.append(
            Finding(
                ERROR,
                "E021",
                rel,
                f"`status` must be one of draft, stable, deprecated; got "
                f"{raw_status!r} (a misspelling is withheld from publishing "
                "and, on a high-risk concept, dodges the human-review gate)",
            )
        )

    # The scorecard is the evaluator's own record: the report, the viewer
    # and `okf_info` read it only at evaluations/geo-scorecard.md, and a
    # draft typed `GEO Scorecard` anywhere else is a producer's text
    # wearing the measurement's name (review 2026-10-21, S-U1).
    if concept.type == "GEO Scorecard" and (
        not rel.startswith("evaluations/") or concept.status == "draft"
    ):
        findings.append(
            Finding(
                ERROR,
                "E022",
                rel,
                "a GEO Scorecard is the evaluator's own record: it lives under "
                "evaluations/ and is never a draft (the report, the viewer and "
                "okf_info read only evaluations/geo-scorecard.md; a produced "
                "one is not a measurement)",
            )
        )

    # -- profile: human-in-the-loop gate -----------------------------------
    # Keyed on the *effective* classification: declared risk `a`, plus
    # types that are high-risk by definition (Product Passports carry
    # compliance claims regardless of what their frontmatter declares).
    if concept.is_high_risk:
        if concept.status == "stable" and concept.trust_tier != TRUST_HUMAN:
            findings.append(
                Finding(
                    ERROR,
                    "E010",
                    rel,
                    "high-risk concept is `stable` but has no "
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

    # -- spec: source credibility signal shapes (SPEC §5.1) ----------------
    # The signals are optional; when present they must be machine-usable,
    # or consumers inferring trust from them will choke on the very
    # bundles that tried hardest to earn it.
    for entry in concept.sources:
        label = str(entry.get("id") or entry.get("resource") or "?")
        count = entry.get("usage_count")
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 0
        ):
            findings.append(
                Finding(
                    WARNING,
                    "W035",
                    rel,
                    f"source `{label}`: `usage_count` must be a non-negative "
                    f"integer, got {count!r}",
                )
            )
        last_modified = entry.get("last_modified")
        if last_modified is not None and as_date(last_modified) is None:
            findings.append(
                Finding(
                    WARNING,
                    "W035",
                    rel,
                    f"source `{label}`: `last_modified` is not a date: "
                    f"{last_modified!r}",
                )
            )
        window = entry.get("usage_window")
        if window is not None and not _valid_usage_window(window):
            findings.append(
                Finding(
                    WARNING,
                    "W035",
                    rel,
                    f"source `{label}`: `usage_window` must be a mapping with "
                    "`from` and `to` dates",
                )
            )
    window = concept.frontmatter.get("usage_window")
    if window is not None and not _valid_usage_window(window):
        findings.append(
            Finding(
                WARNING,
                "W035",
                rel,
                "`usage_window` must be a mapping with `from` and `to` dates",
            )
        )

    # -- profile: risk floor -----------------------------------------------
    if concept.type in _RISK_FLOOR_TYPES and concept.risk != RISK_HIGH:
        findings.append(
            Finding(
                WARNING,
                "W034",
                rel,
                f"`{concept.type}` declares risk `{concept.risk}`; the profile "
                "type table floors this type at `a` — a lower declared risk "
                "would unlock batch approval",
            )
        )

    # -- profile: type-specific requirements -------------------------------
    if concept.type == "Attested Computation":
        findings.extend(_lint_attested_computation(concept))
    if concept.type == "Promotion":
        findings.extend(_lint_promotion(concept, today))
    contract = TYPE_CONTRACTS.get(concept.type)
    if contract is not None:
        findings.extend(_lint_contract(concept, contract))

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
    if concept.resource and not str(concept.resource).startswith(("http://", "https://")):
        findings.append(
            Finding(
                ERROR,
                "E020",
                rel,
                f"`resource` must be an http(s) URL, got {concept.resource!r}: a "
                "non-web scheme is never a page ↔ concept binding, and the "
                "viewer, linkmap.json and the JSON-LD `url` will not link it",
            )
        )
    for index, source in enumerate(concept.sources):
        if not isinstance(source, dict):
            continue
        source_url = source.get("resource")
        if source_url and not str(source_url).startswith(("http://", "https://")):
            label = source.get("id") or f"#{index}"
            findings.append(
                Finding(
                    WARNING,
                    "W038",
                    rel,
                    f"source `{label}`: `resource` is not an http(s) URL "
                    f"({source_url!r}); a citation nobody can follow",
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
    if (
        concept.status == "stable"
        and concept.frontmatter.get("stale_after") is None
        and concept.type in FRESHNESS_SLA_DAYS
    ):
        findings.append(
            Finding(
                WARNING,
                "W041",
                rel,
                "stable concept has no `stale_after`: nothing will ever ask for "
                f"it to be re-checked (the profile's default for {concept.type} "
                f"is {FRESHNESS_SLA_DAYS[concept.type]} days; `okf-web review "
                "approve --stale-after YYYY-MM-DD` sets one)",
            )
        )

    return findings


def lint_bundle(
    root: Path | str, today: _dt.date | None = None, strict_okf: bool = False
) -> tuple[Bundle, list[Finding]]:
    bundle = load_bundle(root)
    findings: list[Finding] = []

    for rel, error in sorted(bundle.broken.items()):
        findings.append(Finding(ERROR, "E001", rel, f"unparseable frontmatter: {error}"))

    version = bundle.okf_version
    if version is not None and version != OKF_VERSION:
        findings.append(
            Finding(ERROR, "E003", "index.md", f"okf_version is {version!r}, expected '0.2'")
        )

    for concept in bundle.concepts.values():
        findings.extend(lint_concept(concept, today=today))

    # Entity references must resolve: an agent follows `fits: [sku:X]`
    # (or `works_with`/`covers`) by looking up the concept whose
    # x_geo.entity is sku:X — a dangling reference is guidance no
    # engine can attach to a product.
    entities = bundle.entities()
    for rel, concept in sorted(bundle.concepts.items()):
        if split_l10n(rel) is not None:
            continue
        for ref in concept.entity_refs:
            if ref not in entities:
                findings.append(
                    Finding(
                        WARNING,
                        "W032",
                        rel,
                        f"entity reference {ref!r} does not resolve to any "
                        "concept's `x_geo.entity` in this bundle",
                    )
                )

    # Reviewer identity (GAPS item 5): when the root index names who may
    # approve, a human actor outside that list is worth a look — the
    # stamp stays (history is history), the warning says whose it is.
    reviewers = bundle.reviewers
    if reviewers is not None:
        for rel, concept in sorted(bundle.concepts.items()):
            for entry in concept.verified_entries:
                actor = str(entry.get("by", ""))
                prefix, _, ident = actor.partition(":")
                if prefix in ("human", "human-batch") and ident not in reviewers:
                    findings.append(
                        Finding(
                            WARNING,
                            "W042",
                            rel,
                            f"verified by `{actor}`, who is not in index.md's "
                            "`x_geo.reviewers`",
                        )
                    )

    # The declared language (profile 1.12): retrieval, question generation
    # and the derived tier read it, so a tag nothing can parse is worth a
    # warning — the bundle then behaves as undeclared.
    declared = bundle.declared_language
    if declared is not None and not bundle.language:
        findings.append(
            Finding(
                WARNING,
                "W043",
                "index.md",
                f"x_geo.language {declared!r} is not a language tag (want a "
                "BCP-47 tag like `en` or `pt-BR`)",
            )
        )

    # Translation parity: l10n/<lang>/<rel> mirrors <rel>. A translation
    # is knowledge too — but one whose source moved on is worse than
    # none, because it contradicts the default language with equal
    # confidence.
    for rel, concept in sorted(bundle.concepts.items()):
        parsed = split_l10n(rel)
        if parsed is None:
            continue
        _, source_rel = parsed
        source = bundle.concepts.get(source_rel)
        if source is None:
            findings.append(
                Finding(
                    WARNING,
                    "W030",
                    rel,
                    f"translation has no source concept at {source_rel}",
                )
            )
            continue
        pinned = concept.x_geo.get("l10n_source_hash")
        if not pinned:
            findings.append(
                Finding(
                    WARNING,
                    "W031",
                    rel,
                    "translation is not pinned to its source — set "
                    "x_geo.l10n_source_hash to the source concept's content hash",
                )
            )
        elif str(pinned) != concept_content_hash(source):
            findings.append(
                Finding(
                    WARNING,
                    "W031",
                    rel,
                    f"translation is out of date: {source_rel} changed since "
                    "it was translated — re-translate and re-pin",
                )
            )

    # Attester artifacts: a bundle-relative attester must actually ship.
    for rel, concept in sorted(bundle.concepts.items()):
        if concept.type != "Attested Computation":
            continue
        attester = concept.frontmatter.get("attester")
        resource = (
            str(attester.get("resource") or "") if isinstance(attester, dict) else ""
        )
        if resource.startswith("/") and not (bundle.root / resource.lstrip("/")).exists():
            findings.append(
                Finding(
                    WARNING,
                    "W036",
                    rel,
                    f"attester artifact not found in bundle: {resource}",
                )
            )

    if strict_okf:
        # Base-spec deviations the profile makes deliberately (documented
        # in GEO-PROFILE §7): report, so an operator targeting strict OKF
        # consumers can see exactly where this bundle exceeds SPEC §8.
        root_index = bundle.indexes.get("index.md")
        extra = (
            sorted(set(root_index.frontmatter) - {"okf_version"})
            if root_index is not None
            else []
        )
        if extra:
            findings.append(
                Finding(
                    WARNING,
                    "W040",
                    "index.md",
                    "base-spec deviation (SPEC §8): root index frontmatter "
                    "carries keys beyond `okf_version`: " + ", ".join(extra)
                    + " — manifest.json `site` is the normative copy of the "
                    "binding for consumers",
                )
            )
        for rel, doc in sorted(bundle.indexes.items()):
            if rel != "index.md" and doc.frontmatter:
                findings.append(
                    Finding(
                        WARNING,
                        "W040",
                        rel,
                        "base-spec deviation (SPEC §8): non-root index carries "
                        "frontmatter",
                    )
                )

    # Capability endpoints are expected on the store's own domain: an
    # executor pointing elsewhere is either a delegation worth a human
    # glance or bait aimed at whoever executes the bundle's capabilities
    # (READINESS A4). Warn, don't error — legitimate delegations exist
    # (a payments processor's status endpoint) but must be conspicuous.
    site_host = _site_host(bundle)
    if site_host:
        base_host = site_host.removeprefix("www.")
        for rel, concept in sorted(bundle.concepts.items()):
            if concept.type != "Attested Computation":
                continue
            executor = concept.frontmatter.get("executor")
            resource = executor.get("resource") if isinstance(executor, dict) else None
            if not isinstance(resource, str) or not resource.startswith(
                ("http://", "https://")
            ):
                continue
            host = (urllib.parse.urlsplit(resource).hostname or "").lower()
            if host and host != site_host and host != base_host and not host.endswith(
                "." + base_host
            ):
                findings.append(
                    Finding(
                        WARNING,
                        "W037",
                        rel,
                        f"capability endpoint host `{host}` is outside the "
                        f"declared site's domain (`{site_host}`); verify the "
                        "delegation is intentional before publishing",
                    )
                )

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
