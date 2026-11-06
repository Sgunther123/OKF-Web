import base64
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from okf_web import signing
from okf_web.publisher import publish

REPO = Path(__file__).resolve().parents[1]


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


# --- the login reaches whoever signs (found on a machine without a browser) --

_POSIX_TTY = hasattr(os, "openpty") and not sys.platform.startswith(("win", "darwin"))


def _login_sigstore(tmp_path, code: str = "okf-test-code"):
    """A stand-in for sigstore's out-of-band login: prints the link on
    standard error, asks for the code, and signs only when the right one
    comes back. It records the flow variable and what its input held."""
    script = tmp_path / "login-sigstore"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--bundle') + 1]\n"
        "seen = {'oob': os.environ.get('SIGSTORE_OAUTH_FORCE_OOB'),\n"
        "        'stdout_tty': os.isatty(1)}\n"
        "open(sys.argv[0] + '.seen', 'w').write(json.dumps(seen))\n"
        "print('Go to the following link in a browser:\\n\\n\\t'\n"
        "      'https://oauth2.example.test/auth?state=okf', file=sys.stderr)\n"
        "got = input('Enter verification code: ')\n"
        f"if got.strip() != {code!r}:\n"
        "    print('wrong code', file=sys.stderr)\n"
        "    sys.exit(4)\n"
        "open(out, 'w').write('{\"fake\": \"signed after login\"}')\n"
        "print('Sigstore bundle written to ' + out)\n"
    )
    script.chmod(0o755)
    return script


def _seen(script):
    return json.loads(Path(str(script) + ".seen").read_text())


def test_headless_means_no_display_where_a_browser_needs_one():
    assert signing._headless({}, "linux")
    assert not signing._headless({"DISPLAY": ":0"}, "linux")
    assert not signing._headless({"WAYLAND_DISPLAY": "wayland-0"}, "linux")
    assert signing._headless({"DISPLAY": ""}, "freebsd13")
    assert not signing._headless({}, "darwin")
    assert not signing._headless({}, "win32")


def test_sign_file_writes_beside_the_file_by_default(tmp_path):
    target = tmp_path / "2026-08.json"
    target.write_text("{}")
    out = signing.sign_file(target, sigstore_bin=_fake_sigstore(tmp_path))
    assert out == tmp_path / "2026-08.json.sigstore.json"
    assert json.loads(out.read_text())["fake"] == "sigstore-bundle"


def test_unattended_signing_closes_input_and_names_the_way_out(tmp_path, monkeypatch):
    """Nobody at a terminal: a login that needs a person fails at once,
    with sigstore's own last words and what would let it succeed."""
    monkeypatch.setattr(signing, "_attended", lambda: False)
    monkeypatch.setattr(signing, "_headless", lambda env: True)
    monkeypatch.delenv("SIGSTORE_OAUTH_FORCE_OOB", raising=False)
    target = tmp_path / "statement.json"
    target.write_text("{}")
    fake = _login_sigstore(tmp_path)
    started = time.monotonic()
    with pytest.raises(signing.SigningError) as excinfo:
        signing.sign_file(target, sigstore_bin=str(fake), timeout=60)
    assert time.monotonic() - started < 30  # closed input, not the timeout
    message = str(excinfo.value)
    assert "EOFError" in message and "person at a terminal" in message
    assert "timed out" not in message
    assert _seen(fake)["oob"] == "1"


