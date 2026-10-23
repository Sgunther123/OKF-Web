"""Review 2026-10-21, U6: the guards the suite lacked. Determinism
across processes (T-U3), the mirror's refusals and its resilience to a
bad re-check (T-U7), the CLI paths never driven through `main` (T-U8),
the static scans for the one door and the one clock (T-U9), the
checked-in example kept clean (T-U10), and the HTML extractor's
recovery from an unclosed script with a large-feed canary (T-U12)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
from email.message import Message
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from okf_web import cli as cli_mod
from okf_web import feed, publisher, surveyor
from okf_web.llm import StaticClient
from okf_web.model import load_bundle
from okf_web.net import FetchResult
from okf_web.remote import MAX_FILES, MAX_TOTAL_BYTES, RemoteError, RemoteSource
from okf_web.surveyor import html_to_text

from conftest import EXAMPLE_BUNDLE

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "okf_web"


# --- T-U3: the same answer in every process ------------------------------------------------

_DETERMINISM_SCRIPT = r'''
import json, sys
from pathlib import Path
from okf_web.evaluator import load_questions, retrieve_scored
from okf_web.model import load_bundle
from okf_web.retrieval import HashingEmbedder
root = Path(sys.argv[1])
bundle = load_bundle(root)
questions = load_questions(root / "evaluations" / "questions.yaml")[:12]
ranked = {q.id: [(c.rel_path, r) for c, r in retrieve_scored(bundle, q.question, top_k=5)] for q in questions}
vectors = HashingEmbedder(dim=64).embed([q.question for q in questions])
print(json.dumps({"ranked": ranked, "vectors": vectors}, sort_keys=True))
'''


def _ranked_under_seed(seed: int, root: Path) -> dict:
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": str(REPO / "src")}
    proc = subprocess.run([sys.executable, "-c", _DETERMINISM_SCRIPT, str(root)],
                          env=env, capture_output=True, text=True, check=True, timeout=180)
    return json.loads(proc.stdout)


def test_rankings_and_vectors_do_not_depend_on_the_hash_seed(example_bundle):
    """The PYTHONHASHSEED incident (MEMORY, incidents) has an enforcing
    test: two interpreters with different seeds rank and embed alike."""
    first = _ranked_under_seed(1, example_bundle)
    second = _ranked_under_seed(2, example_bundle)
    assert first == second
    assert first["ranked"] and all(first["ranked"].values())
    assert any(any(v) for v in first["vectors"])


# --- T-U7: the mirror refuses what it cannot trust and outlives a bad re-check -------------

def _answer(status: int, body: bytes, headers: dict | None = None, url: str = "http://origin.example/x") -> FetchResult:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return FetchResult(url=url, status=status, headers=message, body=body)


class _Origin:
    """A fake origin: answers by the URL's tail, records every request."""

    def __init__(self, files: dict[str, FetchResult]):
        self.files = files
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, policy=None, headers=None, **_):
        self.calls.append((url, dict(headers or {})))
        tail = url.rsplit("/", 1)[-1]
        answer = self.files[tail]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _manifest(files: dict) -> bytes:
    return json.dumps({"files": files}).encode()


@pytest.mark.parametrize("body,status,phrase", [
    (b"[1, 2]", 200, "no `files` mapping"),
    (json.dumps({"files": "nope"}).encode(), 200, "no `files` mapping"),
    (b"{", 200, "not valid JSON"),
    (_manifest({f"c{i}.md": {"sha256": "x"} for i in range(MAX_FILES + 1)}), 200, "stops at"),
    (_manifest({"a.md": {"sha256": "x", "bytes": MAX_TOTAL_BYTES + 1}}), 200, "declares"),
    (_manifest({"a.md": {"bytes": 3}}), 200, "without a sha256"),
    (b"", 500, "HTTP 500"),
])
def test_the_mirror_refuses_manifests_it_cannot_trust(tmp_path, body, status, phrase):
    origin = _Origin({"manifest.json": _answer(status, body)})
    source = RemoteSource("http://origin.example", tmp_path / "mirror", fetch=origin)
    with pytest.raises(RemoteError, match=re.escape(phrase)):
        source.sync()
    assert not (tmp_path / "mirror" / "manifest.json").exists()


def test_the_mirror_honours_a_304_and_keeps_serving_through_a_bad_recheck(tmp_path):
    page = b"---\ntype: FAQ\ntitle: Shop\nstatus: stable\n---\n\n# Shop\n\nWe ship.\n"
    manifest = _manifest({"index.md": {"sha256": hashlib.sha256(page).hexdigest(), "bytes": len(page)}})
    origin = _Origin({
        "manifest.json": _answer(200, manifest, {"ETag": '"v1"'}),
        "index.md": _answer(200, page),
    })
    source = RemoteSource("http://origin.example", tmp_path / "mirror", fetch=origin, refresh_seconds=0)
    first = source.sync()
    assert first == {"changed": True, "fetched": 1, "removed": 0} and source.etag == '"v1"'
    digest = source.signature()
    assert digest == hashlib.sha256(manifest).hexdigest()

    # The conditional re-check: nothing changed, nothing fetched.
    origin.files["manifest.json"] = _answer(304, b"")
    assert source.sync() == {"changed": False, "fetched": 0, "removed": 0}
    assert origin.calls[-1][1].get("If-None-Match") == '"v1"'

    # The origin now answers badly: the mirror keeps serving what it has.
    for bad in (_answer(200, b"not json at all"), _answer(200, b"[]"), OSError("disk full")):
        origin.files["manifest.json"] = bad
        source._checked = None  # force a re-check
        assert source.signature() == digest
        assert source.last_error
    assert source.load() is not None  # the mirrored copy still loads
    assert (tmp_path / "mirror" / "index.md").read_bytes() == page


