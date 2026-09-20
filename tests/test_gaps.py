"""GAPS.md — the gap-analysis items, one section per item as they land.

Phase A: item 1 (Unicode tokenizer), item 2 (relevance floor and
scored, labeled results), item 6 (bridge revalidation and clamps).
"""

from __future__ import annotations

import json
import re

import pytest

from okf_web import cli as cli_mod
from okf_web import evaluator, mcp_bridge, text
from okf_web.model import load_bundle
from okf_web.retrieval import EmbeddingIndex, HashingEmbedder

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def _concept(root, rel, type_, title, body, status="stable", verified=True, extra=""):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = [
        "---",
        f"type: {type_}",
        f"title: {title}",
        f"status: {status}",
        "x_geo:",
        "  risk: c",
    ]
    if extra:
        fm.append(extra)
    if verified:
        fm += ["verified:", "  - by: human:qa@shop.example", "    at: 2026-08-01T00:00:00Z"]
    fm.append("---")
    path.write_text("\n".join(fm) + "\n" + body + "\n", encoding="utf-8")


def _spanish_bundle(tmp_path):
    root = tmp_path / "tienda"
    root.mkdir()
    (root / "index.md").write_text(
        "---\nokf_version: '0.2'\ntitle: Tienda\n---\n# Tienda\n", encoding="utf-8"
    )
    _concept(
        root, "policies/devoluciones.md", "Policy", "Política de devoluciones",
        "Puedes solicitar una devolución dentro de 30 días desde la entrega. "
        "El envío de vuelta es gratuito en la Península.",
    )
    _concept(
        root, "faq/shipping.md", "FAQ", "Shipping FAQ",
        "Orders ship within two business days from our Denver warehouse.",
    )
    _concept(
        root, "faq/haisou.md", "FAQ", "配送について",
        "配送は注文から3日以内に届きます。送料は無料です。",
    )
    return root


# --- item 1: one tokenizer, any script ------------------------------------------------

def test_words_fold_accents_and_case_and_keep_ascii_identical():
    assert text.words("Devolución ENVÍO año") == ["devolucion", "envio", "ano"]
    sample = "Order_status X-Ray 27mm 30-day RETURNS"
    assert text.words(sample) == re.findall(r"[a-z0-9]+", sample.lower())
    assert text.words("размер обуви") == ["размер", "обуви"]
    assert "配送" in text.words("配送は3日以内")
    assert text.words("配送 ab") == ["配送", "ab"]  # bigrams for CJK only


def test_accented_spanish_questions_retrieve_spanish_concepts(tmp_path):
    bundle = load_bundle(_spanish_bundle(tmp_path))
    hits = evaluator.retrieve(bundle, "¿Cuál es la política de devolución?")
    assert hits and hits[0].rel_path == "policies/devoluciones.md"
    # The shopper types without accents; the merchant wrote with them.
    hits = evaluator.retrieve(bundle, "devolucion 30 dias")
    assert hits and hits[0].rel_path == "policies/devoluciones.md"
    # A CJK concept has tokens now, so a CJK question can reach it at all.
    assert evaluator.retrieve(bundle, "配送は3日以内に届きますか") != []


def test_hashing_embedder_folds_too_and_renamed_its_model():
    embedder = HashingEmbedder()
    assert embedder.model == "hashing-crc32u-512"
    a, b = embedder.embed(["devolución gratuita", "devolucion gratuita"])
    assert a == b


# --- item 2: a floor that removes noise and scores that travel --------------------------

def test_retrieve_scored_reports_relevance_and_applies_the_floor(tmp_path):
    bundle = load_bundle(_spanish_bundle(tmp_path))
    pairs = evaluator.retrieve_scored(bundle, "free return shipping from Denver")
    assert pairs and all(0.0 < r <= 1.0 for _, r in pairs)
    assert [c for c, _ in pairs] == evaluator.retrieve(bundle, "free return shipping from Denver")
    # A high floor turns a weak overlap into an honest empty result.
    assert evaluator.retrieve_scored(bundle, "warehouse quantum flux", min_relevance=0.9) == []
    assert evaluator.retrieve(bundle, "quantum flux capacitor") == []


def test_example_bundle_keeps_its_hit_rate_under_the_default_floor():
    bundle = load_bundle(REPO / "bundle-example")
    questions = evaluator.load_questions(REPO / "bundle-example" / "evaluations" / "questions.yaml")
    assert all(evaluator.retrieve(bundle, q.question) for q in questions)


