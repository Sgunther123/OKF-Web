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
import tempfile
from typing import Protocol

from .config import DEFAULT_MODEL
from .errors import Refusal

__all__ = [
    "LLMClient",
    "AnthropicClient",
    "LLMUnavailable",
    "probe_cli_help",
    "SubscriptionCLIClient",
    "claude_code_client",
    "StaticClient",
    "estimate_tokens",
    "add_llm_args",
    "client_from_args",
    "DEFAULT_MODEL",
]


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


class LLMUnavailable(RuntimeError, Refusal):
    """The requested LLM path cannot run safely on this machine; the
    message says what to change."""


# Flags the agent CLI must offer before untrusted page text is allowed
# anywhere near it: no tools, the rules delivered out of band, and no
# MCP servers from the operator's own settings (``--tools ""`` disables
# the built-in tools only; review 2026-10-21, S-U9).
_REQUIRED_CLI_FLAGS = ("--tools", "--system-prompt", "--strict-mcp-config")
# Added when the installed CLI offers them: settings files ignored too.
_OPTIONAL_CLI_FLAGS = ("--restricted",)


def probe_cli_help(executable: str, timeout: float = 30.0) -> str | None:
    """``<executable> --help`` as text, or ``None`` when the binary is
    missing (a missing binary gets its own actionable error at the first
    completion). A probe that fails for any other reason (a timeout, a
    permission error) raises :class:`LLMUnavailable`: a CLI whose flags
    could not be read is not run on untrusted text (S-U9)."""
    try:
        proc = subprocess.run(
            [executable, "--help"], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        raise LLMUnavailable(
            f"could not read `{executable} --help` ({exc}); okf-web runs an "
            "agent CLI only after confirming it supports "
            + ", ".join(_REQUIRED_CLI_FLAGS)
            + ", so the probe has to succeed first. Retry, or use the API path "
            "instead (drop --llm claude-code and set ANTHROPIC_API_KEY)"
        ) from exc
    return (proc.stdout or "") + (proc.stderr or "")


class SubscriptionCLIClient:
    """Run prompts through a local agent CLI on the user's subscription.

    Without ``system_flag`` the command receives the combined system +
    user prompt on stdin and must print the completion to stdout — the
    contract of Claude Code's print mode (``claude -p``), and equally of
    other agent CLIs, so the open tooling stays provider-neutral. With
    ``system_flag`` the system text travels as that flag's value and
    only the user text (page content, untrusted) goes to stdin. Every
    run happens in an empty temporary working directory, so an agent
    CLI sees no project files whatever the prompt asks for.

    Scope: **interactive, human-initiated runs only.** Consumer LLM
    subscriptions are personal and rate-limited in rolling windows;
    scheduled or unattended automation (cron surveys, CI evaluations,
    hosted services) belongs on API credentials. A rate-limit pause
    mid-survey is safe: the surveyor's source-hash incrementality means
    a re-run resumes with only unprocessed pages costing anything.
    """

    def __init__(self, command: list[str], model: str = "subscription-cli",
                 timeout: float = 600.0, system_flag: str | None = None):
        self.command = list(command)
        self.model = model
        self._timeout = timeout
        self.system_flag = system_flag

    def argv(self, system: str) -> list[str]:
        """The exact command a completion runs: the system text rides
        on ``system_flag`` when there is one."""
        if self.system_flag:
            return self.command + [self.system_flag, system.strip()]
        return list(self.command)

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        # Agent CLIs take one prompt; max_tokens is not applicable.
        if self.system_flag:
            argv, prompt = self.argv(system), user
        else:
            argv, prompt = list(self.command), f"{system.strip()}\n\n---\n\n{user}"
        try:
            with tempfile.TemporaryDirectory(prefix="okf-web-llm-") as workdir:
                proc = subprocess.run(
                    argv,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=self._timeout,
                    cwd=workdir,
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


def claude_code_client(
    model: str | None = None, timeout: float = 600.0, help_text: str | None = None
) -> SubscriptionCLIClient:
    """Claude Code in print mode, authenticated however the local
    ``claude`` install is — including a Claude Pro/Max subscription —
    with every tool disabled and the rules as its system prompt.

    The installed CLI is probed once (``claude --help``; pass
    ``help_text`` to skip the probe). A CLI without the tool-disabling
    or system-prompt flag is refused with an explanation rather than run
    with tools on: surveyed pages are untrusted text and must never
    steer an agent that can touch the operator's machine. A missing
    binary is not a refusal here; the first completion reports it."""
    if help_text is None:
        help_text = probe_cli_help("claude")
    command = ["claude", "-p", "--tools", "", "--strict-mcp-config"]
    if help_text is not None:
        missing = [flag for flag in _REQUIRED_CLI_FLAGS if flag not in help_text]
        if missing:
            raise LLMUnavailable(
                "the installed `claude` CLI does not support "
                + ", ".join(missing)
                + ": okf-web runs Claude Code with all tools disabled, no MCP "
                "servers from your settings, and the extraction rules as its "
                "system prompt, so text from surveyed pages cannot steer an "
                "agent that has tools. Update Claude Code (`claude update`), or "
                "use the API path instead (drop --llm claude-code and set "
                "ANTHROPIC_API_KEY)"
            )
        command += [flag for flag in _OPTIONAL_CLI_FLAGS if flag in help_text]
    if model:
        command += ["--model", model]
    return SubscriptionCLIClient(
        command, model=model or "claude-code", timeout=timeout, system_flag="--system-prompt"
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


# --- the CLI's wiring, public (review 2026-10-21, A-U2) -----------------------------

def add_llm_args(parser) -> None:
    """The two arguments every LLM-driven command takes: ``--model``
    (default :data:`DEFAULT_MODEL`) and ``--llm`` (``api`` — the
    Anthropic SDK; ``claude-code`` — a local ``claude -p`` under the
    operator's subscription, interactive runs only)."""
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--llm",
        choices=["api", "claude-code"],
        default="api",
        help="api: Anthropic SDK (API key or `ant auth login` profile); "
        "claude-code: your Claude subscription via a local `claude -p` "
        "(interactive runs only)",
    )


def client_from_args(args, model: str | None = None):
    """The LLM client the parsed arguments ask for; ``model`` overrides
    ``args.model`` (a judge on a second model). The hosted edition's
    `okf-hosted` wires its metered runs through this same door."""
    model = model or args.model
    if getattr(args, "llm", "api") == "claude-code":
        return claude_code_client(model=model)
    return AnthropicClient(model=model)
