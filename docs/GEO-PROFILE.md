# The `ecommerce-geo/1.10` Profile for OKF v0.2

This profile specializes the
[Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format)
for storefront companion bundles. It adds **no breaking changes**: a
profile bundle is a fully conformant OKF v0.2 bundle (unknown types
and keys are legal for OKF consumers), and any OKF reader can consume
it. GEO-aware producers and consumers additionally get the guarantees
below.

A concept opts in by declaring `x_geo.profile: ecommerce-geo/1.10`.

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
| `Product Passport` | Materials, origin, certifications, repairability (added in 1.6) | `a` (always) |
| `Store Location` | A physical store or pickup point: address, hours, services (added in 1.7) | `b` |
| `Trade Program` | Wholesale/B2B terms, eligibility, RFQ process (added in 1.8) | `a` (always) |
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
- **`Product Passport`:** compliance claims, so the gates are the
  strictest in the profile. `x_geo.passport_for` binds the passport
  to exactly one entity (resolution per W032), and `x_geo.passport`
  MUST carry at least `materials` and `origin` before `stable`
  (E017; `certifications` and `repairability` as stated). **The type
  is risk `a` by definition**: tooling gates on the effective
  classification — E010 (human verifier before stable), E013
  (sources), W024 (footnotes), publisher draft-withholding, and
  batch-approve exclusion all apply even if the frontmatter declares
  a lower risk (W033 flags the mismatch). Every certification claim
  cites its certificate document, not just a marketing page. The
  signed manifest (§7) covers the passport file's hash — bundle
  signature verification is the tamper-evidence chain, and a
  third-party auditor countersignature over the same manifest is the
  designed extension point.
- **`Store Location`:** the static layer of omnichannel — most of
  the value needs no API at all. `x_geo.entity` (a stable `loc:` id
  other concepts and stock capabilities reference) and
  `x_geo.location.address` required before `stable` (E018; W032 for
  drafts); `hours`, `phone`, `services` as posted. Risk `b` at
  minimum (W033 flags `c`) — a wrong address sends someone to a
  closed door. *Posted* hours are static claims; **open right now
  and shelf stock are live values** (§4) — a per-location stock
  capability (parameters `sku` + `location`, availability classes
  rather than counts) is the upgrade when the store has the API, and
  BOPIS ordering is a mutating flow that stays on the store's pages
  (§5).
- **`Trade Program`:** the store-level B2B contract. `x_geo.trade`
  MUST carry at least `payment_terms` and `min_order` before
  `stable` (E019; W032 for drafts), `lead_time` as stated. **The
  type is risk `a` by definition** — commercial and payment terms
  are money/legal claims, so the effective-risk rule applies exactly
  as for Product Passports: E010/E013/W024, publisher
  draft-withholding, and batch-approve exclusion gate on the type,
  whatever the frontmatter declares (W033 flags a mismatch).
  **Wholesale and contract prices are live values** (§4): quoted per
  RFQ, never published. Applying and requesting quotes are mutating
  flows (§5) — described in the body, done by the buyer on the
  store's pages; a token-scoped quote-*status* lookup is a fine
  capability, same pattern as warranty claims. Products MAY carry
  `x_geo.procurement` (`moq`, `case_pack`, `lead_time`) for per-SKU
  trade facts — terms only.
- **`GEO Scorecard`:** `generated` required; metrics live under
  `x_geo.metrics` (schema in [EVALUATION.md](EVALUATION.md)).

## 2. The `x_geo` extension namespace

All profile extensions live under one frontmatter key, `x_geo`, so
the OKF core surface stays pristine.

