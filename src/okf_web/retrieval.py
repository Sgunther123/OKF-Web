"""Pluggable retrieval: embedding-based ranking behind the same
interface as the default lexical retriever.

The evaluator's contract is one callable — ``(bundle, question,
top_k) -> [Concept]`` — so retrieval strategy is swappable without
touching the harness or the metrics. This module provides the
embedding implementation:

* :class:`VoyageClient` — real semantic embeddings via Voyage AI
  (Anthropic's recommended embeddings partner). Needs
  ``pip install okf-web[embed]`` and ``VOYAGE_API_KEY``.
* :class:`HashingEmbedder` — a dependency-free feature-hashing
  embedder. Deterministic and local; its quality is roughly lexical
  (it cannot know synonyms), so it is the test vehicle and offline
  fallback, not the semantic upgrade — that's what Voyage is for.
* :class:`EmbeddingIndex` — the retriever itself, with an incremental
  on-disk cache (``<bundle>/.embeddings.json``): concepts are
  re-embedded only when their text hash changes, mirroring the
  surveyor's source-hash economics. The cache is a hidden file, which
  the publisher never ships.
"""

from __future__ import annotations

import json
import math
import zlib
from pathlib import Path
from typing import Protocol

from .evaluator import META_TYPES  # same exclusion as the lexical retriever
from .model import Bundle, Concept, sha256_text, split_l10n, write_atomic
from .text import words


class EmbeddingClient(Protocol):
    model: str

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        ...


class VoyageClient:
    """Voyage AI embeddings. ``input_type`` distinguishes documents
    from queries, which measurably helps retrieval quality."""

    def __init__(self, model: str = "voyage-3.5"):
        try:
            import voyageai
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "the `voyageai` package is required for embedding retrieval; "
                "install with `pip install okf-web[embed]` and set VOYAGE_API_KEY"
            ) from exc
        self.model = model
        self._client = voyageai.Client()

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        result = self._client.embed(texts, model=self.model, input_type=input_type)
        return result.embeddings


