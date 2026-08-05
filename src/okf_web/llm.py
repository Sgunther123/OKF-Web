"""Minimal LLM client abstraction.

The surveyor and evaluator only need one operation: a system prompt plus
a user message in, text out. Any provider can sit behind
:class:`LLMClient`; :class:`AnthropicClient` is the shipped default and
:class:`StaticClient` makes the pipelines testable offline.
"""

from __future__ import annotations

from typing import Protocol

DEFAULT_MODEL = "claude-sonnet-5"


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        ...


class AnthropicClient:
    """Claude-backed client. Requires the ``anthropic`` package and an
    ``ANTHROPIC_API_KEY`` in the environment."""

    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "the `anthropic` package is required for LLM-backed commands; "
                "install with `pip install okf-web[llm]`"
            ) from exc
        self.model = model
        self._client = anthropic.Anthropic()

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        response = self._client.messages.create(
            model=self.model,
            system=system,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )


class StaticClient:
    """Deterministic client for tests: replays canned responses in order."""

    def __init__(self, responses: list[str], model: str = "static/test"):
        self.model = model
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise RuntimeError("StaticClient ran out of canned responses")
        return self._responses.pop(0)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) for efficiency metrics."""
    return max(1, len(text) // 4)
