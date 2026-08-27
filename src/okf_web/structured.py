"""Derived structured data: emit what engines read *today*.

The bundle is the source of truth — human-verified, provenance-tracked,
citable. This module derives the formats today's engines demonstrably
consume from it at publish time, so a merchant gets value from day one
even if no engine ever fetches ``/.well-known/okf/`` (READINESS R2):

* **JSON-LD** (schema.org), one file per eligible concept under
  ``dist/jsonld/``, mirroring the bundle's paths. Only concepts a
  **named human** vouched for are restated — per-item review
  (``human:``) or wholesale attestation (``human-batch:``, READINESS
  R3) — so the downgrade cannot launder unverified or merely
  machine-checked text into the merchant's own markup, while
  feed-derived catalogs a person took responsibility for still emit.
  Every object carries ``subjectOf`` pointing back at its bundle
  concept, where the exact attestation is readable, one hop away.
* **llms.txt**, a complete file for sites that do not have one. Its
  links point into the published bundle (concept files are markdown —
  exactly what llms.txt consumers want). Links are navigation, not
  restatement, so they cover the whole published set; the
  human-verified gate applies to restated content (JSON-LD), not to
  pointers. ``llms-snippet.txt`` remains for sites that already have
  an llms.txt to paste into.

The live-values rule survives the downgrade: Product JSON-LD carries
identity (name, brand, GTIN/MPN/SKU, canonical URL) and **no price or
availability** — schema.org permits a Product without offers, and an
invented or stale price would be exactly the failure OKF-Web exists to
prevent. Live values stay where they are executable: the bundle's
capability concepts, reachable via ``subjectOf``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .model import Bundle, Concept, TRUST_HUMAN, TRUST_HUMAN_BATCH, split_l10n

_CONTEXT = "https://schema.org"

# How many individual products llms.txt lists before pointing at the
# manifest instead — a 5,000-SKU catalog must not become a 5,000-line
# llms.txt (collections and the manifest carry the tail).
LLMS_PRODUCT_CAP = 50

_FOOTNOTE_DEF_RE = re.compile(r"^\[\^[^\]]+\]:.*$", re.MULTILINE)
_FOOTNOTE_REF_RE = re.compile(r"\[\^[^\]]+\]")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_EMPHASIS_RE = re.compile(r"[*_`]{1,3}")


def _plain(text: str) -> str:
    """Markdown → display text: drop footnote apparatus, unwrap links,
    strip emphasis markers, collapse whitespace."""
    text = _FOOTNOTE_DEF_RE.sub("", text)
    text = _FOOTNOTE_REF_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _EMPHASIS_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _sections(body: str) -> list[tuple[str, str]]:
    """Split a concept body into (heading, plain text) pairs."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = (match.group(1).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return [
        (heading, _plain("\n".join(lines)))
        for heading, lines in sections
        if _plain("\n".join(lines))
    ]


def _subject_of(rel: str, base: str) -> dict:
    return {
        "@type": "CreativeWork",
        "url": f"{base}/{rel}",
        "encodingFormat": "text/markdown",
    }


def _product(concept: Concept, base: str) -> dict:
    obj: dict = {
        "@context": _CONTEXT,
        "@type": "Product",
        "name": concept.title,
        "description": _plain(str(concept.frontmatter.get("description") or "")),
    }
    if concept.resource:
        obj["url"] = concept.resource
    brand = concept.x_geo.get("brand")
    if brand:
        obj["brand"] = {"@type": "Brand", "name": str(brand)}
    entity = str(concept.x_geo.get("entity") or "")
    for prefix, prop in (("gtin:", "gtin"), ("mpn:", "mpn"), ("sku:", "sku")):
        if entity.startswith(prefix):
            obj[prop] = entity[len(prefix):]
            break
    # Deliberately no `offers`: price and availability are live values.
    # The capability that serves them is in the bundle concept behind
    # `subjectOf` (x_geo.live_price / live_stock).
    obj["subjectOf"] = _subject_of(concept.rel_path, base)
    return obj


