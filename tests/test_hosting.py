"""Hosting recipes, exercised for real.

docs/HOSTING.md promises that a published dist served under three header
rules is discoverable over both routes: same-origin at /.well-known/okf,
and delegated through the head tag. These tests serve the example bundle
over real HTTP from the stdlib server, configured exactly like every
recipe, and run the consumer-side verifier against it. They also keep
the document honest: the recipes' fenced blocks must still carry the
rules the server implements.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from okf_web import publisher
from okf_web.discover import discover

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "HOSTING.md"

# The serving rules of HOSTING.md §0, as this test's server implements them.
CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
}
HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "public, max-age=300, must-revalidate",
}


class _RecipeHandler(SimpleHTTPRequestHandler):
    """A static host configured like every recipe: typed, CORS-open, cached."""

    def guess_type(self, path):
        return CONTENT_TYPES.get(Path(path).suffix) or super().guess_type(path)

    def end_headers(self):
        for name, value in HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, *args):  # keep pytest output clean
        pass


class _SpaFallbackHandler(_RecipeHandler):
    """A single-page-app host: every missing path answers index.html, 200."""

    def translate_path(self, path):
        target = super().translate_path(path)
        if not Path(target).exists():
            return str(Path(self.directory) / "index.html")
        return target


@contextmanager
def _serve(root: Path, handler=_RecipeHandler):
    root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(handler, directory=str(root))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _head(url: str):
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.headers


# --- the two routes, over real HTTP ------------------------------------------


def test_same_origin_recipe_serves_a_discoverable_bundle(example_bundle, tmp_path):
    root = tmp_path / "site"
    with _serve(root) as origin:
        (root / "index.html").write_text(
            "<!doctype html><title>store</title>", encoding="utf-8"
        )
        result = publisher.publish(
            example_bundle, root / ".well-known" / "okf", site=origin
        )

        report = discover(origin, allow_private=True)
        assert report.routes == ["well-known"]
        assert report.binding == "same-origin" and report.ok
        assert report.problems == []
        assert report.files == len(result.published)
        assert not report.signed

        status, headers = _head(f"{origin}/.well-known/okf/index.md")
        assert status == 200
        assert headers["Content-Type"] == CONTENT_TYPES[".md"]
        for name, value in HEADERS.items():
            assert headers[name] == value
        _, headers = _head(f"{origin}/.well-known/okf/manifest.json")
        assert headers["Content-Type"] == CONTENT_TYPES[".json"]
        _, headers = _head(f"{origin}/.well-known/okf/attesters/http_refetch.py")
        assert headers["Content-Type"].startswith("text/")


def test_delegated_recipe_binds_the_bundle_to_the_store(example_bundle, tmp_path):
    with _serve(tmp_path / "store") as store, _serve(tmp_path / "cdn") as cdn:
        dist = tmp_path / "cdn" / ".well-known" / "okf"
        bundle_url = f"{cdn}/.well-known/okf"
        publisher.publish(example_bundle, dist, site=store, bundle_url=bundle_url)

        # The merchant pastes the tag exactly as the publisher emitted it.
        snippet = (dist / "llms-snippet.txt").read_text(encoding="utf-8")
        tag = next(
            line for line in snippet.splitlines()
            if line.startswith('<link rel="okf-bundle"')
        )
        assert tag == f'<link rel="okf-bundle" href="{bundle_url}/">'
        (tmp_path / "store" / "index.html").write_text(
            f"<!doctype html><html><head><title>store</title>{tag}</head>"
            "<body><p>platform-hosted storefront</p></body></html>",
            encoding="utf-8",
        )

        report = discover(store, allow_private=True)
        assert report.routes == ["link-tag"]
        assert report.bundle_url == bundle_url
        assert report.binding == "bound" and report.ok
        assert report.problems == []


def test_delegated_recipe_rejects_a_bundle_that_names_another_store(
    example_bundle, tmp_path
):
    with _serve(tmp_path / "store") as store, _serve(tmp_path / "cdn") as cdn:
        dist = tmp_path / "cdn" / "okf"
        bundle_url = f"{cdn}/okf"
        (tmp_path / "store" / "index.html").write_text(
            f'<html><head><link rel="okf-bundle" href="{bundle_url}/"></head></html>',
            encoding="utf-8",
        )

        publisher.publish(
            example_bundle, dist, site="https://other.example", bundle_url=bundle_url
        )
        report = discover(store, allow_private=True)
        assert report.binding == "mismatch" and not report.ok
        assert any("does not speak for this store" in p for p in report.problems)

        publisher.publish(example_bundle, dist, bundle_url=bundle_url)  # no claim
        report = discover(store, allow_private=True)
        assert report.binding == "missing" and not report.ok


def test_html_fallback_cannot_fake_a_signature(example_bundle, tmp_path):
    """Single-page-app hosts answer missing paths with index.html and a 200
    (observed in Cloudflare Pages' emulator without a 404.html). The
    verifier must not read that page as a signature."""
    root = tmp_path / "spa"
    with _serve(root, handler=_SpaFallbackHandler) as origin:
        (root / "index.html").write_text(
            "<!doctype html><title>app</title>", encoding="utf-8"
        )
        publisher.publish(example_bundle, root / ".well-known" / "okf", site=origin)

        status, headers = _head(
            f"{origin}/.well-known/okf/manifest.json.sigstore.json"
        )
        assert status == 200 and headers["Content-Type"].startswith("text/html")

        report = discover(origin, allow_private=True)
        assert report.ok and report.binding == "same-origin"
        assert not report.signed


def test_check_robots_reads_the_served_robots_txt(tmp_path):
    root = tmp_path / "site"
    with _serve(root) as origin:
        (root / "robots.txt").write_text(
            "User-agent: GPTBot\nDisallow: /.well-known/okf/\n\n"
            "User-agent: *\nAllow: /\n",
            encoding="utf-8",
        )
        blocked, error = publisher.check_robots(origin, "/.well-known/okf", allow_private=True)
        assert error is None and blocked == ["GPTBot"]

        (root / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
        assert publisher.check_robots(origin, "/.well-known/okf", allow_private=True) == ([], None)


# --- the document carries the rules the server implements ---------------------


def _fences(text: str) -> list[tuple[str, str]]:
    return re.findall(r"```(\w*)\n(.*?)```", text, re.S)


def _github_anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def test_hosting_doc_recipes_carry_the_serving_rules(example_bundle, tmp_path):
    doc = DOC.read_text(encoding="utf-8")

    # Every in-page link resolves to a heading, so the matrix's recipe
    # column cannot silently point at a renamed section.
    anchors = {
        _github_anchor(h) for h in re.findall(r"^#{1,6} (.+)$", doc, re.M)
    }
    for link in re.findall(r"\]\(#([^)]+)\)", doc):
        assert link in anchors, f"dangling anchor #{link}"
    matrix_rows = [line for line in doc.splitlines() if "| [§" in line]
    assert len(matrix_rows) >= 12

    # The rules themselves, and the gates the document exists to name.
    for value in list(CONTENT_TYPES.values()) + list(HEADERS.values()):
        assert value in doc
    for phrase in (
        "Block AI Bots", "Bot Fight Mode", "AI Crawl Control", "AI Labyrinth",
        "--check-robots", 'rel="okf-bundle"', "404.html", ".nojekyll",
    ):
        assert phrase in doc, phrase

    # The published-file count in §0 stays true to the example bundle.
    result = publisher.publish(example_bundle, tmp_path / "dist")
    assert f"publishes {len(result.published)} files" in doc

    fences = _fences(doc)
    by_lang: dict[str, list[str]] = {}
    for lang, body in fences:
        by_lang.setdefault(lang, []).append(body)

    nginx = by_lang["nginx"][0]
    assert "location ^~ /.well-known/okf/" in nginx
    assert 'default_type "text/markdown; charset=utf-8";' in nginx
    for name, value in HEADERS.items():
        assert f'add_header {name} "{value}" always;' in nginx
    design = (REPO_ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    assert dict(_fences(design)).get("nginx") == nginx, "DESIGN §8 drifted from HOSTING §2.1"

    apache = by_lang["apache"][0]
    for line in (
        "AddType text/markdown .md", "AddCharset utf-8 .md", "RemoveHandler .py",
        'Header set Access-Control-Allow-Origin "*"',
        f'Header set Cache-Control "{HEADERS["Cache-Control"]}"',
    ):
        assert line in apache, line

    caddyfiles = by_lang["caddyfile"]
    assert len(caddyfiles) == 2 and "handle_path /.well-known/okf/*" in caddyfiles[0]
    for body in caddyfiles:
        assert 'header @md >Content-Type "text/markdown; charset=utf-8"' in body
        for name, value in HEADERS.items():
            assert f'header {name} "{value}"' in body
        assert "file_server" in body

    headers_file = next(
        body for lang, body in fences
        if lang == "" and body.startswith("/.well-known/okf/*\n")
    )
    rules = dict(
        line.strip().split(": ", 1)
        for line in headers_file.splitlines()[1:]
        if line.startswith("  ")
    )
    for name, value in HEADERS.items():
        assert rules[name] == value

    for body in by_lang["json"]:
        json.loads(body)
    vercel = json.loads(by_lang["json"][0])
    (rule,) = vercel["headers"]
    assert rule["source"] == "/.well-known/okf/(.*)"
    assert {h["key"]: h["value"] for h in rule["headers"]} == HEADERS
    cors = json.loads(by_lang["json"][1])
    assert cors["CORSRules"][0]["AllowedOrigins"] == ["*"]

    try:
        import tomllib
    except ImportError:  # Python 3.10: the TOML block is still checked textually
        tomllib = None
    netlify = by_lang["toml"][0]
    assert 'for = "/.well-known/okf/*"' in netlify
    if tomllib is not None:
        (rule,) = tomllib.loads(netlify)["headers"]
        assert rule["values"] == HEADERS

    workflow = yaml.safe_load(by_lang["yaml"][0])
    assert workflow["permissions"]["id-token"] == "write"
    runs = [s.get("run", "") for s in workflow["jobs"]["publish"]["steps"]]
    assert any("okf-web publish" in r and "--sign" in r for r in runs)
    assert any("okf-web verify" in r and "--cert-identity" in r for r in runs)

    assert by_lang["Dockerfile"][0].startswith("FROM caddy:2\n")
    bash = "\n".join(by_lang["bash"])
    for command in ("okf-web discover", "aws s3 sync", "rsync -a --delete dist/"):
        assert command in bash
