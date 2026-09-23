"""The TLS side of the safe fetcher, exercised for real (EDGE-CASES E2).

Found on the deployed machine on 2026-09-23: the pinned HTTPS
connection class could not be constructed at all, so every live
``https://`` fetch through :mod:`okf_web.net` failed, and the callers
that treat a failed page as unreachable — the surveyor, drift,
discover, the robots check — hid it. The suite had never built one.
These tests build the class, drive an ``https://`` fetch to its pinned
``connect``, and complete a loopback TLS round trip against a
certificate made for the test."""

import http.client
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from okf_web import net
from okf_web.net import FetchError, FetchPolicy, safe_fetch

LOOPBACK = FetchPolicy(allow_loopback=True, timeout=5.0, deadline=10.0)


def _no_proxy(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


def test_the_pinned_tls_connection_is_constructible():
    conn = net._PinnedHTTPSConnection(
        "shop.example", 443, timeout=5.0, policy=LOOPBACK, pin=True,
        context=ssl.create_default_context(),
    )
    assert isinstance(conn, http.client.HTTPSConnection)
    assert conn._policy is LOOPBACK and conn._pin is True
    assert conn._context is not None and conn.timeout == 5.0
    # The order that makes HTTPSConnection's own super() call land on
    # HTTPConnection rather than on the pinned base.
    assert [c.__name__ for c in type(conn).__mro__[:4]] == [
        "_PinnedHTTPSConnection", "_PinnedHTTPConnection",
        "HTTPSConnection", "HTTPConnection",
    ]


def test_an_https_fetch_reaches_the_pinned_connect(monkeypatch):
    _no_proxy(monkeypatch)
    seen = []

    def connect(self):
        seen.append((self.host, self.port, self._pin, self._policy.allow_loopback))
        raise FetchError("stub: no network in tests")

    monkeypatch.setattr(net._PinnedHTTPSConnection, "connect", connect)
    with pytest.raises(FetchError, match="stub"):
        safe_fetch("https://shop.example/page")
    assert seen == [("shop.example", 443, True, False)]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_a_loopback_tls_round_trip(tmp_path, monkeypatch):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is not available to make a test certificate")
    _no_proxy(monkeypatch)
    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert), str(key))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # The fetcher builds its own default context; trust the test
        # certificate through the same call it makes (captured first:
        # net.ssl is the ssl module itself).
        original = ssl.create_default_context
        monkeypatch.setattr(
            ssl, "create_default_context",
            lambda *a, **k: original(cafile=str(cert)),
        )
        port = server.server_address[1]
        result = safe_fetch(f"https://127.0.0.1:{port}/health", LOOPBACK)
        assert result.status == 200 and result.text == '{"ok": true}'
        assert result.headers.get("Content-Type") == "application/json"
        # Without loopback allowed the same URL is refused before any
        # socket is opened, TLS or not.
        with pytest.raises(net.UnsafeURL):
            safe_fetch(f"https://127.0.0.1:{port}/health", FetchPolicy())
    finally:
        server.shutdown()
        server.server_close()
