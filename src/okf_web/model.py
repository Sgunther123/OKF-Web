"""OKF v0.2 concept and bundle model.

Implements the parts of the spec the rest of the tooling relies on:
frontmatter parsing, trust tiers derived from ``verified`` actors,
staleness from ``stale_after``, and bundle loading with the reserved
filenames (``index.md``, ``log.md``) kept separate from concepts.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

RESERVED_FILENAMES = {"index.md", "log.md"}

# Parse cache (READINESS R4): YAML frontmatter parsing dominates
# bundle-load time (7–10 s at 5,000 concepts), so parsed documents are
# cached in one hidden JSON file keyed by (mtime_ns, size). JSON, never
# pickle — a bundle cloned from someone else must not be able to
# execute code through its working-state files. Hidden ⇒ the publisher
# never ships it; gitignored ⇒ it never reaches a commit.
CONCEPT_CACHE_NAME = ".concepts-cache.json"
_CACHE_VERSION = 1

# Directories the surveyor/review tooling uses for not-yet-accepted content.
# They live inside the bundle checkout but are never published.
INTERNAL_DIRS = {"_quarantine", "_review"}

# The publisher drops this marker into every dist it writes. A dist that
# ends up inside a bundle (E1 forbids creating one there, but older
# publishes and hand-moved directories exist) is a published copy, not
# bundle knowledge, and the loader skips anything under it.
DIST_MARKER = ".okf-dist"


class BundleNotFound(FileNotFoundError):
    """The bundle root is not a directory. Raised instead of returning an
    empty bundle, so a mistyped path cannot lint clean, review clean, or
    publish a dist from nothing (EDGE-CASES U2)."""


def marked_dists(root: Path) -> set[Path]:
    """Directories under ``root`` that carry the dist marker: published
    copies left inside a bundle (moved by hand, or written before the
    publisher learned to refuse the location). The loader and the
    publisher both skip everything beneath them. A marker at the root
    itself is ignored: loading a dist as a bundle (verify, tests) is
    legitimate."""
    return {p.parent for p in root.rglob(DIST_MARKER) if p.parent != root}


def _linked(root: Path, path: Path) -> bool:
    """True when ``path`` or any directory between ``root`` and it is a
    symlink. Links are never bundle content: git stores them, and a link
    to a file outside the bundle would otherwise be read, published, and
    signed as if it were knowledge (EDGE-CASES S4)."""
    if path.is_symlink():
        return True
    for parent in path.relative_to(root).parents:
        if parent == Path("."):
            break
        if (root / parent).is_symlink():
            return True
    return False

# Reserved root directory for translations: l10n/<lang>/<rel-path>
# mirrors the default-language concept at <rel-path> (profile 1.3).
L10N_DIR = "l10n"

TRUST_UNVERIFIED = "unverified"
TRUST_MACHINE = "machine-confirmed"
# A named human vouched for publication wholesale (`human-batch:` —
# review batch-approve) without reading each item. Stronger than a
# machine check, weaker than a per-item review; never sufficient for
# high-risk concepts (E010 demands `human:`). READINESS R3: "5,000
# mechanically ingested facts" and "a person read this" must not share
# a label.
TRUST_HUMAN_BATCH = "human-attested"
TRUST_HUMAN = "human-reviewed"

# Risk tiers from the ecommerce-geo profile (x_geo.risk).
RISK_HIGH = "a"    # prices/promotions, legal & policy, safety/compliance claims
RISK_MEDIUM = "b"  # descriptive product facts extracted from merchant surfaces
RISK_LOW = "c"     # navigation, indexes, machine-generated reports

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FOOTNOTE_REF_RE = re.compile(r"\[\^([A-Za-z0-9_-]+)\](?!:)")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([A-Za-z0-9_-]+)\]:", re.MULTILINE)
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


class FrontmatterError(ValueError):
    """Raised when a document's YAML frontmatter is missing or unparseable."""


def _iso(value: Any) -> str:
    """Render dates/datetimes as compact ISO strings for YAML output."""
    if isinstance(value, _dt.datetime):
        text = value.isoformat()
        return text.replace("+00:00", "Z")
    return value.isoformat()


class _FrontmatterDumper(yaml.SafeDumper):
    """safe_dump variant that keeps key order and ISO-formats dates."""


_FrontmatterDumper.add_representer(
    _dt.date, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", _iso(v))
)
_FrontmatterDumper.add_representer(
    _dt.datetime, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", _iso(v))
)


