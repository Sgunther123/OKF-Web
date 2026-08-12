import pytest

from okf_web.llm import SubscriptionCLIClient, claude_code_client


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
    client = claude_code_client(model="claude-sonnet-5")
    assert client.command == ["claude", "-p", "--model", "claude-sonnet-5"]
    assert client.model == "claude-sonnet-5"
    # Without a model, let the local Claude Code default apply.
    assert claude_code_client().command == ["claude", "-p"]


def test_cli_llm_flag_selects_subscription_client(tmp_path, monkeypatch):
    from okf_web import cli as cli_mod

    parser = cli_mod.build_parser()
    args = parser.parse_args(["survey", "b", "--llm", "claude-code"])
    client = cli_mod._llm(args)
    assert isinstance(client, SubscriptionCLIClient)
    assert client.command[:2] == ["claude", "-p"]
