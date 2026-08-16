# The `ecommerce-geo/1.5` Profile for OKF v0.2

This profile specializes the
[Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
for storefront companion bundles. It adds **no breaking changes**: a
profile bundle is a fully conformant OKF v0.2 bundle (unknown types
and keys are legal for OKF consumers), and any OKF reader can consume
it. GEO-aware producers and consumers additionally get the guarantees
below.

A concept opts in by declaring `x_geo.profile: ecommerce-geo/1.5`.

## 1. Concept types

Type values are free-form in OKF; this profile fixes a vocabulary so
tooling and engines can dispatch on them.

| `type` | Purpose | Typical risk |
| --- | --- | --- |
| `Store Identity` | Who the merchant is, contact, trust facts | `a` |
| `Policy` | Returns, shipping, warranty, privacy, terms | `a` |
| `Product` | One purchasable product (or parent of variants) | `b` |
| `Product Collection` | A navigable grouping of products | `c` |
| `FAQ` | Merchant-authored questions and answers | `b` |
| `Buying Guide` | Comparative/selection guidance across products | `b` |
| `Attested Computation` | An executable capability of the store (OKF core type) | `a` |
| `Promotion` | A time-bounded offer: sales, discount codes (added in 1.1) | `a` |
| `Compatibility` | Fit charts, works-with matrices, part fitment (added in 1.4) | `b` |
| `Ownership Guide` | Care, setup, troubleshooting, warranty process for owners (added in 1.5) | `b` |
| `GEO Scorecard` | Machine-generated answerability evaluation | `c` |

### Per-type requirements (beyond OKF's required `type`)

- **All profile concepts:** `title`, `description` (one sentence),
  `tags`, and `x_geo.profile`. `resource` MUST be the canonical live
  URL of the underlying page/asset when one exists — it is the
  page ⇄ concept binding.
- **`Product`:** `resource` required (lint E012). `x_geo.entity`
  SHOULD carry a stable id (`sku:…`, `gtin:…`). Static price, stock,
  or delivery-date claims MUST NOT appear; link capability concepts
  instead (see §4).
- **`Attested Computation`:** `runtime` required (OKF core; lint
  E011); `executor.resource` expected (lint W026). See §5 for the
  `http` runtime.
- **`Promotion`:** the time bound is the contract. `x_geo.ends_at`
  required before `stable` (lint E014 — unbounded promotions are what
  engines misquote); `x_geo.starts_at` recommended; `stale_after`
  SHOULD equal `ends_at` so freshness machinery retires the concept
  with the sale (W027, and the surveyor defaults it). The discount's
  *terms* are stated in the body; the resulting price never is (§4).
  **The publisher auto-withholds expired promotions** — `ends_at` is
  machine-readable, so this is the one content class with unambiguous
  auto-retirement: a publish after the end date cannot ship a dead
  sale (W028 reminds the producer to retire the file).
- **`Compatibility`:** the machine-resolvable applicability is the
  contract. `x_geo.fits` (entities this gives sizing/fit guidance
  for) and/or `x_geo.works_with` (entities declared interoperable)
  required before `stable` (lint E015; W032 flags drafts still
  missing them) — a fit chart that names no entities cannot be
  targeted by an agent asking "will this fit mine?". Every reference
  must resolve to some concept's `x_geo.entity` in the bundle
  (W032). Risk is `b` at minimum — wrong fit claims drive returns —
  and `a` when fitment is safety-relevant (W033 flags `c`). The
  chart or matrix itself lives in the body as a markdown table with
  footnotes; the live-values rule (§4) still applies — no prices in
  fit charts.
- **`Ownership Guide`:** same applicability contract as
  Compatibility, for the post-purchase audience: `x_geo.covers` names
  the entities the guidance is for, required before `stable` (lint
  E016; W032 flags drafts still missing it), every id resolving to a
  concept's `entity` (W032). Risk `b` at minimum — wrong care advice
  damages products and voids warranties — and `a` when care is
  safety-relevant (W033 flags `c`). Warranty *processes* are
  described in the body with links to the store's pages; mutating
  flows (registration, claim filing) are never exposed as executable
  capabilities (§5) — the read-only status lookup is.
- **`GEO Scorecard`:** `generated` required; metrics live under
  `x_geo.metrics` (schema in [EVALUATION.md](EVALUATION.md)).

## 2. The `x_geo` extension namespace

All profile extensions live under one frontmatter key, `x_geo`, so
the OKF core surface stays pristine.

| Key | Type | Meaning |
| --- | --- | --- |
| `profile` | string | `ecommerce-geo/1.5` (opt-in marker) |
| `risk` | `a` \| `b` \| `c` | Verification gate class, §3 (default `c`) |
| `intents` | list | Question archetypes this concept answers: `discovery`, `product_fact`, `comparison`, `policy`, `fulfillment`, `trust`, `capability`, `promotion`, `fit_compatibility`, `ownership` — retrieval hint for engines |
| `starts_at` / `ends_at` | date | Promotion concepts: the active window (`ends_at` required before stable; drives publisher auto-retirement) |
| `entity` | string | Stable store-local id, e.g. `sku:APO-TENT-A2`, `org:acme` |
| `fits` / `works_with` | list | Compatibility concepts (and products declaring interop): entity ids this concept gives fit guidance for / declares interoperable — every id must resolve to a concept's `entity` (W032) |
| `covers` | list | Ownership Guide concepts: entity ids this is post-purchase guidance for — same resolution rule (W032) |
| `brand` | string | Product brand |
| `source_hash` | string | `sha256:<hex>` of the normalized source text at survey time — powers incremental re-survey |
| `source_fetched_at` | date | When the source was fetched |
| `live_price` / `live_stock` | path | Bundle path of the capability concept serving the live value |
| `review` | mapping | Set by `reject`: `{rejected_by, at, reason}`; cleared on approval |
| `l10n_source_hash` | string | Translations only (§7): content hash of the source concept at translation time — powers the parity check |
| `metrics` / `baseline` | mapping | Scorecard concepts only |
| `rate_limit` / `auth` | string | Capability concepts: consumption etiquette |

Producers MAY add further `x_geo` keys; consumers MUST ignore unknown
ones (mirroring OKF's own rule).

## 3. Risk tiers and the verification gate

`x_geo.risk` classifies the blast radius of a wrong claim:

- **`a` — high.** Anything involving money, legal commitments, or
  safety: prices/promotion wording, return/warranty/shipping terms,
  compliance and safety claims, company identity. **Invariant (lint
  E010):** a risk-`a` concept may be `status: stable` only with a
  `human:` actor in `verified`. The publisher never ships risk-`a`
  drafts. High-risk concepts also require `sources` (E013) and warn
  without claim-level footnotes (W024).
- **`b` — medium.** Descriptive facts extracted from merchant
  surfaces (specs, materials, care). May publish machine-confirmed;
  human review is asynchronous.
- **`c` — low.** Structure and machine-generated reports.

This is the profile's core contract: **the trust tier an engine reads
is backed by a gate a linter enforces**, not by convention.

## 4. Live values rule

Concepts MUST NOT state volatile transactional values (price, stock,
delivery dates, promo end times) as static claims. The pattern:

```yaml
# in a Product concept
x_geo:
  live_price: /capabilities/price-check.md
  live_stock: /capabilities/stock-check.md
```

with a body section directing agents to execute the capability. This
keeps the bundle permanently non-lying about the two facts stores are
most often wrong about in third-party surfaces.

## 5. The `http` runtime for Attested Computations

OKF's `Attested Computation` names runtimes like `bigquery` and
`python`; runtime values are open, and this profile defines **`http`**
for public storefront endpoints:

- `parameters`: OKF-standard `{name, type, required}` holes.
- `executor.resource`: a URI template over those parameters
  (`https://…/price?sku={sku}`). `executor.receipt` lists the response
  fields agents should retain.
- `# Computation` body section: the concrete HTTP request template
  (method, headers) in a fenced block, plus an example response.
- `attester.resource`: how anyone verifies a receipt. Two accepted
  modes: **signature attestation** (endpoint validating a signed
  receipt, e.g. ECDSA over `sku|price|currency|as_of`) or
  **re-execution** (idempotent public endpoint — verify by calling
  again).
- Etiquette in `x_geo`: `rate_limit`, `auth`. Endpoints exposed here
  MUST be safe for anonymous automated callers: read-only, no PII
  beyond token-gated fulfillment state, rate-limited server-side.
- **Mutating flows are never capabilities.** Registration, claim
  filing, ordering — anything that changes state — is described in
  concept bodies with links to the store's own pages, not exposed as
  an executable. This keeps every declared capability safe for an
  anonymous agent to execute (the MCP bridge enforces GET-only), and
  keeps the human owner in the loop for every state change. The
  read-only *status lookup* for such a flow is a fine capability —
  see the warranty pattern: file on the store's page, check by
  token-scoped lookup.

This section is what makes the bundle a companion to site
*functionality*: the store's API surface becomes discoverable,
learnable knowledge with a verification story, instead of something
each agent reverse-engineers.

## 6. Actors

Per OKF: `human:<id>` for people (the prefix consumers key trust on),
`<producer>/<version>` for agents (`okf-web-surveyor/claude-sonnet-5`),
`process:<id>` for automation (`process:okf-web-faithfulness-check`).
This profile requires pipeline stamps to be truthful: tooling MUST
overwrite model-emitted `generated`/`verified` fields (models cannot
self-verify).

## 7. Reserved layout

`index.md`, `log.md` per OKF. Additionally reserved by this profile:
`_review/` (drift proposals awaiting humans) and `_quarantine/`
(rejected LLM output) — working-copy state that MUST NOT be
published; **`l10n/<lang>/<rel-path>`** (added in 1.3) — a
translation of the concept at `<rel-path>`, same layout mirrored
under a language tag. Translations are full concepts (they lint,
verify, and publish like any other) and MUST pin
`x_geo.l10n_source_hash` to their source's content hash so parity is
checkable (W030/W031). Tooling reads a language through a *localized
view*: translations overlay their sources, untranslated concepts
fall back to the default language, and other languages drop out —
partial translation degrades to mixed language, never to missing
knowledge. Default-language retrieval and evaluation exclude `l10n/`
trees so translations never duplicate their sources in ranking.

At publish time, generated artifacts `manifest.json`
(per-file sha256 + bytes), `linkmap.json` (live URL → concept path),
`llms-snippet.txt`, and optionally `manifest.json.sigstore.json` — a
sigstore signature over the manifest that authenticates the entire
published bundle (consumers probe this conventional name, verify the
signer identity, then re-hash files against the manifest).

## 8. Discovery and delegation

How engines find a bundle, in order of preference:

1. **Well-known location** (primary): `https://<store-domain>/.well-known/okf/`,
   entry point `index.md`, `manifest.json` for freshness/delta-sync.
   An entry in the site's `llms.txt` (the publisher emits the block)
   makes the location explicit for engines that read it.
2. **Delegated location**: many platform-hosted stores cannot serve
   files at the domain root. Such a store MAY host the bundle at any
   HTTPS base URL and point to it from the storefront's HTML head —
   a surface every platform's theme editor can edit:

   ```html
   <link rel="okf-bundle" href="https://cdn.example.net/acme-okf/">
   ```

   (and/or an `llms.txt` entry with the absolute URL).

**The binding is bidirectional.** A delegated bundle must prove it
speaks for the store, and the store must prove it chose the bundle:

- *store → bundle*: the pointer above lives on the store's own origin
  — only the merchant can put it there.
- *bundle → store*: the published `manifest.json` carries a `site`
  key naming the storefront origin the bundle claims (the publisher
  writes it from `--site` or the root index's `x_geo.site`).

Consumers of an off-origin bundle MUST check both halves — pointer
origin equals `manifest.site` — before treating the bundle as the
store's own voice, and SHOULD check that concept `resource` URLs
(equivalently `linkmap.json` keys) are on that origin; the publisher
warns at build time when they are not. A sigstore signature over the
manifest (§7) additionally proves *who* published; delegation proves
*for which store*. The two compose: signature for authenticity,
binding for authority.

Same-origin bundles at the well-known location need none of this —
path position is the binding.

## 9. Lint vocabulary

| Code | Level | Rule |
| --- | --- | --- |
| E001 | error | Frontmatter missing/unparseable (OKF conformance) |
| E002 | error | Missing/empty `type` (OKF conformance) |
| E003 | error | Root `okf_version` present but not `0.2` |
| E010 | error | Risk-`a` concept `stable` without `human:` verifier |
| E011 | error | `Attested Computation` without `runtime` |
| E012 | error | `Product` without `resource` |
| E013 | error | Risk-`a` concept without `sources` |
| E014 | error | Stable `Promotion` without `x_geo.ends_at` |
| W020 | warn | Footnote ref without matching `sources[].id`/definition |
| W021 | warn | `stale_after` has passed (publish `--freshness withhold` retires such concepts instead of shipping them) |
| W022 | warn | Broken bundle-internal link |
| W027 | warn | `Promotion` missing end date (draft) or `stale_after` ≠ `ends_at` |
| W028 | warn | Promotion ended; publisher withholds it — retire the concept |
| W024 | warn | Risk-`a` concept with no claim-level footnotes |
| W026 | warn | Attested Computation without `executor.resource` |
| W030 | warn | Translation with no source concept at the mirrored path |
| W031 | warn | Translation unpinned or out of date vs its source (`x_geo.l10n_source_hash`) |
| E015 | error | Stable `Compatibility` without `x_geo.fits`/`works_with` |
| E016 | error | Stable `Ownership Guide` without `x_geo.covers` |
| W032 | warn | Compatibility/Ownership Guide draft missing entity refs, or a `fits`/`works_with`/`covers` id that resolves to no concept's `entity` |
| W033 | warn | `Compatibility`/`Ownership Guide` classified risk `c` — fit claims drive returns, care claims damage products; use `b`/`a` |

Errors block publishing; `--strict` promotes warnings for CI.

## 10. Versioning

**1.5** (current) adds the `Ownership Guide` type, the `covers` key,
the `ownership` intent, lint code E016 (with W032/W033 extended to
the new type), and the mutating-flows rule in §5 — additive; concepts
declaring earlier minors remain fully valid.

**1.4** adds the `Compatibility` type, the
`fits`/`works_with` keys, the `fit_compatibility` intent, and lint
codes E015/W032/W033 — additive; concepts declaring earlier minors
remain fully valid.

**1.3** adds the `l10n/<lang>/` translation convention
(§7), the `l10n_source_hash` key, and lint codes W030/W031 —
additive; concepts declaring earlier minors remain fully valid.

**1.2** adds the discovery/delegation convention (§8) and
the manifest `site`/`bundle_url` keys. Bundle-level only: no concept
frontmatter changes, so concepts declaring 1.1 remain fully valid.

**1.1** adds the `Promotion` type, the `starts_at`/`ends_at` keys,
the `promotion` intent, and lint codes E014/W027/W028 — all additive,
so 1.0 concepts remain valid and 1.0 consumers simply ignore the new
type and keys.

The profile versions independently of OKF (`ecommerce-geo/<major>.<minor>`),
minor = additive. Consumers encountering an unknown minor MUST treat
unknown keys as ignorable; unknown major means fall back to plain OKF
reading, which always works.
