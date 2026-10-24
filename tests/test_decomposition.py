"""Review 2026-10-21, U5: the decomposition is behaviour-preserving and
the new seams hold. `init.run_init` is the first run as a library and
the command only prints what it says (A-U3); the linter's contract
types are rows of one table, the viewer renders from one view model one
section at a time, `publish` is four stages and `build_parser` one
builder per verb (A-U4); the LLM parameters carry their protocol, the
bridge's source is a protocol, the retriever's snapshot is a declared
slot and a localized view aliases nothing (A-U12)."""

from __future__ import annotations

import inspect

import pytest

from okf_web import cli as cli_mod
from okf_web import init, linter, mcp_bridge, publisher, review, surveyor, viewer
from okf_web.model import Bundle, load_bundle, localized_view
from okf_web.remote import RemoteSource

CSV = (
    "id,title,description,link,brand,gtin,product_type,price,availability\n"
    "SKU-1,Trail Stove,A compact canister stove for backpacking. Boils fast.,"
    "https://shop.example/p/trail-stove,Alpine Peak,00012345600012,Camping > Cooking,49.99 USD,in_stock\n"
    "SKU-2,Titanium Pot,A 750 ml titanium pot with lid.,"
    "https://shop.example/p/titanium-pot,Alpine Peak,,Camping > Cooking,34.99 USD,out_of_stock\n"
)


# --- A-U3: the first run as a library ---------------------------------------------------------

def test_run_init_takes_a_feed_through_its_first_publish(tmp_path):
    feed = tmp_path / "products.csv"
    feed.write_text(CSV, encoding="utf-8")
    result = init.run_init(tmp_path / "store", tmp_path / "dist", feed,
                           site="https://shop.example", by="owner@shop.example", pack="outdoor")
    assert result.exit_code == 0 and result.stopped is None
    assert sorted(result.ingest.written) == ["catalog/products/titanium-pot.md", "catalog/products/trail-stove.md"]
    assert result.index_written and load_bundle(tmp_path / "store").site == "https://shop.example"
    assert not [f for f in result.findings if f.severity == linter.ERROR]
    assert len(result.approved) == 2 and result.questions == "written"
    assert result.metrics["questions"] > 0 and "retrieval_hit_rate" in result.metrics
    assert result.publish is not None and (tmp_path / "dist" / "manifest.json").exists()
    assert result.report_path and result.report_path.exists()
    assert result.skipped == [] and result.errors == []
    assert result.lines[0].startswith("[1/7] ingesting") and any(l.startswith("[7/7] published") for l in result.lines)
    assert any('"args": ["mcp", "' in l for l in result.lines)


