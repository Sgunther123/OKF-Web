import os

import pytest

from okf_web import llm as llm_mod
from okf_web.llm import LLMUnavailable, SubscriptionCLIClient, claude_code_client

_HELP_WITH_FLAGS = (
    "Usage: claude [options]\n  --tools <list>\n  --system-prompt <text>\n"
    "  --strict-mcp-config   Only use MCP servers from --mcp-config\n"
)


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


_BASE = ["claude", "-p", "--tools", "", "--strict-mcp-config"]


def test_claude_code_client_builds_print_mode_command():
    client = claude_code_client(model="claude-sonnet-5", help_text=_HELP_WITH_FLAGS)
    assert client.command == _BASE + ["--model", "claude-sonnet-5"]
    assert client.model == "claude-sonnet-5"
    assert client.system_flag == "--system-prompt"
    # Without a model, let the local Claude Code default apply.
    assert claude_code_client(help_text=_HELP_WITH_FLAGS).command == _BASE


# --- EDGE-CASES S6: no tools, rules out of band, empty working directory ---

def test_claude_code_client_argv_carries_the_rules_on_the_system_flag():
    client = claude_code_client(help_text=_HELP_WITH_FLAGS + "  --restricted\n")
    assert client.command == _BASE + ["--restricted"]
    assert client.argv("RULES") == client.command + ["--system-prompt", "RULES"]


def test_claude_code_client_refuses_a_cli_without_the_flags():
    with pytest.raises(LLMUnavailable, match="--tools"):
        claude_code_client(help_text="Usage: claude [options]\n  --model <m>\n")
    with pytest.raises(LLMUnavailable, match="--system-prompt"):
        claude_code_client(help_text="Usage: claude\n  --tools <list>\n")
    # S-U9: MCP servers from the operator's settings stay out, or no run.
    with pytest.raises(LLMUnavailable, match="--strict-mcp-config"):
        claude_code_client(help_text="Usage: claude\n  --tools <list>\n  --system-prompt <s>\n")


def test_claude_code_client_keeps_the_flags_when_the_binary_is_absent(monkeypatch):
    # No probe result (binary missing): the flags stay, and the first
    # completion reports the missing binary in its own words.
    monkeypatch.setattr(llm_mod, "probe_cli_help", lambda executable, timeout=30.0: None)
    client = claude_code_client()
    assert client.command == _BASE
    assert client.system_flag == "--system-prompt"


def test_probe_never_raises_for_a_missing_binary():
    assert llm_mod.probe_cli_help("definitely-not-a-real-binary-okfweb") is None


def test_probe_failure_other_than_a_missing_binary_refuses_the_cli(monkeypatch):
    # S-U9: a probe that times out or cannot run leaves the flags unknown,
    # and an agent CLI with unknown flags is not run on untrusted text.
    import subprocess

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude --help", timeout=30)

    monkeypatch.setattr(llm_mod.subprocess, "run", boom)
    with pytest.raises(LLMUnavailable, match="could not read"):
        llm_mod.probe_cli_help("claude")


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


# --- the API client and a reply cut at its output limit ---------------------------
#
# The default model reasons before it writes, and the provider's output
# limit covers the reasoning as well as the answer. Until 2026-11-12 the
# client asked for the answer's size alone and returned whatever came
# back: a question set cut after its third question was a set of three.

from types import SimpleNamespace  # noqa: E402

from okf_web import errors, evaluator, surveyor  # noqa: E402
from okf_web.llm import AnthropicClient, LLMTruncated  # noqa: E402
from okf_web.model import Bundle, Concept, load_bundle  # noqa: E402


