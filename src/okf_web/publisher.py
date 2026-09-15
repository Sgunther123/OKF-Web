"""Publish the companion bundle next to the storefront.

Turns a bundle working copy into the static artifact served at
``/.well-known/okf/``:

* **Publication policy** — ``stable`` concepts always ship; drafts ship
  only when explicitly allowed *and* they are not high-risk. A
  high-risk concept (``x_geo.risk: a``) can only ever reach the public
  bundle through a human approval, because approval is what makes it
  ``stable``. Internal dirs (``_review``, ``_quarantine``) never ship.
* **manifest.json** — per-file sha256 + sizes so consuming agents can
  delta-sync the bundle instead of re-reading it.
* **linkmap.json** — live URL → concept path, for the site to emit
  ``<link rel="alternate" type="text/markdown" ...>`` on each page (the
  page ↔ concept binding in the other direction).
* **llms-snippet.txt** — the blocks to add to the site's ``llms.txt``
  and HTML ``<head>`` so generative engines discover the bundle, on
  this origin or a delegated one.
* **Freshness policy** — ``freshness="warn"`` (default) ships concepts
  past ``stale_after`` with a loud warning; ``freshness="withhold"``
  retires them from the published set, capping the damage an
  unmaintained bundle can do. Expired promotions are withheld under
  either policy (their end date is machine-readable and unambiguous).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.robotparser import RobotFileParser

from . import OKF_VERSION, PROFILE
from .linter import has_errors, lint_bundle
from .model import Bundle, DIST_MARKER, INTERNAL_DIRS, _linked, load_bundle, marked_dists
from .structured import write_llms_txt, write_structured


@dataclass
class PublishResult:
    dist: Path
    published: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structured: list[str] = field(default_factory=list)
    # Non-markdown files shipped from the bundle (spec sheets, attester
    # code): named in the output so nothing rides along unnoticed.
    assets: list[str] = field(default_factory=list)


class PublishError(RuntimeError):
    pass


class UnsafeDist(PublishError):
    """The dist path would destroy something: the bundle itself, a
    directory containing it, or a directory that is not a previous
    publish (EDGE-CASES U1, A1)."""


# Operator files that belong beside a bundle but never in a published
# one: the bundle viewer (drafts and read logs) and feed exports (prices
# and costs the live-values rule keeps out of concepts).
_OPERATOR_FILES = {"bundle-viewer.html"}
_OPERATOR_SUFFIXES = {".csv", ".tsv"}


def check_dist(bundle_root: Path | str, dist: Path | str, force: bool = False) -> None:
    """Refuse a dist that publishing would wrongly empty. Publishing
    deletes the target first, so the target must be outside the bundle,
    must not contain it, and must be either empty, a previous publish
    (it carries ``manifest.json``), or explicitly forced."""
    bundle_root, dist = Path(bundle_root), Path(dist)
    root, target = bundle_root.resolve(), dist.resolve()
    if target == root or root in target.parents:
        raise UnsafeDist(
            f"refusing to publish into the bundle itself ({dist}); choose a "
            f"directory outside {bundle_root}"
        )
    if target in root.parents:
        raise UnsafeDist(
            f"refusing to publish into {dist}: it contains the bundle "
            f"{bundle_root}, and publishing empties the target first"
        )
    if not dist.exists():
        return
    if not dist.is_dir():
        raise UnsafeDist(f"{dist} exists and is not a directory")
    if any(dist.iterdir()) and not (dist / "manifest.json").exists() and not force:
        raise UnsafeDist(
            f"refusing to empty {dist}: it is not empty and carries no "
            "manifest.json from a previous publish (pass --force to replace it)"
        )


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
        elif include_machine_confirmed and not concept.is_high_risk:
            include.add(rel)
        else:
            withheld.append(rel)
    return include, withheld


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


def publish(
    bundle_root: Path | str,
    dist: Path | str,
    include_machine_confirmed: bool = False,
    base_path: str = "/.well-known/okf",
    freshness: str = "warn",
    today: _dt.date | None = None,
    site: str | None = None,
    bundle_url: str | None = None,
    structured: bool = True,
    force: bool = False,
) -> PublishResult:
    """Build the static bundle.

    ``site`` is the storefront origin the bundle speaks for; when the
    bundle is served off-origin (platform-hosted stores that cannot
    serve root paths), ``bundle_url`` is the absolute base URL where
    this dist will live. Both feed the discovery/delegation artifacts:
    ``manifest.json`` records the claimed ``site`` (the bundle→store
    half of the binding; the store→bundle half is the pointer the
    merchant pastes from ``llms-snippet.txt``).
    """
    bundle_root = Path(bundle_root)
    dist = Path(dist)
    site = site.rstrip("/") if site else None
    if bundle_url is None and site:
        bundle_url = site + base_path
    bundle_url = bundle_url.rstrip("/") if bundle_url else None

    check_dist(bundle_root, dist, force=force)
    _, findings = lint_bundle(bundle_root)
    if has_errors(findings):
        details = "\n".join(str(f) for f in findings if f.severity == "error")
        raise PublishError(f"bundle has lint errors; refusing to publish:\n{details}")

    bundle = load_bundle(bundle_root)
    if not bundle.concepts and not bundle.indexes:
        raise PublishError(
            f"nothing to publish: {bundle_root} holds no OKF documents "
            "(is the path right?)"
        )
    result = PublishResult(dist=dist)

    concept_include, result.withheld = select_publishable(
        bundle, include_machine_confirmed, today, freshness
    )
    include = concept_include | set(bundle.indexes) | set(bundle.logs)

    # Freshness warnings under the default policy: shipping a concept
    # its own frontmatter says not to trust is exactly the failure an
    # unmaintained bundle decays into, so it never happens silently.
    for rel in sorted(concept_include):
        concept = bundle.concepts[rel]
        if concept.is_stale(today):
            result.warnings.append(
                f"{rel} is past stale_after "
                f"({concept.frontmatter.get('stale_after')}) but ships anyway; "
                "re-survey it or publish with --freshness withhold"
            )

    # Origin consistency: a bundle claiming to speak for `site` whose
    # concepts cite pages on a different origin is either misdeclared
    # or misassembled — either way consumers will reject the binding.
    if site:
        site_origin = _origin(site)
        for rel in sorted(concept_include):
            resource = bundle.concepts[rel].resource
            if resource and resource.startswith(("http://", "https://")) and _origin(resource) != site_origin:
                result.warnings.append(
                    f"{rel} resource {resource} is not on the declared site "
                    f"origin {site_origin} — delegation verifiers will flag it"
                )

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    (dist / DIST_MARKER).write_text(
        "published by okf-web: a copy of a bundle, never bundle knowledge\n",
        encoding="utf-8",
    )

    # Copy selected markdown plus any non-markdown assets (question sets,
    # spec sheets) that live outside internal dirs. A published copy left
    # inside the bundle is skipped whole, like the loader skips it.
    marked = marked_dists(bundle_root)
    skipped_dists: set[Path] = set()
    for path in sorted(bundle_root.rglob("*")):
        rel = path.relative_to(bundle_root).as_posix()
        if rel.split("/", 1)[0] in INTERNAL_DIRS:
            continue
        copy = next((d for d in marked if d in path.parents), None)
        if copy is not None:
            if copy not in skipped_dists:
                skipped_dists.add(copy)
                result.warnings.append(
                    f"{copy.relative_to(bundle_root).as_posix()}/ is a "
                    f"published copy ({DIST_MARKER} marker); not published"
                )
            continue
        # Hidden files are working state (embedding caches, editor
        # droppings), never published knowledge.
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if _linked(bundle_root, path):
            if path.is_symlink():
                result.warnings.append(f"{rel} is a symlink; not published")
            continue
        if not path.is_file():
            continue
        if path.name in _OPERATOR_FILES or path.suffix.lower() in _OPERATOR_SUFFIXES:
            result.warnings.append(
                f"{rel} is an operator file (viewer page or feed export); "
                "not published"
            )
            continue
        if path.suffix == ".md":
            if rel not in include:
                continue
        else:
            result.assets.append(rel)
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        result.published.append(rel)

    # Derived tier: what engines read today, generated from the verified
    # bundle (READINESS R2). Emitted before the manifest so the manifest
    # hashes — and any signature over it — cover these artifacts too.
    if structured:
        base = bundle_url or base_path
        result.structured = write_structured(
            dist, bundle, concept_include, base, site=site
        )
        result.structured.append(
            write_llms_txt(dist, bundle, concept_include, base)
        )
        result.published.extend(result.structured)

    _write_manifest(dist, result.published, site=site, bundle_url=bundle_url)
    _write_linkmap(dist, bundle, result.published, bundle_url or base_path)
    _write_llms_snippet(dist, base_path, site=site, bundle_url=bundle_url)

    # An index that advertises withheld concepts ships dangling links —
    # legal per the spec (consumers must tolerate them) but a producer
    # smell worth a loud warning.
    published_set = set(result.published)
    for rel, doc in bundle.indexes.items():
        if rel not in published_set:
            continue
        for target in doc.internal_links():
            resolved = bundle.resolve_link(rel, target)
            if resolved.endswith(".md") and resolved not in published_set:
                result.warnings.append(
                    f"published {rel} links {target}, which is not in the "
                    "published set (withheld or missing)"
                )
    return result


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _file_digest(path: Path) -> tuple[str, int]:
    """sha256 + size in 64 KB chunks: manifest hashing must not load a
    whole file — spec-sheet PDFs and media assets publish alongside the
    concepts, and peak memory must not track the largest asset
    (READINESS R4)."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_manifest(
    dist: Path,
    published: list[str],
    site: str | None = None,
    bundle_url: str | None = None,
) -> None:
    files = {}
    for rel in sorted(published):
        sha256, size = _file_digest(dist / rel)
        files[rel] = {
            "sha256": sha256,
            "bytes": size,
        }
    manifest = {
        "okf_version": OKF_VERSION,
        "profile": PROFILE,
        "published_at": _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "files": files,
    }
    # The bundle→store half of the delegation binding (the store→bundle
    # half is the pointer on the site itself). Consumers of an
    # off-origin bundle MUST check manifest.site against the origin
    # that pointed them here.
    if site:
        manifest["site"] = site
    if bundle_url:
        manifest["bundle_url"] = bundle_url
    (dist / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def _write_linkmap(dist: Path, bundle, published: list[str], prefix: str) -> None:
    published_set = set(published)
    linkmap = {
        concept.resource: f"{prefix}/{rel}"
        for rel, concept in sorted(bundle.concepts.items())
        if concept.resource and rel in published_set
    }
    (dist / "linkmap.json").write_text(
        json.dumps(linkmap, indent=2) + "\n", encoding="utf-8"
    )


# AI crawlers/agents a bundle exists to serve. If robots.txt blocks
# them from the bundle path, publishing is a no-op in practice — the
# check surfaces that before the merchant wonders why nothing reads it.
AI_USER_AGENTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-User",
    "Google-Extended",
    "PerplexityBot",
    "CCBot",
]


