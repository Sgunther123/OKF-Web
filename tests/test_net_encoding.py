"""``safe_fetch`` and content encodings: identity is asked for, and a
body that arrives compressed anyway (objects stored pre-gzipped at rest,
a proxy that compresses unconditionally) is decoded under the byte cap,
never handed to a parser as gzip bytes. Found on 2026-09-30 while
confirming the hosting recipes: a pre-compressed manifest read as
"no bundle found"."""

import gzip
import json
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from okf_web.net import FetchError, FetchPolicy, FetchTooLarge, safe_fetch

LOOPBACK = FetchPolicy(allow_loopback=True)
PAYLOAD = (
    b'{"files": {"index.md": {"sha256": "x", "bytes": 1}}, '
    b'"site": "https://store.example"}'
)


@pytest.fixture
def _no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


class _Encoded(BaseHTTPRequestHandler):
    def do_GET(self):
        encoding = None
        if self.path == "/echo":
            body = (self.headers.get("Accept-Encoding") or "<none>").encode()
        elif self.path in ("/gzip", "/x-gzip"):
            body, encoding = gzip.compress(PAYLOAD), self.path[1:]
        elif self.path == "/deflate":
            body, encoding = zlib.compress(PAYLOAD), "deflate"
        elif self.path == "/raw-deflate":
            raw = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            body, encoding = raw.compress(PAYLOAD) + raw.flush(), "deflate"
        elif self.path == "/br":
            body, encoding = b"\x0bnot-brotli-at-all", "br"
        elif self.path == "/bomb":
            body, encoding = gzip.compress(b"0" * 200_000), "gzip"
        elif self.path == "/broken":
            body, encoding = b"\x1f\x8b\x08garbage-not-a-stream", "gzip"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(_no_proxy):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Encoded)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_identity_is_requested_and_a_caller_may_override(server):
    assert safe_fetch(f"{server}/echo", LOOPBACK).text == "identity"
    assert safe_fetch(f"{server}/echo", LOOPBACK,
                      headers={"Accept-Encoding": "gzip"}).text == "gzip"


def test_compressed_answers_are_decoded_under_the_cap(server):
    for path in ("/gzip", "/x-gzip", "/deflate", "/raw-deflate"):
        result = safe_fetch(f"{server}{path}", LOOPBACK)
        assert result.body == PAYLOAD, path
        assert result.headers.get("Content-Encoding") is None, path
        assert json.loads(result.text)["site"] == "https://store.example"


def test_unknown_or_broken_encodings_and_bombs_are_errors(server):
    with pytest.raises(FetchError, match="Content-Encoding 'br'"):
        safe_fetch(f"{server}/br", LOOPBACK)
    with pytest.raises(FetchError, match="could not be decoded"):
        safe_fetch(f"{server}/broken", LOOPBACK)
    small = FetchPolicy(allow_loopback=True, max_bytes=50_000)
    # A few hundred bytes on the wire that inflate to 200 KB: the cap
    # applies to what the parser would see, not to what the wire carried.
    with pytest.raises(FetchTooLarge, match="inflates past"):
        safe_fetch(f"{server}/bomb", small)
    assert len(safe_fetch(f"{server}/bomb", LOOPBACK).body) == 200_000
