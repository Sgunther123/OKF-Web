import datetime as dt

from okf_web import evaluator
from okf_web.linter import lint_bundle
from okf_web.model import Concept, load_bundle
from okf_web.publisher import publish, published_view, select_publishable
from okf_web.retrieval import EmbeddingIndex, HashingEmbedder

TODAY = dt.date(2026, 8, 5)

_PROMO = (
    "---\n"
    "type: Promotion\n"
    "title: Flash Sale\n"
    "description: 10% off tents this week.\n"
    "resource: https://shop.example/sale\n"
    "status: {status}\n"
    "{stale}"
    "verified:\n"
    "  - by: human:merch@shop.example\n"
    "    at: 2026-08-01T10:00:00Z\n"
    "sources:\n"
    "  - id: sale\n"
    "    resource: https://shop.example/sale\n"
    "x_geo:\n"
    "  risk: a\n"
    "{window}"
    "---\n\n10% off all tents.[^sale]\n\n[^sale]: sale page.\n"
)


def _write_promo(root, status="stable", starts="2026-08-01", ends="2026-08-31",
                 stale="2026-08-31"):
    window = ""
    if starts:
        window += f"  starts_at: {starts}\n"
    if ends:
        window += f"  ends_at: {ends}\n"
    stale_line = f"stale_after: {stale}\n" if stale else ""
    path = root / "promotions" / "flash-sale.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_PROMO.format(status=status, window=window, stale=stale_line))
    return path


# --- promotion model + lint ------------------------------------------------

def test_promo_window_parsing():
    concept = Concept(
        "p.md",
        {"type": "Promotion", "x_geo": {"starts_at": "2026-08-01", "ends_at": dt.date(2026, 8, 31)}},
        "",
    )
    assert concept.promo_starts == dt.date(2026, 8, 1)
    assert concept.promo_ends == dt.date(2026, 8, 31)
    assert not concept.promo_expired(dt.date(2026, 8, 31))
    assert concept.promo_expired(dt.date(2026, 9, 1))


def test_stable_promotion_without_end_date_is_error(tmp_path):
    _write_promo(tmp_path, ends=None, stale=None)
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert any(f.code == "E014" for f in findings)


def test_draft_promotion_without_end_date_warns_only(tmp_path):
    _write_promo(tmp_path, status="draft", ends=None, stale=None)
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert not any(f.code == "E014" for f in findings)
    assert any(f.code == "W027" for f in findings)


def test_misaligned_stale_after_warns(tmp_path):
    _write_promo(tmp_path, ends="2026-08-31", stale="2026-10-01")
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert any(f.code == "W027" for f in findings)


def test_expired_promotion_warns(tmp_path):
    _write_promo(tmp_path, ends="2026-07-01", stale="2026-07-01")
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert any(f.code == "W028" for f in findings)


def test_aligned_active_promotion_is_clean(tmp_path):
    _write_promo(tmp_path)
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert findings == []


# --- publisher auto-retirement --------------------------------------------

def test_publisher_withholds_expired_promotion(bundle_copy, tmp_path):
    # Expired long before any plausible "real today": date-safe forever.
    _write_promo(bundle_copy, ends="2020-01-01", stale="2020-01-01")
    result = publish(bundle_copy, tmp_path / "dist")
    assert "promotions/flash-sale.md" in result.withheld
    assert not (tmp_path / "dist" / "promotions" / "flash-sale.md").exists()


def test_select_publishable_honors_pinned_today(bundle_copy):
    bundle = load_bundle(bundle_copy)
    active_include, _ = select_publishable(bundle, today=dt.date(2026, 8, 5))
    expired_include, expired_withheld = select_publishable(
        bundle, today=dt.date(2027, 1, 1)
    )
    assert "promotions/fall-clearance.md" in active_include
    assert "promotions/fall-clearance.md" not in expired_include
    assert "promotions/fall-clearance.md" in expired_withheld
    # published_view mirrors the same clock.
    view = published_view(bundle, today=dt.date(2027, 1, 1))
    assert "promotions/fall-clearance.md" not in view.concepts


# --- embedding retrieval ---------------------------------------------------

class CountingEmbedder(HashingEmbedder):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def embed(self, texts, input_type="document"):
        self.calls += len(texts)
        return super().embed(texts, input_type)


def test_hashing_embedder_is_deterministic():
    embedder = HashingEmbedder()
    a = embedder.embed(["two person tent packed weight"])[0]
    b = embedder.embed(["two person tent packed weight"])[0]
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9  # normalized


def test_embedding_index_retrieves_relevant_concepts(example_bundle):
    bundle = load_bundle(example_bundle)
    index = EmbeddingIndex(HashingEmbedder())
    hits = index(bundle, "How much does the Alpine 2 tent weigh?", 4)
    assert "catalog/products/alpine-2-tent.md" in [c.rel_path for c in hits]
    # Scorecards stay excluded, same as lexical retrieval.
    assert all(c.type != "GEO Scorecard" for c in hits)


def test_embedding_cache_is_incremental(bundle_copy):
    bundle = load_bundle(bundle_copy)
    cache = bundle_copy / ".embeddings.json"
    cache.unlink(missing_ok=True)  # hermetic even if the source tree has a local cache
    embedder = CountingEmbedder()
    index = EmbeddingIndex(embedder, cache_path=cache)
    first = index.build(bundle)
    # Mirrors the build filter: scorecards and translation trees don't embed.
    assert first == len(
        [
            c
            for rel, c in bundle.concepts.items()
            if c.type != "GEO Scorecard" and not rel.startswith("l10n/")
        ]
    )
    assert cache.exists()

    # Fresh index over an unchanged bundle: full cache hit, zero embeds.
    embedder2 = CountingEmbedder()
    second = EmbeddingIndex(embedder2, cache_path=cache).build(load_bundle(bundle_copy))
    assert second == 0
    assert embedder2.calls == 0

    # Touch one concept; only it re-embeds.
    faq = bundle_copy / "faq" / "general.md"
    faq.write_text(faq.read_text() + "\nNew line.\n")
    third = EmbeddingIndex(CountingEmbedder(), cache_path=cache).build(load_bundle(bundle_copy))
    assert third == 1


def test_evaluate_accepts_pluggable_retriever(example_bundle):
    bundle = load_bundle(example_bundle)
    questions = evaluator.load_questions(example_bundle / "evaluations" / "questions.yaml")
    report = evaluator.evaluate(
        bundle, questions, llm=None, retriever=EmbeddingIndex(HashingEmbedder())
    )
    metrics = report.metrics(bundle)
    assert metrics["questions"] == 24
    assert metrics["retrieval_hit_rate"] == 1.0


def test_publisher_never_ships_the_embedding_cache(bundle_copy, tmp_path):
    bundle = load_bundle(bundle_copy)
    EmbeddingIndex(HashingEmbedder(), cache_path=bundle_copy / ".embeddings.json").build(bundle)
    result = publish(bundle_copy, tmp_path / "dist")
    assert not (tmp_path / "dist" / ".embeddings.json").exists()
    assert ".embeddings.json" not in result.published


def test_cli_hashing_retriever_end_to_end(bundle_copy):
    from okf_web import cli as cli_mod

    assert cli_mod.main(
        ["evaluate", str(bundle_copy), "--dry-run", "--retriever", "hashing"]
    ) == 0
