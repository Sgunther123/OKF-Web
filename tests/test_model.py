import datetime as dt

from okf_web.model import (
    Concept,
    TRUST_HUMAN,
    TRUST_MACHINE,
    TRUST_UNVERIFIED,
    load_bundle,
    parse_document,
    render_document,
)


def test_parse_and_render_roundtrip():
    text = "---\ntype: Product\ntitle: Widget\n---\n\n# Overview\n\nA widget.\n"
    fm, body = parse_document(text)
    assert fm["type"] == "Product"
    rendered = render_document(fm, body)
    fm2, body2 = parse_document(rendered)
    assert fm2 == fm
    assert body2.strip() == body.strip()


def test_dates_render_as_iso_strings():
    fm = {
        "type": "Policy",
        "stale_after": dt.date(2027, 2, 1),
        "generated": {"by": "x/y", "at": dt.datetime(2026, 8, 4, 9, 0, tzinfo=dt.timezone.utc)},
    }
    rendered = render_document(fm, "\nbody\n")
    assert "stale_after: '2027-02-01'" in rendered or "stale_after: 2027-02-01" in rendered
    assert "2026-08-04T09:00:00Z" in rendered


def test_trust_tiers():
    unverified = Concept("a.md", {"type": "Product"}, "")
    assert unverified.trust_tier == TRUST_UNVERIFIED

    machine = Concept(
        "b.md",
        {"type": "Product", "verified": [{"by": "process:check", "at": "2026-08-04"}]},
        "",
    )
    assert machine.trust_tier == TRUST_MACHINE

    human = Concept(
        "c.md",
        {
            "type": "Product",
            "verified": [
                {"by": "process:check", "at": "2026-08-04"},
                {"by": "human:reviewer@example.test", "at": "2026-08-05"},
            ],
        },
        "",
    )
    assert human.trust_tier == TRUST_HUMAN


def test_bare_verified_mapping_is_single_entry():
    concept = Concept(
        "a.md",
        {"type": "Product", "verified": {"by": "human:x", "at": "2026-08-05"}},
        "",
    )
    assert len(concept.verified_entries) == 1
    assert concept.trust_tier == TRUST_HUMAN


def test_staleness():
    concept = Concept("a.md", {"type": "Product", "stale_after": "2026-06-01"}, "")
    assert concept.is_stale(dt.date(2026, 8, 5))
    assert not concept.is_stale(dt.date(2026, 5, 1))
    no_stale = Concept("b.md", {"type": "Product"}, "")
    assert not no_stale.is_stale(dt.date(2099, 1, 1))


def test_status_defaults_to_stable():
    assert Concept("a.md", {"type": "Product"}, "").status == "stable"


def test_load_bundle_separates_reserved_and_internal(tmp_path):
    (tmp_path / "index.md").write_text("---\nokf_version: '0.2'\n---\n\n# T\n")
    (tmp_path / "log.md").write_text("# Directory Update Log\n")
    (tmp_path / "c.md").write_text("---\ntype: FAQ\n---\n\nbody\n")
    internal = tmp_path / "_review" / "proposed"
    internal.mkdir(parents=True)
    (internal / "c.md").write_text("---\ntype: FAQ\n---\n\nnew\n")

    bundle = load_bundle(tmp_path)
    assert set(bundle.concepts) == {"c.md"}
    assert set(bundle.indexes) == {"index.md"}
    assert set(bundle.logs) == {"log.md"}
    assert bundle.okf_version == "0.2"


def test_resolve_link():
    from pathlib import Path

    from okf_web.model import Bundle

    b = Bundle(root=Path("."))
    assert b.resolve_link("catalog/products/a.md", "/policies/returns.md") == "policies/returns.md"
    assert b.resolve_link("catalog/products/a.md", "../tents.md") == "catalog/tents.md"
    assert b.resolve_link("catalog/products/a.md", "./b.md") == "catalog/products/b.md"
