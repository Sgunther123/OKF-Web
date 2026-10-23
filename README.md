# OKF-Web

**A companion knowledge layer for ecommerce GEO** — survey a
storefront into an [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format)
bundle with an LLM, verify it with a human in the loop, measure its
answerability for generative engines, and publish it alongside the
site at `/.well-known/okf/`.

Shoppers now ask AI assistants the questions they used to type into
search. OKF-Web gives a store a machine-native tier those engines can
actually use: compact, citable, provenance-tracked markdown facts —
plus **attested computations** that teach agents to fetch live prices
and stock from the store's own APIs instead of quoting stale numbers.

```mermaid
flowchart LR
    P[Storefront pages] -->|fetch + hash| S[Surveyor LLM]
    S -->|draft concepts,<br/>every claim cited| H{Human review<br/>risk-tiered}
    H -->|"verified: human:&lt;id&gt;"| B[(Companion bundle)]
    B -->|publish| W["/.well-known/okf/"]
    W --> G[Generative engines<br/>and shopping agents]
    B --> E[Evaluator LLM]
    E -->|GEO scorecard + gaps| B
    E -.->|gap backlog| S
```

The loop in one sentence: **an LLM populates, a linter gates, a human
verifies, a static host serves, and an evaluator measures — then the
gaps feed the next pass.**

## Why OKF

OKF bundles are plain markdown + YAML frontmatter with provenance
built in: `generated` (who wrote it), `verified` (who checked it —
trust tiers key off the `human:` actor prefix), `sources` with
per-claim footnotes, `stale_after` freshness, and `Attested
Computation` for facts that must be executed, not stored. No SDK, no
lock-in; any engine that reads files can consume it.

## Where adoption stands (honestly)

OKF is a real, Google-published spec — framed for enterprise agent
knowledge. The web convention here — `/.well-known/okf/`, the site
binding, the `ecommerce-geo` profile — is **this project's**, and no
generative engine fetches OKF bundles yet. So the toolchain is built
to pay for itself *without* that bet: every `publish` also emits
**schema.org JSON-LD** and a complete **`llms.txt`** — formats engines
read today — derived only from human-verified concepts, with prices
and stock deliberately absent (live values stay executable, never
static). `okf-web report` renders the measured answerability lift as
a shareable page, and `okf-web mcp` serves the bundle to assistants
now. If engines adopt bundle-style knowledge, yours is already
published; if they don't, the verified tier still feeds your markup,
your `llms.txt`, and your own bots.

## Repository map

| Path | What it is |
| --- | --- |
| [`docs/USER-GUIDE.md`](docs/USER-GUIDE.md) | Plain-English guide for store owners — walkthrough and FAQs, no programming background needed |
| [`docs/DESIGN.md`](docs/DESIGN.md) | The system design — architecture, novelty, threat model, efficiency budget |
| [`docs/GEO-PROFILE.md`](docs/GEO-PROFILE.md) | The `ecommerce-geo/1.12` profile: concept types, `x_geo` namespace, risk tiers, `http` runtime |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | The answerability rubric: archetypes, metrics, gating |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased tooling roadmap, ranked by adoption leverage |
| [`docs/EXPANSION.md`](docs/EXPANSION.md) | Value expansion plan: fit, ownership, passports, omnichannel, B2B |
| [`docs/MEASUREMENT.md`](docs/MEASUREMENT.md) | Seeing engines consume the bundle (logscan + log recipes) |
| [`docs/HOSTING.md`](docs/HOSTING.md) | Hosting matrix: a tested recipe per hosting type (own server, static hosts, hosted platforms, containers, CI) and the bot-gate note |
| [`docs/FIDELITY.md`](docs/FIDELITY.md) | Audit against the published OKF v0.2 spec + the shipped hardening phases |
| [`docs/READINESS.md`](docs/READINESS.md) | Adversarial readiness review: suitability and adoption findings, remediation phases R1–R4 |
| [`docs/EDGE-CASES.md`](docs/EDGE-CASES.md) | Edge-case review: UI, automation and security findings with the E1–E5 remediation plan |
| [`docs/API.md`](docs/API.md) | The library surface that stays put: one error family and exit table, one home per primitive, the names the hosted edition imports |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch policy: protected `main`, the fast-forward flow, and the exact rule to apply on GitHub |
| [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) | Distribution plan: audiences, PyPI strategy, the MCP assistant channel, release gates |
| [`bundle-example/`](bundle-example/index.md) | Complete conformant companion bundle for a fictional store |
| [`src/okf_web/`](src/okf_web/) | Reference implementation (`okf-web` CLI) |
| [`src/okf_web/prompts/`](src/okf_web/prompts/) | The versioned LLM prompts: extraction contract, question generation, answerer, judge |
| [`tests/`](tests/) | Test suite; the example bundle is linted in CI |

## Quickstart

