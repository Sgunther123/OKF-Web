"""Feed-file catalog ingestion: draft Product concepts from a product
feed, no LLM required.

Most platforms export a product feed (Google Merchant TSV/XML, plain
CSV) that already carries structured facts — title, description,
brand, GTIN, category, canonical link. Paying LLM tokens to
re-extract structure the merchant already has would be waste, so this
path is **deterministic and free**: each feed row becomes a draft
`Product` concept mechanically. It is the connector-neutral answer to
"can it read my catalog directly?" — export the feed, run
``okf-web survey my-bundle --feed products.csv``; live platform
connectors that sync continuously remain a hosted capability.

The pipeline's rules apply unchanged:

* **Live values are dropped.** Feeds carry ``price``, ``sale_price``,
  ``availability``, ``shipping`` — exactly the volatile facts the
  profile forbids as static claims. The ingester never copies them;
  the generated body points at capability concepts instead.
* **Same write gate as the LLM surveyor** (:func:`surveyor.place_draft`):
  path stability, collision safety, drift proposals protecting
  human-approved concepts.
* **Same incrementality**: the row's stable text is hashed into
  ``x_geo.source_hash``, so unchanged rows cost nothing on re-ingest.
* **Same review flow**: everything lands as an unverified draft
  (``generated.by: process:okf-web-feed-ingest``) for humans (or
  ``review batch-approve``) to promote.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import PROFILE
from .linter import ERROR, lint_concept
from .model import Concept, load_bundle, utc_instant
from .surveyor import SurveyResult, place_draft, stable_page_hash

FEED_ACTOR = "process:okf-web-feed-ingest"

# Columns a delimited feed must carry for a row to become a concept.
REQUIRED_COLUMNS = ("title", "link")


class FeedError(ValueError):
    """The feed file as a whole cannot be used, with the reason in plain
    words (EDGE-CASES U6)."""

# Volatile transactional fields a feed carries that must never become
# static claims (the live-values rule). Everything else is fair game.
DROPPED_FIELDS = {
    "price", "sale_price", "sale_price_effective_date", "availability",
    "availability_date", "shipping", "shipping_weight", "tax",
    "quantity", "inventory",
    # Money-bearing Merchant fields beyond the obvious ones: COGS is
    # merchant-private margin data, and the rest are price claims in
    # disguise. None of them may reach a published body.
    "cost_of_goods_sold", "installment", "subscription_cost",
    "loyalty_points", "auto_pricing_min_price",
}

# Deny-by-category backstop for columns the explicit list does not name:
# a key carrying one of these tokens is a live value or money figure.
# Matching is on `_`-split tokens, not substrings, so
# `google_product_taxonomy` (token `taxonomy`) survives while
# `wholesale_price_usd` (token `price`) is dropped — and logged, since a
# backstop catch deserves a human glance.
_LIVE_VALUE_TOKENS = {
    "price", "prices", "pricing", "cost", "costs", "tax", "taxes", "vat",
    "inventory", "quantity", "qty", "stock", "availability", "loyalty",
    "installment", "installments", "subscription",
}


def _is_live_value_key(key: str) -> bool:
    return key in DROPPED_FIELDS or bool(_LIVE_VALUE_TOKENS & set(key.split("_")))

_G_NS = "{http://base.google.com/ns/1.0}"


@dataclass
class FeedItem:
    id: str = ""
    title: str = ""
    description: str = ""
    link: str = ""
    brand: str = ""
    gtin: str = ""
    mpn: str = ""
    product_type: str = ""
    item_group_id: str = ""
    extras: dict = field(default_factory=dict)
    dropped: tuple = ()


_KNOWN = {"id", "title", "description", "link", "brand", "gtin", "mpn",
          "product_type", "item_group_id"}


def _clean_key(key: str) -> str:
    return key.strip().lower().removeprefix("g:")


def parse_feed(path: Path | str) -> list[FeedItem]:
    """Parse a Google Merchant XML feed or a CSV/TSV feed into items.

    Reads ``utf-8-sig`` so an Excel-style byte-order mark never becomes
    part of the first column's name; an empty feed, a feed without the
    required columns or an XML feed without ``<item>`` entries raise
    :class:`FeedError` once, up front, instead of one error per row."""
    path = Path(path)
    if not path.is_file():
        raise FeedError(f"feed file not found: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        raise FeedError(f"feed is empty: {path}")
    if text.lstrip().startswith("<"):
        items = _parse_merchant_xml(text)
        if not items:
            raise FeedError(f"no <item> entries found in {path}")
        return items
    return _parse_delimited(text)


def _parse_merchant_xml(text: str) -> list[FeedItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedError(f"feed XML does not parse: {exc}") from exc
    items: list[FeedItem] = []
    for node in root.iter("item"):
        fields: dict[str, str] = {}
        for child in node:
            tag = child.tag.replace(_G_NS, "")
            if child.text and child.text.strip():
                fields[_clean_key(tag)] = child.text.strip()
        items.append(_item_from(fields))
    return items


def _parse_delimited(text: str) -> list[FeedItem]:
    # The header line decides the delimiter: a TSV whose descriptions
    # carry commas is still a TSV.
    header = text.lstrip("\ufeff").splitlines()[0]
    delimiter = "\t" if header.count("\t") > header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = [_clean_key(name) for name in (reader.fieldnames or []) if name is not None]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise FeedError(
            f"column {missing[0]!r} not found in the feed header "
            f"(have: {', '.join(columns) or 'nothing'}); a Google Merchant "
            "export or a CSV/TSV with id, title, description and link columns "
            "is expected"
        )
    items: list[FeedItem] = []
    for row in reader:
        fields = {
            _clean_key(k): (v or "").strip()
            for k, v in row.items()
            if k is not None
        }
        items.append(_item_from(fields))
    return items


def _item_from(fields: dict[str, str]) -> FeedItem:
    item = FeedItem(
        extras={
            k: v for k, v in fields.items()
            if k not in _KNOWN and v and not _is_live_value_key(k)
        },
        dropped=tuple(sorted(
            k for k in fields
            if k not in _KNOWN and k not in DROPPED_FIELDS
            and _is_live_value_key(k)
        )),
    )
    for name in _KNOWN:
        setattr(item, name, fields.get(name, ""))
    return item


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def item_text(item: FeedItem) -> str:
    """The row's stable text — the source_hash basis. Dropped (live)
    fields deliberately don't participate: a price change must not
    force a re-ingest of a product whose facts didn't change."""
    parts = [item.id, item.title, item.description, item.link, item.brand,
             item.gtin, item.mpn, item.product_type, item.item_group_id]
    parts += [f"{k}={v}" for k, v in sorted(item.extras.items())]
    return "\n".join(p for p in parts if p)


