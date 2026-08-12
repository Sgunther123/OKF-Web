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
* **llms-snippet.txt** — the block to add to the site's ``llms.txt`` so
  generative engines discover the bundle.
* **viewer.html** (optional, on by default) — a self-contained,
  ``noindex`` provenance view for humans who click an AI's citation:
  trust badges, verification history, sources, and a prominent link to
  the live page. A trust surface, deliberately not a shadow storefront.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import render
from .linter import has_errors, lint_bundle
from .model import INTERNAL_DIRS, RISK_HIGH, load_bundle


@dataclass
class PublishResult:
    dist: Path
    published: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)


class PublishError(RuntimeError):
    pass


def publish(
    bundle_root: Path | str,
    dist: Path | str,
    include_machine_confirmed: bool = False,
    base_path: str = "/.well-known/okf",
    viewer: bool = True,
) -> PublishResult:
    bundle_root = Path(bundle_root)
    dist = Path(dist)

    _, findings = lint_bundle(bundle_root)
    if has_errors(findings):
        details = "\n".join(str(f) for f in findings if f.severity == "error")
        raise PublishError(f"bundle has lint errors; refusing to publish:\n{details}")

    bundle = load_bundle(bundle_root)
    result = PublishResult(dist=dist)

    include: set[str] = set(bundle.indexes) | set(bundle.logs)
    for rel, concept in bundle.concepts.items():
        if concept.status == "stable":
            include.add(rel)
        elif include_machine_confirmed and concept.risk != RISK_HIGH:
            include.add(rel)
        else:
            result.withheld.append(rel)

    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    # Copy selected markdown plus any non-markdown assets (question sets,
    # spec sheets) that live outside internal dirs.
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_root).as_posix()
        if rel.split("/", 1)[0] in INTERNAL_DIRS:
            continue
        if path.suffix == ".md" and rel not in include:
            continue
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        result.published.append(rel)

    _write_manifest(dist, result.published)
    _write_linkmap(dist, bundle, result.published, base_path)
    _write_llms_snippet(dist, base_path)
    if viewer:
        (dist / "viewer.html").write_text(
            render.build_viewer_html(bundle, set(result.published)), encoding="utf-8"
        )
    return result


def _write_manifest(dist: Path, published: list[str]) -> None:
    files = {}
    for rel in sorted(published):
        data = (dist / rel).read_bytes()
        files[rel] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
    manifest = {
        "okf_version": "0.2",
        "profile": "ecommerce-geo/1.0",
        "published_at": _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "files": files,
    }
    (dist / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def _write_linkmap(dist: Path, bundle, published: list[str], base_path: str) -> None:
    published_set = set(published)
    linkmap = {
        concept.resource: f"{base_path}/{rel}"
        for rel, concept in sorted(bundle.concepts.items())
        if concept.resource and rel in published_set
    }
    (dist / "linkmap.json").write_text(
        json.dumps(linkmap, indent=2) + "\n", encoding="utf-8"
    )


def _write_llms_snippet(dist: Path, base_path: str) -> None:
    snippet = (
        "## Knowledge\n"
        "\n"
        f"- [OKF knowledge bundle]({base_path}/index.md): Curated, "
        "provenance-tracked facts about this store (products, policies, "
        "capabilities) in Open Knowledge Format v0.2. Start at index.md; "
        f"see {base_path}/manifest.json for freshness and delta sync.\n"
    )
    (dist / "llms-snippet.txt").write_text(snippet, encoding="utf-8")