| Key | Type | Meaning |
| --- | --- | --- |
| `profile` | string | `ecommerce-geo/1.10` (opt-in marker) |
| `risk` | `a` \| `b` \| `c` | Verification gate class, §3 (default `c`) |
| `intents` | list | Question archetypes this concept answers: `discovery`, `product_fact`, `comparison`, `policy`, `fulfillment`, `trust`, `capability`, `promotion`, `fit_compatibility`, `ownership`, `compliance`, `local_availability`, `procurement` — retrieval hint for engines |
| `starts_at` / `ends_at` | date | Promotion concepts: the active window (`ends_at` required before stable; drives publisher auto-retirement) |
| `entity` | string | Stable store-local id, e.g. `sku:APO-TENT-A2`, `org:acme` |
| `fits` / `works_with` | list | Compatibility concepts (and products declaring interop): entity ids this concept gives fit guidance for / declares interoperable — every id must resolve to a concept's `entity` (W032) |
| `covers` | list | Ownership Guide concepts: entity ids this is post-purchase guidance for — same resolution rule (W032) |
| `passport_for` | string | Product Passport concepts: the single entity described — same resolution rule (W032) |
| `passport` | mapping | Product Passport concepts: `materials` (list), `origin`, `certifications` (list of name/issuer/resource), `repairability` — extra keys legal |
| `location` | mapping | Store Location concepts: `address` (required before stable), `hours`, `phone`, `services` — extra keys legal |
| `trade` | mapping | Trade Program concepts: `payment_terms` and `min_order` (required before stable), `lead_time` — terms, never prices |
| `procurement` | mapping | Product concepts: per-SKU trade facts — `moq`, `case_pack`, `lead_time` |
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
most often wrong about in third-party surfaces. The same rule covers
physical presence: *posted* hours are static claims, but whether a
store is open **right now** and what is on the shelf **right now**
are live values — quote posted hours, execute a stock capability.
It also covers trade: **wholesale and contract prices are quoted per
RFQ and never published** — terms (minimums, payment terms, lead
times) are the static claims; the price is always the quote.

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
- `attester.resource`: deterministic verifier **code** (no LLM) that
  takes a receipt and returns a verdict, per SPEC §10.2 — a bundle
  artifact, not an endpoint (1.10; W036 flags an http(s) attester).
  The profile ships the reference comparator
  `/attesters/http_refetch.py`: re-fetch the executor endpoint and
  compare the **attest-stable receipt fields** (identity and echo
  fields such as `sku`, `order_id`) against what the agent displayed.
  A live value has no job id to re-read, so http attestation
  certifies receipt fidelity — the value came from the declared
  endpoint, unaltered — never that a volatile number is eternal.
  Signature attestation (a signed receipt, e.g. ECDSA over
  `sku|price|currency|as_of`, checked by the artifact) remains the
  stronger mode where the store supports it.
- Etiquette in `x_geo`: `rate_limit`, `auth`. Endpoints exposed here
  MUST be safe for anonymous automated callers: read-only, no PII
  beyond token-gated fulfillment state, rate-limited server-side.
- **Endpoint locality.** Capability endpoints are expected on the
  declared site's own domain; the linter flags an executor host
  outside it (W037) so a delegation — or bait aimed at whoever
  executes the bundle — is conspicuous before publishing. Executors,
  in turn, refuse loopback/private/link-local targets by default
  (`okf-web mcp --allow-private-hosts` opts a local dev server back
  in): a bundle is data, and the hosts it names must not become a
  bridge into the operator's network.
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