def item_to_document(item: FeedItem) -> tuple[str, dict, str]:
    """Mechanical transform: one feed item → (rel_path, frontmatter, body)."""
    if item.gtin:
        entity = f"gtin:{item.gtin}"
    elif item.mpn:
        entity = f"mpn:{item.mpn}"
    else:
        entity = f"sku:{item.id}"

    rel = f"catalog/products/{_slug(item.title) or _slug(item.id)}.md"

    description = item.description.split(". ")[0].strip()
    if len(description) > 160:
        description = description[:157].rstrip() + "…"
    if description and not description.endswith((".", "…")):
        description += "."

    tags = [_slug(part) for part in item.product_type.split(">") if part.strip()][:5]
    fm = {
        "type": "Product",
        "title": item.title,
        "description": description or f"{item.title}.",
        "resource": item.link,
        "tags": tags or ["catalog"],
        "sources": [
            {"id": "feed", "resource": item.link, "title": "Product feed entry"}
        ],
        "x_geo": {
            "profile": PROFILE,
            "risk": "b",
            "intents": ["product_fact", "discovery"],
            "entity": entity,
        },
    }
    if item.brand:
        fm["x_geo"]["brand"] = item.brand

    lines = ["", "# Overview", "", f"{item.description.strip()}[^feed]", ""]
    attributes = []
    if item.brand:
        attributes.append(f"* Brand: {item.brand}.[^feed]")
    if item.gtin:
        attributes.append(f"* GTIN: {item.gtin}.[^feed]")
    if item.mpn:
        attributes.append(f"* MPN: {item.mpn}.[^feed]")
    if item.product_type:
        attributes.append(f"* Category: {item.product_type}.[^feed]")
    if item.item_group_id:
        attributes.append(f"* Variant group: {item.item_group_id}.[^feed]")
    for key, value in sorted(item.extras.items()):
        attributes.append(f"* {key.replace('_', ' ').capitalize()}: {value}.[^feed]")
    if attributes:
        lines += ["# Attributes", "", *attributes, ""]
    lines += [
        "# Price and availability",
        "",
        "The feed's price and availability fields are volatile and are "
        "deliberately not stated here; live values come from the "
        "bundle's capability concepts.",
        "",
        "[^feed]: Product feed entry.",
    ]
    return rel, fm, "\n".join(lines) + "\n"


