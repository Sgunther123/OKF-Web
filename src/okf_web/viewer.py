"""The bundle viewer: what is in a bundle, and how engines use it.

``okf-web view`` renders one self-contained HTML page over a bundle
for the people who own it: what the bundle holds (every concept with
its type, trust tier, risk, freshness and connections; what a publish
would ship and what it would hold back), how an AI system discovers,
interprets and surfaces it (the well-known location and the head tag,
the index and provenance an engine reads, the retrieval pass from
shopper questions to knowledge, the live-value capabilities, the
derived JSON-LD and ``llms.txt``, the MCP tools), where each kind of
knowledge earns its keep (the purchase moment each question archetype
serves, what the bundle holds for it, and what the last evaluation
measured), and — given access logs — who has actually read it.

Like the report, the viewer never invents a number: every count is
read from the bundle, the recorded scorecard, or the logs handed to
it, and the retrieval rows are recomputed deterministically at render
time. No LLM call, no dependency beyond the stdlib, and no scripts on
the page. It is an operator's page rather than a consumer surface —
it shows withheld drafts and read logs — so its default output path
is outside the bundle.
"""

from __future__ import annotations

import datetime as _dt
import html
from pathlib import Path

from . import __version__
from .discover import WELL_KNOWN_PATH
from .evaluator import ARCHETYPES, SCORECARD_PATH
from .llm import estimate_tokens
from .logscan import LogScanReport
from .mcp_bridge import TOOLS
from .model import (
    write_atomic,
    Bundle,
    Concept,
    TRUST_HUMAN,
    TRUST_HUMAN_BATCH,
    TRUST_MACHINE,
    TRUST_UNVERIFIED,
    load_bundle,
    split_l10n,
    trust_mix,
    utc_today,
)
from .publisher import AI_USER_AGENTS, select_publishable
from .report import ARCHETYPE_LABELS, _count, _gaps, _judged_verdicts, _question_blocks
from .structured import _LLMS_SECTIONS, jsonld_for

# The purchase moment each question archetype serves, and why it
# matters to a store's revenue. Editorial vocabulary, not measurement:
# the counts beside it are measured, these sentences name the stakes.
REVENUE_MOMENTS: dict[str, tuple[str, str]] = {
    "discovery": (
        "Does this store sell what I need?",
        "Demand captured at the top of the funnel: an assistant that can "
        "say yes, with a product, sends the shopper here instead of "
        "elsewhere.",
    ),
    "product_fact": (
        "Does this product do what I need?",
        "Confidence before the cart: exact facts answer the objection that "
        "otherwise ends the session.",
    ),
    "comparison": (
        "Which of these should I choose?",
        "The choice made on the store's own terms: guides steer to the "
        "right product rather than the cheapest guess, and fewer wrong "
        "choices come back.",
    ),
    "policy": (
        "Can I return it, and what is covered?",
        "Checkout confidence: clear returns and warranty terms remove the "
        "last hesitation.",
    ),
    "fulfillment": (
        "When will it arrive, and what will shipping cost?",
        "Fewer abandoned carts: shipping cost and timing answered before "
        "checkout, not discovered at it.",
    ),
    "trust": (
        "Is this a real store I can trust?",
        "The decision to buy here at all: identity, contact and guarantees "
        "stated once and verified by a named person.",
    ),
    "capability": (
        "What does it cost and is it in stock right now?",
        "Accurate offers: the price and stock an assistant quotes are the "
        "ones at checkout, so no dispute and no sale lost to a stale "
        "number.",
    ),
    "promotion": (
        "Is there a sale or a code?",
        "Timed demand: the current offer reaches the shopper while it "
        "runs, and disappears the day it ends.",
    ),
    "fit_compatibility": (
        "Will it fit me, or work with what I own?",
        "Attach rate and fewer returns: the right size and the right "
        "pairing chosen before purchase.",
    ),
    "ownership": (
        "I own it: how do I care for it and get help?",
        "Retention: owners who get help come back, and warranty and care "
        "answers cost less than support tickets.",
    ),
    "compliance": (
        "What is it made of, where, and is it certified?",
        "Sales to buyers who require proof: materials, origin and "
        "certifications answered with the certificate attached.",
    ),
    "local_availability": (
        "Can I get it near me today?",
        "Store traffic and same-day sales: hours, pickup and shelf "
        "availability answered.",
    ),
    "procurement": (
        "Can my business buy at volume, and on what terms?",
        "Wholesale and B2B orders: eligibility, minimums, terms and lead "
        "times answered for buyers.",
    ),
}

# GEO-PROFILE §1 order, so the inventory reads the way the profile does.
_TYPE_ORDER = [
    "Store Identity", "Policy", "Product", "Product Collection", "FAQ",
    "Buying Guide", "Attested Computation", "Promotion", "Compatibility",
    "Ownership Guide", "Product Passport", "Store Location",
    "Trade Program", "GEO Scorecard",
]

_TIER_CLASS = {
    TRUST_HUMAN: "t-human",
    TRUST_HUMAN_BATCH: "t-batch",
    TRUST_MACHINE: "t-machine",
    TRUST_UNVERIFIED: "t-none",
}

