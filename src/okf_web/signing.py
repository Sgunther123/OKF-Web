"""Signed bundles: sigstore over ``manifest.json``.

``manifest.json`` records the sha256 of every published file, so it is
effectively the bundle's merkle root — one signature over the manifest
authenticates the entire published bundle. Signing uses sigstore's
keyless flow: the signer authenticates via OIDC (a browser login for a
human, ambient credentials in CI), Fulcio issues a short-lived
certificate bound to that identity, and the signature lands in the
Rekor transparency log. No keys for the merchant to generate, store,
or leak. The signature is written next to the manifest at the
conventional name ``manifest.json.sigstore.json``, where consumers
probe for it.

Consumer verification is two independent layers:

* :func:`verify_integrity` — pure stdlib, no sigstore needed: re-hash
  every file the manifest lists and flag missing files, hash
  mismatches, and unlisted markdown files.
* :func:`verify_signature` — sigstore identity verification: the
  manifest was signed by the expected identity (an email, or a CI
  workflow URI) under the expected OIDC issuer.

A bundle passing both is byte-authentic to what the named identity
published. Third-party attestation stands on the same substrate: an
auditor **countersigns the same manifest** with their own identity,
written to the conventional name
``manifest.json.<label>.sigstore.json`` (``okf-web sign --as
<label>``). Consumers verify a countersignature exactly like the
primary signature, expecting the *auditor's* identity — the merchant
signature says who published; each countersignature says who vouched.

The heavy lifting shells out to the ``sigstore`` CLI (installed by
``pip install okf-web[sign]``), which keeps this module stable across
sigstore-python API churn and lets tests (and cosign users) substitute
the executable.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

SIGNATURE_NAME = "manifest.json.sigstore.json"

_LABEL_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

# Publisher-generated artifacts expected in a dist without appearing in
# the manifest (the manifest cannot list itself or its own signature).
_EXPECTED_EXTRAS = {"manifest.json", SIGNATURE_NAME, "linkmap.json", "llms-snippet.txt"}


class SigningError(RuntimeError):
    pass


def signature_path(dist: Path | str, label: str | None = None) -> Path:
    """Primary signature path, or a countersignature's when
    ``label`` names the attester (e.g. ``auditor-acme``)."""
    if label is None:
        return Path(dist) / SIGNATURE_NAME
    if not _LABEL_RE.match(label):
        raise SigningError(
            f"invalid countersignature label {label!r}: lowercase letters, "
            "digits, and hyphens only"
        )
    return Path(dist) / f"manifest.json.{label}.sigstore.json"


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SigningError(
            f"{command[0]!r} not found on PATH; install the signing extra "
            "(`pip install okf-web[sign]`) or pass --sigstore-bin"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SigningError(f"{command[0]} timed out after {timeout:.0f}s") from exc


def sign_manifest(
    dist: Path | str,
    sigstore_bin: str = "sigstore",
    staging: bool = False,
    timeout: float = 600.0,
    label: str | None = None,
) -> Path:
    """Sign ``dist/manifest.json``; returns the signature bundle path.

    Interactive runs open a browser for the OIDC login; CI runs (e.g.
    GitHub Actions with ``id-token: write``) sign with the workflow's
    ambient identity, which is the recommended mode for automated
    publishes: the signing identity then *is* the pipeline.
    """
    dist = Path(dist)
    manifest = dist / "manifest.json"
    if not manifest.exists():
        raise SigningError(f"no manifest.json in {dist}; run `okf-web publish` first")
    out = signature_path(dist, label)
    command = [sigstore_bin]
    if staging:
        command.append("--staging")
    command += ["sign", "--bundle", str(out), "--overwrite", str(manifest)]
    proc = _run(command, timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:800]
        raise SigningError(f"{sigstore_bin} sign exited {proc.returncode}: {detail}")
    if not out.exists():
        raise SigningError(f"{sigstore_bin} reported success but wrote no {out.name}")
    return out


def verify_signature(
    dist: Path | str,
    cert_identity: str,
    cert_oidc_issuer: str,
    sigstore_bin: str = "sigstore",
    staging: bool = False,
    timeout: float = 300.0,
    label: str | None = None,
) -> None:
    """Verify the manifest signature against an expected identity.

    Raises :class:`SigningError` on any failure; returning means the
    manifest bytes were signed by ``cert_identity`` under
    ``cert_oidc_issuer`` and the signature is logged in Rekor.
    """
    dist = Path(dist)
    manifest = dist / "manifest.json"
    sig = signature_path(dist, label)
    if not sig.exists():
        if label:
            raise SigningError(
                f"no countersignature {sig.name} in {dist}; nothing to verify"
            )
        raise SigningError(f"no {SIGNATURE_NAME} in {dist}; bundle is unsigned")
    command = [sigstore_bin]
    if staging:
        command.append("--staging")
    command += [
        "verify", "identity",
        "--bundle", str(sig),
        "--cert-identity", cert_identity,
        "--cert-oidc-issuer", cert_oidc_issuer,
        str(manifest),
    ]
    proc = _run(command, timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:800]
        raise SigningError(f"signature verification FAILED: {detail}")


def verify_integrity(dist: Path | str) -> tuple[list[str], list[str]]:
    """Check every manifest-listed file against its recorded sha256.

    Returns ``(errors, warnings)``. Pure stdlib — this layer needs no
    sigstore and should run in every consumer regardless of whether it
    verifies the signature.
    """
    dist = Path(dist)
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = dist / "manifest.json"
    if not manifest_path.exists():
        return [f"no manifest.json in {dist}"], []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json is not valid JSON: {exc}"], []

    files = manifest.get("files")
    if not isinstance(files, dict):
        return ["manifest.json has no `files` mapping"], []

    for rel, meta in sorted(files.items()):
        path = dist / rel
        if not path.exists():
            errors.append(f"listed in manifest but missing from dist: {rel}")
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != meta.get("sha256"):
            errors.append(f"hash mismatch (file modified after publish): {rel}")
        elif meta.get("bytes") not in (None, len(data)):
            errors.append(f"size mismatch: {rel}")

    for path in sorted(dist.rglob("*.md")):
        rel = path.relative_to(dist).as_posix()
        if rel not in files and rel not in _EXPECTED_EXTRAS:
            warnings.append(f"markdown file not listed in manifest: {rel}")

    return errors, warnings