def ingest_feed(
    feed_path: Path | str,
    bundle_root: Path | str,
    today: _dt.date | None = None,
) -> SurveyResult:
    """Turn every feed item into a draft concept via the shared gate."""
    bundle_root = Path(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)
    result = SurveyResult()

    # One bundle load per ingest, maintained incrementally by
    # place_draft — never a reload per row, which made large catalogs
    # quadratic. The resource map keeps unchanged-row detection O(1).
    state = load_bundle(bundle_root)
    by_resource = {c.resource: c for c in state.concepts.values() if c.resource}

    # The one credibility signal a feed genuinely carries (SPEC §5.1):
    # when the source itself last changed. File mtime is that fact,
    # stamped at the spec's instant precision (F5).
    feed_last_modified = utc_instant(
        _dt.datetime.fromtimestamp(
            Path(feed_path).stat().st_mtime, tz=_dt.timezone.utc
        )
    )

    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    seen_links: dict[str, str] = {}
    for item in parse_feed(feed_path):
        for name in item.dropped:
            if name not in result.dropped_live_fields:
                result.dropped_live_fields.append(name)
        if not item.link or not item.title:
            result.errors.append(
                f"feed item {item.id or '?'!s}: missing link or title; skipped"
            )
            continue
        # One page, one concept: a second row for the same link (a
        # variant sharing the product page) would overwrite the first,
        # so it is recorded and skipped instead (EDGE-CASES U6).
        first = seen_links.get(item.link)
        if first is not None:
            result.collisions.append(
                f"feed item {item.id or '?'}: link {item.link} already used by "
                f"item {first} in this feed; skipped (variants sharing one page "
                "need distinct links, or one row per page)"
            )
            continue
        seen_links[item.link] = item.id or "?"
        source_hash = stable_page_hash(item_text(item))
        existing = by_resource.get(item.link)
        if existing is not None and existing.source_hash == source_hash:
            result.skipped_unchanged.append(item.link)
            continue

        rel, fm, body = item_to_document(item)
        fm["sources"][0]["last_modified"] = feed_last_modified
        fm["status"] = "draft"
        fm["generated"] = {
            "by": FEED_ACTOR,
            "at": now.isoformat().replace("+00:00", "Z"),
        }
        fm["x_geo"]["source_hash"] = source_hash
        fm["x_geo"]["source_fetched_at"] = now.date().isoformat()

        concept = Concept(rel, fm, body)
        hard_errors = [
            f for f in lint_concept(concept, today=today) if f.severity == ERROR
        ]
        if hard_errors:
            result.errors.append(
                f"{item.link}: generated concept failed lint: "
                + "; ".join(f.message for f in hard_errors)
            )
            continue
        final = place_draft(bundle_root, item.link, rel, fm, body, result, state=state)
        placed = state.concepts.get(final)
        if placed is not None:
            by_resource[item.link] = placed
    return result
