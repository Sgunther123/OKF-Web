# Fidelity review — OKF-Web against the OKF v0.2 specification

**Status:** measured audit, 2026-08-17 · Companion to [DESIGN.md](DESIGN.md),
[GEO-PROFILE.md](GEO-PROFILE.md), and [EXPANSION.md](EXPANSION.md).

**Reference:** the Open Knowledge Format specification's canonical home,
[`GoogleCloudPlatform/open-knowledge-format`](https://github.com/GoogleCloudPlatform/open-knowledge-format)
at `SPEC.md` (OKF **v0.2** — the same version this project targets),
re-audited at upstream commit `ad30107` (2026-08-27). The original audit ran
against the spec's prior location, `GoogleCloudPlatform/knowledge-catalog`
at `okf/SPEC.md`, commit `fe3268a` (2026-08-14); that copy is now declared a
frozen, unmaintained snapshot by its own README, and this document tracks
the living repository instead (READINESS R1.2). The reference repository
also carries the implementation and sample bundles
(`bundles/stackoverflow`, `bundles/acme_retail`) used to check conventions
the prose leaves loose. Code findings below were verified against this
repository's source at profile 1.9 with the full verification loop green
(173 tests twice, `lint --strict` 0/0, dry-run at the reference numbers) —
every finding is latent, none is a current regression.

**Delta at re-audit (fe3268a → ad30107):** exactly one normative change —
every timestamp-valued key (`stale_after`, `sources[].last_modified`,
`usage_window.from/to`) is now an ISO 8601 datetime with an explicit UTC
offset, and staleness reads `now >= stale_after`; §5/§11 also drop a
duplicated timestamp-conformance bullet. Every §2 verdict below survives
the rev; the format change is recorded as **D15**, closed by the shipped
writer-side migration **F5** (§4).

## 1. Verdict

The implementation is **substantially faithful** to OKF v0.2. The spec's
load-bearing machinery is implemented, tested, and in several places cited in
code: concept documents as markdown + YAML frontmatter with `type` required;
tolerant consumption of unknown types and keys; `sources` with keyed footnote
attribution; `generated`/`verified` with the actor convention and the
three trust tiers keyed on the `human:` prefix; bare-mapping `verified`
normalized to a one-element list (a consumer MUST); `status` defaulting to
`stable`; absolute `stale_after` (read at date granularity — D15);
bundle-absolute and relative links
with broken links tolerated; reserved `index.md`/`log.md`; `okf_version`
read from the root index; and the full Attested Computation contract
(`runtime` required and lint-enforced as E011, `parameters` as
`{name, type, required}`, `executor.resource` + `executor.receipt`).

The `ecommerce-geo` profile itself is a legitimate use of the spec's
extension posture: `x_geo` is exactly the producer-defined key family §4.1
invites, the profile only *tightens* producer requirements (consumers stay
permissive), and the live-values rule is a domain-correct application of
§10's "record the computation, not the value."

The deviations the original audit found are enumerated below: two
spec-conformance deviations (D5, D12), one weak convention (D13), one
unexercised spec family (D14), and ten code-level findings (D1–D4, D6–D11)
where the implementation undercut its own invariants or its consumer
surfaces. All fourteen are closed by the shipped phases F1–F4. The
re-audit at `ad30107` opened one new finding, **D15** (timestamp
precision), closed by the shipped Phase F5 — every finding this
document has ever recorded is now closed.

## 2. Conformance audit by spec section

| SPEC § | Requirement | Status | Anchor |
| --- | --- | --- | --- |
| §3 | Bundle = directory tree of markdown; git-distributable | ✓ | `model.load_bundle` |
| §3.1 | `index.md`/`log.md` reserved, never concepts | ✓ | `model.L10N_DIR`/index handling, `evaluator.META_TYPES` |
| §4.1 | `type` required; unknown types/keys tolerated | ✓ | linter E001-family (producer gate only); loader is permissive |
| §4.1 | Extensions via producer-defined keys | ✓ | the `x_geo` namespace |
| §5.1 | `sources[].resource` required; keyed footnote attribution | ✓ | linter source/footnote checks; `feed.item_to_document` |
| §5.1 | Source credibility signals (`author`, `usage_count`, `last_modified`, `usage_window`) — datetimes since ad30107 | ✓ (closed, F4) | D14 — W035 validates, feed/example emit, retrieval surfaces; datetime values read (D15 test) |
| §5.2 | `generated {by, at}`; `verified` list; bare mapping = one-element list (MUST) | ✓ | `model.Concept.verified_entries` |
| §5.3 | Trust tiers from `verified` + `human:` prefix | ✓ | `model.Concept.trust_tier` |
| §5.4 | `status` absent ⇒ `stable` | ✓ | `model.Concept.status` |
| §5.5 | Stale when `now >= stale_after` (datetime since ad30107) | ✓ (closed, F1+F5) | `>=` shipped (F1); instants emitted and instant-granular comparison with a datetime clock (F5); date-clock paths stay conservatively date-granular |
| §6 | `/`-absolute + relative links; broken links tolerated | ✓ | `model.Bundle.resolve_link`; W-codes warn, never reject |
| §7 | Actor convention (`producer/version`, `human:`, `process:`) | ✓ | surveyor/feed stamps; trust tiers |
| §8 | Index frontmatter: only `okf_version`, root only | **deviation, declared** | D12 (declared, F4) — root index carries the site binding; W040 reports under `--strict-okf` |
| §9 | `log.md`: ISO date headings, newest first | ✓ | `bundle-example/log.md` |
| §10.2 | Attested Computation: `runtime` REQUIRED; `parameters` typed; `executor.receipt` | ✓ | E011; `bundle-example/capabilities/*` |
| §10.2 | `attester.resource` names deterministic verifier code | ✓ (closed, F4) | D13 — W036 enforces; `/attesters/http_refetch.py` ships in the example |
| §11 | Consumer permissiveness (no rejection for optional families) | ✓ | loader + evaluator + publisher |
| §12 | `okf_version` declared in root index | ✓ | `bundle-example/index.md`, `model.Bundle.okf_version` |

## 3. Deviations and gaps

Ordered by severity. D1–D4 and D6–D11 were also reported as review findings
with file/line anchors; D5, D12–D14 are the spec-conformance items.

- **D1 — Feed drop-list misses money-bearing fields.** `feed.DROPPED_FIELDS`
  omits `cost_of_goods_sold`, `installment`, `subscription_cost`,
  `loyalty_points`, and `auto_pricing_min_price`; such fields pass through
  `extras` into published concept bodies. Publishing COGS leaks merchant
  margin; installment/subscription figures are stale price claims — both
  violate the live-values invariant. *(src/okf_web/feed.py:49)*
- **D2 — Risk floor absent for the original money/legal types.** W033 floors
  exist for the five newer high-stakes types but not Policy, Promotion, or
  Store Identity: a surveyor mis-declaring `risk: b` silently unlocks
  `batch-approve` for a legal claim. *(src/okf_web/linter.py)*
- **D3 — Localized views advertise paths that cannot be looked up.**
  `localized_view` overlays translation concepts under source keys without
  rewriting `rel_path`; `--lang` evaluation undercounts citability and the
  MCP bridge's search→get round-trip 404s for translations.
  *(src/okf_web/model.py:436)*
- **D4 — Feed ingestion is O(N²) in bundle loads.** Two full-bundle reparses
  per row makes 10k–100k-SKU catalogs (the sizes delegation-scale adoption
  implies) take hours for an operation advertised as free.
  *(src/okf_web/feed.py:225)*
- **D5 — Staleness off by one day against §5.5.** `is_stale` uses `>` where
  the spec says a concept is stale when `today >= stale_after`; every
  freshness surface (publisher withhold/warn, lint, drift context) treats
  concepts as fresh for the whole of their stale date.
  *(src/okf_web/model.py:184)*
- **D6 — Review triage keyed on declared, not effective, risk.** Sorting,
  `--risk` filtering, and the CI summary count a mis-declared Trade Program
  or Product Passport in the `b` tier even though every gate treats it as
  `a`. The gates hold; the triage surface contradicts them.
  *(src/okf_web/review.py:73)*
- **D7 — Delegation verifier mis-resolves relative link hrefs.** `discover`
  appends `/` to the page URL before `urljoin`, so `href="bundle/okf"` on
  `/home.html` resolves to `/home.html/bundle/okf` and a healthy binding is
  reported broken. *(src/okf_web/discover.py:113)*
- **D8 — Embedding index staleness keyed on `id(bundle)`.** A recycled
  object address serves another bundle's vectors; an in-place mutation never
  re-embeds. *(src/okf_web/retrieval.py:182)*
- **D9 — Capability placeholder validation scans only path+query.** A
  placeholder in the URL host or fragment escapes the undeclared-arguments
  check and surfaces as a DNS error instead of the contractual message.
  *(src/okf_web/mcp_bridge.py:207)*
- **D10 — Index rebuild pluralizes naively.** `okf-web index` writes
  headings like "Compatibilitys" and "Store Identitys" onto the published
  navigation surface. *(src/okf_web/surveyor.py:396)*
- **D11 — Invalid countersignature label crashes `verify`.** The label is
  validated outside the CLI's error handling, producing a traceback instead
  of the clean message every other signing path prints.
  *(src/okf_web/cli.py:502)*
- **D12 — Root index frontmatter exceeds §8's allowance.** §8 permits
  exactly one frontmatter key in a reserved `index.md` (`okf_version`, root
  only); ours also carries `title`, `description`, and `x_geo` — including
  the `site` binding that discovery delegation and `publish --site`
  auto-resolution hang on. A strict §11-clause-3 checker flags the bundle,
  and spec-faithful consumers never look for a site binding there.
- **D13 — The attester convention is thinner than §10.2.** Capability
  concepts set `attester.resource` to the live endpoint rather than
  deterministic verifier code that inspects a receipt and returns a verdict.
  Attestation degenerates to an undocumented re-fetch convention; the
  "was this produced the sanctioned way" check cannot actually run.
- **D14 — Credibility signals are unexercised.** §5.1's per-source `author`,
  `usage_count`, `last_modified`, and `usage_window` are the spec's
  trust-inference machinery — precisely the GEO use case — yet the surveyor
  prompt requests only `last_modified`, the feed emits none, the linter
  validates none, and no consumer surface reads them.

- **D15 — Timestamp precision (spec rev ad30107) — closed by F5.** The
  spec now makes every timestamp-valued key an ISO 8601 datetime with an
  explicit UTC offset (`2026-06-30T14:00:00Z`), staleness reading
  `now >= stale_after`. The **reader side** accepts datetime objects and
  ISO datetime strings alongside bare dates (tested), and `is_stale`
  compares at instant granularity when given a datetime clock; date-clock
  paths keep the date-granular reading, which marks a mid-day instant
  stale from the start of its day — the conservative direction. The
  **writer side conforms since F5**: every spec timestamp is emitted as
  an instant, and the profile's own `x_geo` calendar-date keys are
  declared date-precision by design (GEO-PROFILE §7).

Minor doc drift, folded into Phase F1 chores: the evaluator module
docstring still says "seven shopping intents" (there are thirteen
archetypes).

## 4. Phased hardening plan

Standing admission rule (as in EXPANSION.md): a phase ships only with lint
gates, tests, example-bundle coverage where user-visible, and a re-measured
scorecard whenever behavior can move a number. Every phase ends with the
full verification loop; anything that changes rankings or cached vectors
bumps the embedder model id; any new `x_geo` surface bumps the profile with
a GEO-PROFILE §10 row.

### Phase F1 — Trust-invariant integrity (D1, D2, D5, D6 + chores) — **shipped**

The invariants the product's credibility rests on, made true everywhere,
not just at the final gates. Extend `DROPPED_FIELDS` to every money-bearing
Merchant field and add a deny-by-category guard (any field whose name
matches price/cost/inventory patterns is dropped and logged); add W033
floors for Policy, Promotion, and Store Identity; change `is_stale` to
`>=` per §5.5 (one-day shifts in example dates and tests are expected and
re-pinned deliberately); key review-queue ordering, filtering, and the
summary line on effective risk. Chore: evaluator docstring count.
*Acceptance:* a feed fixture carrying COGS/installment fields publishes
none of them; a risk-`b` Policy draft warns; a `stale_after == today`
concept is withheld under `--freshness withhold`; `review list --risk a`
lists a mis-declared Trade Program draft.

### Phase F2 — Consumer-surface correctness (D3, D7, D9, D10, D11) — **shipped**

The surfaces engines and operators actually touch. Rewrite `localized_view`
to re-key translated concepts so advertised paths round-trip through
`get`/`okf_get`; resolve relative link hrefs against the page URL exactly
as browsers do; extend placeholder validation to the whole URL; give
`rebuild_index` a small irregular-plural map (or per-type heading strings
in one table); route the countersignature-label error through the CLI's
clean error path. *Acceptance:* `--lang es` citability equals the source
bundle's on identical content; a relative-href fixture discovers
successfully; a `{region}`-host capability raises the contractual error;
`okf-web index` output contains no malformed headings; an invalid label
exits 2 with a one-line message.

### Phase F3 — Scale and determinism (D4, D8) — **shipped**

Note on the shipped form: the O(N) proof is a deterministic
load-count assertion (one `load_bundle` per ingest, monkeypatch-counted)
rather than a wall-clock bound — strictly stronger, and immune to CI
timing noise. The risk floor landed as lint code **W034**; the staleness
guard in `EmbeddingIndex` is a content signature over the retrievable
slice, so cross-process cache correctness holds by construction.

What delegation-scale catalogs require. Load the bundle's resource map once
per `ingest_feed` and maintain it incrementally across writes (target:
provably O(N) bundle loads per ingest, demonstrated with a synthetic
10k-row fixture timed in CI as a sanity bound, not a benchmark); replace
`id(bundle)`-keyed staleness in `EmbeddingIndex` with content-addressed
staleness (the concept-hash set it already computes), which also makes the
cache correct across processes by construction.

### Phase F4 — Spec-coverage and conventions (D12, D13, D14) — **shipped, profile 1.10**

Close the gap between "conformant where exercised" and "exercises the
spec." Credibility signals: surveyor and feed emit `author`/`last_modified`
(and `usage_count`/`usage_window` where the source exposes it), a W-code
validates shapes, and the evaluator's retrieval context surfaces them so
engines can rank on them. Attestation: define the profile's http-attester
convention properly — a small deterministic comparator (re-fetch, compare
receipt fields, return a verdict) shipped as a referenced artifact, per
§10.2's "code, not endpoint." Root-index posture: declare the deviation
explicitly in GEO-PROFILE (§8-extension: the profile stores its site
binding in root-index frontmatter alongside `okf_version`), mirror the
binding into `manifest.json` (already present) as the normative location
for consumers, and add a `lint --strict-okf` mode that reports D12-class
deviations so operators can see exactly where the profile exceeds the base
spec. F4's additions to `x_geo` or emitted frontmatter are additive and
ship as a profile bump with the standard §10 history row.

Shipped form: lint W035 (signal shapes) and W036 (endpoint-as-attester,
missing artifact); the reference comparator lives at
`/attesters/http_refetch.py` in the example bundle and publishes with
it; `lint --strict-okf` reports W040; the example FAQ and Store
Identity sources carry live signals; the feed stamps `last_modified`
from the file itself.

### Phase F5 — Instant-precision timestamps (D15) — **shipped**

Emit ISO 8601 datetime stamps wherever the base spec now expects them:
`stale_after` in generated concepts and the surveyor prompt contract,
feed-derived `sources[].last_modified`, and the example bundle's stamps,
with `is_stale` gaining instant-granular comparison when given a
datetime clock. Profile-owned `x_geo` date keys (`ends_at`,
`source_fetched_at`) migrate together or are declared date-precision in
GEO-PROFILE §7 — decided when the phase is implemented. Reader
tolerance for both forms already ships and is pinned by tests (D15), so
this phase is writer-side only and additive.

Shipped form. Every writer of a spec timestamp now stamps instants:
the feed's `last_modified` from file mtime (`model.utc_instant`), the
surveyor's Promotion `stale_after` (midnight UTC of the profile's
`ends_at` calendar date — W027's date-granular equality holds), the
surveyor prompt contract's credibility signals, and `write_scorecard`,
which now also emits the 30-day evaluation SLA as a real
`stale_after` instant (EVALUATION.md's "scorecard SLA" made
machine-readable — the freshness machinery retires an un-renewed
scorecard). The example bundle's `stale_after`, `last_modified`, and
`usage_window` values all migrated to instants (es
`l10n_source_hash` re-pinned). The decision the plan left open landed
as **declared date-precision**: `x_geo.starts_at`/`ends_at`/
`source_fetched_at` remain calendar dates by design, recorded in
GEO-PROFILE §7. `is_stale` gained the spec's exact `now >=
stale_after` when handed a datetime clock (tested at the boundary
minute); every date-clock path — linter, publisher — keeps the
date-granular reading, which errs stale-earlier: the conservative
direction.

F1–F5 are complete. The audit table in §2 should be re-run against
the next OKF spec revision when one lands (the reference repo is
versioned; MEMORY records the audited commit — currently `ad30107` in
`GoogleCloudPlatform/open-knowledge-format`).

## 5. Why fidelity is the adoption lever

The spec's own ecosystem is the distribution channel this project does not
have to build: any consumer written against `okf/SPEC.md` — including the
reference implementation's own tooling — should consume an `ecommerce-geo`
bundle with zero special-casing. Every deviation above is friction in
exactly that path: D5 mis-times freshness for spec-faithful consumers, D12
hides the site binding from them, D13 breaks the attestation walkthrough in
§10.5, and D14 leaves our bundles signal-poor next to the reference
samples. Conversely, the profile's tightenings (risk gates, live-values,
GET-only capabilities) are invisible to base-spec consumers and cost
nothing. The plan therefore optimizes for: **read identically to the
reference bundles, verify more strictly than they require.**