def test_the_flow_variable_is_set_only_without_a_display_and_never_overridden(
        tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    target.write_text("{}")
    monkeypatch.setattr(signing, "_attended", lambda: False)
    recorder = tmp_path / "env-sigstore"
    recorder.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "open(args[args.index('--bundle') + 1], 'w').write('{}')\n"
        "open(sys.argv[0] + '.oob', 'w').write(os.environ.get('SIGSTORE_OAUTH_FORCE_OOB', '<unset>'))\n"
    )
    recorder.chmod(0o755)
    oob = Path(str(recorder) + ".oob")

    monkeypatch.delenv("SIGSTORE_OAUTH_FORCE_OOB", raising=False)
    monkeypatch.setattr(signing, "_headless", lambda env: False)
    signing.sign_file(target, sigstore_bin=str(recorder))
    assert oob.read_text() == "<unset>"  # a display: sigstore opens the browser

    monkeypatch.setattr(signing, "_headless", lambda env: True)
    signing.sign_file(target, sigstore_bin=str(recorder))
    assert oob.read_text() == "1"  # none: the link and the typed-back code

    monkeypatch.setenv("SIGSTORE_OAUTH_FORCE_OOB", "0")
    signing.sign_file(target, sigstore_bin=str(recorder))
    assert oob.read_text() == "0"  # the operator's own choice stands
    assert "SIGSTORE_OAUTH_FORCE_OOB" in os.environ  # ours, untouched


@pytest.mark.skipif(not _POSIX_TTY, reason="needs a pseudo-terminal and no default browser")
def test_an_operator_at_a_terminal_sees_the_link_and_types_the_code(dist, tmp_path):
    """The boundary is a terminal, so it is verified over one: `okf-web
    sign` on a machine without a display, as over SSH. Before the fix the
    link and the prompt were captured, the operator saw nothing, and the
    login waited out its ten minutes."""
    fake = _login_sigstore(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "SIGSTORE_OAUTH_FORCE_OOB")}
    env["PYTHONPATH"] = str(REPO / "src")
    master, slave = os.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", "okf_web.cli", "sign", str(dist), "--sigstore-bin", str(fake)],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    seen, answered = b"", False
    deadline = time.monotonic() + 60
    prompt_by = time.monotonic() + 20  # a captured prompt never comes
    try:
        while time.monotonic() < deadline:
            if not answered and time.monotonic() > prompt_by:
                break
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:  # every writer is gone
                    break
                if not chunk:
                    break
                seen += chunk
                if not answered and b"Enter verification code:" in seen:
                    os.write(master, b"okf-test-code\n")
                    answered = True
            elif proc.poll() is not None:
                break
        if not answered:
            proc.kill()
        rc = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)
    text = seen.decode("utf-8", "replace")
    assert answered, text  # the prompt reached the terminal
    assert "https://oauth2.example.test/auth?state=okf" in text
    assert rc == 0, text
    assert "signed:" in text
    signature = dist / "manifest.json.sigstore.json"
    assert json.loads(signature.read_text()) == {"fake": "signed after login"}
    assert _seen(fake) == {"oob": "1", "stdout_tty": True}


