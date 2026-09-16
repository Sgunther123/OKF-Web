import os

import pytest

from okf_web import llm as llm_mod
from okf_web.llm import LLMUnavailable, SubscriptionCLIClient, claude_code_client

_HELP_WITH_FLAGS = "Usage: claude [options]\n  --tools <list>\n  --system-prompt <text>\n"


def _fake_cli(tmp_path, body: str):
    script = tmp_path / "fake-llm"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return str(script)


def test_subscription_cli_client_pipes_prompt_and_returns_stdout(tmp_path):
    # Echo the prompt back so we can verify system + user both arrived on stdin.
    script = _fake_cli(tmp_path, "cat")
    client = SubscriptionCLIClient([script], model="fake/test")
    out = client.complete("SYSTEM RULES", "USER QUESTION")
    assert "SYSTEM RULES" in out
    assert "USER QUESTION" in out
    assert client.model == "fake/test"


def test_subscription_cli_client_surfaces_nonzero_exit(tmp_path):
    script = _fake_cli(tmp_path, "echo 'weekly limit reached' >&2; exit 1")
    client = SubscriptionCLIClient([script])
    with pytest.raises(RuntimeError, match="weekly limit reached"):
        client.complete("sys", "user")


def test_subscription_cli_client_missing_binary_is_actionable():
    client = SubscriptionCLIClient(["definitely-not-a-real-binary-okfweb"])
    with pytest.raises(RuntimeError, match="not found on PATH"):
        client.complete("sys", "user")


def test_claude_code_client_builds_print_mode_command():
    client = claude_code_client(model="claude-sonnet-5", help_text=_HELP_WITH_FLAGS)
    assert client.command == ["claude", "-p", "--tools", "", "--model", "claude-sonnet-5"]
    assert client.model == "claude-sonnet-5"
    assert client.system_flag == "--system-prompt"
    # Without a model, let the local Claude Code default apply.
    assert claude_code_client(help_text=_HELP_WITH_FLAGS).command == ["claude", "-p", "--tools", ""]


# --- EDGE-CASES S6: no tools, rules out of band, empty working directory ---

def test_claude_code_client_argv_carries_the_rules_on_the_system_flag():
    client = claude_code_client(help_text=_HELP_WITH_FLAGS + "  --strict-mcp-config\n")
    assert client.command == ["claude", "-p", "--tools", "", "--strict-mcp-config"]
    assert client.argv("RULES") == client.command + ["--system-prompt", "RULES"]


def test_claude_code_client_refuses_a_cli_without_the_flags():
    with pytest.raises(LLMUnavailable, match="--tools"):
        claude_code_client(help_text="Usage: claude [options]\n  --model <m>\n")
    with pytest.raises(LLMUnavailable, match="--system-prompt"):
        claude_code_client(help_text="Usage: claude\n  --tools <list>\n")


def test_claude_code_client_keeps_the_flags_when_the_binary_is_absent(monkeypatch):
    # No probe result (binary missing): the flags stay, and the first
    # completion reports the missing binary in its own words.
    monkeypatch.setattr(llm_mod, "probe_cli_help", lambda executable, timeout=30.0: None)
    client = claude_code_client()
    assert client.command == ["claude", "-p", "--tools", ""]
    assert client.system_flag == "--system-prompt"


def test_probe_never_raises_for_a_missing_binary():
    assert llm_mod.probe_cli_help("definitely-not-a-real-binary-okfweb") is None


def test_subscription_client_passes_system_via_flag_and_runs_in_an_empty_dir(tmp_path):
    (tmp_path / "secret.txt").write_text("not for the agent", encoding="utf-8")
    script = _fake_cli(
        tmp_path,
        'printf "ARGS:%s\\nCWD:%s\\nFILES:%s\\nSTDIN:" "$*" "$PWD" "$(ls -A | wc -l | tr -d \' \')"; cat',
    )
    client = SubscriptionCLIClient([script], system_flag="--system-prompt")
    out = client.complete("RULES", "USER TEXT")
    head, stdin = out.split("STDIN:")
    assert "ARGS:--system-prompt RULES" in head
    assert stdin == "USER TEXT"  # the rules never travel with the untrusted text
    cwd = head.split("CWD:")[1].split("\n")[0]
    assert cwd not in (str(tmp_path), os.getcwd())
    assert "FILES:0" in head  # an empty directory: no project files to read


def test_cli_llm_flag_selects_subscription_client(tmp_path, monkeypatch):
    from okf_web import cli as cli_mod

    monkeypatch.setattr(llm_mod, "probe_cli_help", lambda executable, timeout=30.0: _HELP_WITH_FLAGS)
    parser = cli_mod.build_parser()
    args = parser.parse_args(["survey", "b", "--llm", "claude-code"])
    client = cli_mod._llm(args)
    assert isinstance(client, SubscriptionCLIClient)
    assert client.command[:4] == ["claude", "-p", "--tools", ""]


def test_cli_maps_an_unsupported_cli_to_exit_2(tmp_path, monkeypatch, capsys):
    from okf_web import cli as cli_mod

    monkeypatch.setattr(
        llm_mod, "probe_cli_help", lambda executable, timeout=30.0: "Usage: claude\n  --model\n"
    )
    urls = tmp_path / "urls.txt"
    urls.write_text("https://shop.example/p/1\n", encoding="utf-8")
    code = cli_mod.main(["survey", str(tmp_path / "b"), "--urls", str(urls), "--llm", "claude-code"])
    assert code == 2
    err = capsys.readouterr().err
    assert "does not support --tools" in err and "ANTHROPIC_API_KEY" in err
