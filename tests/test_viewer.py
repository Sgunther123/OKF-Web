"""The bundle viewer: measured facts only, both routes of use shown,
read activity from real log lines, and no scripts on the page."""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from okf_web import cli as cli_mod
from okf_web import logscan
from okf_web.evaluator import ARCHETYPES
from okf_web.model import load_bundle, split_l10n
from okf_web.viewer import REVENUE_MOMENTS, build_viewer, write_viewer

TODAY = _dt.date(2026, 8, 5)

_CLF = (
    '203.0.113.7 - - [10/Aug/2026:13:55:36 +0000] "GET /.well-known/okf/index.md HTTP/1.1" 200 2357 "-" "Mozilla/5.0 (compatible; GPTBot/1.1)"\n'
    '203.0.113.8 - - [10/Aug/2026:14:00:00 +0000] "GET /.well-known/okf/policies/returns.md HTTP/1.1" 200 1800 "-" "Mozilla/5.0"\n'
    '203.0.113.9 - - [10/Aug/2026:14:05:00 +0000] "GET /products/tent HTTP/1.1" 200 51000 "-" "GPTBot/1.1"\n'
    '203.0.113.7 - - [12/Aug/2026:08:15:00 +0000] "GET /.well-known/okf/manifest.json HTTP/1.1" 200 900 "-" "GPTBot/1.1"\n'
)
_JSONL = json.dumps({
    "path": "/.well-known/okf/manifest.json",
    "user_agent": "ClaudeBot/1.0 (+https://anthropic.com)",
    "time": "2026-08-11T09:00:00Z",
}) + "\n"


def test_viewer_shows_the_example_bundle_from_measured_facts(example_bundle):
    bundle = load_bundle(example_bundle)
    page = build_viewer(bundle, today=TODAY)

    assert "<script" not in page
    assert page == build_viewer(load_bundle(example_bundle), today=TODAY)
    assert "<title>Alpine Peak Outfitters bundle viewer</title>" in page

    # Every concept in the working copy is listed, translations by key excluded.
    for rel, concept in bundle.concepts.items():
        if split_l10n(rel) is None:
            assert f"<code>/{rel}</code>" in page, rel
    assert "Translations in es" in page

    # What a publish would hold back, and why.
    assert "Limited Warranty" in page and "held back" in page
    assert "draft awaiting human review (high risk" in page

    # The pipeline strip carries this bundle's own facts.
    assert "https://www.alpinepeakoutfitters.example/.well-known/okf/" in page
    assert "okf_info, okf_search, okf_get, okf_capabilities, okf_execute" in page

    # Revenue map: one row per archetype, measured counts from the scorecard.
    assert len(re.findall(r'<tr><td><strong>[^<]+</strong><div class="sub">“', page)) == len(ARCHETYPES)
    assert set(REVENUE_MOMENTS) == set(ARCHETYPES)
    assert page.count('<span class="warn">2 / 3 answered</span>') == 2
    assert page.count("3 / 3 answered") == len(ARCHETYPES) - 2

    # Live lookups and the derived tier, counted from the bundle.
    assert page.count("<td><strong>Live ") + page.count("<td><strong>Order Status") >= 1
    live_rows = re.findall(r'<td><strong>[^<]*</strong><div class="sub"><code>/capabilities/', page)
    assert len(live_rows) == 5
    assert "5 objects would be emitted" in page
    assert "Alpine 2 Tent" in page and "no named person has vouched" in page

    # Retrieval rows reuse the report's blocks, judged rows link to gaps.
    assert page.count("<details") == len(ARCHETYPES)
    assert page.count("judged not answered") == 2
    assert 'id="gap-pol-3"' in page and 'href="#gap-pol-3"' in page
    assert 'id="gap-cap-3"' in page

    # Read activity without a log: an honest empty state, not a number.
    assert "No access log was given" in page
    assert "GPTBot" in page


def test_viewer_without_scorecard_or_question_pack(bundle_copy):
    (bundle_copy / "evaluations" / "geo-scorecard.md").unlink()
    (bundle_copy / "evaluations" / "questions.yaml").unlink()
    page = build_viewer(load_bundle(bundle_copy), today=TODAY)
    assert "<script" not in page
    assert page.count("not measured yet") == len(ARCHETYPES)
    assert "No question pack is committed" in page
    assert "judged not answered" not in page
    assert "<details" not in page
    assert "questions that find matching knowledge" not in page


def test_logscan_records_days_and_recency():
    report = logscan.scan_lines((_CLF + _JSONL).splitlines())
    assert report.ai_hits == 3
    assert dict(report.by_day) == {"2026-08-10": 1, "2026-08-11": 1, "2026-08-12": 1}
    assert report.agent_last_seen["GPTBot"].date() == _dt.date(2026, 8, 12)
    assert report.agent_last_seen["ClaudeBot"].date() == _dt.date(2026, 8, 11)


def test_viewer_read_activity_panel(example_bundle, tmp_path):
    bundle = load_bundle(example_bundle)
    report = logscan.scan_lines((_CLF + _JSONL).splitlines())
    page = build_viewer(bundle, today=TODAY, access_logs=report,
                        log_sources=["access.log"])
    assert "from access.log" in page
    assert "<td>GPTBot</td><td class=\"num\">2</td>" in page
    assert "<td>ClaudeBot</td><td class=\"num\">1</td>" in page
    assert "<code>manifest.json</code></td><td class=\"num\">2</td>" in page
    assert page.count('class="day"') == 3
    assert "between 2026-08-10 and 2026-08-12" in page
    assert "1</div><div class=\"label\">fetches by other clients" in page

    quiet = logscan.scan_lines([_CLF.splitlines()[1]])
    page = build_viewer(bundle, today=TODAY, access_logs=quiet, log_sources=["quiet.log"])
    assert "no fetch of the bundle by a named AI agent" in page
    assert "docs/HOSTING.md" in page


def test_view_cli_writes_outside_the_bundle(example_bundle, tmp_path, capsys):
    log = tmp_path / "access.log"
    log.write_text(_CLF + _JSONL, encoding="utf-8")
    out = tmp_path / "pages" / "viewer.html"
    assert cli_mod.main([
        "view", str(example_bundle), "--out", str(out), "--access-log", str(log),
    ]) == 0
    text = out.read_text(encoding="utf-8")
    assert "<title>Alpine Peak Outfitters bundle viewer</title>" in text
    assert "3 AI-agent fetch(es) by 2 agent(s)" in capsys.readouterr().out

    written = write_viewer(example_bundle, out=tmp_path / "plain.html", today=TODAY)
    assert written.exists() and "No access log was given" in written.read_text(encoding="utf-8")
    assert not (example_bundle / "bundle-viewer.html").exists()
