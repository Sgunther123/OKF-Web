"""Who is actually fetching the bundle? Scan server/CDN access logs.

Publishing is one-way: the merchant ships static files and hears
nothing back. This closes the loop with what the serving
infrastructure already records — access logs. It reuses the same
``AI_USER_AGENTS`` roster the robots checker maintains, so "which
engines can reach the bundle" and "which engines did" are answered
from one list.

Two input formats, auto-detected per line:

* **Combined/Common Log Format** (Apache, nginx default,
  most CDN log exports)::

    203.0.113.7 - - [10/Aug/2026:13:55:36 +0000] "GET /.well-known/okf/index.md HTTP/1.1" 200 2357 "-" "GPTBot/1.1"

* **JSON lines** (structured CDN logs): objects with a path (``path``,
  ``url``, or ``request_uri``), a user agent (``user_agent``, ``ua``,
  or ``userAgent``), and optionally a timestamp (``time``,
  ``timestamp``, or ``ts``, ISO-8601).

Honest caveats, so the numbers are read correctly: user agents are
self-declared (an unlisted scraper can wear any name); CDN logs are
often sampled; and a lone ``manifest.json`` fetch is *good* news —
delta sync means an engine checked freshness and needed nothing else.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .publisher import AI_USER_AGENTS

# The request line's pieces do not overlap (the path ends at the first
# space or quote, and whatever follows must start with a space), so a
# long request line without a closing quote matches in linear time
# instead of backtracking quadratically (review 2026-10-21, S-U8).
_CLF_RE = re.compile(
    r'^\S+ \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>[^"\s]+)(?: [^"]*)?"'
    r' (?P<status>\d{3}) \S+(?:\s+"[^"]*"\s+"(?P<ua>[^"]*)")?'
)


def match_agent(user_agent: str | None) -> str | None:
    """The canonical AI agent name a user-agent string declares, if any."""
    if not user_agent:
        return None
    lowered = user_agent.lower()
    for agent in AI_USER_AGENTS:
        if agent.lower() in lowered:
            return agent
    return None


def _parse_time(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    for parse in (
        lambda v: _dt.datetime.strptime(v, "%d/%b/%Y:%H:%M:%S %z"),
        lambda v: _dt.datetime.fromisoformat(v.replace("Z", "+00:00")),
    ):
        try:
            return parse(value)
        except ValueError:
            continue
    return None


def _parse_line(line: str) -> tuple[str, str | None, _dt.datetime | None] | None:
    """Extract ``(path, user_agent, when)`` from one log line, if possible."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None
        raw_path = record.get("path") or record.get("url") or record.get("request_uri")
        if not raw_path:
            return None
        path = urlsplit(str(raw_path)).path or str(raw_path)
        ua = record.get("user_agent") or record.get("ua") or record.get("userAgent")
        when = _parse_time(
            str(record.get("time") or record.get("timestamp") or record.get("ts") or "")
        )
        return path, (str(ua) if ua else None), when
    match = _CLF_RE.match(line)
    if not match:
        return None
    return match.group("path"), match.group("ua"), _parse_time(match.group("time"))


@dataclass
class LogScanReport:
    lines: int = 0
    ai_hits: int = 0            # bundle fetches by known AI agents
    other_hits: int = 0         # bundle fetches by everyone else
    by_agent: Counter = field(default_factory=Counter)
    by_file: Counter = field(default_factory=Counter)
    first_seen: _dt.datetime | None = None
    last_seen: _dt.datetime | None = None
    # AI-agent fetches per calendar day (ISO date → count) and the
    # most recent fetch per agent: the viewer's read-activity panel
    # draws its timeline and "last seen" column from these.
    by_day: Counter = field(default_factory=Counter)
    agent_last_seen: dict = field(default_factory=dict)


# A log line longer than this is not a request record; it is skipped
# before the regex sees it, so a hostile log cannot make matching slow.
MAX_LINE_LENGTH = 16 * 1024


def scan_lines(lines, base_path: str = "/.well-known/okf") -> LogScanReport:
    report = LogScanReport()
    prefix = base_path.rstrip("/")
    for line in lines:
        report.lines += 1
        if len(line) > MAX_LINE_LENGTH:
            continue
        parsed = _parse_line(line)
        if parsed is None:
            continue
        path, ua, when = parsed
        if not (path == prefix or path.startswith(prefix + "/")):
            continue
        agent = match_agent(ua)
        if agent is None:
            report.other_hits += 1
            continue
        report.ai_hits += 1
        report.by_agent[agent] += 1
        report.by_file[path[len(prefix):].lstrip("/") or "(root)"] += 1
        if when is not None:
            if report.first_seen is None or when < report.first_seen:
                report.first_seen = when
            if report.last_seen is None or when > report.last_seen:
                report.last_seen = when
            report.by_day[when.date().isoformat()] += 1
            previous = report.agent_last_seen.get(agent)
            if previous is None or when > previous:
                report.agent_last_seen[agent] = when
    return report
