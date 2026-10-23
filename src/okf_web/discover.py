"""Consumer-side discovery verifier: does this store have a bundle,
and does the bundle really speak for the store?

The producer half of discovery/delegation lives in the publisher
(GEO-PROFILE §8). This is the counterpart any consumer — an engine
operator, an auditor, or the merchant checking their own setup — can
run in one command:

1. **Find** the bundle: probe the well-known location
   (``<origin>/.well-known/okf/``), and parse the given page for a
   ``<link rel="okf-bundle" href="…">`` pointer.
2. **Verify the binding**: a same-origin bundle is bound by path
   position; an off-origin (delegated) bundle must carry a
   ``manifest.site`` claim matching the store origin that pointed at
   it — the bidirectional handshake.
3. **Report** what an engine would conclude: routes found, file
   count, profile, signature presence, and every problem in plain
   words.

Signature *presence* is reported here (a 200 whose body is a JSON
object; an HTML fallback page does not count); verifying the signer
identity needs `okf-web verify` with the expected identity, because only
the consumer knows which identity they trust.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from .config import WELL_KNOWN_PATH, user_agent  # noqa: F401 — WELL_KNOWN_PATH re-exported
from .net import PAGE_POLICY, FetchPolicy, UnsafeURL, check_url, origin, safe_fetch
from .signing import SIGNATURE_NAME

__all__ = [
    "USER_AGENT",
    "DiscoveryReport",
    "discover",
    "WELL_KNOWN_PATH",
]

USER_AGENT = user_agent("discover")


def _policy(timeout: float = 15.0, allow_private: bool = False) -> FetchPolicy:
    return PAGE_POLICY.derive(
        timeout=timeout,
        deadline=max(PAGE_POLICY.deadline, timeout * 2),
        allow_private=allow_private,
        user_agent=USER_AGENT,
    )


def _fetch(
    url: str,
    timeout: float = 15.0,
    allow_private: bool = False,
    policy: FetchPolicy | None = None,
) -> tuple[int, str]:
    """Status and text through the shared safe fetcher; every status is
    returned (a missing manifest is a 404, not an exception)."""
    result = safe_fetch(url, policy or _policy(timeout, allow_private))
    return result.status, result.text


class _LinkTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "link":
            return
        mapping = dict(attrs)
        rels = (mapping.get("rel") or "").lower().split()
        if "okf-bundle" in rels and mapping.get("href"):
            self.hrefs.append(mapping["href"])


@dataclass
class DiscoveryReport:
    store_origin: str
    routes: list[str] = field(default_factory=list)
    bundle_url: str | None = None
    manifest: dict | None = None
    files: int = 0
    signed: bool = False
    binding: str = "none"  # same-origin | bound | missing | mismatch | none
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.manifest is not None and self.binding in ("same-origin", "bound")


#: Statuses a bot gate, a challenge page or an access rule answers with
#: before the origin is ever asked.
_GATE_STATUSES = (401, 402, 403, 429, 503)


def _try_manifest(fetch, bundle_url: str) -> tuple[dict | None, str]:
    """The manifest at ``bundle_url``, or None with the reason in words:
    what the location answered, so a bot gate (a 403 challenge page, a
    402 pay-per-crawl answer) or a single-page-app fallback is told
    apart from an absent bundle in the report."""
    try:
        status, text = fetch(bundle_url.rstrip("/") + "/manifest.json")
    except Exception as exc:
        return None, f"could not be fetched ({exc})"
    if status != 200:
        hint = (
            " (a bot gate, a challenge or an access rule answering before "
            "the origin?)" if status in _GATE_STATUSES else ""
        )
        return None, f"answered HTTP {status}{hint}"
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return None, (
            "answered 200 with something other than JSON (a single-page-app "
            "fallback page?)"
        )
    if not isinstance(manifest, dict) or "files" not in manifest:
        return None, "answered JSON that is not a manifest (no files map)"
    return manifest, "answered a manifest"


def _is_json_object(text: str) -> bool:
    """A sigstore bundle is a JSON object. Hosts that answer every missing
    path with a 200 HTML page (the single-page-app fallback; observed on
    a static host's emulator, docs/HOSTING.md §3.1) must not read as
    signed."""
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def discover(
    store_url: str,
    fetch=None,
    timeout: float = 15.0,
    allow_private: bool = False,
    policy: FetchPolicy | None = None,
) -> DiscoveryReport:
    explicit = policy
    policy = policy or _policy(timeout, allow_private)
    if fetch is None:
        if explicit is not None:
            fetch = lambda url: _fetch(url, policy=explicit)  # noqa: E731
        else:
            extra = {"allow_private": True} if allow_private else {}
            fetch = lambda url: _fetch(url, timeout=timeout, **extra)  # noqa: E731
    store_origin = origin(store_url)
    report = DiscoveryReport(store_origin=store_origin)
    try:
        check_url(store_url, policy)
    except UnsafeURL as exc:
        report.problems.append(str(exc))
        return report

    # Route 1: the well-known location on the store's own origin.
    well_known = store_origin + WELL_KNOWN_PATH
    manifest, well_known_note = _try_manifest(fetch, well_known)
    if manifest is not None:
        report.routes.append("well-known")
        report.bundle_url, report.manifest = well_known, manifest

    # Route 2: a <link rel="okf-bundle"> pointer on the given page.
    try:
        status, html = fetch(store_url)
    except Exception as exc:
        report.problems.append(f"could not fetch {store_url}: {exc}")
    else:
        if status == 200:
            parser = _LinkTagParser()
            parser.feed(html)
            if parser.hrefs:
                # Resolve exactly as a browser resolves the page's own
                # relative URLs — against the document URL itself, not a
                # directory-ified variant of it.
                pointed = urljoin(store_url, parser.hrefs[0]).rstrip("/")
                report.routes.append("link-tag")
                # The pointer is the page's word, not the auditor's: a
                # file: or private-host target is reported, never fetched.
                try:
                    check_url(pointed, policy)
                except UnsafeURL as exc:
                    report.problems.append(f"link tag points at {pointed}, not fetched: {exc}")
                else:
                    if report.manifest is None:
                        pointed_manifest, note = _try_manifest(fetch, pointed)
                        if pointed_manifest is not None:
                            report.bundle_url, report.manifest = pointed, pointed_manifest
                        else:
                            report.problems.append(
                                f"link tag points at {pointed} but no readable "
                                f"manifest.json is there: it {note}"
                            )

    if report.manifest is None:
        report.problems.append(
            f"no bundle found: the well-known location {well_known}/manifest.json "
            f"{well_known_note}, and no usable <link rel=\"okf-bundle\"> pointer"
        )
        return report

    report.files = len(report.manifest.get("files", {}))
    try:
        sig_status, sig_text = fetch(report.bundle_url.rstrip("/") + "/" + SIGNATURE_NAME)
        report.signed = sig_status == 200 and _is_json_object(sig_text)
    except Exception:
        report.signed = False

    site_claim = report.manifest.get("site")
    if origin(report.bundle_url) == store_origin:
        report.binding = "same-origin"
        if site_claim and origin(str(site_claim)) != store_origin:
            report.problems.append(
                f"manifest.site ({site_claim}) disagrees with the origin "
                "serving the bundle — fix the publish --site value"
            )
    elif not site_claim:
        report.binding = "missing"
        report.problems.append(
            "off-origin bundle carries no manifest.site claim — consumers "
            "cannot verify it speaks for this store (republish with --site)"
        )
    elif origin(str(site_claim)) == store_origin:
        report.binding = "bound"
    else:
        report.binding = "mismatch"
        report.problems.append(
            f"manifest.site is {site_claim}, but the pointer came from "
            f"{origin} — the bundle does not speak for this store"
        )
    return report