def test_min_relevance_flag_reaches_the_evaluator(capsys):
    assert cli_mod.main([
        "evaluate", str(REPO / "bundle-example"), "--dry-run", "--min-relevance", "0.95",
    ]) == 0
    out = capsys.readouterr().out
    rate = float(re.search(r"^retrieval_hit_rate: ([0-9.]+)", out, re.M).group(1))
    assert rate < 1.0


# --- item 6: the bridge labels coverage, clamps, and revalidates -----------------------

def _call(state, name, **arguments):
    response = mcp_bridge.handle_message(
        state, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}},
    )
    result = response["result"]
    text_ = result["content"][0]["text"]
    return result["isError"], text_


def test_search_results_carry_relevance_and_coverage(tmp_path):
    state = mcp_bridge.build_state(_spanish_bundle(tmp_path))
    is_error, body = _call(state, "okf_search", question="How fast do orders ship from Denver?")
    payload = json.loads(body)
    assert not is_error and payload["coverage"] == "found"
    assert payload["results"][0]["path"] == "faq/shipping.md"
    assert 0.0 < payload["results"][0]["relevance"] <= 1.0

    _, body = _call(state, "okf_search", question="quantum flux capacitor lunar module")
    payload = json.loads(body)
    assert payload["results"] == [] and payload["coverage"] == "none"
    assert "does not cover" in payload["note"]


def test_search_clamps_top_k_and_clips_long_bodies(tmp_path):
    root = _spanish_bundle(tmp_path)
    _concept(root, "faq/long.md", "FAQ", "Long answer", "shipping " * 3000)
    state = mcp_bridge.build_state(root)
    _, body = _call(state, "okf_search", question="shipping", top_k=500)
    payload = json.loads(body)
    assert 0 < len(payload["results"]) <= mcp_bridge.MAX_TOP_K
    long_hit = next(r for r in payload["results"] if r["path"] == "faq/long.md")
    assert long_hit["truncated"] is True
    assert len(long_hit["body"]) <= mcp_bridge._BODY_LIMIT + 1
    assert "okf_get" in long_hit["note"]


def test_get_miss_names_nearest_paths_not_the_whole_bundle():
    state = mcp_bridge.build_state(REPO / "bundle-example")
    is_error, message = _call(state, "okf_get", path="policies/return.md")
    assert is_error
    assert "policies/returns.md" in message
    assert message.count(".md") <= mcp_bridge._SUGGESTIONS + 1
    assert len(message) < 400


def test_bridge_serves_a_concept_added_during_the_session(tmp_path):
    root = _spanish_bundle(tmp_path)
    state = mcp_bridge.build_state(root)
    _, before = _call(state, "okf_info")
    _concept(root, "faq/hours.md", "FAQ", "Opening hours", "We open at nine every weekday.")
    _, after = _call(state, "okf_info")
    counts_before = json.loads(before)["concepts_by_type"]
    counts_after = json.loads(after)["concepts_by_type"]
    assert counts_after["FAQ"] == counts_before["FAQ"] + 1
    _, body = _call(state, "okf_search", question="when do you open on weekdays")
    assert json.loads(body)["results"][0]["path"] == "faq/hours.md"


# --- item 4 (part): the embedding cache is versioned and written atomically -----------

def test_embedding_cache_is_versioned_and_an_unversioned_cache_is_ignored(tmp_path):
    root = _spanish_bundle(tmp_path)
    bundle = load_bundle(root)
    cache = tmp_path / ".embeddings.json"
    cache.write_text(json.dumps({"model": "hashing-crc32u-512", "entries": {"faq/shipping.md": {"hash": "x", "vector": [1.0]}}}), encoding="utf-8")
    index = EmbeddingIndex(HashingEmbedder(), cache_path=cache)
    embedded = index.build(bundle)
    assert embedded == len(bundle.concepts)  # the unversioned cache vouched for nothing
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["model"] == "hashing-crc32u-512"
    assert not list(tmp_path.glob(".*.tmp"))


# --- item 10: any published bundle, served with no server of ours -------------------------

import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from okf_web import publisher, signing
from okf_web.net import FetchError, FetchPolicy
from okf_web.remote import RemoteError, RemoteSource, cache_dir_for

LOOPBACK = FetchPolicy(allow_loopback=True)


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 — silence the test server
        pass


