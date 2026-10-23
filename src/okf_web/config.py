"""The tunables every module used to spell for itself (review
2026-10-21, A-U6): the well-known path, the default model, the
repository, and one ``user_agent`` that carries the package version,
so no request ever again identifies itself as a release that never
shipped."""

from __future__ import annotations

from . import OKF_VERSION, PROFILE, __version__  # noqa: F401 — the version trio, re-exported

__all__ = ["WELL_KNOWN_PATH", "DEFAULT_MODEL", "REPOSITORY_URL", "OKF_VERSION",
           "PROFILE", "user_agent"]

#: Where a bundle lives under its site, by convention (GEO-PROFILE §8).
WELL_KNOWN_PATH = "/.well-known/okf"
#: The model the CLI asks for when the operator names none.
DEFAULT_MODEL = "claude-sonnet-5"
#: Named in every user agent, so a site owner reading a log can find us.
REPOSITORY_URL = "https://github.com/sgunther123/okf-web"


def user_agent(component: str = "") -> str:
    """``okf-web-<component>/<version> (+<repository>)``: the one user
    agent string, versioned from the package, for the surveyor, the
    discoverer, the bridge, the mirror and the robots check."""
    name = f"okf-web-{component}" if component else "okf-web"
    return f"{name}/{__version__} (+{REPOSITORY_URL})"