def test_run_init_stops_and_says_why(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("id,title,link\nSKU-1,,https://shop.example/p/x\n", encoding="utf-8")
    result = init.run_init(tmp_path / "store", tmp_path / "dist", bad)
    assert result.exit_code == 1 and result.stopped == "nothing drafted"
    assert result.publish is None and not (tmp_path / "dist").exists()
    assert any("nothing was drafted" in line for line in result.errors)
    # without --by and --pack the steps are named as skipped, with the way to take them
    feed = tmp_path / "products.csv"
    feed.write_text(CSV, encoding="utf-8")
    result = init.run_init(tmp_path / "store2", tmp_path / "dist2", feed)
    assert result.exit_code == 0 and result.approved == [] and result.questions == "skipped"
    assert len(result.skipped) == 2 and all("pass --" in line for line in result.skipped)
    assert result.publish is not None and set(result.publish.withheld) == set(result.ingest.written)
    assert not any(rel.startswith("catalog/") for rel in result.publish.published)  # drafts publish nothing


def test_the_command_prints_exactly_what_the_library_says(tmp_path, capsys):
    feed = tmp_path / "products.csv"
    feed.write_text(CSV, encoding="utf-8")
    sinks: list[str] = []
    assert cli_mod.main(["init", str(tmp_path / "a"), "--feed", str(feed), "--dist", str(tmp_path / "da"),
                         "--by", "owner@shop.example", "--pack", "outdoor"]) == 0
    printed = capsys.readouterr().out
    result = init.run_init(tmp_path / "b", tmp_path / "db", feed, by="owner@shop.example", pack="outdoor",
                           emit=sinks.append)
    assert sinks == result.lines
    normalize = lambda text: text.replace(str(tmp_path / "a"), "<B>").replace(str(tmp_path / "da"), "<D>") \
        .replace(str(tmp_path / "b"), "<B>").replace(str(tmp_path / "db"), "<D>")
    assert normalize(printed) == normalize("\n".join(result.lines) + "\n")


def test_survey_results_merge_and_the_queue_summarizes(bundle_copy):
    first = surveyor.SurveyResult(written=["a.md"], errors=["e1"], dropped_live_fields=["price"])
    second = surveyor.SurveyResult(written=["b.md"], proposed=["c.md"], collisions=["x"], quarantined=["q"],
                                   skipped_unchanged=["s"], errors=["e2"], dropped_live_fields=["stock"])
    first.extend(second)
    assert first == surveyor.SurveyResult(written=["a.md", "b.md"], proposed=["c.md"], skipped_unchanged=["s"],
                                          quarantined=["q"], collisions=["x"], errors=["e1", "e2"],
                                          dropped_live_fields=["price", "stock"])
    bundle = load_bundle(bundle_copy)
    queue = review.queue_summary(bundle)
    assert [i.concept.rel_path for i in queue.items] == [i.concept.rel_path for i in review.pending(bundle)]
    assert queue.by_risk == {"a": 1, "b": 0, "c": 0} and queue.proposed == []
    assert queue.line == "pending: 1 (a: 1, b: 0, c: 0); drift proposals: 0"


# --- A-U4: one table, one view model, four stages, one builder per verb ----------------------

def test_the_contract_types_are_one_table():
    assert set(linter.TYPE_CONTRACTS) == {"Compatibility", "Ownership Guide", "Product Passport",
                                         "Store Location", "Trade Program"}
    codes = [c.error_code for c in linter.TYPE_CONTRACTS.values()]
    assert sorted(codes) == ["E015", "E016", "E017", "E018", "E019"]
    for name, contract in linter.TYPE_CONTRACTS.items():
        assert contract.required and contract.risk_floor in ("a", "b"), name
        assert contract.stable_message(["x"]) and contract.draft_message(["x"]), name
    source = inspect.getsource(linter.lint_concept)
    for name in linter.TYPE_CONTRACTS:
        assert f'concept.type == "{name}"' not in source, f"{name} is checked outside the table"


@pytest.mark.parametrize("type_name", sorted(linter.TYPE_CONTRACTS))
def test_each_contract_row_drives_its_error_and_its_floor(type_name, tmp_path):
    contract = linter.TYPE_CONTRACTS[type_name]
    path = tmp_path / "c.md"
    path.write_text(f"---\ntype: {type_name}\ntitle: T\nstatus: stable\nx_geo:\n  risk: c\n---\n\nBody.\n", encoding="utf-8")
    from okf_web.model import Concept, parse_document
    fm, body = parse_document(path.read_text(encoding="utf-8"))
    codes = [f.code for f in linter.lint_concept(Concept("c.md", fm, body))]
    assert contract.error_code in codes and "W033" in codes
    fm["status"] = "draft"
    codes = [f.code for f in linter.lint_concept(Concept("c.md", fm, body))]
    assert "W032" in codes and contract.error_code not in codes


def test_the_viewer_renders_one_section_at_a_time(example_bundle):
    import datetime as dt
    bundle = load_bundle(example_bundle)
    today = dt.date(2026, 10, 23)
    model = viewer._view_model(bundle, today, "/.well-known/okf")
    page = viewer.build_viewer(bundle, today=today)
    assert viewer.build_viewer(bundle, today=today) == page  # byte-identical double render
    for fragment in (viewer._render_pipeline(model), viewer._render_live_values(model),
                     viewer._render_questions(model), viewer._render_posture(model)):
        assert fragment and fragment in page
    assert all(tile in page for tile in viewer._render_tiles(model))
    inventory, held = viewer._render_inventory(model)
    assert "".join(inventory) in page and held in page


def test_publish_is_four_stages_with_the_same_outcome(bundle_copy, tmp_path):
    import datetime as dt
    today = dt.date(2026, 10, 23)
    whole = publisher.publish(bundle_copy, tmp_path / "dist", site="https://www.alpinepeakoutfitters.example", today=today)
    bundle = load_bundle(bundle_copy)
    result = publisher.PublishResult(dist=tmp_path / "dist2")
    concept_include = publisher._select_and_warn(bundle, result, False, today, "warn", "https://www.alpinepeakoutfitters.example")
    assert sorted(result.withheld) == sorted(whole.withheld)
    assert set(concept_include) == {rel for rel in whole.published if rel.endswith(".md") and rel in bundle.concepts}
    publisher._audit_links(bundle, result)
    assert [w for w in result.warnings if "links" in w] == [w for w in whole.warnings if "links" in w]


def test_every_verb_has_its_own_parser_builder():
    parser = cli_mod.build_parser()
    verbs = list(parser._subparsers._group_actions[0].choices)
    assert len(verbs) == 16
    for verb in verbs:
        builder = getattr(cli_mod, f"_add_{verb.replace('-', '_')}_parser")
        assert callable(builder)
    assert "_add_" in inspect.getsource(cli_mod.build_parser) and "add_argument" not in inspect.getsource(cli_mod.build_parser)


# --- A-U12: typing hygiene ---------------------------------------------------------------------

def test_the_llm_parameters_carry_the_protocol():
    assert inspect.signature(surveyor.survey).parameters["llm"].annotation == "LLMClient"
    assert inspect.signature(init.run_init).parameters["emit"].annotation.startswith("Callable")
    from okf_web import evaluator
    assert inspect.signature(evaluator.evaluate).parameters["judge"].annotation == "LLMClient | None"
    assert inspect.signature(evaluator.generate_questions).parameters["llm"].annotation == "LLMClient"


def test_the_bridge_source_is_a_protocol_the_mirror_satisfies(tmp_path):
    assert isinstance(RemoteSource("http://origin.example", tmp_path / "m"), mcp_bridge.BundleSource)
    assert not isinstance(object(), mcp_bridge.BundleSource)
    assert mcp_bridge.BridgeState.__dataclass_fields__["source"].default is None


def test_the_lexical_index_is_a_declared_slot_and_a_view_aliases_nothing(example_bundle):
    from okf_web.evaluator import retrieve
    bundle = load_bundle(example_bundle)
    assert bundle.lexical_index is None and "lexical_index" in Bundle.__dataclass_fields__
    retrieve(bundle, "return window", 4)
    assert bundle.lexical_index is not None
    assert not Bundle.__dataclass_fields__["lexical_index"].compare
    view = localized_view(bundle, "es")
    overlaid = view.concepts["faq/general.md"]
    source = bundle.concepts["l10n/es/faq/general.md"]
    assert overlaid.frontmatter == source.frontmatter and overlaid.frontmatter is not source.frontmatter
    overlaid.frontmatter["title"] = "changed through the view"
    assert source.frontmatter["title"] != "changed through the view"
