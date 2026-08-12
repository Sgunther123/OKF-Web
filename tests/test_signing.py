import json

import pytest

from okf_web import signing
from okf_web.publisher import publish


def _fake_sigstore(tmp_path, behavior: str = "ok"):
    """A stand-in sigstore CLI: writes the --bundle file and logs argv."""
    script = tmp_path / "fake-sigstore"
    if behavior == "ok":
        body = (
            "#!/bin/sh\n"
            'echo "$@" >> "$0.calls"\n'
            'prev=""\n'
            'for a in "$@"; do\n'
            '  if [ "$prev" = "--bundle" ]; then printf \'{"fake":"sigstore-bundle"}\' > "$a"; fi\n'
            '  prev="$a"\n'
            "done\n"
        )
    else:
        body = "#!/bin/sh\necho 'OIDC identity mismatch' >&2\nexit 1\n"
    script.write_text(body)
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def dist(bundle_copy, tmp_path):
    out = tmp_path / "dist"
    publish(bundle_copy, out)
    return out


# --- integrity layer (stdlib-only) ---------------------------------------

def test_integrity_clean_on_fresh_publish(dist):
    errors, warnings = signing.verify_integrity(dist)
    assert errors == []
    assert warnings == []


def test_integrity_catches_tampering(dist):
    target = dist / "policies" / "returns.md"
    target.write_text(target.read_text().replace("60 days", "90 days"))
    errors, _ = signing.verify_integrity(dist)
    assert any("hash mismatch" in e and "policies/returns.md" in e for e in errors)


def test_integrity_catches_missing_and_unlisted_files(dist):
    (dist / "store.md").unlink()
    (dist / "rogue.md").write_text("---\ntype: FAQ\n---\n\ninjected\n")
    errors, warnings = signing.verify_integrity(dist)
    assert any("missing from dist: store.md" in e for e in errors)
    assert any("not listed in manifest: rogue.md" in w for w in warnings)


def test_integrity_without_manifest(tmp_path):
    errors, _ = signing.verify_integrity(tmp_path)
    assert errors and "no manifest.json" in errors[0]


# --- signing layer (fake CLI) ---------------------------------------------

def test_sign_manifest_writes_conventional_bundle(dist, tmp_path):
    fake = _fake_sigstore(tmp_path)
    out = signing.sign_manifest(dist, sigstore_bin=fake)
    assert out == dist / "manifest.json.sigstore.json"
    assert json.loads(out.read_text())["fake"] == "sigstore-bundle"
    calls = (tmp_path / "fake-sigstore.calls").read_text()
    assert "sign" in calls and "--bundle" in calls and "--overwrite" in calls
    # A signed dist still passes integrity (signature is an expected extra).
    errors, warnings = signing.verify_integrity(dist)
    assert errors == [] and warnings == []


def test_sign_staging_flag_passthrough(dist, tmp_path):
    fake = _fake_sigstore(tmp_path)
    signing.sign_manifest(dist, sigstore_bin=fake, staging=True)
    assert "--staging" in (tmp_path / "fake-sigstore.calls").read_text()


def test_sign_requires_manifest(tmp_path):
    with pytest.raises(signing.SigningError, match="no manifest.json"):
        signing.sign_manifest(tmp_path, sigstore_bin="unused")


def test_sign_missing_tool_is_actionable(dist):
    with pytest.raises(signing.SigningError, match=r"okf-web\[sign\]"):
        signing.sign_manifest(dist, sigstore_bin="definitely-not-sigstore-okfweb")


# --- verification layer ---------------------------------------------------

def test_verify_signature_ok_and_failure(dist, tmp_path):
    good = _fake_sigstore(tmp_path)
    signing.sign_manifest(dist, sigstore_bin=good)
    # Passing run: fake exits 0.
    signing.verify_signature(
        dist, "merchant@example.test", "https://accounts.example", sigstore_bin=good
    )
    calls = (tmp_path / "fake-sigstore.calls").read_text()
    assert "verify identity" in calls
    assert "--cert-identity merchant@example.test" in calls
    # Failing run surfaces the tool's stderr.
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = _fake_sigstore(bad_dir, behavior="fail")
    with pytest.raises(signing.SigningError, match="OIDC identity mismatch"):
        signing.verify_signature(
            dist, "merchant@example.test", "https://accounts.example", sigstore_bin=bad
        )


def test_verify_signature_requires_signature_file(dist):
    with pytest.raises(signing.SigningError, match="unsigned"):
        signing.verify_signature(
            dist, "merchant@example.test", "https://accounts.example", sigstore_bin="unused"
        )


# --- CLI wiring ------------------------------------------------------------

def test_cli_verify_and_sign_flags(dist, tmp_path):
    from okf_web import cli as cli_mod

    fake = _fake_sigstore(tmp_path)
    assert cli_mod.main(["sign", str(dist), "--sigstore-bin", fake]) == 0
    assert cli_mod.main(["verify", str(dist)]) == 0  # integrity + "not checked" note
    assert cli_mod.main([
        "verify", str(dist),
        "--cert-identity", "merchant@example.test",
        "--cert-oidc-issuer", "https://accounts.example",
        "--sigstore-bin", fake,
    ]) == 0
    # Tampering flips the exit code.
    target = dist / "faq" / "general.md"
    target.write_text(target.read_text() + "\ntampered\n")
    assert cli_mod.main(["verify", str(dist)]) == 1