def _faq(concept: Concept, base: str) -> dict | None:
    questions = [
        {
            "@type": "Question",
            "name": heading,
            "acceptedAnswer": {"@type": "Answer", "text": text},
        }
        for heading, text in _sections(concept.body)
    ]
    if not questions:
        return None
    obj: dict = {
        "@context": _CONTEXT,
        "@type": "FAQPage",
        "name": concept.title,
        "mainEntity": questions,
    }
    if concept.resource:
        obj["url"] = concept.resource
    obj["subjectOf"] = _subject_of(concept.rel_path, base)
    return obj


def _organization(concept: Concept, base: str, site: str | None) -> dict:
    obj: dict = {
        "@context": _CONTEXT,
        "@type": "Organization",
        "name": concept.title,
        "description": _plain(str(concept.frontmatter.get("description") or "")),
    }
    if site:
        obj["url"] = site
    elif concept.resource:
        obj["url"] = concept.resource
    obj["subjectOf"] = _subject_of(concept.rel_path, base)
    return obj


# x_geo.location.hours keys → schema.org openingHours day tokens.
_DAY_TOKENS = {
    "mon": "Mo", "tue": "Tu", "wed": "We", "thu": "Th",
    "fri": "Fr", "sat": "Sa", "sun": "Su",
}


def _opening_hours(hours: dict) -> list[str]:
    out = []
    for key, window in hours.items():
        parts = str(key).lower().split("-")
        tokens = [_DAY_TOKENS.get(p) for p in parts]
        if any(t is None for t in tokens):
            continue
        days = "-".join(tokens) if len(tokens) > 1 else tokens[0]
        out.append(f"{days} {window}")
    return out


def _local_business(concept: Concept, base: str) -> dict:
    obj: dict = {
        "@context": _CONTEXT,
        "@type": "LocalBusiness",
        "name": concept.title,
        "description": _plain(str(concept.frontmatter.get("description") or "")),
    }
    if concept.resource:
        obj["url"] = concept.resource
    location = concept.x_geo.get("location")
    if isinstance(location, dict):
        address = location.get("address")
        if address:
            obj["address"] = {"@type": "PostalAddress", "streetAddress": str(address)}
        phone = location.get("phone")
        if phone:
            obj["telephone"] = str(phone)
        hours = location.get("hours")
        if isinstance(hours, dict):
            opening = _opening_hours(hours)
            if opening:
                obj["openingHours"] = opening
    obj["subjectOf"] = _subject_of(concept.rel_path, base)
    return obj


def _return_policy(concept: Concept, base: str) -> dict:
    # The profile keeps policy terms as verified prose, not structured
    # fields, so this stays minimal-but-valid: universal properties
    # only. Engines wanting the terms follow url/subjectOf.
    obj: dict = {
        "@context": _CONTEXT,
        "@type": "MerchantReturnPolicy",
        "name": concept.title,
        "description": _plain(str(concept.frontmatter.get("description") or "")),
    }
    if concept.resource:
        obj["url"] = concept.resource
    obj["subjectOf"] = _subject_of(concept.rel_path, base)
    return obj


def _is_return_policy(concept: Concept) -> bool:
    haystack = concept.rel_path.lower() + " " + " ".join(
        str(t).lower() for t in (concept.frontmatter.get("tags") or [])
    )
    return "return" in haystack


def jsonld_for(concept: Concept, base: str, site: str | None = None) -> dict | None:
    """The schema.org object for one concept, or None when the type has
    no faithful mapping (better no markup than invented markup)."""
    if concept.type == "Product":
        return _product(concept, base)
    if concept.type == "FAQ":
        return _faq(concept, base)
    if concept.type == "Store Identity":
        return _organization(concept, base, site)
    if concept.type == "Store Location":
        return _local_business(concept, base)
    if concept.type == "Policy" and _is_return_policy(concept):
        return _return_policy(concept, base)
    return None


