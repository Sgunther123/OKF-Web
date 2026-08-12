"""Static HTML rendering: the provenance viewer and the review packet.

Two artifacts, one set of rules:

* **Self-contained.** One file each, inline CSS, a few lines of vanilla
  JS in the viewer for hash routing. No external assets, no backend —
  they open from a double-click or any static host (the same
  zero-backend stance as upstream OKF's visualizer).
* **Escaped before rendered.** Concept bodies originate from LLM
  extraction over untrusted web pages, so every character is
  HTML-escaped before our own markup is applied — page content can
  never inject script into a reviewer's or shopper's browser.
* **Provenance, not content.** The viewer exists for the human who
  clicks an AI's citation: it shows who verified what, when, and from
  which sources, and always points at the live store page as the
  canonical destination. It is marked ``noindex`` and framed as a fact
  sheet, so it never becomes a shadow storefront. The review packet is
  the same idea turned inward: a read-only briefing of everything
  awaiting human approval — approvals still happen through the CLI.
"""

from __future__ import annotations

import datetime as _dt
import html
import re
from typing import Callable

from .model import Bundle, Concept, RISK_HIGH, TRUST_HUMAN, TRUST_MACHINE

# ---------------------------------------------------------------------------
# Escaping + a conservative markdown subset
# ---------------------------------------------------------------------------

def esc(value) -> str:
    return html.escape(str(value), quote=True)


_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_FOOT_REF = re.compile(r"\[\^([A-Za-z0-9_-]+)\](?!:)")
_FOOT_DEF = re.compile(r"^\[\^([A-Za-z0-9_-]+)\]:\s*(.*)$")
_TABLE_SEP = re.compile(r"^:?-{3,}:?$")

LinkResolver = Callable[[str], "str | None"]


