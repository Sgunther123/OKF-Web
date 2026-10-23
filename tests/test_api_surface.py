"""Review 2026-10-21, phase U4 (errors, API and configuration): one
error family with one exit table; every module declares its public
names and docs/API.md names only names that exist; the primitives that
used to be re-implemented have one home each; the tunables live in
config."""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import okf_web
from okf_web import cli as cli_mod
from okf_web import config, errors, llm, model, net, packs
from okf_web.model import Bundle, load_bundle

SRC = Path(okf_web.__file__).resolve().parent
REPO = SRC.parent.parent
MODULES = sorted(m.name for m in pkgutil.iter_modules(okf_web.__path__))


def _all_error_classes() -> list[type]:
    for name in MODULES:
        importlib.import_module(f"okf_web.{name}")
    found: set[type] = set()
    todo = [errors.OkfWebError]
    while todo:
        cls = todo.pop()
        for sub in cls.__subclasses__():
            if sub not in found:
                found.add(sub)
                todo.append(sub)
    return sorted((c for c in found if c not in (errors.Refusal, errors.Failure)),
                  key=lambda c: (c.__module__, c.__name__))


ERROR_CLASSES = _all_error_classes()


# --- A-U1: one family, one exit table -------------------------------------------------

def test_every_raised_error_carries_one_verdict():
    assert len(ERROR_CLASSES) >= 17
    for cls in ERROR_CLASSES:
        assert issubclass(cls, (errors.Refusal, errors.Failure)), cls
    with pytest.raises(TypeError):
        errors.exit_code(ValueError("not ours"))


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda c: f"{c.__module__.rsplit('.', 1)[1]}.{c.__name__}")
def test_main_maps_every_error_class_to_its_exit_code(cls, monkeypatch, capsys, bundle_copy):
    expected = errors.exit_code(cls("boom"))
    assert expected == (2 if issubclass(cls, errors.Refusal) else 1)

    def raiser(args):
        raise cls("boom")

    monkeypatch.setattr(cli_mod, "cmd_lint", raiser)
    assert cli_mod.main(["lint", str(bundle_copy)]) == expected
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "boom" in err