# --- T-U8: the command paths never driven through main ---------------------------------------

def _fake_signer(tmp_path: Path, ok: bool = True) -> str:
    script = tmp_path / ("signer-ok" if ok else "signer-bad")
    if ok:
        script.write_text(
            "#!/bin/sh\nprev=''\nfor a in \"$@\"; do\n"
            "  if [ \"$prev\" = \"--bundle\" ]; then printf '{\"fake\":\"sig\"}' > \"$a\"; fi\n"
            "  prev=\"$a\"\ndone\n"
        )
    else:
        script.write_text("#!/bin/sh\necho 'no OIDC identity' >&2\nexit 1\n")
    script.chmod(0o755)
    return str(script)


def test_index_rebuilds_the_root_index_from_what_is_stable(bundle_copy, capsys):
    index = bundle_copy / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "\n* [Stale](/gone.md) - a line the rebuild drops\n", encoding="utf-8")
    assert cli_mod.main(["index", str(bundle_copy)]) == 0
    assert "index.md rebuilt" in capsys.readouterr().out
    text = (bundle_copy / "index.md").read_text(encoding="utf-8")
    assert text == surveyor.rebuild_index(bundle_copy)  # idempotent, from the bundle alone
    assert "ecommerce-geo/1.12" in text and "gone.md" not in text  # the profile kept, the stale line gone


def test_publish_signs_and_a_failing_signer_exits_one(bundle_copy, tmp_path, capsys):
    dist = tmp_path / "dist"
    assert cli_mod.main(["publish", str(bundle_copy), str(dist), "--sign",
                         "--sigstore-bin", _fake_signer(tmp_path)]) == 0
    assert (dist / "manifest.json.sigstore.json").exists()
    assert "signed:" in capsys.readouterr().out
    other = tmp_path / "dist2"
    assert cli_mod.main(["publish", str(bundle_copy), str(other), "--sign",
                         "--sigstore-bin", _fake_signer(tmp_path, ok=False)]) == 1
    assert "sign exited 1" in capsys.readouterr().err
    assert (other / "manifest.json").exists()  # published, then the signing failed
    assert cli_mod.main(["sign", str(other), "--sigstore-bin", _fake_signer(tmp_path, ok=False)]) == 1
    assert "error:" in capsys.readouterr().err


