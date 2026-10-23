"""Review 2026-10-21, phase U2: the proxied branch of the one fetch door
is exercised (T-U4), still refuses a target that resolves privately
(S-U5), and the deadline covers a redirect chain (S-U6)."""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from okf_web import net
from okf_web.net import FetchPolicy, FetchTimeout, UnsafeURL, safe_fetch


class _Proxy(BaseHTTPRequestHandler):
    """A forwarding proxy that never forwards: it answers every absolute
    URL it is handed, so the test sees exactly what reached it."""

    seen: list[str] = []

    def do_GET(self):  # noqa: N802 — http.server's name
        _Proxy.seen.append(self.path)
        body = f"proxied {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def proxy():
    _Proxy.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_configured_proxy_carries_the_fetch_and_the_door_still_refuses_private_targets(proxy, monkeypatch):
    monkeypatch.setenv("http_proxy", proxy)
    policy = FetchPolicy(allow_loopback=True)
    result = safe_fetch("http://127.0.0.1:1/bundle/index.md", policy)
    assert result.text == "proxied http://127.0.0.1:1/bundle/index.md"
    assert _Proxy.seen == ["http://127.0.0.1:1/bundle/index.md"]

    # The literal check runs before anything reaches the proxy.
    with pytest.raises(UnsafeURL):
        safe_fetch("http://10.0.0.5/x", FetchPolicy())
    # S-U5: a public name that resolves privately is refused even though
    # the proxy, not this host, would open the socket.
    monkeypatch.setattr(net, "_resolve", lambda host, port: ["10.0.0.5"])
    with pytest.raises(UnsafeURL, match="resolves to 10.0.0.5"):
        safe_fetch("http://internal.example/x", FetchPolicy())
    assert len(_Proxy.seen) == 1

    # A name this host cannot resolve is the proxy's to resolve.
    def unresolvable(host, port):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(net, "_resolve", unresolvable)
    assert safe_fetch("http://unresolvable.example/x", FetchPolicy()).text.startswith("proxied")


class _SlowRedirect(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        time.sleep(0.3)
        self.send_response(302)
        self.send_header("Location", "/again")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_deadline_covers_a_slow_redirect_chain():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowRedirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        policy = FetchPolicy(allow_loopback=True, timeout=5.0, deadline=0.5, max_redirects=10)
        started = time.monotonic()
        with pytest.raises(FetchTimeout, match="deadline"):
            safe_fetch(f"http://127.0.0.1:{server.server_address[1]}/start", policy)
        assert time.monotonic() - started < 3.0  # not ten hops of 0.3 s
    finally:
        server.shutdown()
        server.server_close()
