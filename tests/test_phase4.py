import pytest

from okf_web import feed, review, signing
from okf_web.cli import main as cli_main
from okf_web.linter import lint_bundle
from okf_web.model import load_bundle
from okf_web.publisher import publish

_CSV = (
    "id,title,description,link,brand,gtin,product_type,price,availability\n"
    "SKU-1,Trail Stove,A compact canister stove for backpacking. Boils fast.,"
    "https://shop.example/p/trail-stove,Alpine Peak,00012345600012,"
    "Camping > Cooking,49.99 USD,in_stock\n"
    "SKU-2,Titanium Pot,A 750 ml titanium pot with lid.,"
    "https://shop.example/p/titanium-pot,Alpine Peak,,Camping > Cooking,"
    "34.99 USD,out_of_stock\n"
)

_XML = """<?xml version="1.0"?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0"><channel>
<item>
  <g:id>SKU-9</g:id>
  <g:title>Camp Mug</g:title>
  <g:description>An enamel camp mug.</g:description>
  <g:link>https://shop.example/p/camp-mug</g:link>
  <g:brand>Alpine Peak</g:brand>
  <g:price>12.00 USD</g:price>
  <g:availability>in_stock</g:availability>
</item>
</channel></rss>
"""


def _write_feed(tmp_path, text=_CSV, name="products.csv"):
    path = tmp_path / name
    path.write_text(text)
    return path


# --- feed parsing -----------------------------------------------------------

def test_parse_csv_and_xml(tmp_path):
    items = feed.parse_feed(_write_feed(tmp_path))
    assert [i.id for i in items] == ["SKU-1", "SKU-2"]
    assert items[0].gtin == "00012345600012"
    # Dropped fields never survive parsing into extras.
    assert "price" not in items[0].extras and "availability" not in items[0].extras

    items = feed.parse_feed(_write_feed(tmp_path, _XML, "feed.xml"))
    assert items[0].id == "SKU-9" and items[0].brand == "Alpine Peak"
    assert "price" not in items[0].extras


def test_price_changes_do_not_change_the_row_hash(tmp_path):
    a = feed.parse_feed(_write_feed(tmp_path))[0]
    b = feed.parse_feed(
        _write_feed(tmp_path, _CSV.replace("49.99", "39.99"), "p2.csv")
    )[0]
    assert feed.item_text(a) == feed.item_text(b)


# --- ingestion --------------------------------------------------------------

def test_ingest_creates_lint_clean_drafts_without_live_values(tmp_path):
    root = tmp_path / "bundle"
    result = feed.ingest_feed(_write_feed(tmp_path), root)
    assert sorted(result.written) == [
        "catalog/products/titanium-pot.md", "catalog/products/trail-stove.md",
    ]
    bundle = load_bundle(root)
    stove = bundle.concepts["catalog/products/trail-stove.md"]
    assert stove.status == "draft"
    assert stove.entity == "gtin:00012345600012"
    assert stove.generated_by == feed.FEED_ACTOR
    assert "49.99" not in stove.render() and "in_stock" not in stove.render()
    # Whole bundle (drafts included) lints clean.
    _, findings = lint_bundle(root)
    assert not [f for f in findings if f.severity == "error"]


def test_reingest_is_incremental_and_respects_human_approval(tmp_path):
    root = tmp_path / "bundle"
    feed_path = _write_feed(tmp_path)
    feed.ingest_feed(feed_path, root)

    # Unchanged rows cost nothing.
    again = feed.ingest_feed(feed_path, root)
    assert len(again.skipped_unchanged) == 2 and not again.written

    # Approve one product, then change its row: drift proposal, not overwrite.
    review.approve(load_bundle(root), "catalog/products/trail-stove.md", "merch@shop.example")
    changed = _write_feed(
        tmp_path, _CSV.replace("Boils fast.", "Now boils faster."), "v2.csv"
    )
    third = feed.ingest_feed(changed, root)
    assert "catalog/products/trail-stove.md" in third.proposed
    assert (root / "_review" / "proposed" / "catalog/products/trail-stove.md").exists()
    approved = load_bundle(root).concepts["catalog/products/trail-stove.md"]
    assert "Boils fast." in approved.body  # human-approved text untouched


