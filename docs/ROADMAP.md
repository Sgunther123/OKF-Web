# Roadmap

The gaps below came out of an adoption/operational-friction review of
the whole pipeline: where does a merchant (or the agency running
bundles for many merchants) hit resistance, and which of those points
are addressable in the open-source tool. Items are phased by
leverage — how much adoption or trust each unit of work unlocks — not
by size.

## Phase 1 — shipped

The three highest-leverage fixes plus the consumption bridge:

- **Discovery delegation** ([GEO-PROFILE §8](GEO-PROFILE.md)):
  platform-hosted stores that cannot serve `/.well-known/*` can host
  the bundle anywhere and bind it to the storefront with a
  `<link rel="okf-bundle">` pointer + `manifest.site` handshake.
  Re-scopes the addressable market from "stores that control their
  web server" to "stores that can edit their theme" — most of them.
- **`okf-web drift`**: LLM-free nightly check that each surveyed
  concept's source page still matches the hash it was extracted
  from. Closes the docs-vs-code gap on the faithfulness sweep for
  the cost of a few HTTP GETs.
- **Freshness publish policy** (`--freshness withhold`): generalizes
  promotion auto-retirement to any concept past `stale_after`. An
  unmaintained bundle now degrades to "says less" instead of
  "keeps asserting facts its own frontmatter says not to trust".
- **MCP bridge** (`okf-web mcp`): the bundle as tools for Claude
  Desktop/Code and other MCP clients — retrieval, concept reads,
  capability execution over the published view. Consumption today,
  without waiting for crawler adoption.

## Phase 2 — packaging and operator ergonomics

Lowering the floor for the first bundle and thinning the standing
human cost:

- **PyPI release** — `pipx install okf-web` instead of a git clone.
  (Cheapest single friction fix available; blocked only on cutting a
  version.)
- **Review ergonomics** — filter the queue by risk tier, batch-approve
  machine-confirmed `b`/`c` concepts, surface queue counts in CI
  output so a rotting queue is visible before it rots.
- **Starter question packs** — per-vertical `questions.yaml` seeds
  (apparel, outdoor, electronics, grocery) so the first evaluation
  doesn't require question-writing skill.
- **Consumption measurement recipe** — a documented CDN-log query
  (reusing the `AI_USER_AGENTS` list the robots checker already
  maintains) so merchants can see engines fetching the bundle. The
  feedback loop that sustains maintenance.

## Phase 3 — reach

- **Multi-language bundles** — concept-per-locale layout and lint
  rules; international stores are currently first-language-only.
- **Delegation verifier** — `okf-web discover <store-url>`: the
  consumer-side counterpart to §8 (find the pointer, fetch the
  bundle, check the bidirectional binding and signature) so anyone
  can audit a store's delegation in one command.
- **Log-scan tool** — promote the Phase-2 recipe into
  `okf-web logscan` over common CDN log formats.

## Elsewhere

Capabilities that need a service rather than a CLI — a web review
queue, scorecard history and drift dashboards, catalog connectors
(Shopify/BigCommerce) — live in the
[hosted edition](https://www.okf-web.com). The
split rule stays what it has always been: anything a single merchant
needs to publish a truthful bundle is here, open source; anything
that only makes sense operated for many merchants at once is there.
