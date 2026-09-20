"""Remote published bundles: ``okf-web mcp --url`` (GAPS item 10).

A published dist is static files behind HTTPS; nothing about it needs
a server of ours to be queried. This module mirrors the markdown files
a ``manifest.json`` lists into a local cache directory, verifying every
file against the manifest's sha256, and re-checks the manifest on a
schedule with conditional requests (``If-None-Match`` /
``If-Modified-Since``). The bridge then serves a bundle that is at most
``refresh_seconds`` behind the origin and never a torn or tampered
copy. Delta sync is the manifest's purpose: only files whose sha256
changed are fetched, and files that left the manifest are removed.

Every fetch goes through :func:`okf_web.net.safe_fetch` — http(s)
only, private hosts refused unless the caller opted in, bodies capped
under a deadline — and the manifest is untrusted input: a listed path
must be a plain relative markdown path inside the mirror, or it is
ignored. The mirror carries the ``.okf-dist`` marker like any other
copy, so a stray one never becomes knowledge.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from .model import (
    DIST_MARKER,
    Bundle,
    load_bundle,
    localized_view,
    utc_instant,
    write_atomic,
)
from .net import PAGE_POLICY, FetchError, FetchPolicy, FetchResult, safe_fetch
from .publisher import published_view

USER_AGENT = "okf-web-mcp/0.1"
META_NAME = ".okf-remote.json"
MAX_FILES = 20_000  # a manifest listing more than this is not a bundle we mirror
DEFAULT_REFRESH_SECONDS = 300.0  # HOSTING §0's Cache-Control max-age


class RemoteError(FetchError):
    """A remote bundle that cannot be mirrored safely: an unusable
    manifest, or a file that does not match the hash it is listed with."""


def default_policy(allow_private: bool = False) -> FetchPolicy:
    return FetchPolicy(
        max_bytes=PAGE_POLICY.max_bytes,
        timeout=PAGE_POLICY.timeout,
        deadline=PAGE_POLICY.deadline,
        allow_private=allow_private,
        allow_loopback=allow_private,
        user_agent=USER_AGENT,
    )


def cache_dir_for(base_url: str) -> Path:
    """``$XDG_CACHE_HOME/okf-web/remote/<digest>`` (``~/.cache`` by default):
    one mirror per origin URL, outside any bundle."""
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    digest = hashlib.sha256(base_url.rstrip("/").encode("utf-8")).hexdigest()[:16]
    return root / "okf-web" / "remote" / digest


def _safe_rel(rel: str) -> bool:
    """A manifest path we will mirror: relative, markdown, no traversal,
    no hidden segments, no Windows spellings."""
    if not rel or not rel.endswith(".md") or "\\" in rel or ":" in rel:
        return False
    if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute():
        return False
    parts = PurePosixPath(rel).parts
    return all(part not in ("..", ".") and not part.startswith(".") for part in parts)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RemoteSource:
    """A published bundle at ``base_url`` (the directory holding
    ``manifest.json``), mirrored under ``cache_dir``. Implements the
    bridge's source protocol: :meth:`signature` and :meth:`load`."""

    base_url: str
    cache_dir: Path
    policy: FetchPolicy = field(default_factory=default_policy)
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS
    lang: str | None = None
    fetch: Callable[..., FetchResult] = safe_fetch
    manifest: dict | None = None
    etag: str | None = None
    last_modified: str | None = None
    synced_at: str | None = None
    last_error: str | None = None
    _checked: float | None = field(default=None, repr=False)
    _signature: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.cache_dir = Path(self.cache_dir)

    # -- sync ---------------------------------------------------------------
    def _url(self, rel: str) -> str:
        return f"{self.base_url}/{rel}"

    def sync(self) -> dict[str, Any]:
        """Bring the mirror up to date with the origin's manifest. Returns
        ``{"changed": bool, "fetched": n, "removed": n}``. Raises
        :class:`FetchError` (or :class:`RemoteError`) when the origin
        cannot be read or a file fails its hash."""
        headers: dict[str, str] = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        result = self.fetch(self._url("manifest.json"), self.policy, headers)
        self._checked = time.monotonic()
        if result.status == 304 and self.manifest is not None:
            return {"changed": False, "fetched": 0, "removed": 0}
        if result.status != 200:
            raise RemoteError(f"HTTP {result.status} for {self._url('manifest.json')}")
        try:
            manifest = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise RemoteError(f"{self._url('manifest.json')} is not valid JSON: {exc}") from exc
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, dict):
            raise RemoteError(f"{self._url('manifest.json')} has no `files` mapping")
        wanted = {
            rel: meta for rel, meta in files.items()
            if isinstance(rel, str) and isinstance(meta, dict) and _safe_rel(rel)
        }
        if len(wanted) > MAX_FILES:
            raise RemoteError(
                f"{self.base_url} lists {len(wanted)} markdown files; the mirror stops at {MAX_FILES}"
            )

        fetched = 0
        for rel, meta in sorted(wanted.items()):
            expected = meta.get("sha256")
            if not isinstance(expected, str):
                raise RemoteError(f"manifest lists {rel} without a sha256")
            target = self.cache_dir / rel
            if target.is_file() and _digest(target) == expected:
                continue
            page = self.fetch(self._url(rel), self.policy)
            if page.status != 200:
                raise RemoteError(f"HTTP {page.status} for {self._url(rel)}")
            if hashlib.sha256(page.body).hexdigest() != expected:
                raise RemoteError(
                    f"{rel} does not match the sha256 its manifest lists (changed in "
                    "transit or after publish); refusing to serve it"
                )
            _write_bytes_atomic(target, page.body)
            fetched += 1

        removed = 0
        if self.cache_dir.is_dir():
            for path in sorted(self.cache_dir.rglob("*.md")):
                rel = path.relative_to(self.cache_dir).as_posix()
                if rel not in wanted and not any(p.startswith(".") for p in path.relative_to(self.cache_dir).parts):
                    path.unlink()
                    removed += 1

        # The mirror's own manifest lists what it holds (the markdown); the
        # origin's other artifacts (JSON-LD, llms.txt) are not needed here.
        mirrored = {k: v for k, v in manifest.items() if k != "files"}
        mirrored["files"] = {rel: files[rel] for rel in sorted(wanted)}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        write_atomic(self.cache_dir / "manifest.json", json.dumps(mirrored, indent=2) + "\n")
        write_atomic(
            self.cache_dir / DIST_MARKER,
            "mirror of a published bundle (okf-web mcp --url): a copy, never bundle knowledge\n",
        )
        self.manifest = manifest
        self.etag = result.headers.get("ETag")
        self.last_modified = result.headers.get("Last-Modified")
        self.synced_at = utc_instant()
        self._signature = hashlib.sha256(result.body).hexdigest()
        self.last_error = None
        write_atomic(
            self.cache_dir / META_NAME,
            json.dumps({
                "base_url": self.base_url,
                "etag": self.etag,
                "last_modified": self.last_modified,
                "synced_at": self.synced_at,
                "manifest_sha256": self._signature,
            }, indent=2) + "\n",
        )
        return {"changed": True, "fetched": fetched, "removed": removed}

    # -- bridge source protocol --------------------------------------------
    def signature(self) -> Any:
        """The mirrored manifest's digest, re-checked against the origin at
        most every ``refresh_seconds``. A failed re-check keeps serving the
        mirror (the origin's outage is recorded in :attr:`last_error` and
        shown by ``okf_info``), so an assistant session degrades to
        lateness, never to an error."""
        if self._checked is None or time.monotonic() - self._checked >= self.refresh_seconds:
            try:
                self.sync()
            except FetchError as exc:
                if self.manifest is None:
                    raise
                self.last_error = str(exc)
                self._checked = time.monotonic()
        return self._signature

    def load(self) -> Bundle:
        bundle = load_bundle(self.cache_dir)
        if self.lang:
            bundle = localized_view(bundle, self.lang)
        return published_view(bundle)

    def describe(self) -> dict[str, Any]:
        return {
            "url": self.base_url,
            "mirror": str(self.cache_dir),
            "synced_at": self.synced_at,
            "refresh_seconds": self.refresh_seconds,
            "last_error": self.last_error,
        }
