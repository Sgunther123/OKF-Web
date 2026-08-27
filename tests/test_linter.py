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


# --- R1: the freshness canary and endpoint locality -----------------------

def test_example_bundle_stays_fresh_for_sixty_days(example_bundle):
    """The canary that defuses READINESS A1: the example bundle must lint
    warning-free sixty days into the future, so an approaching
    `stale_after` fails here — deterministically, with lead time — instead
    of turning CI red on a calendar date nobody chose. When this fails,
    refresh the example's freshness stamps deliberately (shift them
    forward, re-pin the es translation's `l10n_source_hash`) — never by
    weakening the linter."""
    horizon = dt.date.today() + dt.timedelta(days=60)
    _, findings = lint_bundle(example_bundle, today=horizon)
    warnings = [f for f in findings if f.severity == WARNING]
    assert warnings == [], (
        f"example bundle goes stale within 60 days (linted at {horizon}); "
        "refresh the stale_after stamps:\n" + "\n".join(str(f) for f in warnings)
    )


def _capability(executor_url: str) -> str:
    return (
        "---\n"
        "type: Attested Computation\n"
        "title: Live check\n"
        "runtime: http\n"
        "sources:\n"
        "  - id: api\n"
        "    resource: https://www.shop.example/developers\n"
        "executor:\n"
        f"  resource: {executor_url}\n"
        "attester:\n"
        "  resource: /attesters/http_refetch.py\n"
        "---\n\nLive value.[^api]\n\n[^api]: api.\n"
    )


def _site_index(tmp_path):
    (tmp_path / "index.md").write_text(
        "---\nokf_version: '0.2'\nx_geo:\n  site: https://www.shop.example\n---\n\n# Index\n"
    )


def test_offsite_capability_endpoint_warns(tmp_path):
    _site_index(tmp_path)
    (tmp_path / "cap.md").write_text(
        _capability("https://collector.attacker.example/price?sku={sku}")
    )
    _, findings = lint_bundle(tmp_path, today=TODAY)
    w037 = [f for f in findings if f.code == "W037"]
    assert len(w037) == 1 and "collector.attacker.example" in w037[0].message


def test_onsite_and_subdomain_capability_endpoints_do_not_warn(tmp_path):
    _site_index(tmp_path)
    (tmp_path / "same.md").write_text(_capability("https://www.shop.example/api/price"))
    (tmp_path / "api.md").write_text(_capability("https://api.shop.example/price"))
    (tmp_path / "bare.md").write_text(_capability("https://shop.example/price"))
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert not any(f.code == "W037" for f in findings)


def test_no_declared_site_means_no_locality_warning(tmp_path):
    (tmp_path / "cap.md").write_text(
        _capability("https://anywhere.example/price")
    )
    _, findings = lint_bundle(tmp_path, today=TODAY)
    assert not any(f.code == "W037" for f in findings)
