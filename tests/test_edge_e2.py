"""EDGE-CASES phase E2: reachability hardening for every fetcher.

Covers S1 (the private-host guard bypassed by shorthand literals,
private DNS and redirects), S5 (fetchers accepting any scheme and any
host), S7 (unbounded reads) and the fetch side of S6. Every network test
runs against a loopback server started here; nothing leaves the machine.
"""
from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from okf_web import cli as cli_mod
from okf_web import discover as discover_mod
from okf_web import drift, logscan, mcp_bridge, net, publisher, surveyor
from okf_web.net import (
    FetchError,
    FetchPolicy,
    FetchTimeout,
    FetchTooLarge,
    TooManyRedirects,
    UnsafeURL,
    check_url,
    is_private_host,
    safe_fetch,
)

LOOPBACK = FetchPolicy(allow_loopback=True)


class _Server(ThreadingHTTPServer):
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def _send(self, status: int, body: bytes, ctype: str = "text/plain; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _redirect(self, location: str):
        self._send(302, b"", extra={"Location": location})

    def do_GET(self):  # noqa: C901 - a small router
        path = self.path
        if path == "/ok":
            self._send(200, b"hello")
        elif path == "/page":
            self._send(200, b"<html><body><h1>Trail Pack</h1><p>A pack.</p></body></html>",
                       "text/html; charset=utf-8")
        elif path == "/big":
            body = b"x" * (1024 * 1024)
            self._send(200, body)
        elif path == "/drip":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "200")
            self.end_headers()
            try:
                for _ in range(200):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif path == "/redirect-file":
            self._redirect("file:///etc/hostname")
        elif path == "/redirect-metadata":
            self._redirect("http://169.254.169.254/latest/meta-data/")
        elif path == "/redirect-private":
            self._redirect("http://10.0.0.5/internal")
        elif path == "/redirect-ok":
            self._redirect(self.base + "/ok")
        elif path == "/loop":
            self._redirect(self.base + "/loop")
        elif path == "/sitemap.xml":
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{self.base}/page</loc></url>
  <url><loc>file:///etc/hostname</loc></url>
  <url><loc>http://10.0.0.5/internal</loc></url>
  <url><loc>http://169.254.169.254/latest/meta-data/</loc></url>
  <url><loc>http://0x7f000001/shorthand</loc></url>
</urlset>"""
            self._send(200, body.encode(), "application/xml")
        elif path == "/robots.txt":
            self._send(200, b"User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        elif path == "/index.html":
            self._send(200, b'<html><head><link rel="okf-bundle" href="file:///srv/okf/"></head></html>',
                       "text/html; charset=utf-8")
        else:
            self._send(404, b"nope")


class _IndexHandler(_Handler):
    """A sitemap index whose children include refused locations."""

    def do_GET(self):
        if self.path == "/sitemap.xml":
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{self.base}/nested.xml</loc></sitemap>
  <sitemap><loc>file:///etc/sitemap.xml</loc></sitemap>
  <sitemap><loc>http://10.0.0.5/sitemap.xml</loc></sitemap>
</sitemapindex>"""
            self._send(200, body.encode(), "application/xml")
        elif self.path == "/nested.xml":
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{self.base}/nested-page</loc></url>
  <url><loc>ftp://127.0.0.1/pub</loc></url>
