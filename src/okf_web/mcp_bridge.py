"""MCP bridge: serve a bundle to AI assistants *today*.

Generative-engine crawlers adopting ``/.well-known/okf/`` is the
long game. This bridge is the short game: any MCP client (Claude
Desktop, Claude Code, and a growing list of assistants) can mount the
bundle as a set of tools and use it right now — retrieval over the
published view, full concept reads, and execution of the store's
declared capability endpoints. Consumption stops waiting on crawler
adoption, and merchants can watch an assistant answer from their own
bundle before any engine ever fetches it.

Design constraints:

* **Stdlib only.** Like the hashing retriever, the bridge must not
  cost a dependency. MCP's stdio transport is newline-delimited
  JSON-RPC 2.0; the minimal server surface (``initialize``,
  ``tools/list``, ``tools/call``, ``ping``) is small enough to
  implement directly.
* **Published view by default.** Assistants are consumers: they see
  what engines would see — drafts and expired promotions withheld.
  ``--working`` serves the working copy for merchant self-testing.
* **Trust travels with the answer.** Every search hit carries its
  trust tier, risk class, and staleness so the assistant can prefer
  human-reviewed concepts and say so.
* **Capabilities stay read-only.** ``okf_execute`` only runs
  ``runtime: http`` capabilities with GET, exactly as the profile
  requires capability endpoints to be safe for anonymous callers.

Claude Desktop config (``claude_desktop_config.json``)::

    {"mcpServers": {"my-store": {
        "command": "okf-web",
        "args": ["mcp", "/path/to/bundle"]}}}

or, for any *published* bundle without cloning anything (GAPS item 10;
:mod:`okf_web.remote`)::

    "args": ["mcp", "--url", "https://store.example/.well-known/okf"]
"""

from __future__ import annotations

import datetime as _dt
import difflib
import functools
import json
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import evaluator
from .model import INTERNAL_DIRS, Bundle, Concept, load_bundle, localized_view, marked_dists
from .net import CAPABILITY_POLICY, FetchPolicy, is_private_host, safe_fetch
from .publisher import published_view

USER_AGENT = "okf-web-mcp/0.1"
_DEFAULT_PROTOCOL = "2025-03-26"
_BODY_LIMIT = 4000  # chars of a capability response, or of a search hit's body
MAX_TOP_K = 10  # a caller cannot ask for the whole bundle in one search
WEAK_RELEVANCE = 0.2  # below this share the best hit is labeled weak
_SUGGESTIONS = 5  # nearest paths named when okf_get misses


def _http_get(
    url: str,
    timeout: float = 15.0,
    allow_private: bool = False,
    policy: FetchPolicy | None = None,
) -> tuple[int, str]:
    """Fetch a capability endpoint under the capability policy (1 MiB
    cap, deadline, redirect re-check, private hosts refused on every
    resolved address unless the merchant opted in). Any HTTP status is
    an answer the assistant gets to see."""
    policy = policy or FetchPolicy(
        max_bytes=CAPABILITY_POLICY.max_bytes,
        timeout=timeout,
        deadline=CAPABILITY_POLICY.deadline,
        allow_private=allow_private,
        user_agent=USER_AGENT,
    )
    result = safe_fetch(url, policy)
    return result.status, result.text


# The literal-host fast path (local names, every spelling of a loopback,
# private, link-local, reserved, multicast or unspecified literal). A name
# that *resolves* privately is refused at connection time by safe_fetch.
_is_private_host = is_private_host


def bundle_signature(root: Path | str) -> tuple[int, int, int]:
    """``(files, newest mtime_ns, total bytes)`` over the bundle's
    knowledge files — hidden paths, internal dirs, published copies and
    symlinks excluded, as the loader excludes them. Cheap enough to
    take on every tool call; any edit, addition or deletion moves it,
    and the content-hashed parse cache makes the reload it triggers
    nearly free (GAPS item 6)."""
    root = Path(root)
    marked = marked_dists(root)
    files = newest = total = 0
    for path in root.rglob("*.md"):
        parts = path.relative_to(root).parts
        if parts[0] in INTERNAL_DIRS or any(part.startswith(".") for part in parts):
            continue
        if any(copy in path.parents for copy in marked) or path.is_symlink():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        files += 1
        newest = max(newest, st.st_mtime_ns)
        total += st.st_size
    return files, newest, total


@dataclass
class LocalSource:
    """A bundle directory, served as the view the flags select. The
    bridge re-reads it whenever :func:`bundle_signature` moves, so a
    survey, an approval or a re-publish during an assistant session
    is served from the next tool call on — no restart, no lock (each
    file is written atomically, so a read never sees a torn one)."""

    root: Path
    working: bool = False
    include_machine_confirmed: bool = False
    today: _dt.date | None = None
    lang: str | None = None

    def signature(self) -> Any:
        return bundle_signature(self.root)

    def load(self) -> Bundle:
        bundle = load_bundle(self.root)
        if self.lang:
            bundle = localized_view(bundle, self.lang)
        if not self.working:
            bundle = published_view(bundle, self.include_machine_confirmed, self.today)
        return bundle

    def describe(self) -> dict[str, Any]:
        return {"path": str(self.root), "view": "working copy" if self.working else "published"}


