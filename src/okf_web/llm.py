"""Minimal LLM client abstraction.

The surveyor and evaluator only need one operation: a system prompt plus
a user message in, text out. Any provider can sit behind
:class:`LLMClient`:

* :class:`AnthropicClient` — the API path. Works with an
  ``ANTHROPIC_API_KEY`` **or** keyless via an ``ant auth login`` OAuth
  profile (the SDK resolves credentials automatically). Metered API
  billing; the right path for anything scheduled or unattended.
* :class:`SubscriptionCLIClient` — the bring-your-own-subscription
  path. Runs each call through a locally installed agent CLI (Claude
  Code in print mode by default), so interactive runs draw on the LLM
  subscription the user already pays for instead of API billing.
* :class:`StaticClient` — deterministic, for tests.
"""

from __future__ import annotations

import subprocess
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


class SubscriptionCLIClient:
    """Run prompts through a local agent CLI on the user's subscription.

    The command receives the combined system + user prompt on stdin and
    must print the completion to stdout — the contract of Claude Code's
    print mode (``claude -p``), and equally of other agent CLIs, so the
    open tooling stays provider-neutral.

    Scope: **interactive, human-initiated runs only.** Consumer LLM
    subscriptions are personal and rate-limited in rolling windows;
    scheduled or unattended automation (cron surveys, CI evaluations,
    hosted services) belongs on API credentials. A rate-limit pause
    mid-survey is safe: the surveyor's source-hash incrementality means
    a re-run resumes with only unprocessed pages costing anything.
    """

    def __init__(self, command: list[str], model: str = "subscription-cli",
                 timeout: float = 600.0):
        self.command = list(command)
        self.model = model
        self._timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        # Agent CLIs take one prompt; max_tokens is not applicable.
        prompt = f"{system.strip()}\n\n---\n\n{user}"
        try:
            proc = subprocess.run(
                self.command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{self.command[0]!r} not found on PATH; install it and log "
                "in (for Claude Code: `claude` + `/login`), or use the API "
                "path instead"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{self.command[0]} timed out after {self._timeout:.0f}s"
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:500]
            raise RuntimeError(
                f"{self.command[0]} exited {proc.returncode}: {detail}"
            )
        return proc.stdout


def claude_code_client(model: str | None = None, timeout: float = 600.0) -> SubscriptionCLIClient:
    """Claude Code in print mode, authenticated however the local
    ``claude`` install is — including a Claude Pro/Max subscription."""
    command = ["claude", "-p"]
    if model:
        command += ["--model", model]
    return SubscriptionCLIClient(command, model=model or "claude-code", timeout=timeout)


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