def parse_document(text: str) -> tuple[dict[str, Any], str]:
    """Split an OKF document into (frontmatter mapping, markdown body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise FrontmatterError("no YAML frontmatter block found")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")
    return data, text[match.end():]


def render_document(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body back to an OKF markdown document."""
    dumped = yaml.dump(
        frontmatter,
        Dumper=_FrontmatterDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    return f"---\n{dumped}---\n{body if body.startswith(chr(10)) else chr(10) + body}"


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_date(value: Any) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _as_instant(value: Any) -> _dt.datetime | None:
    """The value as a tz-aware instant (SPEC since ad30107): datetimes
    pass through (naive ⇒ UTC), bare dates mean midnight UTC, strings
    parse either form. None when unparseable."""
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(
            value, _dt.time.min, tzinfo=_dt.timezone.utc
        )
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            return _as_instant(_dt.datetime.fromisoformat(text))
        except ValueError:
            date = _as_date(value)
            return None if date is None else _as_instant(date)
    return None


def utc_instant(moment: _dt.datetime | None = None) -> str:
    """Now (or ``moment``) as the spec's timestamp form:
    ``2026-06-30T14:00:00Z`` — what every writer stamps since F5."""
    moment = moment or _dt.datetime.now(_dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    return (
        moment.astimezone(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass
class Concept:
    """A single non-reserved ``.md`` file in a bundle."""

    rel_path: str
    frontmatter: dict[str, Any]
    body: str
    abs_path: Path | None = None

    # -- core fields -------------------------------------------------------
    @property
    def type(self) -> str | None:
        value = self.frontmatter.get("type")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or self.rel_path)

    @property
    def status(self) -> str:
        # Spec: default is "stable" when absent.
        return str(self.frontmatter.get("status") or "stable")

    @property
    def resource(self) -> str | None:
        value = self.frontmatter.get("resource")
        return str(value) if value else None

    @property
    def tags(self) -> list[str]:
        value = self.frontmatter.get("tags")
        return [str(t) for t in value] if isinstance(value, list) else []

    # -- provenance / trust ------------------------------------------------
    @property
    def verified_entries(self) -> list[dict[str, Any]]:
        """``verified`` normalized to a list; a bare mapping is one entry."""
        value = self.frontmatter.get("verified")
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        return []

    @property
    def trust_tier(self) -> str:
        entries = self.verified_entries
        if not entries:
            return TRUST_UNVERIFIED
        actors = [str(entry.get("by", "")) for entry in entries]
        if any(actor.startswith("human:") for actor in actors):
            return TRUST_HUMAN
        if any(actor.startswith("human-batch:") for actor in actors):
            return TRUST_HUMAN_BATCH
        return TRUST_MACHINE

    @property
    def generated_by(self) -> str | None:
        gen = self.frontmatter.get("generated")
        if isinstance(gen, dict):
            by = gen.get("by")
            return str(by) if by else None
        return None

    def is_stale(self, today: _dt.date | _dt.datetime | None = None) -> bool:
        """Spec §5.5: stale when ``now >= stale_after``. With a datetime
        clock the comparison is instant-granular (the spec's exact
        semantics since ad30107); with a date clock — every linter and
        publisher path — it stays date-granular, which marks a mid-day
        instant stale from the start of its day: the conservative
        direction, declared as D15."""
        raw = self.frontmatter.get("stale_after")
        if raw is None:
            return False
        if isinstance(today, _dt.datetime):
            instant = _as_instant(raw)
            if instant is None:
                return False
            now = (
                today
                if today.tzinfo
                else today.replace(tzinfo=_dt.timezone.utc)
            )
            return now >= instant
        stale_after = _as_date(raw)
        if stale_after is None:
            return False
        return (today or _dt.date.today()) >= stale_after

    # -- ecommerce-geo profile extensions ----------------------------------
    @property
    def x_geo(self) -> dict[str, Any]:
        value = self.frontmatter.get("x_geo")
        return value if isinstance(value, dict) else {}

    @property
    def risk(self) -> str:
        return str(self.x_geo.get("risk") or RISK_LOW)

    @property
    def intents(self) -> list[str]:
        value = self.x_geo.get("intents")
        return [str(v) for v in value] if isinstance(value, list) else []

    @property
    def source_hash(self) -> str | None:
        value = self.x_geo.get("source_hash")
        return str(value) if value else None

    @property
    def entity(self) -> str | None:
        """Stable store-local id (``sku:…``) other concepts can reference."""
        value = self.x_geo.get("entity")
        return str(value) if value else None

    # -- fit & compatibility (profile 1.4) ---------------------------------
    @property
    def fits(self) -> list[str]:
        """Entities this concept gives fit/sizing guidance for."""
        value = self.x_geo.get("fits")
        return [str(v) for v in value] if isinstance(value, list) else []

    @property
    def works_with(self) -> list[str]:
        """Entities this concept declares interoperability with."""
        value = self.x_geo.get("works_with")
        return [str(v) for v in value] if isinstance(value, list) else []

    # -- post-purchase ownership (profile 1.5) -----------------------------
    @property
    def covers(self) -> list[str]:
        """Entities this concept gives ownership guidance for (care,
        setup, troubleshooting, warranty process)."""
        value = self.x_geo.get("covers")
        return [str(v) for v in value] if isinstance(value, list) else []

    # -- omnichannel availability (profile 1.7) ----------------------------
    @property
    def location(self) -> dict[str, Any]:
        """Structured location data for Store Location concepts:
        address, hours, phone, services (extra keys legal)."""
        value = self.x_geo.get("location")
        return value if isinstance(value, dict) else {}

    # -- compliance / product passports (profile 1.6) ----------------------
    @property
    def passport_for(self) -> str | None:
        """The single entity this Product Passport describes."""
        value = self.x_geo.get("passport_for")
        return str(value) if value else None

    @property
    def passport(self) -> dict[str, Any]:
        """Structured passport data: materials, origin, certifications,
        repairability (extra keys legal; consumers ignore unknowns)."""
        value = self.x_geo.get("passport")
        return value if isinstance(value, dict) else {}

    # -- B2B / procurement (profile 1.8) -----------------------------------
    @property
    def trade(self) -> dict[str, Any]:
        """Trade Program concepts: the machine-readable commercial
        terms — payment_terms, min_order, lead_time (extra keys legal)."""
        value = self.x_geo.get("trade")
        return value if isinstance(value, dict) else {}

    @property
    def procurement(self) -> dict[str, Any]:
        """Product concepts: per-SKU trade facts — moq, case_pack,
        lead_time. Terms only; quoted prices are live values."""
        value = self.x_geo.get("procurement")
        return value if isinstance(value, dict) else {}

    # High-risk-by-definition types: their claims are money/legal
    # whatever the frontmatter declares.
    _HIGH_RISK_TYPES = ("Product Passport", "Trade Program")

    @property
    def is_high_risk(self) -> bool:
        """The gate classification the tooling enforces.

        Declared ``x_geo.risk`` — except that some types are high-risk
        *by definition*: Product Passports carry compliance claims and
        Trade Programs carry commercial/payment terms. A concept of
        these types declaring ``b`` must not dodge the human-verifier
        gate, the publisher's draft withholding, or batch approval
        exclusion.
        """
        return self.risk == RISK_HIGH or self.type in self._HIGH_RISK_TYPES

    @property
    def effective_risk(self) -> str:
        """The risk letter after the by-definition floor — what triage
        surfaces must sort, filter, and count on so they agree with the
        gates that enforce ``is_high_risk``."""
        return RISK_HIGH if self.is_high_risk else self.risk

    @property
    def entity_refs(self) -> list[str]:
        """All outgoing entity references, whatever key they ride on."""
        refs = self.fits + self.works_with + self.covers
        if self.passport_for:
            refs.append(self.passport_for)
        return refs

    # -- promotion time bounds (type: Promotion) ---------------------------
    @property
    def promo_starts(self) -> _dt.date | None:
        return _as_date(self.x_geo.get("starts_at"))

    @property
    def promo_ends(self) -> _dt.date | None:
        return _as_date(self.x_geo.get("ends_at"))

    def promo_expired(self, today: _dt.date | None = None) -> bool:
        ends = self.promo_ends
        return ends is not None and (today or _dt.date.today()) > ends

    # -- sources / citations ----------------------------------------------
    @property
    def sources(self) -> list[dict[str, Any]]:
        value = self.frontmatter.get("sources")
        if isinstance(value, list):
            return [s for s in value if isinstance(s, dict)]
        return []

    @property
    def source_ids(self) -> set[str]:
        return {str(s["id"]) for s in self.sources if s.get("id")}

    @property
    def footnote_refs(self) -> set[str]:
        return set(_FOOTNOTE_REF_RE.findall(self.body))

    @property
    def footnote_defs(self) -> set[str]:
        return set(_FOOTNOTE_DEF_RE.findall(self.body))

    def internal_links(self) -> list[str]:
        """Bundle-internal markdown link targets (absolute or relative)."""
        out = []
        for target in _LINK_RE.findall(self.body):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            out.append(target.split("#", 1)[0])
        return [t for t in out if t]

    # -- text views --------------------------------------------------------
    def retrieval_text(self) -> str:
        """Text used for lexical retrieval by the evaluator."""
        parts = [self.title, str(self.frontmatter.get("description") or "")]
        parts.extend(self.tags)
        parts.append(self.body)
        return "\n".join(p for p in parts if p)

    def render(self) -> str:
        return render_document(self.frontmatter, self.body)

    def save(self) -> None:
        if self.abs_path is None:
            raise ValueError("concept has no filesystem path")
        self.abs_path.write_text(self.render(), encoding="utf-8")


@dataclass
class Bundle:
    """An OKF bundle: a directory of markdown files."""

    root: Path
    concepts: dict[str, Concept] = field(default_factory=dict)
    indexes: dict[str, Concept] = field(default_factory=dict)
    logs: dict[str, str] = field(default_factory=dict)
    broken: dict[str, str] = field(default_factory=dict)  # rel_path -> error

    @property
    def okf_version(self) -> str | None:
        root_index = self.indexes.get("index.md")
        if root_index:
            value = root_index.frontmatter.get("okf_version")
            return str(value) if value is not None else None
        return None

    def get(self, rel_path: str) -> Concept | None:
        return self.concepts.get(rel_path.lstrip("/"))

    def resolve_link(self, from_rel: str, target: str) -> str:
        """Resolve a bundle-absolute or relative link to a bundle rel path."""
        if target.startswith("/"):
            return target.lstrip("/")
        base = Path(from_rel).parent
        joined = (base / target).as_posix()
        parts: list[str] = []
        for part in joined.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/".join(parts)

    def all_documents(self) -> Iterator[Concept]:
        yield from self.indexes.values()
        yield from self.concepts.values()

    def entities(self) -> dict[str, str]:
        """``x_geo.entity`` id → rel_path, for resolving fit/compat references."""
        return {
            c.entity: rel
            for rel, c in self.concepts.items()
            if c.entity and split_l10n(rel) is None
        }


def split_l10n(rel_path: str) -> tuple[str, str] | None:
    """``('es', 'faq/general.md')`` for ``l10n/es/faq/general.md``; else None."""
    parts = rel_path.split("/", 2)
    if len(parts) == 3 and parts[0] == L10N_DIR and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None


def concept_content_hash(concept: Concept) -> str:
    """Content identity of a concept — what a translation pins itself to
    via ``x_geo.l10n_source_hash`` so parity is checkable offline."""
    return sha256_text(concept.render())


def trust_mix(bundle: Bundle) -> dict[str, int]:
    """Concept counts by trust tier (translations excluded by key) —
    the scorecard's honest account of how much was actually read by a
    person versus attested wholesale or machine-checked (READINESS R3)."""
    mix: dict[str, int] = {}
    for rel, concept in bundle.concepts.items():
        if split_l10n(rel) is not None:
            continue
        mix[concept.trust_tier] = mix.get(concept.trust_tier, 0) + 1
    return dict(sorted(mix.items()))


def localized_view(bundle: Bundle, lang: str) -> Bundle:
    """The bundle a ``lang`` shopper's engine reads.

    Translations under ``l10n/<lang>/`` overlay their source concepts
    (same bundle path, translated content); untranslated concepts stay
    in the default language — a partial translation degrades to mixed
    language, never to missing knowledge. Other languages' trees drop
    out. ``l10n/<lang>/index.md``, when present, replaces the root
    index.
    """
    view = Bundle(root=bundle.root)
    view.concepts = {
        rel: c for rel, c in bundle.concepts.items() if split_l10n(rel) is None
    }
    for rel, concept in bundle.concepts.items():
        parsed = split_l10n(rel)
        if parsed and parsed[0] == lang:
            # Re-key *and* re-path: the overlay must advertise the same
            # rel_path a consumer can look back up (search → get, the
            # citability metric), not an l10n/ path this view no longer
            # exposes.
            view.concepts[parsed[1]] = Concept(
                parsed[1], concept.frontmatter, concept.body,
                abs_path=concept.abs_path,
            )
    view.indexes = {
        rel: doc for rel, doc in bundle.indexes.items() if split_l10n(rel) is None
    }
    localized_index = bundle.indexes.get(f"{L10N_DIR}/{lang}/index.md")
    if localized_index is not None:
        view.indexes["index.md"] = Concept(
            "index.md", localized_index.frontmatter, localized_index.body,
            abs_path=localized_index.abs_path,
        )
    view.logs = dict(bundle.logs)
    return view


def _cache_encode(value: Any) -> Any:
    """Frontmatter → JSON-safe: YAML's date/datetime scalars survive the
    round trip as tagged objects (a real frontmatter mapping whose only
    key is one of the tags would be misread — no OKF key looks like
    that)."""
    if isinstance(value, _dt.datetime):
        return {"__dt__": value.isoformat()}
    if isinstance(value, _dt.date):
        return {"__d__": value.isoformat()}
    if isinstance(value, dict):
        return {k: _cache_encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cache_encode(v) for v in value]
    return value


def _cache_decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__dt__"}:
            return _dt.datetime.fromisoformat(value["__dt__"])
        if set(value) == {"__d__"}:
            return _dt.date.fromisoformat(value["__d__"])
        return {k: _cache_decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cache_decode(v) for v in value]
    return value


def _read_parse_cache(cache_path: Path) -> dict[str, dict]:
    if not cache_path.exists():
        return {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != _CACHE_VERSION:
        return {}
    entries = raw.get("entries")
    return entries if isinstance(entries, dict) else {}


def _parse_entry(name: str, text: str) -> dict:
    """Parse one document into its cacheable form."""
    if name == "index.md":
        try:
            fm, body = parse_document(text)
        except FrontmatterError:
            # Index files are reserved; frontmatter is optional there.
            fm, body = {}, text
        return {"fm": _cache_encode(fm), "body": body, "broken": None}
    try:
        fm, body = parse_document(text)
    except FrontmatterError as exc:
        return {"fm": None, "body": "", "broken": str(exc)}
    return {"fm": _cache_encode(fm), "body": body, "broken": None}


def load_bundle(
    root: Path | str, include_internal: bool = False, use_cache: bool = True
) -> Bundle:
    """Load every ``.md`` file under ``root`` into a :class:`Bundle`.

    Files under internal dirs (``_review``, ``_quarantine``) are skipped
    unless ``include_internal`` is set; they are workflow state, not
    published knowledge.

    Parsed documents are served from ``.concepts-cache.json`` when the
    file's (mtime_ns, size) is unchanged (READINESS R4); an edit, a new
    file, or a deletion re-parses exactly what changed and rewrites the
    cache. A missing, stale, or corrupt cache degrades to a full parse —
    never to an error — and a read-only bundle simply skips the rewrite.
    """
    root = Path(root)
    if not root.is_dir():
        raise BundleNotFound(f"bundle directory not found: {root}")
    bundle = Bundle(root=root)
    cache_path = root / CONCEPT_CACHE_NAME
    cached = _read_parse_cache(cache_path) if use_cache else {}
    fresh: dict[str, dict] = {}
    dirty = False
    # Published dists left inside the bundle are skipped wholesale (the
    # marker at the root itself means the caller is loading a dist as a
    # bundle on purpose, which is fine).
    marked = marked_dists(root)
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        top = rel.split("/", 1)[0]
        if top in INTERNAL_DIRS and not include_internal:
            continue
        if marked and any(parent in marked for parent in path.parents):
            continue
        if _linked(root, path):
            continue
        name = path.name
        if name == "log.md":
            bundle.logs[rel] = path.read_text(encoding="utf-8")
            continue
        st = path.stat()
        entry = cached.get(rel)
        if (
            entry is None
            or entry.get("mtime_ns") != st.st_mtime_ns
            or entry.get("size") != st.st_size
        ):
            entry = {
                "mtime_ns": st.st_mtime_ns,
                "size": st.st_size,
                **_parse_entry(name, path.read_text(encoding="utf-8")),
            }
            dirty = True
        fresh[rel] = entry
        if entry["broken"] is not None:
            bundle.broken[rel] = entry["broken"]
            continue
        concept = Concept(
            rel, _cache_decode(entry["fm"]), entry["body"], abs_path=path
        )
        if name == "index.md":
            bundle.indexes[rel] = concept
        else:
            bundle.concepts[rel] = concept
    if use_cache and (dirty or set(fresh) != set(cached)):
        try:
            cache_path.write_text(
                json.dumps({"version": _CACHE_VERSION, "entries": fresh}),
                encoding="utf-8",
            )
        except OSError:
            pass  # read-only checkout: the cache is a convenience, not state
    return bundle