_RISK_WORDS = {"a": "a · high", "b": "b · medium", "c": "c · low"}

SOON_DAYS = 30


class ViewerError(RuntimeError):
    pass


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _date(value) -> str:
    return str(value)[:10] if value else ""


def _verified_line(concept: Concept) -> str:
    entries = concept.verified_entries
    if not entries:
        return ""
    entry = entries[0]
    return f"{entry.get('by', '')} · {_date(entry.get('at'))}"


def _type_key(type_name: str | None) -> tuple[int, str]:
    name = type_name or "Unknown"
    return (
        _TYPE_ORDER.index(name) if name in _TYPE_ORDER else len(_TYPE_ORDER),
        name,
    )


def _tile(value: str, label: str, detail: str = "") -> str:
    detail_html = f'<div class="detail">{_e(detail)}</div>' if detail else ""
    return (
        f'<div class="tile"><div class="value">{_e(value)}</div>'
        f'<div class="label">{_e(label)}</div>{detail_html}</div>'
    )


def _chip(tier: str) -> str:
    return f'<span class="chip {_TIER_CLASS.get(tier, "t-none")}">{_e(tier)}</span>'


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


# --- the sections --------------------------------------------------------


def _read_activity(report: LogScanReport | None, sources: list[str] | None,
                   base_path: str) -> str:
    """The read-activity panel: evidence, from access logs, that AI
    agents fetch the bundle — which agents, which files, which days."""
    roster = ", ".join(AI_USER_AGENTS)
    if report is None:
        return (
            '<p class="meaning">No access log was given, so this page cannot '
            "say who has read the bundle. The evidence lives in the web "
            "server's or CDN's access log: every fetch of a file under "
            f"<code>{_e(base_path)}/</code> by a named AI agent is a read. "
            "Re-render with <code>okf-web view &lt;bundle&gt; --access-log "
            "access.log</code> (Combined Log Format or JSON lines; several "
            "files may be given) and this panel fills in with the agents, "
            "the files they read, and the days they came. Where the log "
            "lives for each kind of host is in docs/MEASUREMENT.md. "
            f"Agents counted as AI readers: {_e(roster)}. Reads through the "
            "MCP bridge happen inside an assistant and never reach an HTTP "
            "log.</p>"
        )
    source_line = (
        f" from {_e(', '.join(sources))}" if sources else ""
    )
    if report.ai_hits == 0:
        return (
            f'<p class="meaning">{report.lines:,} log line(s) read{source_line}: '
            f"<strong>no fetch of the bundle by a named AI agent</strong> "
            f"({report.other_hits:,} fetch(es) of bundle files by other "
            "clients). Zero is a finding. Check, in this order: that the "
            "bundle is reachable (<code>okf-web discover</code>), that "
            "robots.txt allows the agents (<code>okf-web publish "
            "--check-robots</code>), that no bot gate above robots.txt "
            "blocks them (docs/HOSTING.md §6), and that the log window is "
            "long enough for a crawl cycle. Agents counted as AI readers: "
            f"{_e(roster)}.</p>"
        )
    window = ""
    if report.first_seen and report.last_seen:
        window = (
            f" between {_e(report.first_seen.date().isoformat())} and "
            f"{_e(report.last_seen.date().isoformat())}"
        )
    agents = len(report.by_agent)
    tiles = "".join([
        _tile(f"{report.ai_hits:,}", "bundle fetches by named AI agents",
              f"{_plural(agents, 'agent')}{window}"),
        _tile(f"{len(report.by_file):,}", "distinct bundle files they read",
              "a lone manifest.json fetch is delta sync working as designed"),
        _tile(f"{report.other_hits:,}", "fetches by other clients",
              "browsers, unlisted crawlers, your own checks"),
    ])
    agent_rows = []
    for agent, count in report.by_agent.most_common():
        seen = report.agent_last_seen.get(agent)
        agent_rows.append(
            f"<tr><td>{_e(agent)}</td><td class=\"num\">{count:,}</td>"
            f"<td class=\"num\">{round(100 * count / report.ai_hits)}%</td>"
            f"<td>{_e(seen.date().isoformat()) if seen else '—'}</td></tr>"
        )
    file_rows = "".join(
        f"<tr><td><code>{_e(path)}</code></td><td class=\"num\">{count:,}</td></tr>"
        for path, count in report.by_file.most_common(12)
    )
    days_html = ""
    if report.by_day:
        days = sorted(report.by_day.items())[-90:]
        peak = max(count for _, count in days)
        bars = "".join(
            f'<div class="day" title="{_e(day)}: {count}">'
            f'<div class="bar" style="height:{max(4, round(100 * count / peak))}%"></div>'
            f"<span>{_e(day[5:])}</span></div>"
            for day, count in days
        )
        days_html = (
            f"<h3>Fetches per day</h3><div class=\"days\">{bars}</div>"
            '<p class="note">Each bar is one calendar day with at least one '
            "AI-agent fetch; height is relative to the busiest day shown "
            "(at most the last 90 days with fetches).</p>"
        )
    return (
        f'<p class="meaning">{report.lines:,} log line(s) read{source_line}. '
        "A read is one fetch of a file under "
        f"<code>{_e(base_path)}/</code> by a client naming one of the "
        f"known AI agents ({_e(roster)}). Names are self-declared, so treat "
        "the counts as a floor for the named engines, not a census; CDN "
        "logs are often sampled.</p>"
        f'<div class="tiles">{tiles}</div>'
        "<h3>Who read it</h3>"
        '<div class="scroll"><table><thead><tr><th>Agent</th><th class="num">Fetches</th>'
        '<th class="num">Share</th><th>Last seen</th></tr></thead>'
        f"<tbody>{''.join(agent_rows)}</tbody></table></div>"
        "<h3>What they read</h3>"
        '<div class="scroll"><table><thead><tr><th>File</th><th class="num">Fetches</th>'
        f"</tr></thead><tbody>{file_rows}</tbody></table></div>"
        + days_html
    )