def evaluate_robots(robots_txt: str, site: str, base_path: str) -> list[str]:
    """Return the AI user agents that robots.txt blocks from the bundle."""
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    url = site.rstrip("/") + base_path + "/index.md"
    return [ua for ua in AI_USER_AGENTS if not parser.can_fetch(ua, url)]


def check_robots(
    site: str, base_path: str, timeout: float = 15.0
) -> tuple[list[str], str | None]:
    """Fetch the live robots.txt and report blocked AI agents.

    Returns ``(blocked_agents, fetch_error)``; a fetch error means the
    check was inconclusive, not that agents are allowed.
    """
    robots_url = site.rstrip("/") + "/robots.txt"
    try:
        request = urllib.request.Request(
            robots_url, headers={"User-Agent": "okf-web-publisher/0.1"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            robots_txt = response.read().decode(charset, errors="replace")
    except OSError as exc:
        return [], f"could not fetch {robots_url}: {exc}"
    return evaluate_robots(robots_txt, site, base_path), None


def _write_llms_snippet(
    dist: Path,
    base_path: str,
    site: str | None = None,
    bundle_url: str | None = None,
) -> None:
    base = bundle_url or base_path
    snippet = (
        "# Paste into your site's llms.txt:\n"
        "\n"
        "## Knowledge\n"
        "\n"
        f"- [OKF knowledge bundle]({base}/index.md): Curated, "
        "provenance-tracked facts about this store (products, policies, "
        "capabilities) in Open Knowledge Format v0.2. Start at index.md; "
        f"see {base}/manifest.json for freshness and delta sync.\n"
    )
    if bundle_url:
        # The store→bundle half of the discovery binding. On platforms
        # that cannot serve /.well-known/*, this head tag (which every
        # platform's theme editor can add) is how engines find an
        # off-origin bundle — and, paired with manifest.site, how they
        # verify it speaks for this store.
        snippet += (
            "\n"
            "# Paste into your storefront's HTML <head> "
            "(required when the bundle is hosted off-origin):\n"
            "\n"
            f'<link rel="okf-bundle" href="{bundle_url}/">\n'
        )
    (dist / "llms-snippet.txt").write_text(snippet, encoding="utf-8")