`index.md`, `log.md` per OKF — with one declared deviation from SPEC
§8: the bundle-root `index.md` frontmatter carries `title`,
`description`, and `x_geo` (`profile`, `site`) alongside the
`okf_version` key the spec permits there, because the site binding
must live somewhere both strict consumers and tooling can find before
any concept is read. `manifest.json`'s `site` is the **normative**
copy of the binding for consumers; `lint --strict-okf` reports the
deviation (W040) for operators targeting strict base-spec readers.
Additionally reserved by this profile:
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
signer identity, then re-hash files against the manifest). Third
parties MAY **countersign the same manifest** at
`manifest.json.<label>.sigstore.json` (label: lowercase letters,
digits, hyphens — e.g. `manifest.json.auditor-acme.sigstore.json`,
written by `okf-web sign --as auditor-acme` with the attester's own
OIDC identity). The merchant signature says who published; each
countersignature says who vouched. Consumers verify a
countersignature exactly like the primary, expecting the attester's
identity (`okf-web verify --countersignature <label>`).

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
| E010 | error | High-risk concept `stable` without `human:` verifier (declared risk `a`, or a type that is high-risk by definition) |
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
| E017 | error | Stable `Product Passport` missing `passport_for` or `passport.materials`/`origin` |
| E018 | error | Stable `Store Location` missing `x_geo.entity` or `location.address` |
| E019 | error | Stable `Trade Program` missing `trade.payment_terms`/`min_order` |
| W032 | warn | Compatibility/Ownership Guide/Passport draft missing its refs, or a `fits`/`works_with`/`covers`/`passport_for` id that resolves to no concept's `entity` |
| W033 | warn | `Compatibility`/`Ownership Guide`/`Store Location` classified risk `c`, or `Product Passport`/`Trade Program` declaring anything but `a` (both are gated as `a` regardless) |
| W034 | warn | `Policy`/`Promotion`/`Store Identity` declaring a risk below the type table's `a` floor — a lower declared risk would unlock batch approval |
| W035 | warn | Malformed source credibility signal (SPEC §5.1): `usage_count` not a non-negative integer, `last_modified` not a date, or `usage_window` without `from`/`to` dates |
| W036 | warn | `attester.resource` names an endpoint instead of deterministic verifier code, or a bundle-relative attester artifact missing from the bundle |
| W037 | warn | Capability `executor.resource` host lies outside the declared site's domain — a delegation worth a human glance before publishing (legitimate ones exist; they must be conspicuous) |
| W040 | warn | (`--strict-okf` only) declared base-spec deviation: index frontmatter beyond SPEC §8's allowance (§7) |

Errors block publishing; `--strict` promotes warnings for CI.

## 10. Versioning

**1.10** (current) closes the spec-coverage gaps found by the
fidelity audit ([FIDELITY.md](FIDELITY.md), Phase F4): source
credibility signals are emitted by the surveyor contract and the feed
ingester and validated by lint (W035, with `usage_window` support);
the http attester convention becomes deterministic verifier code
shipped as a bundle artifact (`/attesters/http_refetch.py`; W036),
replacing the endpoint-as-attester mode; the root-index frontmatter
deviation from SPEC §8 is declared in §7 and reportable via
`lint --strict-okf` (W040); and the risk-floor lint W034
(`Policy`/`Promotion`/`Store Identity`) ships alongside. Additive;
concepts declaring earlier minors remain fully valid.

**1.9** adds the countersignature convention (§7) —
bundle-level only: third parties attest a published bundle by
signing the same manifest under their own identity. No concept
frontmatter changes; concepts declaring earlier minors remain fully
valid.

**1.8** adds the `Trade Program` type, the
`trade`/`procurement` mappings, the `procurement` intent, lint code
E019, the extension of the effective-risk rule to trade programs,
and the quoted-prices live-values clarification — additive; concepts
declaring earlier minors remain fully valid. This completes the
five-phase value-expansion plan ([EXPANSION.md](EXPANSION.md)).

**1.7** adds the `Store Location` type, the `location`
mapping, the `local_availability` intent, lint code E018, and the
live-values clarification for open-right-now and shelf stock —
additive; concepts declaring earlier minors remain fully valid.

**1.6** adds the `Product Passport` type, the
`passport_for`/`passport` keys, the `compliance` intent, lint code
E017, and the effective-risk rule (passports gate as `a` regardless
of declared risk, enforced across linter, publisher, and batch
approval) — additive; concepts declaring earlier minors remain fully
valid.

**1.5** adds the `Ownership Guide` type, the `covers` key,
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
