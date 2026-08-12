"""Regression tests for the five simulation-probe findings."""

from okf_web import evaluator, surveyor
from okf_web.llm import StaticClient
from okf_web.model import load_bundle
from okf_web.publisher import evaluate_robots, publish, published_view


def _concept(path: str, title: str, url: str) -> str:
    return (
        f'<<<CONCEPT path="{path}">>>\n---\ntype: Product\n'
        f"title: {title}\nresource: {url}\n---\n\nBody for {title}.\n<<<END>>>\n"
    )


# --- Fix 1: evaluate the published view, not the working copy ------------

def test_published_view_excludes_withheld_drafts(example_bundle):
    working = load_bundle(example_bundle)
    view = published_view(working)
    assert "policies/warranty.md" in working.concepts
    assert "policies/warranty.md" not in view.concepts
    # Retrieval over the view can no longer answer from the withheld draft.
    hits = evaluator.retrieve(view, "What warranty does the store offer on its own-brand gear?")
    assert "policies/warranty.md" not in [c.rel_path for c in hits]


def test_published_view_can_mirror_machine_confirmed_mode(bundle_copy):
    working = load_bundle(bundle_copy)
    strict = published_view(working)
    loose = published_view(working, include_machine_confirmed=True)
    # warranty is risk-a, so even the loose mode withholds it.
    assert "policies/warranty.md" not in loose.concepts
    assert set(strict.concepts) <= set(loose.concepts)


# --- Fix 2: deterministic paths — no silent overwrites, no renames --------

def test_survey_path_collision_is_disambiguated(tmp_path):
    result = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://shop.example/p/trail-2", "text A", tmp_path,
        StaticClient([_concept("catalog/products/tent.md", "Trail 2 Tent",
                               "https://shop.example/p/trail-2")]), result,
    )
    surveyor.survey_page(
        "https://shop.example/p/summit-3", "text B", tmp_path,
        StaticClient([_concept("catalog/products/tent.md", "Summit 3 Tent",
                               "https://shop.example/p/summit-3")]), result,
    )
    bundle = load_bundle(tmp_path)
    titles = {c.title for c in bundle.concepts.values()}
    assert titles == {"Trail 2 Tent", "Summit 3 Tent"}  # both survive
    assert "catalog/products/tent-summit-3.md" in bundle.concepts
    assert result.collisions and "already belongs to" in result.collisions[0]


def test_survey_keeps_stable_path_when_model_renames(tmp_path):
    result = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://shop.example/p/trail-2", "text v1", tmp_path,
        StaticClient([_concept("catalog/products/trail-2.md", "Trail 2 Tent",
                               "https://shop.example/p/trail-2")]), result,
    )
    # Re-survey of the same URL with changed text; model proposes a new name.
    surveyor.survey_page(
        "https://shop.example/p/trail-2", "text v2 changed", tmp_path,
        StaticClient([_concept("catalog/products/trail-two-tent.md", "Trail 2 Tent",
                               "https://shop.example/p/trail-2")]), result,
    )
    bundle = load_bundle(tmp_path)
    assert "catalog/products/trail-2.md" in bundle.concepts  # original path kept
    assert "catalog/products/trail-two-tent.md" not in bundle.concepts  # no orphan twin
    assert "text" not in bundle.get("catalog/products/trail-2.md").body  # updated body
    assert "Body for Trail 2 Tent" in bundle.get("catalog/products/trail-2.md").body


# --- Fix 3: volatile chrome no longer defeats incrementality --------------

def test_stable_hash_ignores_dynamic_chrome(tmp_path):
    page_v1 = "Trail 2 Tent\nPacked weight 2.1 kg.\nItems in cart: 0 · Tue Aug 11"
    page_v2 = "Trail 2 Tent\nPacked weight 2.1 kg.\nItems in cart: 3 · Wed Aug 12"
    assert surveyor.stable_page_hash(page_v1) == surveyor.stable_page_hash(page_v2)
    # Real content changes still change the hash.
    page_v3 = "Trail 2 Tent\nPacked weight 2.4 kg.\nItems in cart: 3 · Wed Aug 12"
    assert surveyor.stable_page_hash(page_v1) != surveyor.stable_page_hash(page_v3)

    # End to end: the second survey of chrome-only change costs zero LLM calls.
    result = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://shop.example/p/trail-2", page_v1, tmp_path,
        StaticClient([_concept("catalog/products/trail-2.md", "Trail 2 Tent",
                               "https://shop.example/p/trail-2")]), result,
    )
    silent = StaticClient([])  # would raise if consulted
    result2 = surveyor.SurveyResult()
    surveyor.survey_page(
        "https://shop.example/p/trail-2", page_v2, tmp_path, silent, result2
    )
    assert result2.skipped_unchanged == ["https://shop.example/p/trail-2"]
    assert not silent.calls


# --- Fix 4: publish warns when the index advertises withheld concepts -----

def test_publish_warns_on_index_links_to_withheld(bundle_copy, tmp_path):
    ship = bundle_copy / "policies" / "shipping.md"
    ship.write_text(ship.read_text().replace("status: stable", "status: draft"))
    result = publish(bundle_copy, tmp_path / "dist")
    assert "policies/shipping.md" in result.withheld
    assert any("policies/shipping.md" in w for w in result.warnings)


def test_publish_emits_no_warnings_for_consistent_bundle(bundle_copy, tmp_path):
    # The example bundle's index deliberately omits the warranty draft.
    result = publish(bundle_copy, tmp_path / "dist")
    assert result.warnings == []


# --- Fix 5: robots.txt check --------------------------------------------

def test_evaluate_robots_flags_blocked_agents():
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    blocked = evaluate_robots(robots, "https://shop.example", "/.well-known/okf")
    assert blocked == ["GPTBot"]


def test_evaluate_robots_all_allowed():
    robots = "User-agent: *\nAllow: /\n"
    assert evaluate_robots(robots, "https://shop.example", "/.well-known/okf") == []


def test_evaluate_robots_blanket_block():
    robots = "User-agent: *\nDisallow: /\n"
    blocked = evaluate_robots(robots, "https://shop.example", "/.well-known/okf")
    assert set(blocked) == {
        "GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-User",
        "Google-Extended", "PerplexityBot", "CCBot",
    }