def test_only_the_signing_module_runs_sigstore_to_sign():
    """One door for signing, as for fetching: a second spelling of the
    sign command would carry the captured-login bug back in."""
    spawn = re.compile(r"""["']sign["']\s*,\s*["']--bundle["']""")
    for path in sorted((REPO / "src" / "okf_web").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        found = len(spawn.findall(source))
        assert found == (1 if path.name == "signing.py" else 0), path.name


# --- the signer a certificate names ------------------------------------------

#: A real Fulcio leaf certificate (public: Rekor entry 3705121167), the
#: countersignature of the hosted edition's audit rehearsal on 2026-11-06,
#: signed as info@okf-web.com through Google.
_FULCIO_LEAF = (
    "MIIDBzCCAoygAwIBAgIUT7gPnNnWwavf2Moe+MzV5ZBd7GIwCgYIKoZIzj0EAwMwNzEVMBMG"
    "A1UEChMMc2lnc3RvcmUuZGV2MR4wHAYDVQQDExVzaWdzdG9yZS1pbnRlcm1lZGlhdGUwHhcN"
    "MjYxMTA2MDAyMjE0WhcNMjYxMTA2MDAzMjE0WjAAMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcD"
    "QgAE88M5n1MYP74mqWJjI7xGN7ivI/4Nk8cZd83qJBAnHO+SwWf4KSeczMUb6R0DJw/cGK8t"
    "BqPh7yxidPF7jY9I0qOCAaswggGnMA4GA1UdDwEB/wQEAwIHgDATBgNVHSUEDDAKBggrBgEF"
    "BQcDAzAfBgNVHSMEGDAWgBTf0+nPViQRlvmo2OkoVaLGLhhkPzAeBgNVHREBAf8EFDASgRBp"
    "bmZvQG9rZi13ZWIuY29tMCkGCisGAQQBg78wAQEEG2h0dHBzOi8vYWNjb3VudHMuZ29vZ2xl"
    "LmNvbTArBgorBgEEAYO/MAEIBB0MG2h0dHBzOi8vYWNjb3VudHMuZ29vZ2xlLmNvbTBbBgor"
    "BgEEAYO/MAEYBE0MS0NoVXhNRGcyTlRrM01UQTBPREk0TmpVNE56YzRPVFlTSDJoMGRIQnpP"
    "aVV5UmlVeVJtRmpZMjkxYm5SekxtZHZiMmRzWlM1amIyMDCBiQYKKwYBBAHWeQIEAgR7BHkA"
    "dwB1AN09MGrGxxEyYxkeHJlnNwKiSl643jyt/4eKcoAvKe6OAAABoa48EO0AAAQDAEYwRAIg"
    "cIOd2uKZfiZ6C0P5ROfVU4oabQ5tspMafFpVnOgydMMCIFEwjwk/UmbfADT0EkIwI8h5IWS8"
    "c2GgTU9/jdhb3ax5MAoGCCqGSM49BAMDA2kAMGYCMQD8Hl+ziNN/Xm4P0c7S0Blx/N8s/hf9"
    "Ktvsp0zSeMTRTcTvna12HzLl322R3eEApH4CMQCPNKh8s/0LSShbg850fWYwEL7miso+hHt+"
    "2MlRGIPdkntoJww8XJ4n0nx/QJmG/c0="
)

_REAL = ("info@okf-web.com", "https://accounts.google.com")


def _bundle_file(tmp_path, material, name="bundle.sigstore.json"):
    path = tmp_path / name
    path.write_text(json.dumps({
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": material,
    }))
    return path


def _der(tag: int, content: bytes) -> bytes:
    """A DER element, for building certificates the reader must handle."""
    size = len(content)
    if size < 0x80:
        return bytes([tag, size]) + content
    width = (size.bit_length() + 7) // 8
    return bytes([tag, 0x80 | width]) + size.to_bytes(width, "big") + content


def _der_oid(dotted: str) -> bytes:
    arcs = [int(arc) for arc in dotted.split(".")]
    body = bytearray([arcs[0] * 40 + arcs[1]])
    for arc in arcs[2:]:
        chunk = [arc & 0x7F]
        arc >>= 7
        while arc:
            chunk.append(0x80 | (arc & 0x7F))
            arc >>= 7
        body += bytes(reversed(chunk))
    return _der(0x06, bytes(body))


def test_signer_reads_the_leaf_a_bundle_carries(tmp_path):
    """The identity and issuer a consumer verifies against, read off the
    signature itself: a v0.3 bundle's leaf, and the first certificate of
    an older bundle's chain."""
    v03 = _bundle_file(tmp_path, {"certificate": {"rawBytes": _FULCIO_LEAF}})
    assert signing.signer(v03) == _REAL
    older = _bundle_file(tmp_path, {"x509CertificateChain": {"certificates": [
        {"rawBytes": _FULCIO_LEAF}, {"rawBytes": "AAAA"},
    ]}}, "older.sigstore.json")
    assert signing.signer(older) == _REAL


def test_signer_reads_a_workflow_identity_and_the_older_issuer_form(tmp_path):
    """A CI signature names a workflow URI, and certificates before 2022
    carry the issuer as raw bytes (``.1.1``) rather than a DER string."""
    uri = b"https://github.com/acme/shop/.github/workflows/publish.yml@refs/heads/main"
    issuer = b"https://token.actions.githubusercontent.com"
    names = _der(0x30, _der(0x86, uri))
    extensions = _der(0x30, (
        _der(0x30, _der_oid("2.5.29.17") + _der(0x04, names))
        + _der(0x30, _der_oid("1.3.6.1.4.1.57264.1.1") + _der(0x04, issuer))
    ))
    certificate = _der(0x30, _der(0x30, _der(0xA0, _der(0x02, b"\x02")) + _der(0xA3, extensions)))
    path = _bundle_file(tmp_path, {"certificate": {"rawBytes": base64.b64encode(certificate).decode()}})
    assert signing.signer(path) == (uri.decode(), issuer.decode())


def test_signer_answers_none_for_whatever_it_cannot_read(tmp_path):
    """A stand-in, a key-based bundle, a corrupt file: None, never an
    exception, so a caller can say "no identity" instead of crashing."""
    leaf = base64.b64decode(_FULCIO_LEAF)
    cases = {
        "not-json": "not json",
        "a-list": "[1, 2]",
        "a-stand-in": '{"fake":"sigstore-bundle"}',
        "key-based": json.dumps({"verificationMaterial": {"publicKey": {"hint": "k"}}}),
        "not-base64": json.dumps({"verificationMaterial": {"certificate": {"rawBytes": "%%%"}}}),
        "truncated": json.dumps({"verificationMaterial": {"certificate": {
            "rawBytes": base64.b64encode(leaf[:300]).decode()}}}),
        "not-a-certificate": json.dumps({"verificationMaterial": {"certificate": {
            "rawBytes": base64.b64encode(b"\x02\x01\x05").decode()}}}),
    }
    for name, text in cases.items():
        path = tmp_path / f"{name}.json"
        path.write_text(text)
        assert signing.signer(path) is None, name
    (tmp_path / "binary.json").write_bytes(b"\xff\xfe\x00")
    assert signing.signer(tmp_path / "binary.json") is None
    assert signing.signer(tmp_path / "missing.json") is None
    for cut in range(0, len(leaf), 7):  # every truncation of a real leaf
        encoded = base64.b64encode(leaf[:cut]).decode()
        path = _bundle_file(tmp_path, {"certificate": {"rawBytes": encoded}}, "cut.json")
        assert signing.signer(path) in (None, _REAL), cut


def test_sign_hands_consumers_the_complete_verify_command(dist, tmp_path, capsys):
    """After signing, the command printed for consumers names the
    identity and issuer the new certificate carries; a placeholder only
    when the bundle names nobody."""
    from okf_web import cli as cli_mod

    signed = _bundle_file(tmp_path, {"certificate": {"rawBytes": _FULCIO_LEAF}}, "real.json")
    copying = tmp_path / "copying-sigstore"
    copying.write_text(
        "#!/bin/sh\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        f'  if [ "$prev" = "--bundle" ]; then cp "{signed}" "$a"; fi\n'
        '  prev="$a"\n'
        "done\n"
    )
    copying.chmod(0o755)
    assert cli_mod.main(["sign", str(dist), "--sigstore-bin", str(copying), "--as", "auditor-acme"]) == 0
    out = capsys.readouterr().out
    assert (
        f"okf-web verify {dist} --countersignature auditor-acme "
        "--cert-identity info@okf-web.com --cert-oidc-issuer https://accounts.google.com"
    ) in out
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    assert cli_mod.main(["sign", str(dist), "--sigstore-bin", _fake_sigstore(stub_dir)]) == 0
    assert "--cert-identity <your-oidc-identity> --cert-oidc-issuer <issuer-url>" in capsys.readouterr().out
