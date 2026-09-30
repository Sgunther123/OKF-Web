"""Outbound HTTP for every fetcher in the toolchain (EDGE-CASES E2).

Every URL this toolchain fetches comes from data it does not control: a
surveyed page, a sitemap, a capability concept, a store's link tag, a
concept's ``resource``. The fetch is therefore a security boundary, and
there is exactly one of it: :func:`safe_fetch`, governed by a
:class:`FetchPolicy`.

What the boundary enforces:

- **Scheme allowlist**: ``http`` and ``https`` only. ``file:``, ``ftp:``,
  ``data:`` and the rest are refused before any handler sees them.
- **Host refusal**: loopback, private (RFC 1918 and the rest of the
  IANA special registry), link-local (the cloud metadata service lives
  there), reserved, multicast and unspecified addresses are refused. The
  check runs on the literal host in every spelling the resolver would
  accept (``127.1``, ``0x7f000001``, ``2130706433``, ``017700000001``,
  ``0``, bracketed IPv6, IPv4-mapped IPv6) and, at connection time, on
  every address the resolver returns for a name. The socket then
  connects to the address that was checked, so the check cannot be
  raced by a DNS answer that changes between lookup and connect.
- **Redirects**: every hop is re-checked like the first URL, and at most
  ``max_redirects`` hops are followed.
- **Size**: at most ``max_bytes`` of body are read; one byte more is an
  error, never a truncated success.
- **Time**: ``timeout`` bounds each socket operation and ``deadline``
  bounds the body read as a whole, so a server that drips bytes cannot
  hold a fetch open indefinitely.
- **Encoding**: ``Accept-Encoding: identity`` is requested; a body that
  arrives gzip- or deflate-compressed anyway (objects stored
  pre-compressed, a proxy that compresses unconditionally) is decoded
  under the same byte cap, and any other encoding is an error, never
  compressed bytes handed to a parser.

Opt-outs are explicit and never the default: ``allow_loopback`` permits
the operator's own machine (the hosting recipes are verified against a
local server), ``allow_private`` permits everything else as well (a
staging host on the LAN). The CLI's ``--allow-private-hosts`` sets both.

Behind an HTTP proxy (``HTTPS_PROXY`` and friends, honoured as urllib
does), the proxy host itself is not vetted, since the operator
configured it, and the target's addresses are vetted as far as the
local resolver can see them; the proxy does the final resolution.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from email.message import Message

from . import __version__

DEFAULT_USER_AGENT = f"okf-web/{__version__}"
_ALLOWED_SCHEMES = ("http", "https")
_CHUNK = 64 * 1024


class FetchError(OSError):
    """Any refusal or failure inside :func:`safe_fetch`. An ``OSError``
    so that callers which already treat fetch failures as one signal
    keep doing so."""


class UnsafeURL(FetchError):
    """The scheme or the host is outside what the policy allows."""


class FetchTooLarge(FetchError):
    """The body exceeded the policy's byte cap."""


class FetchTimeout(FetchError):
    """The whole fetch exceeded the policy's deadline."""


class TooManyRedirects(FetchError):
    """More redirect hops than the policy allows."""


@dataclass(frozen=True)
class FetchPolicy:
    max_bytes: int = 5 * 1024 * 1024
    timeout: float = 15.0
    deadline: float = 60.0
    max_redirects: int = 5
    allow_private: bool = False
    allow_loopback: bool = False
    user_agent: str = DEFAULT_USER_AGENT

    def permits(self, host: str) -> str | None:
        """Why ``host`` is refused by this policy, or ``None``. Checks the
        literal spelling and the local-name conventions only; names are
        resolved and re-checked at connection time."""
        return _host_refusal(host, self)


PAGE_POLICY = FetchPolicy(max_bytes=5 * 1024 * 1024, timeout=30.0, deadline=60.0)
ROBOTS_POLICY = FetchPolicy(max_bytes=256 * 1024, timeout=15.0, deadline=30.0)
CAPABILITY_POLICY = FetchPolicy(max_bytes=1024 * 1024, timeout=15.0, deadline=30.0)


@dataclass
class FetchResult:
    url: str
    status: int
    headers: Message
    body: bytes

    @property
    def text(self) -> str:
        charset = self.headers.get_content_charset() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            # A charset Python does not know (EDGE-CASES A4): the page is
            # still a page, so read it as UTF-8 rather than abort the run.
            return self.body.decode("utf-8", errors="replace")


# --- host classification -----------------------------------------------------

