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
import re
from pathlib import Path
from typing import Protocol

from .evaluator import META_TYPES  # same exclusion as the lexical retriever
from .model import Bundle, Concept, sha256_text, split_l10n

_WORD_RE = re.compile(r"[a-z0-9]+")


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
        self.model = f"hashing-crc32-{dim}"
        self._dim = dim

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in _WORD_RE.findall(text.lower()):
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
        self._built_for: int | None = None

    # -- cache -------------------------------------------------------------
    def _load_cache(self) -> dict:
        if self.cache_path and self.cache_path.exists():
            try:
                cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if cache.get("model") == self.embedder.model:
                    return cache
            except (json.JSONDecodeError, OSError):
                pass
        return {"model": self.embedder.model, "entries": {}}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        cache = {
            "model": self.embedder.model,
            "entries": {
                rel: {"hash": self._hashes[rel], "vector": self._vectors[rel]}
                for rel in self._vectors
            },
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache), encoding="utf-8")

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
            entry = cached.get(rel)
            if entry and entry.get("hash") == digest:
                self._vectors[rel] = entry["vector"]
                self._hashes[rel] = digest
            else:
                todo.append((rel, text))
                self._hashes[rel] = digest
        if todo:
            vectors = self.embedder.embed([text for _, text in todo], input_type="document")
            for (rel, _), vec in zip(todo, vectors):
                self._vectors[rel] = vec
        self._save_cache()
        self._built_for = id(bundle)
        return len(todo)

    # -- retrieve ----------------------------------------------------------
    def __call__(self, bundle: Bundle, question: str, top_k: int = 4) -> list[Concept]:
        if self._built_for != id(bundle):
            self.build(bundle)
        query_vec = self.embedder.embed([question], input_type="query")[0]
        scored = [
            (_cosine(query_vec, vec), rel)
            for rel, vec in self._vectors.items()
            if rel in bundle.concepts
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [bundle.concepts[rel] for score, rel in scored[:top_k] if score > 0]
