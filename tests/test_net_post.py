"""``safe_fetch`` with a body: a POST goes through the one door — the
same host checks, pinned connection, caps and deadline as a GET — so
a platform app's token exchanges never need a raw
``urlopen``. A loopback server echoes what it received; the refusals
are exact."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from okf_web import net
from okf_web.net import FetchError, FetchPolicy, safe_fetch

LOOPBACK = FetchPolicy(allow_loopback=True)


@pytest.fixture
def _no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


class _Echo(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        received = self.rfile.read(length)
        body = (
            b"method=POST;type=" + (self.headers.get("Content-Type") or "").encode()
            + b";body=" + received
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        body = b"method=GET"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_a_post_goes_through_the_same_door(_no_proxy):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/token"
        result = safe_fetch(
            url, LOOPBACK, headers={"Content-Type": "application/json"},
            method="POST", data=b'{"code": "c0de"}',
        )
        assert result.status == 200
        assert result.text == 'method=POST;type=application/json;body={"code": "c0de"}'
        # The default stays a GET, and a POST without a body is a POST.
        assert safe_fetch(url, LOOPBACK).text == "method=GET"
        assert safe_fetch(url, LOOPBACK, method="post").text.startswith("method=POST")
        # The policy's refusals precede any socket, method or not.
        with pytest.raises(net.UnsafeURL):
            safe_fetch(url, FetchPolicy(), method="POST", data=b"x")
    finally:
        server.shutdown()
        server.server_close()


def test_only_get_and_post_exist_and_a_body_needs_post():
    with pytest.raises(FetchError, match="unsupported method"):
        safe_fetch("https://shop.example/x", LOOPBACK, method="PUT")
    with pytest.raises(FetchError, match="needs the POST method"):
        safe_fetch("https://shop.example/x", LOOPBACK, data=b"x")
