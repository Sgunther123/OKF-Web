import datetime as dt

from okf_web.linter import ERROR, WARNING, has_errors, lint_bundle

TODAY = dt.date(2026, 8, 5)


def test_example_bundle_has_no_errors(example_bundle):
    _, findings = lint_bundle(example_bundle, today=TODAY)
    errors = [f for f in findings if f.severity == ERROR]
    assert errors == [], "example bundle must stay conformant:\n" + "\n".join(
        str(f) for f in errors
    )


def test_example_bundle_has_no_warnings(example_bundle):
    _, findings = lint_bundle(example_bundle, today=TODAY)
    warnings = [f for f in findings if f.severity == WARNING]
    assert warnings == [], "example bundle should be warning-clean:\n" + "\n".join(
        str(f) for f in warnings
    )


def test_missing_type_is_error(tmp_path):
    (tmp_path / "bad.md").write_text("---\ntitle: No type\n---\n\nbody\n")
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E002" for f in findings)
    assert has_errors(findings)


def test_unparseable_frontmatter_is_error(tmp_path):
    (tmp_path / "bad.md").write_text("no frontmatter at all\n")
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E001" for f in findings)


def test_high_risk_stable_without_human_verifier_is_error(tmp_path):
    (tmp_path / "policy.md").write_text(
        "---\n"
        "type: Policy\n"
        "status: stable\n"
        "sources:\n"
        "  - id: p\n"
        "    resource: https://example.test/p\n"
        "x_geo:\n"
        "  risk: a\n"
        "---\n\nClaim.[^p]\n\n[^p]: p.\n"
    )
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E010" for f in findings)

    # Same concept as a draft is fine (that's the review queue's job).
    (tmp_path / "policy.md").write_text(
        "---\n"
        "type: Policy\n"
        "status: draft\n"
        "sources:\n"
        "  - id: p\n"
        "    resource: https://example.test/p\n"
        "x_geo:\n"
        "  risk: a\n"
        "---\n\nClaim.[^p]\n\n[^p]: p.\n"
    )
    _, findings = lint_bundle(tmp_path)
    assert not any(f.code == "E010" for f in findings)


def test_high_risk_without_sources_is_error(tmp_path):
    (tmp_path / "policy.md").write_text(
        "---\ntype: Policy\nstatus: draft\nx_geo:\n  risk: a\n---\n\nClaim.\n"
    )
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E013" for f in findings)


def test_attested_computation_requires_runtime(tmp_path):
    (tmp_path / "cap.md").write_text(
        "---\ntype: Attested Computation\nstatus: draft\n---\n\nbody\n"
    )
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E011" for f in findings)


def test_product_requires_resource(tmp_path):
    (tmp_path / "p.md").write_text("---\ntype: Product\nstatus: draft\n---\n\nbody\n")
    _, findings = lint_bundle(tmp_path)
    assert any(f.code == "E012" for f in findings)


def test_dangling_footnote_and_broken_link_warn(tmp_path):
    (tmp_path / "c.md").write_text(
        "---\ntype: FAQ\n---\n\nA claim.[^nope] See [x](/missing.md).\n"
    )
    _, findings = lint_bundle(tmp_path)
    codes = {f.code for f in findings}
    assert "W020" in codes
    assert "W022" in codes


def test_stale_concept_warns(tmp_path):
    (tmp_path / "c.md").write_text(
        "---\ntype: FAQ\nstale_after: 2026-01-01\n---\n\nbody\n"
    )
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert any(f.code == "W021" for f in findings)