@dataclass
class BridgeState:
    bundle: Bundle
    retriever: Callable[[Bundle, str, int], list[Concept]]
    top_k: int = 4
    http_get: Callable[[str], tuple[int, str]] = field(default=_http_get)
    allow_private_hosts: bool = False
    # ``(concept, relevance)`` pairs for search results; None when the
    # retriever offers no scores.
    scored: Callable[[Bundle, str, int], list[tuple[Concept, float]]] | None = None
    # Where the bundle comes from and what it looked like when loaded.
    source: Any = None
    signature: Any = None


def refresh(state: BridgeState) -> bool:
    """Reload the bundle when its source moved; True when it did."""
    if state.source is None:
        return False
    signature = state.source.signature()
    if signature == state.signature:
        return False
    state.bundle = state.source.load()
    state.signature = signature
    return True


def _wire_retriever(state: BridgeState, retriever, min_relevance: float) -> None:
    if retriever is None:
        state.retriever = functools.partial(evaluator.retrieve, min_relevance=min_relevance)
        state.scored = functools.partial(evaluator.retrieve_scored, min_relevance=min_relevance)
    else:
        state.retriever = retriever
        state.scored = getattr(retriever, "scored", None)


def build_state(
    bundle_root: Path | str,
    working: bool = False,
    include_machine_confirmed: bool = False,
    retriever: Callable[[Bundle, str, int], list[Concept]] | None = None,
    top_k: int = 4,
    http_get: Callable[[str], tuple[int, str]] | None = None,
    today: _dt.date | None = None,
    lang: str | None = None,
    allow_private_hosts: bool = False,
    min_relevance: float = evaluator.RELEVANCE_FLOOR,
    source: Any = None,
) -> BridgeState:
    """Serve ``bundle_root`` (or any ``source`` with ``signature()`` and
    ``load()``, such as a remote published bundle)."""
    source = source or LocalSource(
        Path(bundle_root), working, include_machine_confirmed, today, lang
    )
    state = BridgeState(
        bundle=source.load(),
        retriever=evaluator.retrieve,
        top_k=top_k,
        http_get=http_get or (lambda url: _http_get(url, allow_private=allow_private_hosts)),
        allow_private_hosts=allow_private_hosts,
        source=source,
    )
    state.signature = source.signature()
    _wire_retriever(state, retriever, min_relevance)
    return state


# --- tool implementations --------------------------------------------------

def _concept_summary(concept: Concept) -> dict[str, Any]:
    return {
        "path": concept.rel_path,
        "type": concept.type,
        "title": concept.title,
        "description": str(concept.frontmatter.get("description") or ""),
        "trust_tier": concept.trust_tier,
        "risk": concept.risk,
        "stale": concept.is_stale(),
        "resource": concept.resource,
    }


def _tool_info(state: BridgeState, args: dict) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for concept in state.bundle.concepts.values():
        by_type[concept.type or "Unknown"] = by_type.get(concept.type or "Unknown", 0) + 1
    identity = next(
        (c for c in state.bundle.concepts.values() if c.type == "Store Identity"), None
    )
    # The scorecard is read only at its own path (S-U1; lint E022).
    scorecard = state.bundle.concepts.get(evaluator.SCORECARD_PATH)
    if scorecard is not None and scorecard.type != "GEO Scorecard":
        scorecard = None
    metrics = (scorecard.x_geo.get("metrics") if scorecard else None) or None
    return {
        "store": _concept_summary(identity) if identity else None,
        "concepts_by_type": dict(sorted(by_type.items())),
        "scorecard_metrics": metrics,
        # A retrieval-only scorecard carries no verdicts: say so, so an
        # assistant never reads found-knowledge counts as answers.
        "scorecard_judged": bool(metrics and "coverage" in metrics),
        "source": state.source.describe() if hasattr(state.source, "describe") else None,
        "usage": (
            "okf_search finds concepts for a shopper question; okf_get reads "
            "one in full; prefer trust_tier=human-reviewed, cite concept "
            "paths, and use okf_execute (see okf_capabilities) for live "
            "values like price and stock instead of quoting static text."
        ),
    }


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= _BODY_LIMIT:
        return text, False
    return text[:_BODY_LIMIT] + "…", True