class _Robots(BaseHTTPRequestHandler):
    text = b""
    status = 200

    def do_GET(self):  # noqa: N802 — the stdlib's name
        body = self.text if self.status == 200 else b""
        self.send_response(self.status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        return


@pytest.fixture
def robots_site():
    handler = type("Handler", (_Robots,), {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler
    finally:
        server.shutdown()
        server.server_close()


def test_publish_check_robots_reads_the_live_file(bundle_copy, tmp_path, capsys, robots_site):
    base, handler = robots_site
    dist = tmp_path / "dist"
    handler.text = b"User-agent: GPTBot\nDisallow: /.well-known/okf\n"
    assert cli_mod.main(["publish", str(bundle_copy), str(dist), "--site", base,
                         "--check-robots", "--allow-private-hosts"]) == 0
    err = capsys.readouterr().err
    assert "robots.txt blocks these AI agents" in err and "GPTBot" in err
    assert cli_mod.main(["publish", str(bundle_copy), str(dist), "--site", base,
                         "--check-robots", "--allow-private-hosts", "--fail-on-warnings"]) == 1
    assert "--fail-on-warnings is set" in capsys.readouterr().err
    handler.status = 404
    assert cli_mod.main(["publish", str(bundle_copy), str(dist), "--site", base,
                         "--check-robots", "--allow-private-hosts"]) == 0
    assert "all checked AI agents may fetch" in capsys.readouterr().out
    # Without the flag the loopback site is refused: inconclusive, a warning, not a verdict.
    assert cli_mod.main(["publish", str(bundle_copy), str(dist), "--site", base, "--check-robots"]) == 0
    assert "inconclusive" in capsys.readouterr().err


def test_publish_without_site_records_the_index_site(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    assert cli_mod.main(["publish", str(bundle_copy), str(dist)]) == 0
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["site"] == load_bundle(bundle_copy).site == "https://www.alpinepeakoutfitters.example"


def test_evaluate_with_a_separate_judge_records_both_identities(bundle_copy, monkeypatch, capsys):
    verdict = json.dumps({"answered": True, "grounded": True, "cited": ["policies/returns.md"]})

    def fake_llm(args, model=None):
        if model is None:
            return StaticClient(["The answer, from the context."] * 60, model="answerer")
        return StaticClient([verdict] * 60, model=model)

    monkeypatch.setattr(cli_mod, "_llm", fake_llm)
    assert cli_mod.main(["evaluate", str(bundle_copy), "--judge-model", "judge-x",
                         "--write-scorecard", "--force"]) == 0
    out = capsys.readouterr().out
    assert "coverage: 1.0" in out
    scorecard = (bundle_copy / "evaluations" / "geo-scorecard.md").read_text(encoding="utf-8")
    assert "okf-web-evaluator/answerer+judge/judge-x" in scorecard


def test_mcp_serves_a_bundle_and_a_mirror_over_stdio(bundle_copy, tmp_path, monkeypatch, capsys):
    requests = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(requests))
    assert cli_mod.main(["mcp", str(bundle_copy)]) == 0
    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.splitlines()]
    assert lines[0]["id"] == 1 and len(lines[1]["result"]["tools"]) == 5
    assert "published view" in captured.err

    dist = tmp_path / "dist"
    publisher.publish(bundle_copy, dist, site="https://shop.example")
    quiet = type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(quiet, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        monkeypatch.setattr(sys, "stdin", io.StringIO(requests))
        assert cli_mod.main(["mcp", "--url", base, "--cache-dir", str(tmp_path / "mirror"),
                             "--allow-private-hosts"]) == 0
    finally:
        server.shutdown()
        server.server_close()
    captured = capsys.readouterr()
    assert "file(s) mirrored" in captured.err and (tmp_path / "mirror" / "index.md").exists()
    assert len([json.loads(line) for line in captured.out.splitlines()]) == 2


def test_survey_records_page_errors_and_exits_one(bundle_copy, tmp_path, monkeypatch, capsys):
    urls = tmp_path / "urls.txt"
    urls.write_text("http://127.0.0.1:9/never\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_llm", lambda args, model=None: StaticClient([]))
    assert cli_mod.main(["survey", str(bundle_copy), "--urls", str(urls)]) == 1
    captured = capsys.readouterr()
    assert "errors: 1" in captured.out and "error:" in captured.err


# --- T-U9: the one door and the one clock, statically ------------------------------------------

def _code_lines(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            yield number, line


def test_pipeline_modules_keep_to_the_one_door_and_the_one_clock():
    """Every fetch is `net.safe_fetch`, every clock `model.utc_now`, and
    no module reaches for the salted builtin `hash` (CLAUDE.md
    invariants; review 2026-10-21, T-U9)."""
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        for number, line in _code_lines(path):
            where = f"{path.name}:{number}"
            if path.name != "net.py" and re.search(r"\burlopen\(|\burllib\.request\b|create_connection\(", line):
                offenders.append(f"{where} opens its own socket")
            if path.name != "model.py" and re.search(r"datetime\.now\(|date\.today\(", line):
                offenders.append(f"{where} reads its own clock")
            if re.search(r"(?<![\w.`])hash\(", line):
                offenders.append(f"{where} uses the salted builtin hash")
    assert offenders == [], offenders


# --- T-U10: the checked-in example is nobody's working directory -----------------------------

def test_the_example_tests_read_is_a_copy(example_bundle):
    assert example_bundle.resolve() != EXAMPLE_BUNDLE.resolve()
    assert (example_bundle / "index.md").read_bytes() == (EXAMPLE_BUNDLE / "index.md").read_bytes()
    load_bundle(example_bundle)  # leaves its cache in the copy, never in the repository
    assert (example_bundle / ".concepts-cache.json").exists()


# --- T-U12: the extractor recovers; a large feed lands whole --------------------------------

def test_html_to_text_recovers_from_an_unclosed_script():
    page = ("<html><body><h1>Trail Stove</h1>"
            "<script>var a = 1; if (a < 2) { go(); }"  # never closed
            "<p>Boils water fast.</p><h2>Specs</h2><p>Weight 85 g.</p></body></html>")
    text = html_to_text(page)
    assert "Boils water fast." in text and "Weight 85 g." in text
    assert "var a" not in text and "go()" not in text
    assert html_to_text("<p>One</p><script>x()</script><p>Two</p>") == "One\n\nTwo"
    assert html_to_text("<p>Tail</p><style>.a{}") == "Tail"  # nothing follows: nothing more to read


@pytest.mark.slow
def test_a_two_thousand_row_feed_lands_whole(tmp_path):
    rows = ["id,title,description,link,brand,gtin,product_type,price,availability"]
    for i in range(2000):
        rows.append(f"SKU-{i},Item {i},A compact item number {i} for camping.,"
                    f"https://shop.example/p/item-{i},Alpine Peak,,Camping > Gear,{10 + i % 90}.99 USD,in_stock")
    path = tmp_path / "big.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    root = tmp_path / "bundle"
    root.mkdir()
    result = feed.ingest_feed(path, root)
    assert len(result.written) == 2000 and not result.errors
    assert sum(1 for c in load_bundle(root).concepts.values() if c.type == "Product") == 2000