def write_structured(
    dist: Path,
    bundle: Bundle,
    published: set[str],
    base: str,
    site: str | None = None,
) -> list[str]:
    """Write ``dist/jsonld/<rel>.json`` for every eligible concept;
    returns the rel paths written (for the manifest)."""
    written: list[str] = []
    for rel in sorted(published):
        concept = bundle.concepts.get(rel)
        if concept is None or split_l10n(rel) is not None:
            continue
        if concept.trust_tier not in (TRUST_HUMAN, TRUST_HUMAN_BATCH):
            continue
        obj = jsonld_for(concept, base, site)
        if obj is None:
            continue
        out_rel = "jsonld/" + rel[:-3] + ".json" if rel.endswith(".md") else f"jsonld/{rel}.json"
        target = dist / out_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(out_rel)
    return written


# llms.txt section order: what a consuming agent most wants first.
_LLMS_SECTIONS = (
    ("Policies", ("Policy",)),
    ("FAQ", ("FAQ",)),
    ("Store", ("Store Identity", "Store Location")),
    ("Guides and compatibility", ("Guide", "Compatibility", "Ownership")),
    ("Catalog", ("Product Collection",)),
    ("Products", ("Product",)),
    ("Live values (executable)", ("Attested Computation",)),
    ("Trade", ("Trade Program",)),
    ("Compliance", ("Product Passport",)),
    ("Promotions", ("Promotion",)),
)


def write_llms_txt(
    dist: Path,
    bundle: Bundle,
    published: set[str],
    base: str,
) -> str:
    """Write a complete ``llms.txt`` whose links point into the
    published bundle; returns its rel path."""
    dist.mkdir(parents=True, exist_ok=True)
    identity = next(
        (
            bundle.concepts[rel]
            for rel in sorted(published)
            if bundle.concepts[rel].type == "Store Identity"
        ),
        None,
    )
    by_type: dict[str, list[Concept]] = {}
    covered: set[str] = set()
    for rel in sorted(published):
        if split_l10n(rel) is not None:
            continue
        concept = bundle.concepts[rel]
        by_type.setdefault(concept.type or "", []).append(concept)

    lines = [f"# {identity.title if identity else 'Store knowledge'}"]
    summary = (
        _plain(str(identity.frontmatter.get("description")))
        if identity is not None
        else "Curated, provenance-tracked store knowledge in Open Knowledge Format."
    )
    lines += ["", f"> {summary}", ""]
    lines.append(
        "Facts below are provenance-tracked OKF concepts (markdown with "
        "YAML frontmatter): who wrote each one, who verified it, and when "
        "it goes stale. Live values (price, stock) are deliberately not "
        "stated — execute the capability concepts instead."
    )

    def _entry(concept: Concept) -> str:
        desc = _plain(str(concept.frontmatter.get("description") or ""))
        suffix = f": {desc}" if desc else ""
        return f"- [{concept.title}]({base}/{concept.rel_path}){suffix}"

    for section, types in _LLMS_SECTIONS:
        concepts = [c for t in types for c in by_type.get(t, [])]
        for t in types:
            covered.add(t)
        if not concepts:
            continue
        lines += ["", f"## {section}", ""]
        if section == "Products" and len(concepts) > LLMS_PRODUCT_CAP:
            shown = concepts[:LLMS_PRODUCT_CAP]
            lines += [_entry(c) for c in shown]
            lines.append(
                f"- …and {len(concepts) - len(shown)} more products — "
                f"see [manifest.json]({base}/manifest.json) for the full "
                "file list with hashes."
            )
        else:
            lines += [_entry(c) for c in concepts]

    leftovers = [
        c
        for t, cs in sorted(by_type.items())
        if t not in covered and t != "GEO Scorecard"
        for c in cs
    ]
    if leftovers:
        lines += ["", "## More", ""] + [_entry(c) for c in leftovers]

    lines += [
        "",
        "## Optional",
        "",
        f"- [Bundle index]({base}/index.md): start here for the full tree.",
        f"- [manifest.json]({base}/manifest.json): per-file sha256 for "
        "freshness checks and delta sync.",
        f"- [linkmap.json]({base}/linkmap.json): live page URL → concept "
        "mapping.",
    ]
    (dist / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "llms.txt"
