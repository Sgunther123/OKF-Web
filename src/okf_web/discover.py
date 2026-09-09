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
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

from .publisher import _origin
from .signing import SIGNATURE_NAME

USER_AGENT = "okf-web-discover/0.2"
WELL_KNOWN_PATH = "/.well-known/okf"


def _fetch(url: str, timeout: float = 15.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.read().decode(charset, errors="replace")


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


def _try_manifest(fetch, bundle_url: str) -> dict | None:
    try:
        status, text = fetch(bundle_url.rstrip("/") + "/manifest.json")
    except Exception:
        return None
    if status != 200:
        return None
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
        return None
    return manifest if isinstance(manifest, dict) and "files" in manifest else None


def _is_json_object(text: str) -> bool:
    """A sigstore bundle is a JSON object. Hosts that answer every missing
    path with a 200 HTML page (the single-page-app fallback; observed on
    a static host's emulator, docs/HOSTING.md §3.1) must not read as
    signed."""
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def discover(store_url: str, fetch=None, timeout: float = 15.0) -> DiscoveryReport:
    fetch = fetch or (lambda url: _fetch(url, timeout=timeout))
    origin = _origin(store_url)
    report = DiscoveryReport(store_origin=origin)

    # Route 1: the well-known location on the store's own origin.
    well_known = origin + WELL_KNOWN_PATH
    manifest = _try_manifest(fetch, well_known)
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
                if report.manifest is None:
                    pointed_manifest = _try_manifest(fetch, pointed)
                    if pointed_manifest is not None:
                        report.bundle_url, report.manifest = pointed, pointed_manifest
                    else:
                        report.problems.append(
                            f"link tag points at {pointed} but no readable "
                            "manifest.json is there"
                        )

    if report.manifest is None:
        report.problems.append(
            "no bundle found: nothing at the well-known location and no "
            "usable <link rel=\"okf-bundle\"> pointer"
        )
        return report

    report.files = len(report.manifest.get("files", {}))
    try:
        sig_status, sig_text = fetch(report.bundle_url.rstrip("/") + "/" + SIGNATURE_NAME)
        report.signed = sig_status == 200 and _is_json_object(sig_text)
    except Exception:
        report.signed = False

    site_claim = report.manifest.get("site")
    if _origin(report.bundle_url) == origin:
        report.binding = "same-origin"
        if site_claim and _origin(str(site_claim)) != origin:
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
    elif _origin(str(site_claim)) == origin:
        report.binding = "bound"
    else:
        report.binding = "mismatch"
        report.problems.append(
            f"manifest.site is {site_claim}, but the pointer came from "
            f"{origin} — the bundle does not speak for this store"
        )
    return report
