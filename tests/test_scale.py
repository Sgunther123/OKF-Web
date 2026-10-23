"""READINESS R4: scale headroom — the parse cache, the inverted
retrieval index, and streaming manifest hashing."""

import datetime as dt
import hashlib
import json

from okf_web.evaluator import retrieve
from okf_web.model import CONCEPT_CACHE_NAME, load_bundle
from okf_web.publisher import publish


def _write_concept(root, rel, title="Thing", body="A fact about camping gear.\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "type: FAQ\n"
        f"title: {title}\n"
        "stale_after: 2028-02-01\n"
        "status: stable\n"
        "---\n\n" + body
    )
    return path


def test_parse_cache_round_trips_documents_exactly(tmp_path):
    _write_concept(tmp_path, "faq/a.md", "Alpha")
    _write_concept(tmp_path, "faq/b.md", "Beta")
    cold = load_bundle(tmp_path)
    assert (tmp_path / CONCEPT_CACHE_NAME).exists()
    warm = load_bundle(tmp_path)
    assert set(warm.concepts) == set(cold.concepts)
    for rel in cold.concepts:
        assert warm.concepts[rel].frontmatter == cold.concepts[rel].frontmatter
        assert warm.concepts[rel].body == cold.concepts[rel].body
    # YAML's typed scalars survive the JSON round trip as their types —
    # a warm-loaded date is a date, not a string.
    assert isinstance(warm.concepts["faq/a.md"].frontmatter["stale_after"], dt.date)


def test_parse_cache_invalidates_on_edit_and_delete(tmp_path):
    _write_concept(tmp_path, "faq/a.md", "Alpha")
    path_b = _write_concept(tmp_path, "faq/b.md", "Beta")
    load_bundle(tmp_path)  # populate the cache

    _write_concept(tmp_path, "faq/a.md", "Alpha revised", body="New body text entirely.\n")
    path_b.unlink()
    reloaded = load_bundle(tmp_path)
    assert reloaded.concepts["faq/a.md"].title == "Alpha revised"
    assert "New body" in reloaded.concepts["faq/a.md"].body
    assert "faq/b.md" not in reloaded.concepts
    # The rewritten cache reflects the deletion too.
    again = load_bundle(tmp_path)
    assert "faq/b.md" not in again.concepts


def test_corrupt_cache_degrades_to_full_parse(tmp_path):
    _write_concept(tmp_path, "faq/a.md", "Alpha")
    (tmp_path / CONCEPT_CACHE_NAME).write_text("{not json at all")
    bundle = load_bundle(tmp_path)
    assert bundle.concepts["faq/a.md"].title == "Alpha"


def test_broken_frontmatter_round_trips_through_cache(tmp_path):
    (tmp_path / "bad.md").write_text("---\ntitle: [unclosed\n---\n\nbody\n")
    _write_concept(tmp_path, "ok.md", "Fine")
    cold = load_bundle(tmp_path)
    assert "bad.md" in cold.broken
    warm = load_bundle(tmp_path)
    assert warm.broken["bad.md"] == cold.broken["bad.md"]
    assert "ok.md" in warm.concepts


def test_cache_file_never_publishes(example_bundle, tmp_path):
    load_bundle(example_bundle)  # ensure the cache exists in the source
    result = publish(example_bundle, tmp_path / "dist")
    assert CONCEPT_CACHE_NAME not in {r.split("/")[-1] for r in result.published}
    assert not (tmp_path / "dist" / CONCEPT_CACHE_NAME).exists()
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    assert all(CONCEPT_CACHE_NAME not in rel for rel in manifest["files"])


def test_use_cache_false_bypasses_cache(tmp_path):
    _write_concept(tmp_path, "faq/a.md", "Alpha")
    load_bundle(tmp_path, use_cache=False)
    assert not (tmp_path / CONCEPT_CACHE_NAME).exists()


def test_lexical_index_caches_per_bundle_instance(example_bundle):
    bundle = load_bundle(example_bundle)
    first = retrieve(bundle, "what is the return window", 4)
    assert hasattr(bundle, "_lexical_cache")
    second = retrieve(bundle, "what is the return window", 4)
    assert [c.rel_path for c in first] == [c.rel_path for c in second]
    assert first and first[0].rel_path == "policies/returns.md"
    # A fresh instance builds its own snapshot.
    other = load_bundle(example_bundle)
    assert not hasattr(other, "_lexical_cache")
    assert [c.rel_path for c in retrieve(other, "what is the return window", 4)] == [
        c.rel_path for c in first
    ]


def test_manifest_hashes_match_full_file_digests(example_bundle, tmp_path):
    # A multi-chunk binary asset must hash identically to a whole-file
    # digest (the chunked reader is an implementation detail).
    result = publish(example_bundle, tmp_path / "dist")
    big = tmp_path / "dist" / "media" / "blob.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(bytes(range(256)) * 1024)  # 256 KB, several chunks
    from okf_web.model import file_digest

    sha, size = file_digest(big)
    assert sha == hashlib.sha256(big.read_bytes()).hexdigest()
    assert size == big.stat().st_size
    manifest = json.loads((tmp_path / "dist" / "manifest.json").read_text())
    sample = next(iter(manifest["files"]))
    data = (tmp_path / "dist" / sample).read_bytes()
    assert manifest["files"][sample]["sha256"] == hashlib.sha256(data).hexdigest()