def _tool_search(state: BridgeState, args: dict) -> dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("`question` is required")
    top_k = min(max(1, int(args.get("top_k") or state.top_k)), MAX_TOP_K)
    if state.scored is not None:
        pairs = state.scored(state.bundle, question, top_k)
    else:
        pairs = [(c, None) for c in state.retriever(state.bundle, question, top_k)]
    results = []
    for concept, relevance in pairs:
        body, truncated = _clip(concept.body.strip())
        entry = {**_concept_summary(concept), "body": body}
        if relevance is not None:
            entry["relevance"] = relevance
        if truncated:
            entry["truncated"] = True
            entry["note"] = "body clipped; okf_get returns the whole concept"
        results.append(entry)
    payload: dict[str, Any] = {"question": question, "results": results}
    # Say what the bundle does not cover, instead of handing the
    # assistant a weak hit to guess from (GAPS item 2).
    if not results:
        payload["coverage"] = "none"
        payload["note"] = (
            "nothing in the bundle is relevant to this question; the store's "
            "published knowledge does not cover it — say so rather than "
            "answering from elsewhere"
        )
    elif results[0].get("relevance") is not None and results[0]["relevance"] < WEAK_RELEVANCE:
        payload["coverage"] = "weak"
        payload["note"] = (
            "weak match: the best hit carries little of the question; treat "
            "it as a lead to read with okf_get, not as an answer"
        )
    else:
        payload["coverage"] = "found"
    return payload


def _tool_get(state: BridgeState, args: dict) -> str:
    path = str(args.get("path") or "").strip().lstrip("/")
    concept = state.bundle.get(path)
    if concept is None:
        # Name the nearest paths, never the whole bundle: on a large
        # bundle the full list is the error nobody can read.
        near = difflib.get_close_matches(path, sorted(state.bundle.concepts), n=_SUGGESTIONS, cutoff=0.3)
        hint = f"; did you mean {', '.join(near)}?" if near else "; use okf_search to find paths"
        raise ValueError(f"no published concept at {path!r}{hint}")
    return concept.render()


def _tool_capabilities(state: BridgeState, args: dict) -> dict[str, Any]:
    caps = []
    for rel, concept in sorted(state.bundle.concepts.items()):
        if concept.type != "Attested Computation":
            continue
        executor = concept.frontmatter.get("executor") or {}
        caps.append({
            **_concept_summary(concept),
            "runtime": concept.frontmatter.get("runtime"),
            "parameters": concept.frontmatter.get("parameters") or [],
            "executor": executor if isinstance(executor, dict) else {},
            "rate_limit": concept.x_geo.get("rate_limit"),
            "auth": concept.x_geo.get("auth"),
        })
    return {"capabilities": caps}


