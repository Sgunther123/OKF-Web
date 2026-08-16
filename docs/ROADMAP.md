# Roadmap

The gaps below came out of an adoption/operational-friction review of
the whole pipeline: where does a merchant (or the agency running
bundles for many merchants) hit resistance, and which of those points
are addressable in the open-source tool. Items are phased by
leverage — how much adoption or trust each unit of work unlocks — not
by size.

This document phases the *tooling*; the companion
[EXPANSION.md](EXPANSION.md) phases the *use case* — the concept
classes that widen what a bundle is worth beyond pre-purchase
answerability.

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

## Phase 2 — packaging and operator ergonomics (shipped)

Lowering the floor for the first bundle and thinning the standing
human cost:

- **Release readiness** — version 0.2.0, complete package metadata,
  and a tag-triggered PyPI publish workflow using Trusted Publishing
  (`.github/workflows/release.yml`). Cutting the release is one
  `git tag v0.2.0` once the PyPI project is registered.
- **Review ergonomics** — `review list --risk a` filters the queue;
  every listing ends with a greppable
  `pending: N (a/b/c)` summary; `review list --fail-nonempty` turns
  a rotting queue into a red CI job; `review batch-approve` clears
  the `b`/`c` draft tail in one command (risk `a` is deliberately not
  batchable — E010 stays individual).
- **Starter question packs** — `okf-web questions my-store --pack
  outdoor|apparel|electronics|grocery`: 30 curated questions across
  every archetype, no LLM or credentials needed for the first
  evaluation.
- **Consumption measurement** — [MEASUREMENT.md](MEASUREMENT.md)
  (where the logs live, how to read them honestly) plus
  `okf-web logscan` over Combined-Log-Format and JSON-lines access
  logs, reusing the `AI_USER_AGENTS` roster; `--fail-empty` is the
  monthly "nobody is reading this" CI alarm.

## Phase 3 — reach (shipped)

- **Multi-language bundles** (profile 1.3) — translations live at
  `l10n/<lang>/<same-path>`, pinned to their source's content hash;
  lint W030/W031 catch orphaned and out-of-date translations;
  `evaluate --lang` / `mcp --lang` serve the localized view
  (translations overlay sources, untranslated concepts fall back to
  the default language).
- **Delegation verifier** — `okf-web discover <store-url>`: finds
  the bundle (well-known probe + `<link rel="okf-bundle">`), checks
  the bidirectional store↔bundle binding and signature presence,
  and reports what an engine would conclude. Exit code makes it
  CI-able.
- **Log-scan tool** — shipped with Phase 2 as `okf-web logscan`.

## Phase 4 — candidates (not started)

- **Connector-neutral catalog ingestion** — survey from a product
  feed file (Google Merchant/CSV) as a sitemap alternative; true
  platform connectors remain a hosted capability.
- **Attestation ecosystem** — auditor countersignatures over the
  published manifest (the signing substrate already supports it).
- **Localized question packs** — starter packs in the languages the
  l10n convention now serves.

## Elsewhere

Capabilities that need a service rather than a CLI — a web review
queue, scorecard history and drift dashboards, catalog connectors
(Shopify/BigCommerce) — live in the
[hosted edition](https://www.okf-web.com). The
split rule stays what it has always been: anything a single merchant
needs to publish a truthful bundle is here, open source; anything
that only makes sense operated for many merchants at once is there.
