import json

import pytest

from okf_web import review
from okf_web.model import TRUST_HUMAN, load_bundle
from okf_web.publisher import PublishError, publish


def test_pending_queue_lists_draft_warranty_first(bundle_copy):
    bundle = load_bundle(bundle_copy)
    items = review.pending(bundle)
    paths = [i.concept.rel_path for i in items]
    assert "policies/warranty.md" in paths
    # High-risk items sort first.
    assert items[0].concept.risk == "a"
    # Stable machine artifacts (risk c) don't demand human attention.
    assert "evaluations/geo-scorecard.md" not in paths


def test_approve_stamps_human_verification_and_logs(bundle_copy):
    bundle = load_bundle(bundle_copy)
    concept = review.approve(
        bundle, "policies/warranty.md", "legal@alpinepeakoutfitters.example"
    )
    assert concept.status == "stable"
    assert concept.trust_tier == TRUST_HUMAN

    # Round-trips from disk, and the log recorded the event.
    reloaded = load_bundle(bundle_copy).get("policies/warranty.md")
    assert reloaded.trust_tier == TRUST_HUMAN
    assert reloaded.status == "stable"
    log_text = (bundle_copy / "log.md").read_text()
    assert "human:legal@alpinepeakoutfitters.example" in log_text

    # Approved concept now clears the review queue.
    remaining = [i.concept.rel_path for i in review.pending(load_bundle(bundle_copy))]
    assert "policies/warranty.md" not in remaining


def test_reject_keeps_draft_and_records_reason(bundle_copy):
    bundle = load_bundle(bundle_copy)
    concept = review.reject(
        bundle, "policies/warranty.md", "legal@alpinepeakoutfitters.example",
        "term is one year, not two",
    )
    assert concept.status == "draft"
    reloaded = load_bundle(bundle_copy).get("policies/warranty.md")
    assert reloaded.x_geo["review"]["reason"] == "term is one year, not two"


def test_publish_withholds_high_risk_draft(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    result = publish(bundle_copy, dist)
    assert "policies/warranty.md" in result.withheld
    assert not (dist / "policies" / "warranty.md").exists()
    assert (dist / "policies" / "returns.md").exists()
    assert (dist / "index.md").exists()
    assert (dist / "log.md").exists()
    # Internal dirs never ship even if present.
    assert not (dist / "_review").exists()

    manifest = json.loads((dist / "manifest.json").read_text())
    assert manifest["okf_version"] == "0.2"
    assert "policies/returns.md" in manifest["files"]
    assert "policies/warranty.md" not in manifest["files"]

    linkmap = json.loads((dist / "linkmap.json").read_text())
    assert (
        linkmap["https://www.alpinepeakoutfitters.example/products/alpine-2-tent"]
        == "/.well-known/okf/catalog/products/alpine-2-tent.md"
    )
    # Withheld concepts don't leak through the linkmap either.
    assert (
        "https://www.alpinepeakoutfitters.example/policies/warranty" not in linkmap
    )


def test_publish_after_approval_includes_warranty(bundle_copy, tmp_path):
    review.approve(
        load_bundle(bundle_copy),
        "policies/warranty.md",
        "legal@alpinepeakoutfitters.example",
    )
    result = publish(bundle_copy, tmp_path / "dist")
    assert "policies/warranty.md" in result.published


def test_publish_refuses_bundle_with_errors(bundle_copy, tmp_path):
    # Force a high-risk stable concept without human verification.
    bad = bundle_copy / "policies" / "warranty.md"
    bad.write_text(bad.read_text().replace("status: draft", "status: stable"))
    with pytest.raises(PublishError):
        publish(bundle_copy, tmp_path / "dist")