def _tool_execute(state: BridgeState, args: dict) -> dict[str, Any]:
    path = str(args.get("path") or "").strip().lstrip("/")
    supplied = args.get("arguments") or {}
    if not isinstance(supplied, dict):
        raise ValueError("`arguments` must be an object of parameter values")
    concept = state.bundle.get(path)
    if concept is None:
        raise ValueError(f"no published concept at {path!r}")
    if concept.type != "Attested Computation" or concept.frontmatter.get("runtime") != "http":
        raise ValueError(f"{path} is not an http-runtime Attested Computation")
    executor = concept.frontmatter.get("executor") or {}
    template = str(executor.get("resource") or "")
    if not template.startswith(("http://", "https://")):
        raise ValueError(f"{path} has no http(s) executor.resource")
    declared = concept.frontmatter.get("parameters") or []
    missing = [
        str(p.get("name"))
        for p in declared
        if isinstance(p, dict) and p.get("required") and p.get("name") not in supplied
    ]
    if missing:
        raise ValueError(f"missing required parameter(s): {', '.join(missing)}")

    # Fill declared holes only; optional-and-absent become empty (the
    # endpoint applies its documented default). Anything the caller
    # supplied beyond the declared parameters is ignored, never spliced
    # into the URL.
    url = template
    for p in declared:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        name = str(p["name"])
        value = supplied.get(name, "")
        url = url.replace("{" + name + "}", urllib.parse.quote(str(value), safe=""))
    # The whole URL, not just path+query: a placeholder left in the host
    # or fragment must fail the same contractual way, not surface later
    # as DNS noise from a literal `{region}` hostname.
    if "{" in url:
        raise ValueError(f"executor template has undeclared placeholders: {url}")
    authority = urllib.parse.urlsplit(template)
    if "{" in authority.scheme or "{" in authority.netloc:
        # Every placeholder is declared by now, so one in the host is a
        # declared parameter that would let the caller choose the target;
        # placeholders belong in the path or query (review 2026-10-21,
        # S-U10; lint E023 says the same at publish time).
        raise ValueError(
            f"{path} executor template puts a placeholder in its scheme or host "
            f"({authority.netloc}); placeholders belong in the path or query"
        )

    # A bundle is data; the hosts it names must not become a bridge into
    # the operator's own network (READINESS A4). Loopback, private, and
    # link-local targets are refused unless the merchant opted in for
    # self-testing against a dev host.
    host = urllib.parse.urlsplit(url).hostname or ""
    if not host:
        raise ValueError(f"{path} executor URL has no host: {url}")
    if not state.allow_private_hosts and _is_private_host(host):
        raise ValueError(
            f"{path} executor points at a private or local host ({host}); "
            "refusing to fetch. Run `okf-web mcp` with "
            "--allow-private-hosts to permit this for local testing."
        )

    status, body = state.http_get(url)
    return {
        "capability": path,
        "url": url,
        "status": status,
        "body": body[:_BODY_LIMIT] + ("…" if len(body) > _BODY_LIMIT else ""),
        "receipt_fields": executor.get("receipt") or [],
        "note": (
            "Retain the receipt fields when quoting this value; treat the "
            "response's own timestamp as its freshness, not the bundle's."
        ),
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "okf_info",
        "description": (
            "Orient yourself: store identity, concept counts by type, the "
            "latest answerability scorecard, and how to use the other tools."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _tool_info,
    },
    {
        "name": "okf_search",
        "description": (
            "Retrieve the bundle concepts most relevant to a shopper "
            "question. Results carry trust_tier (prefer human-reviewed), "
            "risk, staleness, relevance (the share of the question they "
            "cover) and the concept body; `coverage` says found, weak or "
            "none — when none, the bundle does not cover the question. "
            "Cite concept paths in answers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "the shopper's question"},
                "top_k": {"type": "integer", "description": f"max results (default 4, at most {MAX_TOP_K})"},
            },
            "required": ["question"],
        },
        "handler": _tool_search,
    },
    {
        "name": "okf_get",
        "description": "Read one concept in full (frontmatter + body) by bundle path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "e.g. policies/returns.md"}},
            "required": ["path"],
        },
        "handler": _tool_get,
    },
    {
        "name": "okf_capabilities",
        "description": (
            "List the store's executable capabilities (live price, stock, "
            "order status…) with their parameters. Live values must come "
            "from these, never from static concept text."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": _tool_capabilities,
    },
    {
        "name": "okf_execute",
        "description": (
            "Execute a declared http capability (read-only GET) and return "
            "the live response plus its receipt fields."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "capability concept path"},
                "arguments": {
                    "type": "object",
                    "description": "parameter values declared by the capability",
                },
            },
            "required": ["path"],
        },
        "handler": _tool_execute,
    },
]


# --- JSON-RPC / MCP plumbing ----------------------------------------------

def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_message(state: BridgeState, msg: Any) -> dict[str, Any] | list | None:
    """Handle one JSON-RPC message; returns the response, or None for
    notifications (which get no response by protocol). A batch (a JSON
    array) answers with the array of its responses; a message that is
    not an object, or has no string ``method``, is an invalid request
    (-32600) rather than an exception that ends the session (review
    2026-10-21, A-U8)."""
    if isinstance(msg, list):
        if not msg:
            return _error(None, -32600, "invalid request: empty batch")
        responses = [r for r in (handle_message(state, m) for m in msg) if r is not None]
        return responses or None
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request: expected a JSON object")
    method = msg.get("method")
    msg_id = msg.get("id") if isinstance(msg.get("id"), (str, int, type(None))) else None
    is_notification = "id" not in msg
    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return _error(msg_id, -32600, "invalid request: `method` must be a string")

    if method == "initialize":
        from . import __version__

        requested = (msg.get("params") or {}).get("protocolVersion")
        return _result(msg_id, {
            "protocolVersion": requested or _DEFAULT_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "okf-web", "version": __version__},
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {
            "tools": [
                {k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS
            ]
        })
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            return _result(msg_id, _tool_result(f"unknown tool: {name}", is_error=True))
        try:
            refresh(state)
            payload = tool["handler"](state, params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 — tool failures are results, not protocol errors
            return _result(msg_id, _tool_result(str(exc), is_error=True))
        return _result(msg_id, _tool_result(payload))
    if is_notification:
        return None  # notifications/initialized and friends
    return _error(msg_id, -32601, f"method not found: {method}")


def serve_stdio(state: BridgeState, stdin=None, stdout=None) -> None:
    """Blocking newline-delimited JSON-RPC loop over stdio. No input line
    ends the loop: a parse error, an invalid request or an unexpected
    exception each answer with the protocol's error and the session
    goes on (review 2026-10-21, A-U8)."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
        else:
            try:
                response = handle_message(state, msg)
            except Exception as exc:  # noqa: BLE001 — the session must outlive one bad message
                msg_id = msg.get("id") if isinstance(msg, dict) else None
                response = _error(msg_id, -32603, f"internal error: {exc}")
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
