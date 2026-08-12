from okf_web import render, review
from okf_web.model import Concept, load_bundle
from okf_web.publisher import publish


def test_markdown_escapes_untrusted_html():
    body = "\n# Overview\n\nA claim.<script>alert(1)</script>\n"
    out = render.render_markdown(body)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_renders_structures_and_footnotes():
    body = (
        "\n# Specs\n\n* Weight: 1.9 kg.[^pdp]\n\n"
        "See [returns](/policies/returns.md) or [site](https://example.test/x).\n\n"
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "[^pdp]: Product page.\n"
    )
    out = render.render_markdown(body, links=lambda t: t if t.startswith("http") else None)
    assert "<h2>Specs</h2>" in out
    assert "<li>Weight: 1.9 kg." in out and 'class="fn"' in out
    # Internal link resolved to None renders as plain text; external stays a link.
    assert "See returns or" in out
    assert "policies/returns.md" not in out
    assert '<a href="https://example.test/x" target="_blank" rel="noopener">site</a>' in out
    assert "<table>" in out and "<th>a</th>" in out
    assert "Footnotes" in out and "Product page." in out


def test_publish_emits_noindex_viewer_without_withheld_drafts(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    viewer = (dist / "viewer.html").read_text()
    assert '<meta name="robots" content="noindex, nofollow">' in viewer
    assert "Alpine 2 Tent" in viewer
    # The canonical live-page link is present.
    assert "https://www.alpinepeakoutfitters.example/products/alpine-2-tent" in viewer
    assert "View the live page" in viewer
    # Withheld high-risk draft never reaches the viewer.
    assert "Limited Warranty" not in viewer
    # Trust badges render.
    assert "badge-human" in viewer


def test_publish_viewer_escapes_hostile_concept(bundle_copy, tmp_path):
    hostile = bundle_copy / "faq" / "hostile.md"
    hostile.write_text(
        "---\ntype: FAQ\ntitle: Hostile\n---\n\n<img src=x onerror=alert(1)>\n",
        encoding="utf-8",
    )
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    viewer = (dist / "viewer.html").read_text()
    assert "<img src=x" not in viewer
    assert "&lt;img src=x onerror=alert(1)&gt;" in viewer


def test_publish_no_viewer_flag(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist, viewer=False)
    assert not (dist / "viewer.html").exists()


def test_review_packet_lists_pending_and_commands(bundle_copy):
    bundle = load_bundle(bundle_copy)
    items = review.pending(bundle)
    html = render.build_review_packet_html(bundle, items, [])
    assert "Limited Warranty" in html
    assert "risk a" in html
    assert "okf-web review approve" in html and "policies/warranty.md" in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_review_packet_includes_drift_proposals(bundle_copy):
    proposed = bundle_copy / "_review" / "proposed" / "policies"
    proposed.mkdir(parents=True)
    (proposed / "returns.md").write_text(
        "---\ntype: Policy\ntitle: Return Policy (updated)\n"
        "sources:\n  - id: p\n    resource: https://x.example/p\n"
        "x_geo:\n  risk: a\n---\n\nNew 30-day window.[^p]\n\n[^p]: page.\n",
        encoding="utf-8",
    )
    bundle = load_bundle(bundle_copy)
    proposals = review.drift_proposals(bundle_copy)
    assert len(proposals) == 1
    html = render.build_review_packet_html(bundle, review.pending(bundle), proposals)
    assert "Drift proposals" in html
    assert "Return Policy (updated)" in html
    assert "would replace" in html


def test_viewer_internal_links_route_to_published_sections(bundle_copy, tmp_path):
    dist = tmp_path / "dist"
    publish(bundle_copy, dist)
    viewer = (dist / "viewer.html").read_text()
    # The tent concept links to the returns policy; both are published, so
    # the link becomes an in-page hash route.
    assert 'href="#c-policies-returns-md"' in viewer
