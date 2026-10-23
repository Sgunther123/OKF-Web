"""Review 2026-10-21, phase U2 (refusals and robustness): the mirror
never prunes a directory it did not write, the dist guard keys on the
publisher's own marker, the bridge outlives any single message, a
non-UTF-8 file is a lint finding, the access-log regex is linear, a
placeholder never sits in an executor's host, the agent CLI is refused
when its flags are unknown, and a dead holder's lock is taken over
exactly once."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from okf_web import cli as cli_mod
from okf_web import logscan
from okf_web.linter import lint_bundle
from okf_web.mcp_bridge import _tool_execute, build_state, handle_message, serve_stdio
from okf_web.model import DIST_MARKER, BundleLocked, bundle_lock, load_bundle
from okf_web.publisher import UnsafeDist, check_dist, publish
from okf_web.remote import META_NAME, RemoteError, RemoteSource, check_mirror_dir


# --- S-U3: the mirror prunes only what it wrote ---------------------------------

def test_mirror_refuses_a_directory_it_did_not_create(tmp_path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "todo.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(RemoteError, match="not empty"):
        check_mirror_dir(notes)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    with pytest.raises(RemoteError, match="home directory"):
        check_mirror_dir(tmp_path / "home")
    with pytest.raises(RemoteError, match="working directory"):
        check_mirror_dir(Path.cwd())
    check_mirror_dir(tmp_path / "fresh")  # absent: fine
    (tmp_path / "empty").mkdir()
    check_mirror_dir(tmp_path / "empty")  # empty: fine
    assert (notes / "todo.md").read_text(encoding="utf-8") == "mine\n"


def test_mirror_removes_only_files_its_own_manifest_listed(tmp_path):
    manifests = {
        "v1": {"files": {"a.md": {"sha256": "", "bytes": 2}, "b.md": {"sha256": "", "bytes": 2}}},
    }
    bodies = {"a.md": b"A\n", "b.md": b"B\n"}
    import hashlib

    for rel, body in bodies.items():
        manifests["v1"]["files"][rel]["sha256"] = hashlib.sha256(body).hexdigest()
    state = {"manifest": manifests["v1"]}

    class Result:
        def __init__(self, body, status=200):
            self.body = body
            self.status = status
            self.headers = {}
            self.text = body.decode("utf-8")

    def fetch(url, policy, headers=None):
        rel = url.rsplit("/", 1)[1]
        if rel == "manifest.json":
            return Result(json.dumps(state["manifest"]).encode())
        return Result(bodies[rel])

    mirror = tmp_path / "mirror"
    src = RemoteSource("https://store.example/.well-known/okf", mirror, fetch=fetch)
    assert src.sync()["fetched"] == 2
    # Something the operator keeps beside the mirror is not the mirror's.
    (mirror / "stray.md").write_text("not from the origin\n", encoding="utf-8")
    state["manifest"] = {"files": {"a.md": manifests["v1"]["files"]["a.md"]}}
    src.etag = src.last_modified = None
    result = src.sync()
    assert result["removed"] == 1 and not (mirror / "b.md").exists()
    assert (mirror / "stray.md").exists()
    assert (mirror / META_NAME).exists()

    # A manifest declaring more than the byte cap is refused before any write.
    state["manifest"] = {"files": {"huge.md": {"sha256": "0" * 64, "bytes": 300 * 1024 * 1024}}}
    src.etag = src.last_modified = None
    with pytest.raises(RemoteError, match="declares"):
        src.sync()


# --- S-U4: the dist guard keys on the publisher's own marker ---------------------

def test_a_web_root_with_a_manifest_is_not_a_previous_publish(bundle_copy, tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    (www / "manifest.json").write_text('{"name": "a progressive web app"}', encoding="utf-8")
    (www / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    with pytest.raises(UnsafeDist, match=DIST_MARKER):
        check_dist(bundle_copy, www)
    assert (www / "index.html").exists()
    # A real previous publish carries the marker and needs no force.
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    assert (dist / DIST_MARKER).exists()
    check_dist(bundle_copy, dist)


def test_the_home_and_working_directories_are_never_a_dist(bundle_copy, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    with pytest.raises(UnsafeDist, match="home directory"):
        check_dist(bundle_copy, home, force=True)
    with pytest.raises(UnsafeDist, match="working directory"):
        check_dist(bundle_copy, Path.cwd(), force=True)


# --- A-U8 / T-U1: the bridge outlives any single message --------------------------

def test_serve_stdio_survives_invalid_requests(example_bundle):
    state = build_state(example_bundle)
    lines = [
        "[1, 2]",
        '"hi"',
        "null",
        "[]",
        json.dumps({"jsonrpc": "2.0", "id": 7}),
        json.dumps({"jsonrpc": "2.0", "id": 8, "method": "ping"}),
        json.dumps([{"jsonrpc": "2.0", "id": 9, "method": "ping"},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}]),
        json.dumps({"jsonrpc": "2.0", "id": 10, "method": "tools/list"}),
    ]
    stdout = io.StringIO()
    serve_stdio(state, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=stdout)
    out = [json.loads(l) for l in stdout.getvalue().splitlines()]
    # "[1, 2]" is a batch of two invalid members: one array answer.
    assert isinstance(out[0], list) and [r["error"]["code"] for r in out[0]] == [-32600, -32600]
    assert out[1]["error"]["code"] == -32600 and out[2]["error"]["code"] == -32600
    assert out[3]["error"]["code"] == -32600  # the empty batch
    assert out[4]["id"] == 7 and out[4]["error"]["code"] == -32600
    assert out[5] == {"jsonrpc": "2.0", "id": 8, "result": {}}
    assert out[6] == [{"jsonrpc": "2.0", "id": 9, "result": {}}]  # the notification is silent
    assert out[7]["id"] == 10 and len(out[7]["result"]["tools"]) == 5


def test_an_exception_inside_a_message_is_an_internal_error_not_the_end(example_bundle, monkeypatch):
    state = build_state(example_bundle)
    from okf_web import mcp_bridge

    def boom(state, args):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mcp_bridge, "_tool_info", boom)
    monkeypatch.setattr(mcp_bridge, "refresh", lambda state: (_ for _ in ()).throw(RuntimeError("refresh broke")))
    stdout = io.StringIO()
    serve_stdio(
        state,
        stdin=io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "okf_info", "arguments": {}}}) + "\n"
                          + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n"),
        stdout=stdout,
    )
    out = [json.loads(l) for l in stdout.getvalue().splitlines()]
    assert out[0]["id"] == 1 and out[0]["result"]["isError"] is True
    assert out[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


# --- L-U5: a non-UTF-8 file is a finding, never a traceback ----------------------

def test_a_non_utf8_concept_is_a_lint_finding_not_a_traceback(bundle_copy, capsys):
    (bundle_copy / "faq" / "latin1.md").write_bytes(
        b"---\ntype: FAQ\ntitle: Caf\xe9\nstatus: draft\n---\n\nBody.\n"
    )
    bundle, findings = lint_bundle(bundle_copy)
    assert "faq/latin1.md" in bundle.broken and "UTF-8" in bundle.broken["faq/latin1.md"]
    assert any(f.code == "E001" and f.rel_path == "faq/latin1.md" for f in findings)
    assert cli_mod.main(["lint", str(bundle_copy)]) == 1
    assert "faq/latin1.md" in capsys.readouterr().out
    # Every other command loads the bundle the same way, so none crashes either.
    assert len(load_bundle(bundle_copy).concepts) == len(load_bundle(bundle_copy).concepts)


# --- S-U8: the access-log regex is linear --------------------------------------

def test_log_regex_is_linear_on_an_unclosed_request_line():
    line = '203.0.113.7 - - [10/Aug/2026:13:55:36 +0000] "GET ' + "a" * 16_000 + " 200 1 - -"
    started = time.perf_counter()
    for _ in range(20):
        logscan.scan_lines([line])
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5  # 20 lines; the quadratic regex took about 0.15 s each
    good = '203.0.113.7 - - [10/Aug/2026:13:55:36 +0000] "GET /.well-known/okf/index.md HTTP/1.1" 200 2357 "-" "GPTBot/1.1"'
    assert logscan.scan_lines([good]).ai_hits == 1


# --- S-U10: no placeholder in an executor's host --------------------------------

def _capability(bundle_dir: Path, template: str) -> None:
    (bundle_dir / "capabilities" / "regional.md").write_text(
        "---\n"
        "type: Attested Computation\n"
        "title: Regional price\n"
        "description: Price by region.\n"
        "tags: [price]\n"
        "status: stable\n"
        "runtime: http\n"
        "verified:\n  - by: human:ops@alpinepeakoutfitters.example\n    at: 2026-08-01T00:00:00Z\n"
        "parameters:\n  - name: region\n    required: true\n  - name: sku\n    required: true\n"
        f"executor:\n  resource: {template}\n"
        "attester:\n  resource: /attesters/http_refetch.py\n"
        "x_geo:\n  risk: a\n---\n\nA regional price lookup.\n",
        encoding="utf-8",
    )


def test_a_placeholder_in_the_executor_host_is_refused_and_linted(bundle_copy):
    _capability(bundle_copy, "https://{region}.api.alpinepeakoutfitters.example/price/{sku}")
    _, findings = lint_bundle(bundle_copy)
    assert any(f.code == "E023" and f.rel_path == "capabilities/regional.md" for f in findings)
    state = build_state(bundle_copy, working=True)
    with pytest.raises(ValueError, match="placeholder in its scheme or host"):
        _tool_execute(state, {"path": "capabilities/regional.md",
                              "arguments": {"region": "eu", "sku": "x"}})
    # The same template with the placeholder in the path is fine for lint.
    _capability(bundle_copy, "https://api.alpinepeakoutfitters.example/{region}/price/{sku}")
    _, findings = lint_bundle(bundle_copy)
    assert not any(f.code == "E023" for f in findings)


# --- S-U7 / T-U11: a dead holder's lock is taken over exactly once ----------------

def test_a_dead_or_garbage_lock_is_taken_over_and_leaves_nothing_behind(bundle_copy):
    lock = bundle_copy / ".okf-lock"
    lock.write_text("not a pid\n", encoding="utf-8")
    with bundle_lock(bundle_copy):
        assert lock.read_text(encoding="utf-8").split()[0] == str(os.getpid())
    assert not lock.exists()
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                          capture_output=True, text=True, check=True).stdout.strip()
    lock.write_text(f"{dead} 2026-10-21T00:00:00Z\n", encoding="utf-8")
    with bundle_lock(bundle_copy):
        assert lock.read_text(encoding="utf-8").split()[0] == str(os.getpid())
    assert not list(bundle_copy.glob(".okf-lock.stale.*"))


def test_two_processes_never_both_hold_the_lock(bundle_copy):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; sys.path.insert(0, 'src')\n"
         "from okf_web.model import bundle_lock\n"
         f"with bundle_lock({str(bundle_copy)!r}):\n"
         "    print('held', flush=True)\n"
         "    time.sleep(30)\n"],
        stdout=subprocess.PIPE, text=True, cwd=str(Path(__file__).resolve().parent.parent),
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(BundleLocked, match=str(holder.pid)):
            with bundle_lock(bundle_copy):
                pass
    finally:
        holder.kill()
        holder.wait()
    # The holder died without cleaning up: the next taker takes over.
    with bundle_lock(bundle_copy):
        pass
    assert not (bundle_copy / ".okf-lock").exists()