def test_cli_feed_survey_needs_no_llm(tmp_path):
    root = tmp_path / "bundle"
    feed_path = _write_feed(tmp_path)
    assert cli_main(["survey", str(root), "--feed", str(feed_path)]) == 0
    assert (root / "catalog" / "products" / "trail-stove.md").exists()


# --- countersignatures ------------------------------------------------------

def _fake_sigstore(tmp_path):
    script = tmp_path / "fake-sigstore"
    script.write_text(
        "#!/bin/sh\n"
        'echo "$@" >> "$0.calls"\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "--bundle" ]; then printf \'{"fake":"sig"}\' > "$a"; fi\n'
        '  prev="$a"\n'
        "done\n"
    )
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def dist(bundle_copy, tmp_path):
    out = tmp_path / "dist"
    publish(bundle_copy, out)
    return out


def test_countersign_writes_conventional_name(dist, tmp_path):
    fake = _fake_sigstore(tmp_path)
    out = signing.sign_manifest(dist, sigstore_bin=fake, label="auditor-acme")
    assert out.name == "manifest.json.auditor-acme.sigstore.json"
    # Primary signature name untouched by countersigning.
    assert not signing.signature_path(dist).exists()
    # Countersignature files don't trip the unlisted-file warning.
    errors, warnings = signing.verify_integrity(dist)
    assert errors == [] and warnings == []


def test_invalid_label_rejected(dist, tmp_path):
    with pytest.raises(signing.SigningError):
        signing.sign_manifest(dist, sigstore_bin="unused", label="Bad Label!")


def test_verify_countersignature_routes_to_labeled_file(dist, tmp_path):
    fake = _fake_sigstore(tmp_path)
    signing.sign_manifest(dist, sigstore_bin=fake, label="auditor-acme")
    signing.verify_signature(
        dist, cert_identity="auditor@acme.example",
        cert_oidc_issuer="https://issuer.example",
        sigstore_bin=fake, label="auditor-acme",
    )
    calls = (tmp_path / "fake-sigstore.calls").read_text()
    assert "manifest.json.auditor-acme.sigstore.json" in calls

    with pytest.raises(signing.SigningError, match="countersignature"):
        signing.verify_signature(
            dist, cert_identity="x", cert_oidc_issuer="y",
            sigstore_bin=fake, label="never-signed",
        )


def test_cli_countersign_and_verify(dist, tmp_path, capsys):
    fake = _fake_sigstore(tmp_path)
    assert cli_main(
        ["sign", str(dist), "--as", "auditor-acme", "--sigstore-bin", fake]
    ) == 0
    assert "auditor-acme" in capsys.readouterr().out
    assert cli_main([
        "verify", str(dist), "--countersignature", "auditor-acme",
        "--cert-identity", "auditor@acme.example",
        "--cert-oidc-issuer", "https://issuer.example",
        "--sigstore-bin", fake,
    ]) == 0
    assert "countersignature (auditor-acme): valid" in capsys.readouterr().out


# --- localized packs --------------------------------------------------------

def test_spanish_packs_ship_for_all_verticals(tmp_path):
    from okf_web import cli as cli_mod, evaluator

    packs = cli_mod._question_packs()
    for name in ("outdoor.es", "apparel.es", "electronics.es", "grocery.es",
                 "machinery.es"):
        path = tmp_path / f"{name}.yaml"
        path.write_text(packs[name])
        questions = evaluator.load_questions(path)
        assert len(questions) == 39, name
        assert {q.archetype for q in questions} == set(evaluator.ARCHETYPES), name