</urlset>"""
            self._send(200, body.encode(), "application/xml")
        else:
            super().do_GET()


class _HugeRobots(_Handler):
    def do_GET(self):
        if self.path == "/robots.txt":
            self._send(200, b"# padding\n" * 40000)  # ~400 KiB, past the 256 KiB cap
        else:
            super().do_GET()


@contextmanager
def _serve(handler=_Handler):
    server = _Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _no_connections(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("a connection was attempted")
    monkeypatch.setattr(net.socket, "create_connection", boom)


# --- S5: scheme allowlist ----------------------------------------------------

@pytest.mark.parametrize("url", ["file:///etc/hostname", "ftp://127.0.0.1/pub", "data:text/plain,hi", "gopher://x/"])
def test_only_http_and_https_are_fetched(url, monkeypatch):
    _no_connections(monkeypatch)
    with pytest.raises(UnsafeURL, match="only http and https"):
        safe_fetch(url, FetchPolicy(allow_private=True))
    with pytest.raises(UnsafeURL):
        check_url(url, FetchPolicy(allow_private=True))


# --- S1: every spelling of a private literal ----------------------------------

@pytest.mark.parametrize(
    "host",
    ["127.1", "0x7f000001", "2130706433", "017700000001", "0", "[::ffff:127.0.0.1]",
     "127.0.0.1", "[::1]", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
     "100.64.1.1", "0.0.0.0", "localhost", "printer.local", "db.internal.localhost"],
)
def test_private_spellings_are_refused_without_a_connection(host, monkeypatch):
    _no_connections(monkeypatch)
    assert is_private_host(host)
    with pytest.raises(UnsafeURL, match="refusing to fetch"):
        safe_fetch(f"http://{host}/price")


@pytest.mark.parametrize("host", ["8.8.8.8", "shop.example", "www.store.example", "[2606:4700::1111]"])
def test_public_spellings_pass_the_literal_check(host):
    assert not is_private_host(host)
    check_url(f"https://{host}/")  # no exception


def test_loopback_is_refused_by_default_and_allowed_by_policy():
    with _serve() as base:
        with pytest.raises(UnsafeURL, match="loopback address .*--allow-private-hosts"):
            safe_fetch(base + "/ok")
        result = safe_fetch(base + "/ok", LOOPBACK)
        assert (result.status, result.text) == (200, "hello")
        assert safe_fetch(base + "/ok", FetchPolicy(allow_private=True)).text == "hello"


def test_resolver_answers_are_checked_and_the_vetted_address_is_used(monkeypatch):
    # A public-looking name that resolves privately is refused before
    # any socket opens, even when only one of several answers is private.
    answers = {"rebind.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "127.0.0.1"]}
    monkeypatch.setattr(net, "_resolve", lambda host, port: answers[host])
    _no_connections(monkeypatch)
    with pytest.raises(UnsafeURL, match="resolves to 10.0.0.5, a private address"):
        safe_fetch("http://rebind.example:1/")
    with pytest.raises(UnsafeURL, match="resolves to 127.0.0.1, a loopback address"):
        safe_fetch("http://mixed.example:1/")


def test_the_connection_goes_to_the_address_that_was_checked(monkeypatch):
    # "pinned.example" does not exist; the fetch succeeds only because the
    # socket connects to the vetted resolver answer, not to a second lookup.
    with _serve() as base:
        port = int(base.rsplit(":", 1)[1])
        monkeypatch.setattr(net, "_resolve", lambda host, p: ["127.0.0.1"] if host == "pinned.example" else [])
        result = safe_fetch(f"http://pinned.example:{port}/ok", LOOPBACK)
        assert result.text == "hello"


def test_resolution_failure_is_a_fetch_error(monkeypatch):
    def fail(host, port):
        raise socket.gaierror(-2, "Name or service not known")
    monkeypatch.setattr(net, "_resolve", fail)
    with pytest.raises(FetchError, match="cannot resolve"):
        safe_fetch("http://nowhere.example/")


# --- S1: redirects are re-checked --------------------------------------------

def test_redirect_hops_are_rechecked():
    with _serve() as base:
        with pytest.raises(UnsafeURL, match="only http and https"):
            safe_fetch(base + "/redirect-file", LOOPBACK)
        with pytest.raises(UnsafeURL, match="link-local"):
            safe_fetch(base + "/redirect-metadata", LOOPBACK)
        with pytest.raises(UnsafeURL, match="private"):
            safe_fetch(base + "/redirect-private", LOOPBACK)
        ok = safe_fetch(base + "/redirect-ok", LOOPBACK)
        assert ok.text == "hello" and ok.url.endswith("/ok")
        with pytest.raises(TooManyRedirects):
            safe_fetch(base + "/loop", FetchPolicy(allow_loopback=True, max_redirects=3))


# --- S7: caps and deadlines ---------------------------------------------------

def test_body_cap_is_enforced():
    with _serve() as base:
        with pytest.raises(FetchTooLarge, match="exceeds the 65536 byte cap"):
            safe_fetch(base + "/big", FetchPolicy(allow_loopback=True, max_bytes=64 * 1024))
        assert safe_fetch(base + "/ok", FetchPolicy(allow_loopback=True, max_bytes=5)).text == "hello"
        with pytest.raises(FetchTooLarge):
            safe_fetch(base + "/ok", FetchPolicy(allow_loopback=True, max_bytes=4))


def test_deadline_bounds_a_dripping_body():
    with _serve() as base:
        started = time.monotonic()
        with pytest.raises(FetchTimeout, match="deadline"):
            safe_fetch(base + "/drip", FetchPolicy(allow_loopback=True, timeout=5.0, deadline=1.0))
        assert time.monotonic() - started < 4.0


def test_statuses_are_answers_and_fetch_text_treats_errors_as_failures():
    with _serve() as base:
        assert safe_fetch(base + "/missing", LOOPBACK).status == 404
        with pytest.raises(FetchError, match="HTTP 404"):
            net.fetch_text(base + "/missing", LOOPBACK)


def test_log_lines_past_the_bound_are_skipped_before_the_regex():
    line = '1.2.3.4 - - [10/Sep/2026:10:00:00 +0000] "GET /.well-known/okf/index.md HTTP/1.1" 200 12 "-" "GPTBot/1.0"'
    report = logscan.scan_lines([line, "x" * (logscan.MAX_LINE_LENGTH + 1)])
    assert report.lines == 2 and report.ai_hits == 1


# --- the six callers ------------------------------------------------------------

def test_bridge_fetch_follows_the_capability_policy(monkeypatch):
    with _serve() as base:
        with pytest.raises(UnsafeURL, match="loopback"):
            mcp_bridge._http_get(base + "/ok")
        assert mcp_bridge._http_get(base + "/ok", allow_private=True) == (200, "hello")
        # Opting in to private hosts never opens other schemes.
        with pytest.raises(UnsafeURL, match="only http and https"):
            mcp_bridge._http_get(base + "/redirect-file", allow_private=True)
    _no_connections(monkeypatch)
    for host in ("2130706433", "0x7f000001", "127.1", "017700000001", "0"):
        with pytest.raises(UnsafeURL):
            mcp_bridge._http_get(f"http://{host}/price")


def test_surveyor_fetch_and_sitemap_drop_refused_locations():
    with _serve() as base:
        with pytest.raises(UnsafeURL):
            surveyor.fetch(base + "/page")
        assert "Trail Pack" in surveyor.fetch(base + "/page", allow_private=True)
        # Loopback allowed, everything else still refused: the page on this
        # server survives, and so does the loopback literal in shorthand
        # spelling (0x7f000001 is 127.0.0.1); private, link-local and
        # file: locations are dropped.
        assert surveyor.discover_sitemap(base, policy=LOOPBACK) == [
            base + "/page",
            "http://0x7f000001/shorthand",
        ]
        # The operator's opt-in keeps private hosts; file: never comes back.
        opted_in = surveyor.discover_sitemap(base, allow_private=True)
        assert base + "/page" in opted_in and "http://10.0.0.5/internal" in opted_in
        assert not any(url.startswith("file:") for url in opted_in)
    with _serve(_IndexHandler) as base:
        assert surveyor.discover_sitemap(base, policy=LOOPBACK) == [base + "/nested-page"]


def test_survey_records_refused_urls_and_never_calls_the_llm(tmp_path):
    calls = {"fetch": 0, "llm": 0}

    class _LLM:
        model = "fake"

        def complete(self, system, user, max_tokens=4096):
            calls["llm"] += 1
            return "{}"

    def fetcher(url):
        calls["fetch"] += 1
        return "page"

    result = surveyor.survey(
        ["file:///etc/hostname", "http://10.0.0.5/internal", "http://0x7f000001/x"],
        tmp_path / "bundle",
        _LLM(),
        fetcher=fetcher,
    )
    assert len(result.errors) == 3 and all("refusing to fetch" in e for e in result.errors)
    assert calls == {"fetch": 0, "llm": 0}


def test_discover_refuses_unsafe_store_urls_and_pointers():
    fetched: list[str] = []

    def fake_fetch(url):
        fetched.append(url)
        if url.endswith("/manifest.json"):
            return 404, ""
        return 200, '<html><head><link rel="okf-bundle" href="http://10.0.0.5/okf/"></head></html>'

    report = discover_mod.discover("file:///srv/store/index.html", fetch=fake_fetch)
    assert fetched == [] and any("only http and https" in p for p in report.problems)

    report = discover_mod.discover("https://shop.example/home.html", fetch=fake_fetch)
    assert "link-tag" in report.routes
    assert any("not fetched" in p and "private" in p for p in report.problems)
    assert not any(url.startswith("http://10.0.0.5") for url in fetched)


def test_discover_runs_against_a_loopback_store_only_when_allowed(capsys):
    with _serve() as base:
        assert cli_mod.main(["discover", base + "/index.html"]) == 1
        out = capsys.readouterr().out
        assert "loopback address" in out
        assert cli_mod.main(["discover", base + "/index.html", "--allow-private-hosts"]) == 1
        out = capsys.readouterr().out
        assert "link tag points at file:///srv/okf, not fetched" in out
        assert "only http and https" in out


def test_drift_fetch_follows_the_page_policy():
    with _serve() as base:
        with pytest.raises(UnsafeURL):
            drift._fetch_page_text(base + "/page")
        assert "Trail Pack" in drift._fetch_page_text(base + "/page", allow_private=True)


def test_check_robots_refuses_private_hosts_and_caps_the_body():
    with _serve() as base:
        blocked, error = publisher.check_robots(base, "/.well-known/okf")
        assert blocked == [] and "loopback" in error
        assert publisher.check_robots(base, "/.well-known/okf", allow_private=True) == (["GPTBot"], None)
    with _serve(_HugeRobots) as base:
        blocked, error = publisher.check_robots(base, "/.well-known/okf", allow_private=True)
        assert blocked == [] and "byte cap" in error


def test_cli_offers_the_flag_where_untrusted_urls_are_fetched():
    parser = cli_mod.build_parser()
    for argv in (
        ["survey", "b", "--allow-private-hosts"],
        ["drift", "b", "--allow-private-hosts"],
        ["discover", "https://s.example", "--allow-private-hosts"],
        ["publish", "b", "dist", "--allow-private-hosts"],
        ["mcp", "b", "--allow-private-hosts"],
    ):
        assert parser.parse_args(argv).allow_private_hosts is True
    assert parser.parse_args(["discover", "https://s.example"]).allow_private_hosts is False
