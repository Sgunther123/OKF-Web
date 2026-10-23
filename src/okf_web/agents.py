"""The AI crawlers and agents a bundle exists to serve (review
2026-10-21, A-U7: one roster, no longer a publisher detail). The robots
check asks whether ``robots.txt`` blocks them from the bundle path, and
the log scanner counts their fetches, from this one list."""

from __future__ import annotations

__all__ = ["AI_USER_AGENTS"]

AI_USER_AGENTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-User",
    "Google-Extended",
    "PerplexityBot",
    "CCBot",
]