```bash
pip install -e .[dev]        # add [llm] for LLM-backed commands (Anthropic)

# The whole first run in one command, no LLM: feed → lint → attest →
# starter questions → dry-run scorecard → publish (+ jsonld/, llms.txt) → report
okf-web init my-store --feed products.csv --site https://www.example-store.com \
    --by you@store.com --pack outdoor

# Inspect the example bundle
okf-web lint bundle-example --strict
okf-web review list bundle-example
okf-web evaluate bundle-example --dry-run

# The human-in-the-loop moment: approve the draft warranty policy
okf-web review approve bundle-example policies/warranty.md --by legal@alpinepeakoutfitters.example

# Build the static companion (refuses to ship unapproved high-risk drafts)
okf-web publish bundle-example dist/

# Against a real store (see "LLM access" below for credential options)
okf-web survey my-bundle --feed products.csv     # catalog from a feed export — no LLM
okf-web survey my-bundle --sitemap https://www.example-store.com --limit 25
okf-web questions my-bundle --pack outdoor   # or apparel/electronics/grocery/machinery (+ .es variants); no LLM
okf-web evaluate my-bundle --write-scorecard
okf-web report my-bundle                     # scorecard → shareable HTML report; no LLM
okf-web view my-bundle --access-log access.log   # bundle viewer: what's inside, how engines use it, who read it; no LLM

# Keep it honest over time (all LLM-free — nightly-cheap)
okf-web drift my-bundle                          # did source pages change?
okf-web publish my-bundle dist/ --freshness withhold   # retire stale concepts
okf-web review list my-bundle --fail-nonempty    # CI alarm for a rotting queue
okf-web review batch-approve my-bundle --by you@store.com  # named bulk sign-off (human-attested tier)

# See who's consuming, and verify discovery like an engine would
okf-web logscan access.log                       # AI-agent fetches (docs/MEASUREMENT.md)
okf-web discover https://www.example-store.com   # find bundle + verify the binding

# Serve the bundle to Claude Desktop/Code and other MCP clients today
okf-web mcp my-bundle
```

`okf-web review list` on the example bundle shows one item: the
warranty policy — a high-risk draft the linter and publisher both
refuse to ship until a human approves it. That invariant (lint rule
E010) is the heart of the design: **no price, policy, or safety claim
reaches an AI engine without a named human verifier**, while low-risk
descriptive facts flow at machine speed.

## LLM access

The LLM-backed commands (`survey`, `questions`, `evaluate` without
`--dry-run`) support three credential paths — pick with `--llm`:

- **API key** (`--llm api`, default): `pip install okf-web[llm]` and
  `export ANTHROPIC_API_KEY=...`. Metered API billing. **Required for
  anything scheduled or unattended** — cron surveys, CI evaluations,
  hosted services.
- **Keyless OAuth** (also `--llm api`): run `ant auth login` once; the
  SDK picks up the OAuth profile automatically — same metered API
  billing, no key to create or manage.
- **Your Claude subscription** (`--llm claude-code`): routes calls
  through a locally installed, logged-in
  [Claude Code](https://code.claude.com) in print mode, drawing on the
  Claude Pro/Max subscription you already pay for. No API account and
  no extra Python dependency. **Interactive, human-initiated runs
  only**: consumer subscriptions are personal and rate-limited in
  rolling windows — a survey paused by a limit resumes incrementally
  (unchanged pages cost nothing) — and automation belongs on API
  credentials.

Prefer not to run the pipeline yourself? A fully hosted, commercial
edition is developed as
[www.okf-web.com](https://www.okf-web.com).

## Hosting the companion

`okf-web publish` emits a static tree — bundle + `manifest.json`
(sha256 delta sync) + `linkmap.json` (page ⇄ concept `<link>` tags) +
`llms-snippet.txt` (discovery via `llms.txt`) — plus the **derived
tier**: `jsonld/` (schema.org markup from human-verified concepts,
one file per concept, `subjectOf` linking back to its source) and a
complete `llms.txt`. Serve it from the same CDN as the site at
`/.well-known/okf/`; the serving rules are in
[docs/DESIGN.md §8](docs/DESIGN.md#8-hosting-and-discovery), and a
tested recipe per hosting type (nginx, Apache, Caddy, Cloudflare Pages,
Netlify, Vercel, GitHub Pages, S3, containers, CI) is in
[docs/HOSTING.md](docs/HOSTING.md).

**On a hosted platform that can't serve root paths** (Shopify and
friends): publish with `--bundle-url https://<any-host>/<path>`, host
the dist there, and paste the emitted
`<link rel="okf-bundle" href="…">` tag into your storefront's
`<head>` via the theme editor. The pointer on your domain plus the
`site` recorded in `manifest.json` form a verifiable two-way binding
([GEO-PROFILE §8](docs/GEO-PROFILE.md#8-discovery-and-delegation)).

**Consumption doesn't have to wait for crawlers**: `okf-web mcp
my-bundle` serves the published view to any MCP client — Claude
Desktop config:

```json
{"mcpServers": {"my-store": {"command": "okf-web", "args": ["mcp", "/path/to/my-bundle"]}}}
```

giving the assistant `okf_search`, `okf_get`, `okf_capabilities`,
and `okf_execute` (live price/stock via the store's declared
read-only endpoints). `okf-web mcp --url
https://store.example/.well-known/okf` does the same for any
*published* bundle, mirrored locally and verified against its
manifest — no clone, no server.

Bundles can be **signed**: `okf-web publish dist/ --sign` (or
`okf-web sign dist/`, after `pip install okf-web[sign]`) puts a
sigstore keyless signature over `manifest.json` — which lists every
file's sha256, so one signature authenticates the whole bundle, with
no keys for the merchant to manage. Consumers run
`okf-web verify dist/ --cert-identity <id> --cert-oidc-issuer <url>`
for the full chain: signature → manifest → file hashes (the hash
sweep runs stdlib-only, even without sigstore installed).

Third parties can **countersign** the same manifest with their own
identity — `okf-web sign dist/ --as auditor-acme` — and consumers
check that attestation with `okf-web verify dist/ --countersignature
auditor-acme --cert-identity <attester> ...`. The merchant signature
says who published; each countersignature says who vouched.

## Status

Reference implementation accompanying the design. The fictional store
in `bundle-example/` uses reserved `.example` domains throughout.

## License

[Apache-2.0](LICENSE).
