"""OKF v0.2 concept and bundle model.

Implements the parts of the spec the rest of the tooling relies on:
frontmatter parsing, trust tiers derived from ``verified`` actors,
staleness from ``stale_after``, and bundle loading with the reserved
filenames (``index.md``, ``log.md``) kept separate from concepts.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

RESERVED_FILENAMES = {"index.md", "log.md"}

# Directories the surveyor/review tooling uses for not-yet-accepted content.
# They live inside the bundle checkout but are never published.
INTERNAL_DIRS = {"_quarantine", "_review"}

# Reserved root directory for translations: l10n/<lang>/<rel-path>
# mirrors the default-language concept at <rel-path> (profile 1.3).
L10N_DIR = "l10n"

TRUST_UNVERIFIED = "unverified"
TRUST_MACHINE = "machine-confirmed"
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
        for entry in entries:
            if str(entry.get("by", "")).startswith("human:"):
                return TRUST_HUMAN
        return TRUST_MACHINE

    @property
    def generated_by(self) -> str | None:
        gen = self.frontmatter.get("generated")
        if isinstance(gen, dict):
            by = gen.get("by")
            return str(by) if by else None
        return None

    def is_stale(self, today: _dt.date | None = None) -> bool:
        stale_after = _as_date(self.frontmatter.get("stale_after"))
        if stale_after is None:
            return False
        return (today or _dt.date.today()) > stale_after

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

    @property
    def entity_refs(self) -> list[str]:
        """All outgoing entity references, whatever key they ride on."""
        return self.fits + self.works_with + self.covers

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
            view.concepts[parsed[1]] = concept
    view.indexes = {
        rel: doc for rel, doc in bundle.indexes.items() if split_l10n(rel) is None
    }
    localized_index = bundle.indexes.get(f"{L10N_DIR}/{lang}/index.md")
    if localized_index is not None:
        view.indexes["index.md"] = localized_index
    view.logs = dict(bundle.logs)
    return view


def load_bundle(root: Path | str, include_internal: bool = False) -> Bundle:
    """Load every ``.md`` file under ``root`` into a :class:`Bundle`.

    Files under internal dirs (``_review``, ``_quarantine``) are skipped
    unless ``include_internal`` is set; they are workflow state, not
    published knowledge.
    """
    root = Path(root)
    bundle = Bundle(root=root)
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        top = rel.split("/", 1)[0]
        if top in INTERNAL_DIRS and not include_internal:
            continue
        text = path.read_text(encoding="utf-8")
        name = path.name
        if name == "log.md":
            bundle.logs[rel] = text
            continue
        if name == "index.md":
            try:
                fm, body = parse_document(text)
            except FrontmatterError:
                # Index files are reserved; frontmatter is optional there.
                fm, body = {}, text
            bundle.indexes[rel] = Concept(rel, fm, body, abs_path=path)
            continue
        try:
            fm, body = parse_document(text)
        except FrontmatterError as exc:
            bundle.broken[rel] = str(exc)
            continue
        bundle.concepts[rel] = Concept(rel, fm, body, abs_path=path)
    return bundle
