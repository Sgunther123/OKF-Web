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
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import evaluator
from .model import Bundle, Concept, load_bundle, localized_view
from .publisher import published_view

USER_AGENT = "okf-web-mcp/0.1"
_DEFAULT_PROTOCOL = "2025-03-26"
_BODY_LIMIT = 4000  # chars of capability response echoed back


def _http_get(url: str, timeout: float = 15.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, response.read().decode(charset, errors="replace")


@dataclass
class BridgeState:
    bundle: Bundle
    retriever: Callable[[Bundle, str, int], list[Concept]]
    top_k: int = 4
    http_get: Callable[[str], tuple[int, str]] = field(default=_http_get)


def build_state(
    bundle_root: Path | str,
    working: bool = False,
    include_machine_confirmed: bool = False,
    retriever: Callable[[Bundle, str, int], list[Concept]] | None = None,
    top_k: int = 4,
    http_get: Callable[[str], tuple[int, str]] | None = None,
    today: _dt.date | None = None,
    lang: str | None = None,
) -> BridgeState:
    bundle = load_bundle(bundle_root)
    if lang:
        bundle = localized_view(bundle, lang)
    if not working:
        bundle = published_view(bundle, include_machine_confirmed, today)
    return BridgeState(
        bundle=bundle,
        retriever=retriever or evaluator.retrieve,
        top_k=top_k,
        http_get=http_get or _http_get,
    )


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
    scorecard = next(
        (c for c in state.bundle.concepts.values() if c.type == "GEO Scorecard"), None
    )
    return {
        "store": _concept_summary(identity) if identity else None,
        "concepts_by_type": dict(sorted(by_type.items())),
        "scorecard_metrics": (scorecard.x_geo.get("metrics") if scorecard else None),
        "usage": (
            "okf_search finds concepts for a shopper question; okf_get reads "
            "one in full; prefer trust_tier=human-reviewed, cite concept "
            "paths, and use okf_execute (see okf_capabilities) for live "
            "values like price and stock instead of quoting static text."
        ),
    }


def _tool_search(state: BridgeState, args: dict) -> dict[str, Any]:
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("`question` is required")
    top_k = int(args.get("top_k") or state.top_k)
    hits = state.retriever(state.bundle, question, top_k)
    return {
        "question": question,
        "results": [
            {**_concept_summary(c), "body": c.body.strip()} for c in hits
        ],
    }


def _tool_get(state: BridgeState, args: dict) -> str:
    path = str(args.get("path") or "").strip().lstrip("/")
    concept = state.bundle.get(path)
    if concept is None:
        known = ", ".join(sorted(state.bundle.concepts))
        raise ValueError(f"no published concept at {path!r}; available: {known}")
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
    if "{" in urllib.parse.urlsplit(url).path + "?" + (urllib.parse.urlsplit(url).query or ""):
        raise ValueError(f"executor template has undeclared placeholders: {url}")

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
            "risk, staleness, and the full concept body; cite concept "
            "paths in answers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "the shopper's question"},
                "top_k": {"type": "integer", "description": "max results (default 4)"},
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


def handle_message(state: BridgeState, msg: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message; returns the response, or None for
    notifications (which get no response by protocol)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = "id" not in msg

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
            payload = tool["handler"](state, params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001 — tool failures are results, not protocol errors
            return _result(msg_id, _tool_result(str(exc), is_error=True))
        return _result(msg_id, _tool_result(payload))
    if is_notification:
        return None  # notifications/initialized and friends
    return _error(msg_id, -32601, f"method not found: {method}")


def serve_stdio(state: BridgeState, stdin=None, stdout=None) -> None:
    """Blocking newline-delimited JSON-RPC loop over stdio."""
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
            response = handle_message(state, msg)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
