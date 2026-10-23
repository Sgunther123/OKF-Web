"""The starter question packs shipped with the package (review
2026-10-21, A-U2: a public home for what the CLI kept private). The
YAML files live in ``okf_web/questionpacks/`` as package data; this
module reads them."""

from __future__ import annotations

from importlib import resources

__all__ = ["available"]


def available() -> dict[str, str]:
    """Every shipped starter pack: name → YAML text (``apparel``,
    ``apparel.es``, …)."""
    packs: dict[str, str] = {}
    for entry in resources.files("okf_web").joinpath("questionpacks").iterdir():
        if entry.name.endswith(".yaml"):
            packs[entry.name[: -len(".yaml")]] = entry.read_text("utf-8")
    return packs