class HashingEmbedder:
    """Deterministic feature-hashing embedder (no dependencies, no
    network). Tokens hash into a fixed-dimension count vector that is
    then L2-normalized — cosine similarity over these is essentially
    smoothed lexical overlap.

    Tokens are bucketed with crc32, NOT Python's ``hash()``: the
    builtin is salted per process (PYTHONHASHSEED), which would make
    vectors differ between runs — rankings would wobble and the
    on-disk cache would silently disagree with fresh query vectors.
    Determinism here means across processes, not just within one.
    """

    def __init__(self, dim: int = 512):
        # crc32 in the model id: caches written by the old salted
        # implementation key differently and rebuild automatically.
        # The `u` marks the Unicode-folding tokenizer (GAPS item 1):
        # vectors of accented text changed, so those caches rebuild too.
        self.model = f"hashing-crc32u-{dim}"
        self._dim = dim

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in words(text):
                vec[zlib.crc32(token.encode("utf-8")) % self._dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


CACHE_NAME = ".embeddings.json"
_CACHE_VERSION = 2  # 1: no version key, bare write; 2: versioned, written atomically


def _hashes_signature(hashes: dict[str, str]) -> str:
    return sha256_text(
        "\n".join(f"{rel}\x00{digest}" for rel, digest in sorted(hashes.items()))
    )


def _bundle_signature(bundle: Bundle) -> str:
    """Content identity of the retrievable slice of a bundle."""
    return _hashes_signature({
        rel: sha256_text(concept.retrieval_text())
        for rel, concept in bundle.concepts.items()
        if concept.type not in META_TYPES and split_l10n(rel) is None
    })


class EmbeddingIndex:
    """Embedding retriever with an incremental cache.

    Callable with the evaluator's retriever signature:
    ``index(bundle, question, top_k) -> [Concept]``. The index builds
    lazily on first use and re-embeds only concepts whose retrieval
    text changed since the cache was written (or everything, when the
    embedding model changed).
    """

    def __init__(self, embedder: EmbeddingClient, cache_path: Path | str | None = None):
        self.embedder = embedder
        self.cache_path = Path(cache_path) if cache_path else None
        self._vectors: dict[str, list[float]] = {}
        self._hashes: dict[str, str] = {}
        self._built_for: str | None = None

    # -- cache -------------------------------------------------------------
    def _load_cache(self) -> dict:
        if self.cache_path and self.cache_path.exists():
            try:
                cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if (
                    isinstance(cache, dict)
                    and cache.get("version") == _CACHE_VERSION
                    and cache.get("model") == self.embedder.model
                    and isinstance(cache.get("entries"), dict)
                ):
                    return cache
            except (json.JSONDecodeError, OSError):
                pass
        return {"model": self.embedder.model, "entries": {}}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        cache = {
            "version": _CACHE_VERSION,
            "model": self.embedder.model,
            "entries": {
                rel: {"hash": self._hashes[rel], "vector": self._vectors[rel]}
                for rel in self._vectors
            },
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic like every other working-state file (GAPS item 4): a
        # SIGTERM mid-write leaves the previous cache, never a torn one.
        write_atomic(self.cache_path, json.dumps(cache))

    def _cached_vector(self, entry, digest: str) -> list[float] | None:
        """The cached vector for a concept whose text hashes to ``digest``,
        or None when the entry is absent, for another text, or not a
        vector at all (a null, a string, a wrong dimension): a malformed
        working-state entry is a miss to re-embed, never an exception
        (review 2026-10-21, L-U10; the parse cache already held this
        rule, EDGE-CASES S8)."""
        if not isinstance(entry, dict) or entry.get("hash") != digest:
            return None
        vector = entry.get("vector")
        if not isinstance(vector, list) or not vector:
            return None
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector):
            return None
        expected = getattr(self.embedder, "_dim", None)
        if expected is not None and len(vector) != expected:
            return None
        return [float(x) for x in vector]

    # -- build -------------------------------------------------------------
    def build(self, bundle: Bundle) -> int:
        """(Re)build vectors for the bundle; returns how many concepts
        were freshly embedded (0 = full cache hit)."""
        cache = self._load_cache()
        cached = cache.get("entries", {})
        self._vectors, self._hashes = {}, {}
        todo: list[tuple[str, str]] = []
        for rel, concept in bundle.concepts.items():
            if concept.type in META_TYPES or split_l10n(rel) is not None:
                continue
            text = concept.retrieval_text()
            digest = sha256_text(text)
            vector = self._cached_vector(cached.get(rel), digest)
            if vector is not None:
                self._vectors[rel] = vector
                self._hashes[rel] = digest
            else:
                todo.append((rel, text))
                self._hashes[rel] = digest
        if todo:
            vectors = self.embedder.embed([text for _, text in todo], input_type="document")
            for (rel, _), vec in zip(todo, vectors):
                self._vectors[rel] = vec
        self._save_cache()
        self._built_for = _hashes_signature(self._hashes)
        return len(todo)

    # -- retrieve ----------------------------------------------------------
    def scored(self, bundle: Bundle, question: str, top_k: int = 4) -> list[tuple[Concept, float]]:
        """``(concept, cosine)`` pairs, best first; the bridge shows the
        cosine as the hit's relevance."""
        # Content-addressed staleness, never object identity: a recycled
        # `id()` must not serve another bundle's vectors, and an in-place
        # edit must re-embed. Re-hashing is cheap next to embedding, and
        # cheaper than a stale answer — the per-query cost is kept on
        # purpose (GAPS item 6 records the trade-off).
        if self._built_for != _bundle_signature(bundle):
            self.build(bundle)
        query_vec = self.embedder.embed([question], input_type="query")[0]
        scored = [
            (_cosine(query_vec, vec), rel)
            for rel, vec in self._vectors.items()
            if rel in bundle.concepts
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            (bundle.concepts[rel], round(score, 3))
            for score, rel in scored[:top_k]
            if score > 0
        ]

    def __call__(self, bundle: Bundle, question: str, top_k: int = 4) -> list[Concept]:
        return [c for c, _ in self.scored(bundle, question, top_k)]