def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a literal host spells, in any spelling the resolver
    would accept, or ``None`` for a name."""
    bare = host.strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(bare)
    except ValueError:
        pass
    # inet_aton takes the shorthand forms (127.1, 0x7f000001, 2130706433,
    # 017700000001, 0) that ipaddress rejects but getaddrinfo honours.
    try:
        packed = socket.inet_aton(bare)
    except OSError:
        return None
    return ipaddress.IPv4Address(packed)


def _address_refusal(ip, policy: FetchPolicy) -> str | None:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return None if (policy.allow_loopback or policy.allow_private) else "loopback"
    if policy.allow_private:
        return None
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved or not ip.is_global:
        return "reserved"
    return None


def _host_refusal(host: str, policy: FetchPolicy) -> str | None:
    lowered = host.lower().rstrip(".")
    if not lowered:
        return "the URL has no host"
    if lowered == "localhost" or lowered.endswith((".localhost", ".local")):
        if policy.allow_loopback or policy.allow_private:
            return None
        return f"{host} is a local name"
    ip = _literal_address(lowered)
    if ip is None:
        return None
    kind = _address_refusal(ip, policy)
    if kind is None:
        return None
    return f"{host} is a {kind} address"


def is_private_host(host: str) -> bool:
    """True for a host the default policy refuses on its spelling alone:
    local names and literal loopback, private, link-local, reserved,
    multicast or unspecified addresses, in every spelling. A name that
    *resolves* privately is caught at connection time by
    :func:`safe_fetch`, not here."""
    return _host_refusal(host, FetchPolicy()) is not None


def check_url(url: str, policy: FetchPolicy | None = None) -> None:
    """Raise :class:`UnsafeURL` when the policy refuses the URL on its
    scheme or its literal host. Cheap, no network."""
    policy = policy or FetchPolicy()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURL(f"refusing to fetch {url}: only http and https are fetched")
    host = parts.hostname or ""
    reason = _host_refusal(host, policy)
    if reason is not None:
        raise UnsafeURL(
            f"refusing to fetch {url}: {reason}"
            + ("" if policy.allow_private else " (--allow-private-hosts permits a local dev host)")
        )


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _vetted_address(host: str, port: int, policy: FetchPolicy) -> str:
    """Resolve ``host`` and return one address to connect to, after every
    resolved address passed the policy. Any refused address refuses the
    whole name: a mixed answer is how rebinding tricks look."""
    reason = _host_refusal(host, policy)
    if reason is not None:
        raise UnsafeURL(f"refusing to connect: {reason}")
    try:
        addresses = _resolve(host, port)
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve {host}: {exc}") from exc
    if not addresses:
        raise FetchError(f"cannot resolve {host}: no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        kind = _address_refusal(ip, policy)
        if kind is not None:
            raise UnsafeURL(
                f"refusing to connect: {host} resolves to {address}, a {kind} address"
                + ("" if policy.allow_private else " (--allow-private-hosts permits a local dev host)")
            )
    return addresses[0]


# --- pinned connections: the address that was checked is the one used ------

class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, policy: FetchPolicy, pin: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self._policy = policy
        self._pin = pin

    def _open_socket(self) -> socket.socket:
        host = self.host
        if self._pin:
            host = _vetted_address(self.host, self.port, self._policy)
        return socket.create_connection((host, self.port), self.timeout, self.source_address)

    def connect(self) -> None:
        self.sock = self._open_socket()
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(_PinnedHTTPConnection, http.client.HTTPSConnection):
    """The pinned base comes first on purpose: its ``__init__`` takes
    ``policy`` and ``pin`` and forwards the rest, so that
    ``HTTPSConnection.__init__``'s own ``super()`` call lands on
    ``HTTPConnection``. With the bases the other way round that call
    landed on the pinned base without ``policy``, and no TLS connection
    could be built at all — every live ``https://`` fetch failed, and the
    callers that treat a failed page as unreachable hid it (found on the
    deployed machine, 2026-09-23; ``tests/test_net_tls.py`` now builds
    one and completes a loopback TLS round trip)."""

    def __init__(self, *args, policy: FetchPolicy, pin: bool = True, context=None, **kwargs):
        super().__init__(*args, policy=policy, pin=pin, context=context, **kwargs)

    def connect(self) -> None:
        sock = self._open_socket()
        server_hostname = self.host
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
            server_hostname = self._tunnel_host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, policy: FetchPolicy):
        super().__init__()
        self._policy = policy

    def http_open(self, req):
        return self.do_open(
            _PinnedHTTPConnection, req, policy=self._policy, pin=not req.has_proxy()
        )


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, policy: FetchPolicy, context: ssl.SSLContext):
        super().__init__(context=context)
        self._policy = policy
        self._ssl = context

    def https_open(self, req):
        return self.do_open(
            _PinnedHTTPSConnection,
            req,
            policy=self._policy,
            pin=not req.has_proxy(),
            context=self._ssl,
        )


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: FetchPolicy):
        super().__init__()
        self._policy = policy
        self.hops = 0

    def http_error_302(self, req, fp, code, msg, headers):
        # urllib turns a redirect to a non-http scheme into a plain 3xx
        # answer; the policy wants it refused loudly, so the Location is
        # checked here, before urllib looks at it.
        location = headers.get("location") or headers.get("uri")
        if location:
            check_url(urllib.parse.urljoin(req.full_url, location.strip()), self._policy)
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > self._policy.max_redirects:
            raise TooManyRedirects(
                f"more than {self._policy.max_redirects} redirects from {req.full_url}"
            )
        check_url(newurl, self._policy)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(policy: FetchPolicy) -> urllib.request.OpenerDirector:
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        _HTTPHandler(policy),
        _HTTPSHandler(policy, ssl.create_default_context()),
        urllib.request.HTTPDefaultErrorHandler(),
        _RedirectHandler(policy),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def _read_capped(response, policy: FetchPolicy, started: float, url: str) -> bytes:
    # read1 returns after one underlying read, so a server dripping bytes
    # is checked against the deadline every few bytes, not after the whole
    # declared length has arrived.
    reader = getattr(response, "read1", None) or response.read
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() - started > policy.deadline:
            raise FetchTimeout(
                f"fetch of {url} exceeded the {policy.deadline:.0f}s deadline"
            )
        chunk = reader(min(_CHUNK, policy.max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > policy.max_bytes:
            raise FetchTooLarge(
                f"response from {url} exceeds the {policy.max_bytes} byte cap"
            )


_METHODS = ("GET", "POST")


_DECODED_ENCODINGS = ("gzip", "x-gzip", "deflate")


def _decode_body(body: bytes, headers: Message, policy: FetchPolicy, url: str) -> bytes:
    """Undo a ``Content-Encoding`` the server applied although identity
    was asked for. gzip and deflate (zlib-wrapped or raw) are decoded
    under the same byte cap as the wire body: an inflating body past the
    cap is :class:`FetchTooLarge`, never a truncated success; any other
    encoding is a :class:`FetchError`, never garbage handed to a parser.
    The header is removed once the body no longer carries it."""
    encoding = (headers.get("Content-Encoding") or "").strip().lower()
    if not encoding or encoding == "identity":
        return body
    if encoding not in _DECODED_ENCODINGS:
        raise FetchError(
            f"{url} answered with Content-Encoding {encoding!r} although "
            "identity was requested; only gzip and deflate are decoded"
        )
    if encoding == "deflate":
        candidates = (zlib.MAX_WBITS, -zlib.MAX_WBITS)  # zlib-wrapped, then raw
    else:
        candidates = (zlib.MAX_WBITS | 16,)
    last_error: zlib.error | None = None
    for wbits in candidates:
        decompressor = zlib.decompressobj(wbits)
        out = bytearray()
        data = body
        try:
            while data:
                out += decompressor.decompress(data, policy.max_bytes + 1 - len(out))
                if len(out) > policy.max_bytes:
                    raise FetchTooLarge(
                        f"{url} inflates past the {policy.max_bytes} byte cap"
                    )
                data = decompressor.unconsumed_tail
            out += decompressor.flush()
        except zlib.error as exc:
            last_error = exc
            continue
        if len(out) > policy.max_bytes:
            raise FetchTooLarge(f"{url} inflates past the {policy.max_bytes} byte cap")
        del headers["Content-Encoding"]
        return bytes(out)
    raise FetchError(
        f"{url}: the {encoding} body could not be decoded: {last_error}"
    ) from last_error


def safe_fetch(
    url: str,
    policy: FetchPolicy | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> FetchResult:
    """GET (or, with ``method="POST"``, send ``data``) ``url`` under
    ``policy``. Returns every HTTP status as a :class:`FetchResult` (a
    404 is an answer, not a failure); raises a :class:`FetchError`
    subclass for refusals, caps, deadlines and transport failures.

    A POST goes through the same door as a GET: the host checks, the
    pinned connection, the caps and the deadline. The caller sets the
    body's ``Content-Type`` in ``headers``. A redirected POST follows
    the stdlib rule (re-issued as a GET without its body, the target
    re-checked like any redirect).

    Identity encoding is requested (a caller's ``Accept-Encoding``
    header overrides it); a gzip or deflate answer is decoded under the
    byte cap regardless, so the body returned is the document, never
    compressed bytes."""
    policy = policy or FetchPolicy()
    method = (method or "GET").upper()
    if method not in _METHODS:
        raise FetchError(
            f"unsupported method {method!r} (want one of: {', '.join(_METHODS)})"
        )
    if data is not None and method != "POST":
        raise FetchError("a request body needs the POST method")
    if method == "POST" and data is None:
        data = b""
    check_url(url, policy)
    request_headers = {"User-Agent": policy.user_agent,
                       "Accept-Encoding": "identity"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method
    )
    started = time.monotonic()
    opener = _opener(policy)
    try:
        response = opener.open(request, timeout=policy.timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    except FetchError:
        raise
    except urllib.error.URLError as exc:
        inner = exc.reason
        if isinstance(inner, FetchError):
            raise inner
        raise FetchError(f"could not fetch {url}: {inner}") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc
    with response:
        body = _read_capped(response, policy, started, url)
        body = _decode_body(body, response.headers, policy, url)
        return FetchResult(
            url=response.geturl(),
            status=int(getattr(response, "status", None) or response.getcode() or 0),
            headers=response.headers,
            body=body,
        )


def fetch_text(
    url: str,
    policy: FetchPolicy | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """:func:`safe_fetch` for callers that want a page or a document: a
    non-2xx status is a failure here, as it is for the survey, drift and
    robots checks that used to rely on urllib raising."""
    result = safe_fetch(url, policy, headers)
    if result.status >= 400:
        raise FetchError(f"HTTP {result.status} for {url}")
    return result.text