@pytest.fixture
def served_dist(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publisher.publish(bundle_copy, dist, site="https://shop.example")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(dist)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", dist, bundle_copy
    finally:
        server.shutdown()
        server.server_close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_remote_source_mirrors_and_verifies_a_published_bundle(served_dist, tmp_path):
    base, dist, _ = served_dist
    mirror = tmp_path / "mirror"
    src = RemoteSource(base, mirror, policy=LOOPBACK)
    result = src.sync()
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    markdown = [rel for rel in manifest["files"] if rel.endswith(".md")]
    assert result["changed"] and result["fetched"] == len(markdown)
    assert (mirror / "index.md").exists() and (mirror / ".okf-dist").exists()
    assert not (mirror / "jsonld").exists()  # only the knowledge files are mirrored
    errors, _warnings = signing.verify_integrity(mirror)
    assert errors == []
    # Nothing to do the second time: the manifest is re-checked conditionally.
    assert src.sync()["fetched"] == 0


def test_bridge_serves_a_remote_bundle_and_follows_a_republish(served_dist, tmp_path):
    base, dist, bundle_root = served_dist
    src = RemoteSource(base, tmp_path / "mirror", policy=LOOPBACK, refresh_seconds=0)
    src.sync()
    state = mcp_bridge.build_state(None, source=src)
    _, body = _call(state, "okf_search", question="Can I return an item after 30 days?")
    payload = json.loads(body)
    assert payload["coverage"] == "found"
    assert "policies/returns.md" in [r["path"] for r in payload["results"]]
    _, info = _call(state, "okf_info")
    assert json.loads(info)["source"]["url"] == base

    returns = bundle_root / "policies" / "returns.md"
    returns.write_text(
        returns.read_text(encoding="utf-8") + "\nMembers get an extended 45-day window.\n",
        encoding="utf-8",
    )
    publisher.publish(bundle_root, dist, site="https://shop.example")
    src.last_modified = src.etag = None  # the test server stamps to the second
    assert src.sync()["fetched"] == 1  # only the changed file travels
    _, text_ = _call(state, "okf_get", path="policies/returns.md")
    assert "45-day window" in text_


def test_remote_refuses_a_file_that_fails_its_hash(served_dist, tmp_path):
    base, dist, _ = served_dist
    index = dist / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    src = RemoteSource(base, tmp_path / "mirror", policy=LOOPBACK)
    with pytest.raises(RemoteError, match="sha256"):
        src.sync()


def test_remote_ignores_unsafe_manifest_paths_and_removes_delisted_files(served_dist, tmp_path):
    base, dist, _ = served_dist
    mirror = tmp_path / "mirror"
    src = RemoteSource(base, mirror, policy=LOOPBACK)
    src.sync()
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    bogus = {"sha256": "0" * 64, "bytes": 1}
    for rel in ("../escape.md", "/abs.md", ".hidden/x.md", "C:\\win.md"):
        manifest["files"][rel] = bogus
    victim = next(rel for rel in manifest["files"] if rel.startswith("faq/"))
    del manifest["files"][victim]
    (dist / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    src.last_modified = src.etag = None
    result = src.sync()
    assert result["removed"] == 1 and not (mirror / victim).exists()
    assert not (tmp_path / "escape.md").exists() and not (mirror / ".hidden").exists()


def test_remote_keeps_serving_through_an_origin_outage(served_dist, tmp_path):
    base, _dist, _ = served_dist
    src = RemoteSource(base, tmp_path / "mirror", policy=LOOPBACK, refresh_seconds=0)
    src.sync()
    before = src.signature()
    src.base_url = f"http://127.0.0.1:{_free_port()}"
    assert src.signature() == before
    assert src.last_error and "could not fetch" in src.last_error
    assert src.load().concepts


def test_remote_refuses_private_hosts_without_the_flag(tmp_path):
    with pytest.raises(FetchError):
        RemoteSource("http://127.0.0.1:8/", tmp_path / "mirror").sync()


def test_mcp_url_flag_and_argument_rules(capsys):
    args = cli_mod.build_parser().parse_args(["mcp", "--url", "https://shop.example/.well-known/okf"])
    assert args.url and args.bundle is None and args.refresh_seconds == 300.0
    assert cli_mod.main(["mcp"]) == 2
    assert "--url" in capsys.readouterr().err
    assert cli_mod.main(["mcp", str(REPO / "bundle-example"), "--url", "https://x.example"]) == 2


def test_cache_dir_is_stable_and_outside_any_bundle():
    a = cache_dir_for("https://shop.example/.well-known/okf")
    b = cache_dir_for("https://shop.example/.well-known/okf/")
    assert a == b and a.parts[-3:-1] == ("okf-web", "remote")