def build_viewer(
    bundle: Bundle,
    today: _dt.date | None = None,
    access_logs: LogScanReport | None = None,
    log_sources: list[str] | None = None,
    base_path: str = WELL_KNOWN_PATH,
) -> str:
    """Render the bundle viewer as a self-contained HTML page."""
    today = today or utc_today()
    e = _e

    concepts = {
        rel: c for rel, c in bundle.concepts.items() if split_l10n(rel) is None
    }
    if not concepts:
        raise ViewerError("the bundle has no concepts to show")
    identity = next(
        (c for c in concepts.values() if c.type == "Store Identity"), None
    )
    store = identity.title if identity else bundle.root.name
    root_index = bundle.indexes.get("index.md")
    site = str(((root_index.x_geo if root_index else {}) or {}).get("site") or "").rstrip("/")
    # The scorecard is read only at its own path (S-U1; lint E022).
    scorecard = concepts.get(SCORECARD_PATH)
    if scorecard is not None and scorecard.type != "GEO Scorecard":
        scorecard = None
    metrics = (scorecard.x_geo.get("metrics") if scorecard else None) or {}
    baseline = (scorecard.x_geo.get("baseline") if scorecard else None) or {}
    by_archetype = metrics.get("by_archetype") or {}
    full_run = "coverage" in metrics

    # What a publish would ship today, and what it would hold back.
    include, withheld = select_publishable(bundle, False, today, "warn")
    published = {rel: c for rel, c in concepts.items() if rel in include}
    held = []
    for rel in withheld:
        concept = bundle.concepts[rel]
        if concept.type == "Promotion" and concept.promo_expired(today):
            reason = "expired promotion, retired automatically"
        else:
            reason = "draft awaiting human review" + (
                " (high risk: only a named person's approval can publish it)"
                if concept.is_high_risk else ""
            )
        held.append((concept, reason))

    languages = sorted({
        split_l10n(rel)[0] for rel in bundle.concepts if split_l10n(rel)
    })
    entities = bundle.entities()
    capabilities = [c for c in published.values() if c.type == "Attested Computation"]
    jsonld_types: list[tuple[Concept, str]] = []
    for rel in sorted(published):
        concept = published[rel]
        if concept.trust_tier in (TRUST_HUMAN, TRUST_HUMAN_BATCH):
            obj = jsonld_for(concept, base_path, site or None)
            if obj is not None:
                jsonld_types.append((concept, str(obj.get("@type"))))
    mix = trust_mix(bundle)
    human_vouched = mix.get(TRUST_HUMAN, 0) + mix.get(TRUST_HUMAN_BATCH, 0)
    stale = [c for c in published.values() if c.is_stale(today)]
    soon: list[Concept] = []
    for c in published.values():
        raw = c.frontmatter.get("stale_after")
        if raw is None or c.is_stale(today):
            continue
        try:
            due = _dt.date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if due <= today + _dt.timedelta(days=SOON_DAYS):
            soon.append(c)
    total_tokens = sum(estimate_tokens(c.render()) for c in published.values())
    intent_index: dict[str, list[Concept]] = {a: [] for a in ARCHETYPES}
    for rel in sorted(published):
        for intent in published[rel].intents:
            intent_index.setdefault(intent, []).append(published[rel])

    # --- at a glance -------------------------------------------------------
    tiles = [
        _tile(str(len(published)), "knowledge files ready to publish",
              f"{len(held)} held back · {_plural(len(concepts), 'concept')} in the working copy"),
        _tile(f"{round(100 * human_vouched / max(1, len(concepts)))}%",
              "vouched for by a named person",
              f"{mix.get(TRUST_HUMAN, 0)} reviewed one by one · "
              f"{mix.get(TRUST_HUMAN_BATCH, 0)} under a bulk sign-off"),
        _tile(str(len(capabilities)), "live lookups instead of stale numbers",
              "price, stock, order and claim status fetched from the store's own systems"),
        _tile(f"{total_tokens:,}", "tokens to read the whole published bundle",
              "an assistant needs only the few files a question retrieves"),
    ]
    if full_run:
        tiles.append(_tile(
            f"{round(100 * float(metrics['coverage']))}%",
            "shopper questions answered from the bundle",
            (f"{round(100 * float(baseline['coverage']))}% from the website alone"
             if baseline.get("coverage") is not None else
             f"of {metrics.get('questions', 0)} measured questions"),
        ))
    elif metrics.get("retrieval_hit_rate") is not None:
        tiles.append(_tile(
            f"{round(100 * float(metrics['retrieval_hit_rate']))}%",
            "questions that find matching knowledge",
            "retrieval-only dry run; run the full evaluation for answer coverage",
        ))

    # --- discover / interpret / surface -----------------------------------
    well_known = f"{site}{base_path}/" if site else f"{base_path}/"
    index_sections = sum(
        1 for line in (root_index.body.splitlines() if root_index else [])
        if line.startswith("## ")
    )
    llms_sections = [
        section for section, types in _LLMS_SECTIONS
        if any(c.type in types for c in published.values())
    ]
    edges = 0
    for c in published.values():
        edges += len([r for r in c.entity_refs if r in entities])
    pipeline = f"""
<div class="pipeline">
  <div class="stage"><div class="kicker">1 · Discover</div>
    <h3>How an engine finds it</h3>
    <ul>
      <li>The well-known location: <code>{e(well_known)}</code>, with <code>manifest.json</code> listing every published file and its sha256, so a returning engine re-reads only what changed.</li>
      <li>A head tag on the storefront, <code>&lt;link rel="okf-bundle" href="…/"&gt;</code>, for stores that host the bundle elsewhere; <code>manifest.site</code> binds the bundle back to the store.</li>
      <li>An <code>llms.txt</code> with {len(llms_sections)} sections ({e(', '.join(llms_sections))}) linking into the published files.</li>
      <li>Whoever the store allows: robots.txt and any bot gate above it decide whether {e(', '.join(AI_USER_AGENTS[:4]))} and the rest may read.</li>
    </ul></div>
  <div class="stage"><div class="kicker">2 · Interpret</div>
    <h3>What it reads</h3>
    <ul>
      <li><code>index.md</code>, the bundle's own map: {index_sections} sections pointing at only the published concepts.</li>
      <li>Every file's provenance: who generated it, who verified it and when, its sources, its freshness date, its risk class (<code>x_geo.risk</code>), and the questions it is meant to answer (<code>x_geo.intents</code>).</li>
      <li>Stable ids (<code>x_geo.entity</code>) and {edges} typed connections between files: what fits, works with, covers or certifies what.</li>
      <li>A rule it can rely on: prices, stock and order status are never written down; {len(capabilities)} declared lookups fetch them live.{(' Translations in ' + e(', '.join(languages)) + ' sit beside the originals.') if languages else ''}</li>
    </ul></div>
  <div class="stage"><div class="kicker">3 · Surface</div>
    <h3>What the shopper sees</h3>
    <ul>
      <li>An answer that cites the exact file it came from, at a reading cost of a few files rather than the whole site.</li>
      <li>A live price or stock figure with its receipt, executed through the declared lookup, instead of a number copied from a page.</li>
      <li>{len(jsonld_types)} schema.org objects for the engines that read markup today (<code>jsonld/</code>), derived only from files a named person vouched for.</li>
      <li>Assistants connected through <code>okf-web mcp</code> use {len(TOOLS)} read-only tools: {e(', '.join(t['name'] for t in TOOLS))}.</li>
    </ul></div>
</div>"""

    # --- where the revenue is ----------------------------------------------
    verdicts = _judged_verdicts(scorecard) if scorecard else {}
    revenue_rows = []
    blocks = _question_blocks(bundle, by_archetype if full_run else None,
                              verdicts or None, None)
    for archetype in ARCHETYPES:
        moment, why = REVENUE_MOMENTS[archetype]
        holds = intent_index.get(archetype, [])
        titles = ", ".join(c.title for c in holds[:3])
        if len(holds) > 3:
            titles += f" +{len(holds) - 3} more"
        holds_cell = (
            f"{_plural(len(holds), 'file')}<div class=\"sub\">{e(titles)}</div>"
            if holds else '<span class="miss">nothing declared</span>'
        )
        recorded = by_archetype.get(archetype) or {}
        recorded = recorded if isinstance(recorded, dict) else {}
        total = _count(recorded.get("questions"))
        answered = _count(recorded.get("answered")) if full_run else None
        found = _count(recorded.get("found"))
        if total and answered is not None:
            state = "ok" if answered == total else ("warn" if answered else "gap")
            measured = f'<span class="{state}">{answered} / {total} answered</span>'
        elif total and found is not None:
            # A retrieval-only run: knowledge found is not an answer.
            measured = (
                f'<span class="sub">knowledge found for {found} / {total}, '
                "not judged</span>"
            )
        else:
            measured = '<span class="sub">not measured yet</span>'
        revenue_rows.append(
            f"<tr><td><strong>{e(ARCHETYPE_LABELS.get(archetype, archetype))}</strong>"
            f'<div class="sub">“{e(moment)}”</div></td>'
            f"<td>{holds_cell}</td><td>{measured}</td><td>{e(why)}</td></tr>"
        )

    # --- inventory ---------------------------------------------------------
    inventory = []
    by_type: dict[str, list[Concept]] = {}
    for rel in sorted(concepts):
        by_type.setdefault(concepts[rel].type or "Unknown", []).append(concepts[rel])
    for type_name in sorted(by_type, key=_type_key):
        rows = []
        for c in by_type[type_name]:
            state = ""
            if c.rel_path not in include:
                state = '<div class="held">held back</div>'
            elif c.is_stale(today):
                state = '<div class="held">stale</div>'
            elif c in soon:
                state = '<div class="soon">freshness due soon</div>'
            # A resource is a link only when it is a web address; anything
            # else is shown as text (html.escape cannot neutralize a scheme).
            if c.resource and c.resource.startswith(("http://", "https://")):
                resource = (
                    f'<div class="sub"><a href="{e(c.resource)}">{e(c.resource)}</a></div>'
                )
            elif c.resource:
                resource = f'<div class="sub">{e(c.resource)}</div>'
            else:
                resource = ""
            refs = []
            for key, values in (("fits", c.fits), ("works with", c.works_with),
                                ("covers", c.covers),
                                ("passport for", [c.passport_for] if c.passport_for else [])):
                for ref in values:
                    target = bundle.get(entities[ref]) if ref in entities else None
                    refs.append(f"{key} {target.title if target else ref}")
            links = f'<div class="sub">{e("; ".join(refs))}</div>' if refs else ""
            entity = f'<div class="sub"><code>{e(c.entity)}</code></div>' if c.entity else ""
            intents = e(", ".join(c.intents)) if c.intents else "—"
            rows.append(
                f"<tr><td><strong>{e(c.title)}</strong>{resource}"
                f"<div class=\"sub\"><code>/{e(c.rel_path)}</code></div>{entity}{links}</td>"
                f"<td>{_chip(c.trust_tier)}<div class=\"sub\">{e(_verified_line(c))}</div>{state}</td>"
                f"<td>{e(_RISK_WORDS.get(c.effective_risk, c.effective_risk))}</td>"
                f"<td>{e(_date(c.frontmatter.get('stale_after')) or '—')}</td>"
                f"<td>{intents}</td>"
                f"<td class=\"num\">{estimate_tokens(c.render()):,}</td></tr>"
            )
        inventory.append(
            f"<h3 id=\"type-{e(type_name.lower().replace(' ', '-'))}\">{e(type_name)} "
            f'<span class="count">{_plural(len(rows), "file")}</span></h3>'
            '<div class="scroll"><table class="inv"><thead><tr><th>Concept</th><th>Trust</th>'
            "<th>Risk</th><th>Fresh until</th><th>Answers</th><th class=\"num\">Tokens</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
    held_html = ""
    if held:
        held_html = (
            "<h3>Held back from the published bundle</h3><ul class=\"card\">"
            + "".join(
                f"<li><strong>{e(c.title)}</strong> (<code>/{e(c.rel_path)}</code>): {e(reason)}.</li>"
                for c, reason in held
            )
            + "</ul>"
        )

    # --- live values -------------------------------------------------------
    cap_rows = []
    pointing: dict[str, list[str]] = {}
    for c in published.values():
        for key in ("live_price", "live_stock"):
            target = str(c.x_geo.get(key) or "").lstrip("/")
            if target:
                pointing.setdefault(target, []).append(c.title)
    for c in sorted(capabilities, key=lambda k: k.rel_path):
        params = ", ".join(
            f"{p.get('name')}{'' if p.get('required') else '?'}"
            for p in (c.frontmatter.get("parameters") or []) if isinstance(p, dict)
        )
        executor = c.frontmatter.get("executor") or {}
        receipt = ", ".join(str(f) for f in (executor.get("receipt") or []))
        attester = (c.frontmatter.get("attester") or {}).get("resource") or "—"
        used_by = ", ".join(sorted(pointing.get(c.rel_path, []))) or "—"
        cap_rows.append(
            f"<tr><td><strong>{e(c.title)}</strong><div class=\"sub\"><code>/{e(c.rel_path)}</code></div></td>"
            f"<td><code>{e(executor.get('resource') or c.resource or '')}</code>"
            f"<div class=\"sub\">parameters: {e(params or '—')} · {e(str(c.x_geo.get('rate_limit') or ''))}</div></td>"
            f"<td>{e(receipt or '—')}<div class=\"sub\">attester {e(str(attester))}</div></td>"
            f"<td>{e(used_by)}</td></tr>"
        )
    capabilities_html = (
        '<div class="scroll"><table><thead><tr><th>Lookup</th><th>Endpoint (read-only GET)</th>'
        "<th>Receipt fields</th><th>Pointed at by</th></tr></thead>"
        f"<tbody>{''.join(cap_rows)}</tbody></table></div>"
        if cap_rows else
        '<p class="meaning">No live-value lookups are declared. Any price or '
        "stock figure an assistant states about this store is therefore a "
        "copy of static text, which is exactly what this format exists to "
        "avoid.</p>"
    )

    # --- derived tier ------------------------------------------------------
    jsonld_rows = "".join(
        f"<tr><td>{e(c.title)}</td><td><code>{e(t)}</code></td>"
        f"<td><code>jsonld/{e(c.rel_path[:-3] if c.rel_path.endswith('.md') else c.rel_path)}.json</code></td></tr>"
        for c, t in jsonld_types
    )
    excluded = [
        c for c in published.values()
        if c.trust_tier not in (TRUST_HUMAN, TRUST_HUMAN_BATCH)
        and jsonld_for(c, base_path, site or None) is not None
    ]
    derived_note = (
        f" {_plural(len(excluded), 'file')} with a schema.org mapping "
        f"({e(', '.join(c.title for c in excluded[:3]))}) emit nothing because "
        "no named person has vouched for them yet: the markup restates only "
        "human-verified facts." if excluded else ""
    )

    # --- questions → knowledge -----------------------------------------------
    gaps = _gaps(scorecard) if scorecard else []
    gap_items = []
    for gap in gaps:
        qid = gap.split("(", 1)[0].strip()
        anchor = f' id="gap-{e(qid)}"' if qid and " " not in qid else ""
        gap_items.append(f"<li{anchor}>{e(gap)}</li>")
    if blocks:
        # Rebuild the blocks with the gap ids so judged rows link to
        # their gap bullets, exactly as the report does.
        gap_ids = {
            g.split("(", 1)[0].strip() for g in gaps if " " not in g.split("(", 1)[0].strip()
        }
        blocks = _question_blocks(bundle, by_archetype if full_run else None,
                                  verdicts or None, gap_ids)
        questions_html = (
            '<p class="meaning">Every row is recomputed from the committed '
            "question pack each time this page renders: the question, the "
            "knowledge file the retrieval pass finds, and the reading cost. "
            "This pass runs no AI model. Where a full evaluation was "
            "recorded, each topic also shows how many answers the judge "
            "accepted, and a row the judge scored as not answered says so "
            "and links to the recorded gap.</p>" + "".join(blocks)
        )
        if gap_items:
            questions_html += (
                '<h3 id="gaps">Recorded knowledge gaps</h3><ul class="card">'
                + "".join(gap_items) + "</ul>"
            )
    else:
        questions_html = (
            '<p class="meaning">No question pack is committed at '
            "<code>evaluations/questions.yaml</code>, so no retrieval rows "
            "can be shown. <code>okf-web questions &lt;bundle&gt; --pack "
            "&lt;industry&gt;</code> adds a starter set without an AI "
            "account; the full evaluation then measures answers.</p>"
        )

    # --- trust and freshness ------------------------------------------------
    high_risk = [c for c in published.values() if c.is_high_risk]
    high_reviewed = sum(1 for c in high_risk if c.trust_tier == TRUST_HUMAN)
    drafts = [c for c in concepts.values() if c.status != "stable"]
    posture = (
        f"Of {_plural(len(concepts), 'concept')} in the working copy, "
        f"{mix.get(TRUST_HUMAN, 0)} were read and approved one by one by a "
        f"named person, {mix.get(TRUST_HUMAN_BATCH, 0)} were published under "
        f"a named person's bulk sign-off, {mix.get(TRUST_MACHINE, 0)} were "
        f"checked by a machine only, and {mix.get(TRUST_UNVERIFIED, 0)} are "
        f"unverified. {_plural(len(high_risk), 'high-risk file')} "
        "(prices, policies, safety, compliance, commercial terms) would "
        f"publish, {high_reviewed} of them with an individual human review; "
        f"{_plural(len(drafts), 'draft')} wait in the review queue. "
        f"{_plural(len(stale), 'published file')} past its freshness date "
        f"and {len(soon)} due within {SOON_DAYS} days. Engines read all of "
        "this: the tiers, the dates and the risk class travel with every file."
    )

    generated = (
        f"okf-web viewer/{__version__} · rendered {today.isoformat()} from "
        f"{e(bundle.root.name)}"
    )
    title = f"{store} bundle viewer"
    body = f"""
<main>
  <p class="eyebrow">OKF bundle viewer · {e(store)}</p>
  <h1>What this bundle holds, and how AI systems use it</h1>
  <p class="lede">The knowledge bundle of {e(store)} as an AI engine sees it: the
  files it can read, who vouched for them, the questions they answer, the
  live lookups that replace stale numbers, and, when an access log is
  given, who has actually been reading.{(' Published at <code>' + e(well_known) + '</code>.') if site else ''}</p>
  <div class="tiles">{''.join(tiles)}</div>

  <h2 id="pipeline">How an AI system uses this bundle</h2>
  {pipeline}

  <h2 id="revenue">Where the revenue is</h2>
  <p class="meaning">Each row is one kind of shopper question. The middle
  columns are measured from this bundle: the files that declare they answer
  it, and, where a full evaluation was recorded, how many of the pack's
  questions the judge accepted. The last column names what is at stake
  when an assistant can, or cannot, answer.</p>
  <div class="scroll"><table class="rev"><thead><tr><th>Shopper moment</th><th>What the bundle holds</th>
  <th>Measured</th><th>Why it matters to revenue</th></tr></thead>
  <tbody>{''.join(revenue_rows)}</tbody></table></div>

  <h2 id="inside">What is inside</h2>
  <p class="meaning">Every concept in the working copy, grouped by type in
  the profile's order. Trust is the tier an engine sees; risk is the gate
  class the tooling enforces; "answers" lists the question kinds the file
  declares it serves; tokens estimate its reading cost.</p>
  {''.join(inventory)}
  {held_html}

  <h2 id="live">Live values instead of stale numbers</h2>
  <p class="meaning">No price, stock level, order or claim status is written
  in any file. Each is a declared lookup an assistant executes against the
  store's own systems, receiving a receipt it can quote and a verifier can
  check. Only read-only lookups are ever declared; nothing here places an
  order or files a claim.</p>
  {capabilities_html}

  <h2 id="derived">What search engines read today</h2>
  <p class="meaning">A publish also writes schema.org markup for the surfaces
  engines already parse. It restates only files a named person vouched for,
  carries no price or availability, and points back at its source file.
  {len(jsonld_types)} objects would be emitted from this bundle.{derived_note}</p>
  <div class="scroll"><table><thead><tr><th>Source concept</th><th>schema.org type</th><th>File</th></tr></thead>
  <tbody>{jsonld_rows or '<tr><td colspan="3">No human-verified concept has a schema.org mapping yet.</td></tr>'}</tbody></table></div>

  <h2 id="questions">Shopper questions and the knowledge that answers them</h2>
  {questions_html}

  <h2 id="reads">Read activity</h2>
  {_read_activity(access_logs, log_sources, base_path)}

  <h2 id="trust">Trust and freshness posture</h2>
  <p class="meaning">{posture}</p>

  <footer>{e(generated)}. Every figure on this page is read from the bundle,
  its recorded scorecard, or the access log named above; nothing is
  estimated by an AI model. The page carries no scripts. Regenerate with
  <code>okf-web view &lt;bundle&gt; [--access-log access.log]</code>.</footer>
</main>
"""
    return _document(title, body)


_STYLE = """
  :root { --paper: #f4f6f8; --card: #ffffff; --ink: #1c2733; --muted: #5b6b7a;
          --line: #dde3e8; --accent: #245e8c; --tint: #eef3f7; --code: #e9eef2;
          --ok: #1f7a4d; --warn: #9a6b00; --gap: #b3261e; --batch: #1b6f6f; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper: #11171c; --card: #1a2229; --ink: #e4ebf0; --muted: #93a4b1;
      --line: #2b353e; --accent: #6fa8d6; --tint: #18232c; --code: #232d36;
      --ok: #4fbf85; --warn: #d9a441; --gap: #f08c85; --batch: #4fb3b3; }
  }
  :root[data-theme="dark"] {
    --paper: #11171c; --card: #1a2229; --ink: #e4ebf0; --muted: #93a4b1;
    --line: #2b353e; --accent: #6fa8d6; --tint: #18232c; --code: #232d36;
    --ok: #4fbf85; --warn: #d9a441; --gap: #f08c85; --batch: #4fb3b3; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--paper); color: var(--ink);
         font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  main { max-width: 960px; margin: 0 auto; padding: 2.4rem 1.25rem 4rem; }
  h1 { font-size: clamp(1.5rem, 3.4vw, 2rem); line-height: 1.2; margin: 0 0 .6rem;
       text-wrap: balance; }
  h2 { font-size: 1.2rem; margin: 2.6rem 0 .7rem; padding-top: 1.2rem;
       border-top: 1px solid var(--line); }
  h3 { font-size: 1rem; margin: 1.5rem 0 .5rem; }
  h3 .count { color: var(--muted); font-weight: 400; font-size: .88rem; }
  p { max-width: 70ch; }
  .eyebrow { font-size: .74rem; text-transform: uppercase; letter-spacing: .1em;
             font-weight: 600; color: var(--accent); margin: 0 0 .5rem; }
  .lede { color: var(--muted); font-size: 1.05rem; margin: 0 0 1.4rem; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .86em;
         background: var(--code); padding: .08em .35em; border-radius: 4px; }
  a { color: var(--accent); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
           gap: .8rem; margin: .4rem 0 0; }
  .tile { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
          padding: .95rem 1.05rem; }
  .tile .value { font-size: 1.65rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  .tile .label { margin-top: .1rem; }
  .tile .detail { color: var(--muted); font-size: .84rem; margin-top: .3rem; }
  p.meaning { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
              padding: .9rem 1.05rem; max-width: none; }
  .pipeline { display: grid; grid-template-columns: repeat(3, 1fr); gap: .8rem; }
  .stage { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
           padding: .9rem 1.05rem; min-width: 0; }
  .stage code { overflow-wrap: anywhere; }
  .stage .kicker { font-size: .72rem; text-transform: uppercase; letter-spacing: .1em;
                   font-weight: 600; color: var(--accent); }
  .stage h3 { margin: .3rem 0 .5rem; }
  .stage ul { margin: 0; padding-left: 1.1rem; font-size: .93rem; background: none;
              border: 0; border-radius: 0; }
  .stage li { margin: .35rem 0; }
  @media (max-width: 760px) { .pipeline { grid-template-columns: 1fr; } }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: var(--card);
          border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
          font-size: .93rem; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: .8rem;
       text-transform: uppercase; letter-spacing: .06em; padding: .55rem .8rem;
       border-bottom: 1px solid var(--line); }
  td { padding: .6rem .8rem; border-top: 1px solid var(--line); vertical-align: top; }
  tr:first-child td { border-top: none; }
  td.num, th.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .sub { color: var(--muted); font-size: .82rem; margin-top: .15rem; overflow-wrap: anywhere; }
  .sub a { color: var(--muted); }
  .chip { display: inline-block; font-size: .74rem; font-weight: 600; padding: .1em .5em;
          border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
  .t-human { color: var(--ok); } .t-batch { color: var(--batch); }
  .t-machine { color: var(--warn); } .t-none { color: var(--muted); }
  .held { color: var(--gap); font-size: .8rem; font-weight: 600; margin-top: .25rem; }
  .soon { color: var(--warn); font-size: .8rem; font-weight: 600; margin-top: .25rem; }
  .ok { color: var(--ok); font-weight: 600; } .warn { color: var(--warn); font-weight: 600; }
  .gap { color: var(--gap); font-weight: 600; } .miss { color: var(--gap); }
  table.rev td:last-child { color: var(--muted); }
  details.arch { background: var(--card); border: 1px solid var(--line);
                 border-radius: 10px; margin: .6rem 0; }
  details.arch summary { cursor: pointer; padding: .65rem 1rem; font-weight: 600; }
  details.arch summary .count { color: var(--muted); font-weight: 400; font-size: .88rem; }
  details.arch .qtable { border: none; border-top: 1px solid var(--line); border-radius: 0; }
  .qtable th { text-transform: none; letter-spacing: 0; }
  .qtable .para { color: var(--muted); font-size: .82rem; margin-top: .15rem; }
  .qtable .more { color: var(--muted); font-size: .82rem; white-space: nowrap; }
  .qtable .miss { color: var(--gap); }
  .qtable .judged { color: var(--gap); font-size: .82rem; font-weight: 600; margin-top: .15rem; }
  .qtable .judged a { color: inherit; }
  ul.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
            margin: 0; padding: .8rem 1.1rem .8rem 2.1rem; }
  li { margin: .3rem 0; }
  li:target { background: var(--tint); }
  .days { display: flex; align-items: flex-end; gap: 3px; height: 120px;
          padding: .6rem .6rem 1.6rem; background: var(--card); border: 1px solid var(--line);
          border-radius: 10px; overflow-x: auto; }
  .day { flex: 1 0 14px; height: 100%; display: flex; flex-direction: column;
         justify-content: flex-end; align-items: center; position: relative; }
  .day .bar { width: 100%; max-width: 22px; background: var(--accent); border-radius: 3px 3px 0 0; }
  .day span { position: absolute; bottom: -1.3rem; font-size: .62rem; color: var(--muted);
              white-space: nowrap; }
  .note { color: var(--muted); font-size: .84rem; }
  footer { color: var(--muted); font-size: .85rem; margin-top: 2.6rem; padding-top: 1rem;
           border-top: 1px solid var(--line); }
"""


def _document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{_e(title)}</title>\n<style>{_STYLE}</style>\n</head>\n<body>"
        f"{body}</body>\n</html>\n"
    )


def write_viewer(
    bundle_root: Path | str,
    out: Path | str | None = None,
    today: _dt.date | None = None,
    access_logs: LogScanReport | None = None,
    log_sources: list[str] | None = None,
    base_path: str = WELL_KNOWN_PATH,
) -> Path:
    """Render the viewer for the bundle at ``bundle_root``. The default
    output is ``bundle-viewer.html`` in the working directory — outside
    the bundle on purpose, since the page shows drafts and read logs
    meant for the operator, and the publisher ships every non-hidden
    asset it finds inside a bundle."""
    bundle_root = Path(bundle_root)
    bundle = load_bundle(bundle_root)
    target = Path(out) if out else Path("bundle-viewer.html")
    if target.resolve().is_relative_to(bundle_root.resolve()):
        raise ViewerError(
            f"refusing to write the viewer inside the bundle ({target}): the "
            f"page shows drafts and read logs and would be published with "
            f"the bundle; choose a path outside {bundle_root}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(
        target,
        build_viewer(bundle, today=today, access_logs=access_logs,
                     log_sources=log_sources, base_path=base_path),
    )
    return target
