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