def _reply(text, stop="end_turn"):
    # What the provider sends: the reasoning first, with its text
    # withheld, then the words.
    return SimpleNamespace(stop_reason=stop, content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text[: len(text) // 2]),
        SimpleNamespace(type="text", text=text[len(text) // 2:]),
    ])


class BadRequestError(Exception):
    """Named as the provider's client names it."""


class _Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class _Messages:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Stream(outcome)


def _api_client(*outcomes) -> AnthropicClient:
    client = AnthropicClient.__new__(AnthropicClient)  # no SDK and no key needed
    client.model = "some-model"
    client._client = SimpleNamespace(messages=_Messages(*outcomes))
    return client


def _limits(client):
    return [request["max_tokens"] for request in client._client.messages.requests]


def test_the_api_client_asks_for_the_answer_plus_room_for_the_reasoning():
    client = _api_client(_reply("The whole answer."))
    assert client.complete("RULES", "QUESTION", max_tokens=1024) == "The whole answer."
    [request] = client._client.messages.requests
    assert request == {"model": "some-model", "system": "RULES", "max_tokens": 1024 + 8000,
                       "messages": [{"role": "user", "content": "QUESTION"}]}
    assert _limits(_api_client(_reply("x"))) == []  # nothing is sent before a call
    default = _api_client(_reply("x"))
    default.complete("s", "u")
    assert _limits(default) == [4096 + 8000]


def test_a_reply_cut_at_the_limit_is_asked_for_again_with_more_room_and_never_used():
    client = _api_client(_reply("questions:\n  - id: disc-1", stop="max_tokens"),
                         _reply("questions: all twenty-eight"))
    assert client.complete("s", "u", max_tokens=4096) == "questions: all twenty-eight"
    assert _limits(client) == [4096 + 8000, 4096 + 32000]


def test_a_reply_cut_twice_fails_and_says_why():
    client = _api_client(_reply("half", stop="max_tokens"), _reply("half again", stop="max_tokens"))
    with pytest.raises(LLMTruncated, match=r"some-model was cut off at its output limit "
                                           r"\(36096 tokens, its reasoning included\)") as cut:
        client.complete("s", "u", max_tokens=4096)
    assert "a cut-off reply is not used" in str(cut.value)
    assert _limits(client) == [4096 + 8000, 4096 + 32000]  # two tries, never a third
    # The command acted and the outcome failed: exit 1, not a refusal.
    assert isinstance(cut.value, errors.Failure) and errors.exit_code(cut.value) == 1


def test_a_model_with_a_small_output_is_asked_as_the_caller_sized_it():
    too_much = BadRequestError("max_tokens: 12096 > 8192, which is the maximum allowed")
    client = _api_client(too_much, _reply("Fits."))
    assert client.complete("s", "u", max_tokens=4096) == "Fits."
    assert _limits(client) == [4096 + 8000, 4096]
    # Cut at its own size, there is no more room to ask for.
    cut = _api_client(too_much, _reply("ha", stop="max_tokens"))
    with pytest.raises(LLMTruncated, match=r"\(4096 tokens"):
        cut.complete("s", "u", max_tokens=4096)
    assert _limits(cut) == [4096 + 8000, 4096]
    # A reply cut with room, where the model has no more to give: the cut stands.
    capped = _api_client(_reply("ha", stop="max_tokens"), too_much)
    with pytest.raises(LLMTruncated, match=r"\(12096 tokens"):
        capped.complete("s", "u", max_tokens=4096)


@pytest.mark.parametrize("failure", [
    BadRequestError("messages: text content blocks must be non-empty"),
    RuntimeError("overloaded: max_tokens mentioned by something that is no bad request"),
    OSError("connection reset"),
])
def test_any_other_failure_is_the_callers_to_see(failure):
    client = _api_client(failure)
    with pytest.raises(type(failure)):
        client.complete("s", "u")
    assert _limits(client) == [4096 + 8000]  # not asked again
    later = _api_client(_reply("x", stop="max_tokens"), failure)
    with pytest.raises(type(failure)):
        later.complete("s", "u")


class _CutFor:
    """A client whose reply for one kind of request was cut twice."""

    model = "static/cut"

    def __init__(self, marker, otherwise=""):
        self.marker, self.otherwise = marker, otherwise

    def complete(self, system, user, max_tokens=0):
        if self.marker in user:
            raise LLMTruncated("static/cut was cut off at its output limit")
        return self.otherwise


def test_a_cut_question_set_is_a_failure_not_a_short_set(tmp_path):
    bundle = Bundle(root=tmp_path, concepts={"store.md": Concept(
        "store.md", {"type": "Store Identity", "title": "Shop", "description": "A shop."}, "x")})
    with pytest.raises(LLMTruncated):
        evaluator.generate_questions(bundle, _CutFor("PER_ARCHETYPE"))


def test_a_page_whose_extraction_was_cut_is_reported_and_the_others_are_kept(tmp_path):
    block = ('<<<CONCEPT path="faq/b.md">>>\n---\ntype: FAQ\ntitle: B\n---\n\nBody.\n<<<END>>>\n')
    result = surveyor.survey(
        ["https://shop.test/a", "https://shop.test/b"], tmp_path,
        _CutFor("https://shop.test/a", otherwise=block), fetcher=lambda url: f"text of {url}")
    assert result.written == ["faq/b.md"]
    assert result.errors == ["https://shop.test/a: static/cut was cut off at its output limit"]
    assert list(load_bundle(tmp_path).concepts) == ["faq/b.md"]
