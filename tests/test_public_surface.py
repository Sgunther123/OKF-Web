"""The public surface carries no commercial material (CLAUDE.md, "Two
repositories, one history"): the hosted edition's plans, pricing,
operations and records live in its own repository, never here. This
scan is the rule's executable form: every tracked text file is read,
and any hit of a term that would carry such material in fails the
test, outside the example bundle (a fictional store, prices included)
and one example shopper question in DESIGN."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
THIS = Path(__file__).resolve()

#: Terms that mark commercial or private-edition material, matched
#: case-insensitively. This file is the one place they may be spelled.
FORBIDDEN = (
    r"okf-web-v1\.1",            # the hosted edition's private repository
    r"monetiz",
    r"go-to-market",
    r"commercial-(plan|readiness)",
    r"monte carlo",
    r"profitab",
    r"pilot month",
    r"\bstripe\b",
    r"\bdroplet\b",
    r"digitalocean",
    r"@gmail",
    r"\$[0-9]{2,}",               # a dollar amount of two or more digits
)
#: Where a hit is allowed: the example bundle (any term), and one
#: example shopper question in DESIGN.
ALLOWED_PREFIXES = ("bundle-example/",)
ALLOWED_MATCHES = {"docs/DESIGN.md": {"$350"}}
#: Directories a fallback walk skips when git is not at hand.
SKIPPED_DIRS = {".git", "build", "dist", ".venv", "venv", "__pycache__",
                ".pytest_cache", ".eggs"}


def _tracked() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            capture_output=True, check=True, timeout=30,
        ).stdout.decode("utf-8")
        names = [name for name in out.split("\0") if name]
        if names:
            return [REPO / name for name in names]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for path in sorted(REPO.rglob("*")):
        parts = set(path.relative_to(REPO).parts)
        if path.is_file() and not parts & SKIPPED_DIRS and not any(
            part.endswith(".egg-info") for part in parts
        ):
            found.append(path)
    return found


def _hits(path: Path) -> list[tuple[int, str]]:
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return []  # binary
    rel = path.relative_to(REPO).as_posix()
    text = data.decode("utf-8", errors="replace")
    hits = []
    for pattern in FORBIDDEN:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if match.group(0) in ALLOWED_MATCHES.get(rel, set()):
                continue
            line = text.count("\n", 0, match.start()) + 1
            hits.append((line, match.group(0)))
    return sorted(set(hits))


def test_the_public_surface_carries_no_commercial_material():
    files = [
        path for path in _tracked()
        if path.resolve() != THIS and path.exists()
        and not path.relative_to(REPO).as_posix().startswith(ALLOWED_PREFIXES)
    ]
    assert len(files) >= 100, len(files)  # the scan saw the repository
    offending = {}
    for path in files:
        hits = _hits(path)
        if hits:
            offending[path.relative_to(REPO).as_posix()] = hits
    assert not offending, "\n".join(
        f"{rel}:{line}: {found!r}" for rel, hits in sorted(offending.items())
        for line, found in hits
    )
