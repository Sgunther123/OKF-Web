# The `ecommerce-geo/1.0` Profile for OKF v0.2

This profile specializes the
[Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
for storefront companion bundles. It adds **no breaking changes**: a
profile bundle is a fully conformant OKF v0.2 bundle (unknown types
and keys are legal for OKF consumers), and any OKF reader can consume
it. GEO-aware producers and consumers additionally get the guarantees
below.

A concept opts in by declaring `x_geo.profile: ecommerce-geo/1.0`.

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
- **`GEO Scorecard`:** `generated` required; metrics live under
  `x_geo.metrics` (schema in [EVALUATION.md](EVALUATION.md)).

## 2. The `x_geo` extension namespace

All profile extensions live under one frontmatter key, `x_geo`, so
the OKF core surface stays pristine.

| Key | Type | Meaning |
| --- | --- | --- |
| `profile` | string | `ecommerce-geo/1.0` (opt-in marker) |
| `risk` | `a` \| `b` \| `c` | Verification gate class, §3 (default `c`) |
| `intents` | list | Question archetypes this concept answers: `discovery`, `product_fact`, `comparison`, `policy`, `fulfillment`, `trust`, `capability` — retrieval hint for engines |
| `entity` | string | Stable store-local id, e.g. `sku:APO-TENT-A2`, `org:acme` |
| `brand` | string | Product brand |
| `source_hash` | string | `sha256:<hex>` of the normalized source text at survey time — powers incremental re-survey |
| `source_fetched_at` | date | When the source was fetched |
| `live_price` / `live_stock` | path | Bundle path of the capability concept serving the live value |
| `review` | mapping | Set by `reject`: `{rejected_by, at, reason}`; cleared on approval |
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
published; and at publish time, generated artifacts `manifest.json`
(per-file sha256 + bytes), `linkmap.json` (live URL → concept path),
`llms-snippet.txt`, and optionally `manifest.json.sigstore.json` — a
sigstore signature over the manifest that authenticates the entire
published bundle (consumers probe this conventional name, verify the
signer identity, then re-hash files against the manifest).

## 8. Lint vocabulary

| Code | Level | Rule |
| --- | --- | --- |
| E001 | error | Frontmatter missing/unparseable (OKF conformance) |
| E002 | error | Missing/empty `type` (OKF conformance) |
| E003 | error | Root `okf_version` present but not `0.2` |
| E010 | error | Risk-`a` concept `stable` without `human:` verifier |
| E011 | error | `Attested Computation` without `runtime` |
| E012 | error | `Product` without `resource` |
| E013 | error | Risk-`a` concept without `sources` |
| W020 | warn | Footnote ref without matching `sources[].id`/definition |
| W021 | warn | `stale_after` has passed |
| W022 | warn | Broken bundle-internal link |
| W024 | warn | Risk-`a` concept with no claim-level footnotes |
| W026 | warn | Attested Computation without `executor.resource` |

Errors block publishing; `--strict` promotes warnings for CI.

## 9. Versioning

The profile versions independently of OKF (`ecommerce-geo/<major>.<minor>`),
minor = additive. Consumers encountering an unknown minor MUST treat
unknown keys as ignorable; unknown major means fall back to plain OKF
reading, which always works.