def _inline(text: str, links: LinkResolver | None = None) -> str:
    out = esc(text)
    out = _CODE_SPAN.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)

    def _link(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        href = links(target) if links else target
        if not href:
            return label
        extra = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
        return f'<a href="{esc(href)}"{extra}>{label}</a>'

    out = _LINK.sub(_link, out)
    out = _FOOT_REF.sub(lambda m: f'<sup class="fn">{m.group(1)}</sup>', out)
    return out


def _table(rows: list[str], links: LinkResolver | None) -> str:
    parsed = []
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if all(_TABLE_SEP.match(c) for c in cells if c):
            continue
        parsed.append(cells)
    if not parsed:
        return ""
    out = ["<table>"]
    for r, cells in enumerate(parsed):
        tag = "th" if r == 0 else "td"
        out.append(
            "<tr>" + "".join(f"<{tag}>{_inline(c, links)}</{tag}>" for c in cells) + "</tr>"
        )
    out.append("</table>")
    return "".join(out)


def render_markdown(body: str, links: LinkResolver | None = None) -> str:
    """Render the markdown subset used in bundles; everything escaped."""
    lines = body.splitlines()
    out: list[str] = []
    footnotes: list[tuple[str, str]] = []
    para: list[str] = []
    code: list[str] = []
    in_code = False
    in_list = False
    i, n = 0, len(lines)

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append(f"<p>{_inline(' '.join(para), links)}</p>")
            para = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < n:
        line = lines[i]
        if in_code:
            if line.strip().startswith("```"):
                out.append(f"<pre><code>{esc(chr(10).join(code))}</code></pre>")
                code, in_code = [], False
            else:
                code.append(line)
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para(); close_list()
            in_code = True
            i += 1
            continue
        note = _FOOT_DEF.match(stripped)
        if note:
            footnotes.append((note.group(1), note.group(2)))
            i += 1
            continue
        if not stripped:
            flush_para(); close_list()
            i += 1
            continue
        if stripped.startswith("#"):
            flush_para(); close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")) + 1, 5)
            out.append(f"<h{level}>{_inline(stripped.lstrip('#').strip(), links)}</h{level}>")
            i += 1
            continue
        if stripped.startswith(("* ", "- ")):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:], links)}</li>")
            i += 1
            continue
        if in_list and line.startswith("  ") and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][: -len("</li>")] + " " + _inline(stripped, links) + "</li>"
            i += 1
            continue
        if stripped.startswith("|"):
            flush_para(); close_list()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows, links))
            continue
        para.append(stripped)
        i += 1

    if in_code and code:
        out.append(f"<pre><code>{esc(chr(10).join(code))}</code></pre>")
    flush_para(); close_list()
    if footnotes:
        items = "".join(
            f"<li><sup>{esc(fid)}</sup> {_inline(text, links)}</li>"
            for fid, text in footnotes
        )
        out.append(f'<div class="footnotes"><h4>Footnotes</h4><ul>{items}</ul></div>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Shared fragments
# ---------------------------------------------------------------------------

_CSS = """
:root{--ink:#1c2530;--soft:#5c6b7a;--line:#dbe2e8;--bg:#f7f9fa;--card:#ffffff;
--green:#116932;--green-bg:#e5f4e9;--amber:#8a5a00;--amber-bg:#fcf1d8;
--gray:#5c6b7a;--gray-bg:#eceff2;--red:#9c1f1f;--red-bg:#fbe9e9;--link:#0b5fa5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:2rem 1.25rem 4rem}
a{color:var(--link)}h1{font-size:1.6rem;margin:.2rem 0 .6rem}h2{font-size:1.25rem;margin:1.6rem 0 .5rem}
h3,h4{margin:1.2rem 0 .4rem}p{margin:.5rem 0}ul{margin:.4rem 0 .8rem;padding-left:1.4rem}
table{border-collapse:collapse;margin:.8rem 0;width:100%;font-size:.92rem}
th,td{border:1px solid var(--line);padding:.35rem .55rem;text-align:left}
pre{background:#f0f3f5;border:1px solid var(--line);border-radius:6px;padding:.7rem;overflow-x:auto;font-size:.88rem}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1.2rem 1.4rem;margin:1rem 0}
.badge{display:inline-block;padding:.1rem .55rem;border-radius:999px;font-size:.78rem;font-weight:600}
.badge-human{color:var(--green);background:var(--green-bg)}
.badge-machine{color:var(--amber);background:var(--amber-bg)}
.badge-unverified{color:var(--gray);background:var(--gray-bg)}
.chip{display:inline-block;padding:.05rem .5rem;border-radius:6px;font-size:.75rem;background:var(--gray-bg);color:var(--soft);margin-left:.4rem}
.chip.risk-a{background:var(--red-bg);color:var(--red);font-weight:600}
.meta{color:var(--soft);font-size:.85rem}.meta div{margin:.15rem 0}
.live{margin:.9rem 0;padding:.6rem .8rem;background:var(--green-bg);border-radius:8px}
.sources,.footnotes{margin-top:1rem;border-top:1px solid var(--line);padding-top:.6rem}
.sources h4,.footnotes h4{margin:.2rem 0 .3rem;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;color:var(--soft)}
sup.fn{color:var(--soft)}
.disclaimer{color:var(--soft);font-size:.82rem;border-top:1px solid var(--line);margin-top:2rem;padding-top:.8rem}
.reasons{color:var(--red);font-size:.9rem}
nav a{display:block;padding:.15rem 0}
"""


def _slug(rel_path: str) -> str:
    return "c-" + re.sub(r"[^a-z0-9]+", "-", rel_path.lower()).strip("-")


def trust_badge(concept: Concept) -> str:
    tier = concept.trust_tier
    cls = {TRUST_HUMAN: "human", TRUST_MACHINE: "machine"}.get(tier, "unverified")
    return f'<span class="badge badge-{cls}">{esc(tier)}</span>'


def _risk_chip(concept: Concept) -> str:
    risk = concept.risk
    cls = " risk-a" if risk == RISK_HIGH else ""
    return f'<span class="chip{cls}">risk {esc(risk)}</span>'


def _meta_block(concept: Concept) -> str:
    rows = []
    gen = concept.frontmatter.get("generated")
    if isinstance(gen, dict):
        rows.append(f"Drafted by <code>{esc(gen.get('by'))}</code> on {esc(gen.get('at'))}")
    for entry in concept.verified_entries:
        rows.append(f"Verified by <code>{esc(entry.get('by'))}</code> on {esc(entry.get('at'))}")
    stale = concept.frontmatter.get("stale_after")
    if stale:
        rows.append(f"Freshness date: {esc(stale)}")
    return '<div class="meta">' + "".join(f"<div>{r}</div>" for r in rows) + "</div>"


def _sources_block(concept: Concept) -> str:
    if not concept.sources:
        return ""
    items = []
    for source in concept.sources:
        sup = f"<sup>{esc(source['id'])}</sup> " if source.get("id") else ""
        label = esc(source.get("title") or source.get("id") or source.get("resource") or "source")
        resource = str(source.get("resource") or "")
        if resource.startswith("http"):
            body = f'<a href="{esc(resource)}" target="_blank" rel="noopener">{label}</a>'
        else:
            body = label
        tail = (
            f' <span class="meta">last updated {esc(source["last_modified"])}</span>'
            if source.get("last_modified")
            else ""
        )
        items.append(f"<li>{sup}{body}{tail}</li>")
    return f'<div class="sources"><h4>Sources</h4><ul>{"".join(items)}</ul></div>'


def _page(title: str, body: str, script: str = "") -> str:
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n<main>\n"
        f"{body}\n</main>\n{script}</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# The provenance viewer (emitted by the publisher)
# ---------------------------------------------------------------------------

_VIEWER_JS = """<script>
(function(){function route(){var h=location.hash.replace('#','');
var all=document.querySelectorAll('main > section');
for(var i=0;i<all.length;i++){all[i].style.display='none'}
var el=h?document.getElementById(h):null;
(el||document.getElementById('home')).style.display='block';window.scrollTo(0,0)}
window.addEventListener('hashchange',route);route()})();
</script>"""


def build_viewer_html(bundle: Bundle, published: set[str]) -> str:
    root_index = bundle.indexes.get("index.md")
    store_title = str(
        (root_index.frontmatter.get("title") if root_index else None) or "Knowledge Bundle"
    )
    concepts = [bundle.concepts[rel] for rel in sorted(published) if rel in bundle.concepts]

    def links_for(concept: Concept) -> LinkResolver:
        def resolve(target: str) -> str | None:
            if target.startswith(("http://", "https://", "mailto:")):
                return target
            resolved = bundle.resolve_link(concept.rel_path, target)
            if resolved in bundle.concepts and resolved in published:
                return f"#{_slug(resolved)}"
            return None
        return resolve

    by_type: dict[str, list[Concept]] = {}
    for concept in concepts:
        by_type.setdefault(concept.type or "Other", []).append(concept)

    nav = []
    for type_name in sorted(by_type):
        nav.append(f"<h2>{esc(type_name)}</h2><nav>")
        for concept in by_type[type_name]:
            nav.append(
                f'<a href="#{_slug(concept.rel_path)}">{esc(concept.title)}</a>'
            )
        nav.append("</nav>")
    home = (
        '<section id="home"><h1>' + esc(store_title) + "</h1>"
        "<p>These are the fact sheets AI assistants use when they answer "
        "questions about this store. Each one records where its facts came "
        "from and who checked them. This page is a provenance view, not a "
        "store page — for shopping, always use the links to the live site.</p>"
        + "".join(nav)
        + "</section>"
    )

    sections = [home]
    for concept in concepts:
        live = (
            f'<p class="live"><a href="{esc(concept.resource)}">'
            "View the live page on the store site →</a></p>"
            if concept.resource
            else ""
        )
        sections.append(
            f'<section class="concept" id="{_slug(concept.rel_path)}">'
            f'<p><a href="#home">← All fact sheets</a></p>'
            f"<h1>{esc(concept.title)}"
            f'<span class="chip">{esc(concept.type or "")}</span>{_risk_chip(concept)}</h1>'
            f"<p>{trust_badge(concept)}</p>"
            f"{_meta_block(concept)}{live}"
            f'<div class="card">{render_markdown(concept.body, links_for(concept))}</div>'
            f"{_sources_block(concept)}"
            '<p class="disclaimer">This provenance view is generated from the '
            "store's published knowledge bundle (Open Knowledge Format). It "
            "shows the facts as AI assistants read them; it is not a store "
            "page and is excluded from search indexing.</p>"
            "</section>"
        )
    return _page(f"{store_title} — Fact Sheets", "\n".join(sections), _VIEWER_JS)


# ---------------------------------------------------------------------------
# The review packet (read-only briefing for reviewers)
# ---------------------------------------------------------------------------

def build_review_packet_html(bundle: Bundle, items, proposals: list[Concept]) -> str:
    today = _dt.date.today().isoformat()
    parts = [
        f"<h1>Review packet <span class='chip'>{esc(today)}</span></h1>",
        "<p>Everything below is waiting on a person. This page is "
        "<strong>read-only</strong> — to act on an item, copy its command "
        "into your command line. Highest-risk items come first.</p>",
        f"<p class='meta'>{len(items)} item(s) pending · "
        f"{len(proposals)} drift proposal(s)</p>",
    ]

    if not items and not proposals:
        parts.append('<div class="card"><p>The review queue is empty. 🎉</p></div>')

    for item in items:
        concept = item.concept
        approve = (
            f"okf-web review approve {esc(bundle.root)} {esc(concept.rel_path)} "
            "--by you@yourstore.com"
        )
        reject = (
            f"okf-web review reject {esc(bundle.root)} {esc(concept.rel_path)} "
            '--by you@yourstore.com --reason "…"'
        )
        parts.append(
            '<div class="card">'
            f"<h2>{esc(concept.title)}"
            f'<span class="chip">{esc(concept.type or "")}</span>{_risk_chip(concept)}</h2>'
            f"<p>{trust_badge(concept)} "
            f'<span class="meta"><code>{esc(concept.rel_path)}</code></span></p>'
            f'<p class="reasons">Why it needs you: {esc("; ".join(item.reasons))}</p>'
            f"{_meta_block(concept)}"
            f"{render_markdown(concept.body)}"
            f"{_sources_block(concept)}"
            f"<h4>To approve (after checking each claim against its source)</h4>"
            f"<pre><code>{approve}</code></pre>"
            f"<h4>To send back</h4><pre><code>{reject}</code></pre>"
            "</div>"
        )

    if proposals:
        parts.append("<h2>Drift proposals</h2>")
        parts.append(
            "<p>The website changed <em>after</em> a person approved these "
            "fact sheets. The current approved version is untouched; below is "
            "the newly drafted replacement. Compare it with the approved file "
            "of the same name before accepting the change.</p>"
        )
        for concept in proposals:
            parts.append(
                '<div class="card">'
                f"<h3>{esc(concept.title)}"
                f'<span class="chip">proposed update</span>{_risk_chip(concept)}</h3>'
                f'<p class="meta">would replace <code>{esc(concept.rel_path)}</code></p>'
                f"{_meta_block(concept)}"
                f"{render_markdown(concept.body)}"
                f"{_sources_block(concept)}"
                "</div>"
            )

    parts.append(
        '<p class="disclaimer">Generated by okf-web from the working bundle. '
        "Approvals recorded here would be meaningless — only the CLI (or a "
        "git review) writes verification stamps.</p>"
    )
    return _page("Review packet", "\n".join(parts))
