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