def test_the_documented_codes_hold_through_the_commands(bundle_copy, tmp_path, capsys):
    from okf_web.publisher import PublishError, UnsafeDist
    from okf_web.signing import LabelError, SigningError

    assert errors.exit_code(UnsafeDist("x")) == 2 and errors.exit_code(PublishError("x")) == 1
    assert errors.exit_code(SigningError("x")) == 1 and errors.exit_code(LabelError("x")) == 2
    # Through the CLI: an unsafe dist refuses (2), an empty bundle fails to publish (1),
    # a bad label refuses (2) and a report outside its lane refuses (2).
    assert cli_mod.main(["publish", str(bundle_copy), str(bundle_copy)]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli_mod.main(["publish", str(empty), str(tmp_path / "dist")]) == 1
    assert "nothing to publish" in capsys.readouterr().err
    dist = tmp_path / "dist2"
    assert cli_mod.main(["publish", str(bundle_copy), str(dist)]) == 0
    assert cli_mod.main(["verify", str(dist), "--countersignature", "Not Valid!"]) == 2
    assert "invalid countersignature label" in capsys.readouterr().err


# --- A-U2: declared surface -----------------------------------------------------------------

def test_every_module_declares_its_public_names():
    for name in MODULES:
        mod = importlib.import_module(f"okf_web.{name}")
        assert hasattr(mod, "__all__"), name
        for public in mod.__all__:
            assert not public.startswith("_"), (name, public)
            assert hasattr(mod, public), (name, public)


def test_api_doc_names_resolve():
    text = (REPO / "docs" / "API.md").read_text(encoding="utf-8")
    module = None
    seen = 0
    for line in text.splitlines():
        heading = re.match(r"^### `okf_web(?:\.([a-z_]+))?`", line)
        if heading:
            module = heading.group(1) or ""
            continue
        row = re.match(r"^\| `([A-Za-z_][A-Za-z0-9_]*)` \|", line)
        if row and module is not None:
            target = importlib.import_module("okf_web" + (f".{module}" if module else ""))
            assert hasattr(target, row.group(1)), (module, row.group(1))
            if module:
                assert row.group(1) in target.__all__, (module, row.group(1))
            seen += 1
    assert seen > 80


def test_the_cli_keeps_the_names_the_hosted_edition_imports():
    assert cli_mod._add_llm_args is llm.add_llm_args
    assert cli_mod._llm is llm.client_from_args
    assert cli_mod._question_packs is packs.available
    assert model._as_date is model.as_date and model._as_instant is model.as_instant


def test_llm_wiring_from_args(monkeypatch):
    import argparse

    parser = argparse.ArgumentParser()
    llm.add_llm_args(parser)
    args = parser.parse_args([])
    assert args.model == config.DEFAULT_MODEL and args.llm == "api"
    args = parser.parse_args(["--llm", "claude-code", "--model", "m"])
    monkeypatch.setattr(llm, "probe_cli_help", lambda executable, timeout=30.0: (
        "Usage: claude\n  --tools <list>\n  --system-prompt <s>\n  --strict-mcp-config\n"))
    client = llm.client_from_args(args)
    assert isinstance(client, llm.SubscriptionCLIClient) and client.model == "m"
    judge = llm.client_from_args(args, model="judge")
    assert judge.model == "judge"


def test_question_packs_are_read_from_package_data():
    available = packs.available()
    assert len(available) == 10 and "machinery" in available and "machinery.es" in available
    assert all("questions:" in text for text in available.values())


# --- A-U5 / A-U7: one home each -----------------------------------------------------------------

def test_shared_primitives_have_one_home(tmp_path, bundle_copy):
    assert net.origin("https://Store.Example:443/shop/") == "https://store.example"
    assert net.origin("http://[::1]:8080/x") == "http://[::1]:8080"
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\x00\x01" * 70000)
    import hashlib
    assert model.file_digest(blob) == (hashlib.sha256(blob.read_bytes()).hexdigest(), 140000)
    model.write_atomic(tmp_path / "bytes.bin", b"\xff\x00raw")
    assert (tmp_path / "bytes.bin").read_bytes() == b"\xff\x00raw"
    assert not list(tmp_path.glob(".*.tmp"))
    assert model.slug("Alpine 2 Tent / XL!") == "alpine-2-tent-xl-"
    assert model.as_date("2026-08-05T10:00:00Z") == model.as_instant("2026-08-05").date()
    derived = net.PAGE_POLICY.derive(timeout=3.0, user_agent="x")
    assert (derived.timeout, derived.user_agent, derived.max_bytes) == (3.0, "x", net.PAGE_POLICY.max_bytes)
    assert net.PAGE_POLICY.timeout == 30.0  # the base is untouched
    bundle = load_bundle(bundle_copy)
    assert bundle.site == bundle.indexes["index.md"].frontmatter["x_geo"]["site"]
    assert Bundle(root=bundle_copy).site is None


def test_no_module_reimplements_the_shared_primitives():
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "model.py":
            assert 'replace("+00:00", "Z")' not in text, path.name  # utc_instant
            assert "[^a-z0-9]+" not in text, path.name  # slug
        if path.name != "config.py":
            assert '"/.well-known/okf"' not in text, path.name  # WELL_KNOWN_PATH
            assert "claude-sonnet-5" not in text, path.name  # DEFAULT_MODEL
    from okf_web import discover, mcp_bridge, remote, surveyor

    for module in (discover, mcp_bridge, remote, surveyor):
        agent = module.USER_AGENT
        assert agent.startswith("okf-web-") and f"/{okf_web.__version__} " in agent, agent
        assert config.REPOSITORY_URL in agent
    assert net.DEFAULT_USER_AGENT == config.user_agent()


def test_the_publisher_still_answers_for_what_moved_out():
    from okf_web import agents, publisher, views

    assert publisher.AI_USER_AGENTS is agents.AI_USER_AGENTS
    assert publisher.published_view is views.published_view
    assert publisher.select_publishable is views.select_publishable
    assert publisher.withhold_reason is views.withhold_reason
    assert "GPTBot" in agents.AI_USER_AGENTS
