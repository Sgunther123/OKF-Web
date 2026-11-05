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
the executable. :func:`sign_file` is the one place that runs it to
sign, so the login works wherever the signer is: at a terminal the
child shares it (on a machine with no display, sigstore prints a link
to open on any device and reads the code typed back), and without one
its output is captured and its input closed, so a login that needs a
person fails at once instead of waiting out the timeout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .errors import Failure, Refusal
from .model import file_digest

__all__ = [
    "SIGNATURE_NAME",
    "SigningError",
    "LabelError",
    "signature_path",
    "sign_file",
    "sign_manifest",
    "verify_signature",
    "verify_integrity",
]

SIGNATURE_NAME = "manifest.json.sigstore.json"

_LABEL_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

# Read by sigstore (3.0 and later) as the default of `--oauth-force-oob`:
# print the login link and read the code back instead of trying to open
# a browser. Set for the child when there is no display to open one in.
_FORCE_OOB = "SIGSTORE_OAUTH_FORCE_OOB"

# Publisher-generated artifacts expected in a dist without appearing in
# the manifest (the manifest cannot list itself or its own signature).
_EXPECTED_EXTRAS = {"manifest.json", SIGNATURE_NAME, "linkmap.json", "llms-snippet.txt"}


class SigningError(RuntimeError, Failure):
    """Signing or verification did not succeed (exit 1)."""


class LabelError(SigningError, Refusal):
    """A countersignature label the tool will not accept (exit 2)."""


def signature_path(dist: Path | str, label: str | None = None) -> Path:
    """Primary signature path, or a countersignature's when
    ``label`` names the attester (e.g. ``auditor-acme``)."""
    if label is None:
        return Path(dist) / SIGNATURE_NAME
    if not _LABEL_RE.match(label):
        raise LabelError(
            f"invalid countersignature label {label!r}: lowercase letters, "
            "digits, and hyphens only"
        )
    return Path(dist) / f"manifest.json.{label}.sigstore.json"


def _run(command: list[str], timeout: float, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, timeout=timeout, **kwargs)
    except FileNotFoundError as exc:
        raise SigningError(
            f"{command[0]!r} not found on PATH; install the signing extra "
            "(`pip install okf-web[sign]`) or pass --sigstore-bin"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SigningError(f"{command[0]} timed out after {timeout:.0f}s") from exc


def _attended() -> bool:
    """A person can answer: standard input is a terminal, so a code
    sigstore asks for can be typed back."""
    try:
        return os.isatty(0)
    except OSError:  # no standard input at all
        return False


def _headless(environ=None, platform: str | None = None) -> bool:
    """No graphical session a browser could open in: no X or Wayland
    display. macOS and Windows open the default browser without one."""
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform == "darwin" or platform.startswith("win"):
        return False
    return not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def sign_file(
    path: Path | str,
    out: Path | str | None = None,
    sigstore_bin: str = "sigstore",
    staging: bool = False,
    timeout: float = 600.0,
) -> Path:
    """Sigstore-sign one file, keyless; returns the signature bundle,
    written to ``out`` (default: ``<path>.sigstore.json`` beside it).

    The login reaches whoever signs. With a person at a terminal the
    child shares it: its messages go to standard error (its standard
    output too, so the caller's own output stays clean) and it reads the
    code from the keyboard. Where no display exists, the out-of-band
    flow is forced, so sigstore prints a link to open on any device and
    asks for the code that page shows, rather than starting a browser
    nobody can see (an operator's own ``SIGSTORE_OAUTH_FORCE_OOB`` is
    kept). With nobody at a terminal (CI with ``id-token: write``, which
    signs with the workflow's ambient identity, the recommended mode for
    automated publishes), the output is captured for the error message
    and standard input is closed, so a login that needs a person fails
    at once.
    """
    path = Path(path)
    out = Path(out) if out is not None else path.with_name(path.name + ".sigstore.json")
    command = [sigstore_bin]
    if staging:
        command.append("--staging")
    command += ["sign", "--bundle", str(out), "--overwrite", str(path)]
    env = dict(os.environ)
    if _headless(env) and not env.get(_FORCE_OOB):
        env[_FORCE_OOB] = "1"
    if _attended():
        for stream in (sys.stdout, sys.stderr):  # ours first, then the child's
            try:
                stream.flush()
            except (AttributeError, OSError, ValueError):
                pass
        proc = _run(command, timeout, stdout=2, env=env)
        detail = "its messages are above"
    else:
        proc = _run(command, timeout, env=env, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True)
        said = (proc.stderr or proc.stdout or "").strip()
        detail = said[-800:]  # the end of a traceback names the error
        if "link in a browser" in said:  # sigstore asked for a person
            detail += (" (signing needs a person at a terminal to log in, "
                       "or an ambient identity such as a CI workflow's)")
    if proc.returncode != 0:
        raise SigningError(f"{sigstore_bin} sign exited {proc.returncode}: {detail}")
    if not out.exists():
        raise SigningError(f"{sigstore_bin} reported success but wrote no {out.name}")
    return out


def sign_manifest(
    dist: Path | str,
    sigstore_bin: str = "sigstore",
    staging: bool = False,
    timeout: float = 600.0,
    label: str | None = None,
) -> Path:
    """Sign ``dist/manifest.json``; returns the signature bundle path.

    The login is :func:`sign_file`'s: a browser where one can open, a
    link and a typed-back code on a machine without a display, and the
    workflow's ambient identity in CI (``id-token: write``), where the
    signing identity then *is* the pipeline.
    """
    dist = Path(dist)
    manifest = dist / "manifest.json"
    if not manifest.exists():
        raise SigningError(f"no manifest.json in {dist}; run `okf-web publish` first")
    return sign_file(
        manifest,
        signature_path(dist, label),
        sigstore_bin=sigstore_bin,
        staging=staging,
        timeout=timeout,
    )


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
    proc = _run(command, timeout, capture_output=True, text=True)
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

    dist_resolved = dist.resolve()
    for rel, meta in sorted(files.items()):
        # A third-party manifest is untrusted input: every listed path
        # must stay a regular file inside the dist, or the verifier
        # becomes an oracle for (and a reader of) files outside it.
        parts = Path(rel).parts
        if not rel or Path(rel).is_absolute() or ".." in parts:
            errors.append(f"invalid manifest path (must be relative, inside the dist): {rel}")
            continue
        path = dist / rel
        try:
            resolved = path.resolve()
        except OSError:
            errors.append(f"invalid manifest path (unresolvable): {rel}")
            continue
        if dist_resolved not in resolved.parents:
            errors.append(f"invalid manifest path (escapes the dist): {rel}")
            continue
        if not path.exists():
            errors.append(f"listed in manifest but missing from dist: {rel}")
            continue
        if not path.is_file():
            errors.append(f"not a regular file: {rel}")
            continue
        digest, size = file_digest(path)
        if digest != meta.get("sha256"):
            errors.append(f"hash mismatch (file modified after publish): {rel}")
        elif meta.get("bytes") not in (None, size):
            errors.append(f"size mismatch: {rel}")

    for path in sorted(dist.rglob("*.md")):
        rel = path.relative_to(dist).as_posix()
        if rel not in files and rel not in _EXPECTED_EXTRAS:
            warnings.append(f"markdown file not listed in manifest: {rel}")

    return errors, warnings
