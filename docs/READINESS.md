# Adversarial readiness review

A deliberately hostile pass over the toolchain, asking three questions
it would be comfortable not to ask: does it actually do the job
(**suitability**), will anyone actually run it (**adoptability**), and
what would make either answer "no" (**everything below**).

**Verdict.** The machinery is in better shape than the market it aims
at. Every mechanical claim in the design held up under probing — a
5,000-product catalog surveys, lints, publishes and retrieves cleanly,
the live-values rule holds, the write gate holds, the risk gate holds.
The binding constraint is on the demand side and is not a code defect:
**no generative engine reads OKF bundles today**, OKF's own canonical
home has moved out from under this repo's spec audit, and the one
consumption path that works right now (MCP) reaches merchants and
agent developers rather than shoppers. Two findings are dated faults
that will break the build on a calendar tick. The remediation plan in
§4 is ordered accordingly: stop the clock, then make the toolchain
valuable to a merchant on day one *without* assuming any engine ever
shows up.

This document is a snapshot of a review, not a standing contract. Its
peer for spec conformance is [FIDELITY.md](FIDELITY.md); where the two
overlap, FIDELITY governs conformance and this file governs readiness.

## 1. Method

What was actually run, so the findings can be re-derived:

- **Scale probe.** A synthetic 5,000-product Merchant feed through the
  whole LLM-free path: `survey --feed` → `lint --strict` →
  `review batch-approve` → `publish`. Timings in A6.
- **Retrieval trials.** Question sets phrased two ways — naming the
  product, and describing it in a shopper's words — against both the
  lexical retriever and the hashing embedder, measuring hit@4.
- **Date-shifted lint.** `lint_bundle(bundle-example, today=…)` swept
  forward across the next six weeks. This is what surfaced A1.
- **Primary-source check on OKF itself.** The upstream spec repository
  and Google's own announcement, read directly rather than recalled.
  This is what surfaced A2 and A3.
- **Capability-execution probe.** What URLs `okf_execute` will fetch,
  and what the linter constrains about them (A4).

"Adversarial" here means: assume the docs are advocacy, assume the
happy path was the only path tested, and prefer a measurement to a
claim. Findings that turned out to be non-issues are recorded in §5
rather than dropped, because a reviewer's silence reads as an oversight.

## 2. Findings

| id | area | severity | finding |
| --- | --- | --- | --- |
| A1 | operations | **high, dated** | `lint --strict` starts failing on 2026-09-16 with no code change; CI goes red |
| A2 | spec fidelity | **high** | The audited spec location is a frozen snapshot; OKF's canonical home moved |
| A3 | adoption | **high, strategic** | No engine consumes OKF bundles today; the consumption convention is ours alone |
| A4 | security | medium-high | `okf_execute` fetches any host a bundle declares; nothing constrains it |
| A5 | adoption | medium | First publish yields an empty bundle; the sanctioned unblock dilutes the trust signal |
| A6 | scale | medium | Every command re-parses the whole bundle; ~7.4 s at 5,000 concepts |
| A7 | suitability | medium | Lexical retrieval misses roughly a quarter of synonym-phrased questions |
| A8 | adoption | medium, strategic | Nothing is emitted in the formats engines read *today* |
| A9 | distribution | medium | Not on PyPI, not listed anywhere; discovery path is word of mouth |

### A1 — A dated CI failure, twenty days out

`bundle-example/evaluations/geo-scorecard.md` carries
`stale_after: 2026-09-16`. The linter's staleness rule
(`src/okf_web/linter.py:486`) fires W021 once `today >= stale_after`,
and `cmd_lint` exits non-zero when `--strict` is set and any warning is
present (`src/okf_web/cli.py:94`). CI runs exactly that command with
the real date (`.github/workflows/ci.yml`, "okf-web lint bundle-example
--strict").

Swept forward, the example bundle lints 0 errors / 0 warnings today and
0 errors / **1 warning** from 2026-09-16 onward. The test suite does
*not* catch this — `tests/test_linter.py:5` pins `TODAY = 2026-08-05`,
which is correct for testing the rule but means the pinned tests stay
green while the real-date CI step turns red.

This is a fuse, not a bug: the code is right, the fixture expired. It
matters because the repository's central claim to a newcomer is "the
example bundle lints clean," and it will stop being true on a date
nobody is watching for.

### A2 — The spec audit is pinned to a frozen snapshot

`FIDELITY.md` audits against `okf/SPEC.md` in
`GoogleCloudPlatform/knowledge-catalog`. That location is no longer the
specification's home. Its own README now says, verbatim:

> Stop using the copy under `okf/` in this repository. It is a frozen
> snapshot, no longer maintained, and anything built against it will
> drift out of date.

The canonical home is `GoogleCloudPlatform/open-knowledge-format`
(still v0.2 at the time of review). Five files in this repo point at
the dead location — `README.md`, `docs/FIDELITY.md`,
`docs/GEO-PROFILE.md`, `docs/DESIGN.md`, and `.claude/MEMORY.md`.

The immediate consequence is modest (v0.2 is v0.2, so conformance
conclusions stand) and the eventual one is not: the standing audit
watches a file that will never change again, so the next revision of
OKF lands without anything here noticing. A project whose stated
invariant is "spec fidelity is audited, not assumed" cannot have its
audit aimed at a tombstone.

### A3 — Nothing reads the bundles yet, and the convention is ours

This is the finding that reorders the roadmap.

OKF is real and Google-published, but its framing is **enterprise agent
knowledge**: giving agents governed access to an organization's own
knowledge assets. Neither the specification nor Google's launch
material describes websites publishing bundles for search or shopping
engines to crawl. There is no `/.well-known/okf/` convention in the
spec, no engine that fetches one, and no published statement from any
engine vendor that OKF influences generative answers.

Everything this project builds on top of that base — the
`/.well-known/okf/` location, the two-way site binding, the
`ecommerce-geo` profile, the whole premise that publishing a bundle
improves how engines answer about a store — is **this project's own
construction**. That is not a defect (profiles are the spec's own
extension mechanism, and building the ecommerce convention first is a
legitimate bet), but it must be stated plainly in the project's own
documentation, because a merchant reading the README today could
reasonably conclude engines are already consuming this.

The practical consequence: the merchant-visible value of a published
bundle is, today, **zero engine fetches**. The MCP bridge is the only
working consumption path — and the realistic MCP audience is the
merchant's own team and agent developers, not shoppers, because a
shopper does not mount a store's MCP server. Anything downstream that
depends on engines consuming bundles (including efficacy-contingent
billing in the hosted edition) is waiting on an event outside this
project's control that has not begun.

### A4 — `okf_execute` will fetch anything the bundle declares

`_tool_execute` (`src/okf_web/mcp_bridge.py:172`) validates carefully
in every direction except one: it requires the concept to be an
`http`-runtime Attested Computation, requires an `http(s)` scheme,
fills only declared parameters, URL-quotes them, and refuses leftover
placeholders anywhere in the URL. It then calls `state.http_get(url)`
(`:213`) against whatever host the bundle named. There is no allowlist,
no private-range rejection, and the linter constrains only that
`executor.resource` *exists* (`src/okf_web/linter.py:196`), never where
it points.

Mounting a bundle is a deliberate act, so this is not a drive-by
vulnerability. It becomes one the moment a bundle is fetched rather
than chosen — precisely what the planned `okf-web mcp --url`
remote-bundle mode would introduce. A hostile bundle could declare a
capability aimed at `169.254.169.254` or `localhost`, and an assistant
would dutifully GET it from inside the user's network.

The fix is small and belongs in place *before* remote bundles exist,
not after: a linter warning for capability endpoints outside the
bundle's declared site, and a bridge-level refusal of loopback,
link-local and private ranges with an explicit opt-out for merchants
testing against their own dev host.

### A5 — The first publish ships nothing, and the unblock is a rubber stamp

Walk a new merchant's happy path with a real catalog. `survey --feed`
drafts 5,000 Product concepts. Every one lands as an unverified draft
by design, and the publisher withholds drafts. So the first
`publish` emits a bundle containing **no products** — correct
behavior, and a bewildering first impression.

The documented unblock is `review batch-approve`, which cleared all
5,000 drafts in 16 seconds, stamping each `verified: human:<id>`. The
risk-`a` floor holds (high-risk concepts are excluded and still require
individual approval), so the safety invariant is intact. But the trust
tier that the entire design sells — "a named human checked this" — is,
for the bulk catalog tier, produced by one person typing one command.

Both halves are defensible in isolation and corrosive together: the
gate is what makes the bundle trustworthy, and the documented way past
the gate is a single keystroke. The honest resolution is not to remove
batch-approve (feed-derived facts genuinely are mechanical) but to stop
calling its output the same thing as human review — a distinct actor
prefix for bulk attestation, surfaced in the scorecard, tells the truth
without slowing anyone down.

### A6 — Every command pays for the whole bundle

`load_bundle` parses every concept file on every invocation. Measured
on the 5,000-product bundle: feed ingest 8 s, `lint --strict` 6.8 s,
`batch-approve` 16 s, `publish` 15 s (23 MB, 5,001 files), and a fixed
~7.4 s load tax before *any* command does its own work. Extrapolated
linearly, a 50,000-SKU catalog pays ~75 s per command.

Nothing here is pathological — the ingest path was already made
single-load, and 5,000 products is a real store — but the cost is
per-invocation and unavoidable, which makes routine operations (a
nightly drift sweep, a CI lint) scale with catalog size rather than
with change size. `okf_search` similarly costs ~200 ms per query with
no inverted index, which is fine for an assistant and not fine for a
site-embedded search box.

### A7 — Retrieval is lexical, and shoppers are not

Retrieval hit@4 was 1.000 when questions named the product and 0.995
for the hashing embedder — excellent, and also the easy case. Phrased
the way a shopper actually asks ("something warm enough for freezing
nights" rather than the product name), roughly a quarter of questions
missed: 9–10 of 12 in the trials.

This is honest by construction and documented as such —
`src/okf_web/retrieval.py:13` says the hashing embedder's "quality is
roughly lexical (it cannot know synonyms)" — and the real semantic
path (`VoyageClient`) exists behind an optional dependency and an API
key. The finding is not that the code is wrong; it is that the
**default** experience is the lexical one, the scorecard's headline
1.0 hit rate is measured on curated questions that share vocabulary
with the bundle, and a merchant will therefore see a better number
than their shoppers will experience. A scorecard that reported both
phrasings would be measuring the thing that matters.

### A8 — Nothing is emitted in the formats engines read today

`publish` emits the bundle, `manifest.json`, `linkmap.json`, and
`llms-snippet.txt`. That last one is a *pointer* — blocks to paste into
`llms.txt` telling agents the bundle exists. Useful, and still
predicated on an agent that knows what to do with an OKF bundle.

Meanwhile the formats engines demonstrably do consume — schema.org
JSON-LD above all — get no emission at all. `DESIGN.md:24` dismisses
them on the merits ("thin (a few typed fields), says nothing about
provenance or freshness, and cannot express 'here is how to check the
live price'"), and the critique is correct. It is also beside the
point: thin-and-read beats rich-and-unread every day of the week, and
the bundle already contains everything needed to generate the thin
version for free.

This is the single highest-leverage gap in the repository. The bundle
is a *verified, provenance-tracked source of truth*; emitting
derivative JSON-LD from it costs one module and turns "publish a bundle
no one reads yet" into "publish a bundle *and* the structured data
engines already use, both generated from facts a human verified."
Adoption stops being a bet on OKF's future and becomes immediate.

### A9 — Nobody can find it

The package is not on PyPI (release is deliberately user-gated —
`DISTRIBUTION.md` §6), so the README's `pip install -e .` is a clone
away from working, and the plan's MCP directory listings are unfiled.
The discovery path for a merchant who has never heard of this is
currently: hear about it from a person.

That is the expected state for an unreleased project and is listed
here only so the sequencing in §4 accounts for it: R2's work is what
makes a listing worth filing, so listing first would spend the
first-impression on the weakest version of the pitch.

## 3. What the review did not shake

Recorded so that silence is not mistaken for oversight. Each of these
was probed adversarially and held:

- **The live-values rule.** Feed money fields never reach concept text
  or the row hash, including the token-backstop cases
  (`wholesale_price_usd` and friends). No leak found by grep or by
  round-trip through the 5,000-product bundle.
- **The write gate.** Every pipeline write goes through
  `place_draft`; collision handling and human-approval protection held
  under bulk ingest.
- **The risk gate.** E010 refused to publish an unapproved risk-`a`
  draft in every configuration tried, including through
  `batch-approve` (which correctly excludes the high-risk tier).
- **Determinism.** Repeated runs produced byte-identical hashes and
  stable rankings; no `hash()` usage, no ordering nondeterminism
  surfaced across doubled test runs.
- **The MCP bridge's read-only posture.** GET-only, no argument
  splicing, placeholder refusal across the whole URL. A4 is about
  *where* it may fetch, not *what* it may do.
- **Spec conformance.** Nothing in this pass contradicted
  FIDELITY.md's audit; A2 is about where the audit points, not what it
  concluded.

## 4. Remediation plan

Four phases, ordered by "what breaks if we do nothing" rather than by
ambition. R1 is same-day. R2 is the one that changes the project's
odds.

### R1 — Stop the clock (same day, no design change)

Closes: **A1, A2**, and the cheap half of **A4**.

1. **Defuse the dated lint failure.** Re-measure the example bundle's
   scorecard and re-stamp its `stale_after`, then make the fuse
   impossible to re-arm silently: add a test that lints the example
   bundle at `today = <release date + 1 year>` and asserts warning-free,
   so an expiring fixture fails in `pytest` (pinned, deterministic)
   rather than in CI on a date nobody chose. Never hand-edit the
   measured numbers — re-run the evaluation and take what it says.
2. **Re-point the spec audit.** Update the five files carrying the
   frozen-snapshot URL to `GoogleCloudPlatform/open-knowledge-format`,
   re-audit FIDELITY §2 against that repository's current SPEC.md, and
   record the new reference commit. Add the canonical-home URL to
   MEMORY so the next session audits the live document.
3. **Constrain capability endpoints.** Add a linter warning when an
   Attested Computation's `executor.resource` host lies outside the
   bundle's declared `x_geo.site` domain, and refuse loopback,
   link-local and private-range hosts in the bridge unless an explicit
   `--allow-private-hosts` flag is passed. Both are additive and
   neither changes a conformant bundle's lint result.

Exit: `lint --strict` clean at any plausible future date; FIDELITY
aimed at the living spec; no capability can point somewhere surprising
without saying so.

### R2 — Value that does not wait for engines (the pivot)

Closes: **A8**, materially mitigates **A3**, sets up **A5** and **A7**.

The premise: a merchant must get something worth having on day one,
from a bundle no engine has ever fetched. Three deliverables, in order
of leverage.

1. **Emit what engines read today.** A `publish`-time emitter that
   derives schema.org JSON-LD from the verified bundle — `Product`,
   `Offer` (pointing at the capability endpoint rather than stating a
   price), `FAQPage`, `Store`/`LocalBusiness`, `Return­Policy` — plus a
   real `llms.txt` body rather than only a pointer. One module, no new
   dependencies, generated exclusively from human-verified concepts so
   the provenance story survives the downgrade. This converts the
   entire existing corpus into value that lands against today's
   engines, and reframes OKF adoption from precondition to upside.
2. **Make the scorecard the product.** The evaluation already answers
   the question every merchant is actually asking — *can an AI answer
   my shoppers' questions?* — and already carries the raw-HTML baseline
   that quantifies the lift. Give it a standalone, shareable rendering
   (`okf-web report`) that a non-technical owner can read: what your
   site cannot answer, what a bundle fixes, what it costs. This is the
   artifact that sells the toolchain, and it works with zero engine
   adoption.
3. **State the adoption position honestly.** A short section in README
   and DESIGN saying what OKF is (Google-published, enterprise-framed),
   what this project added (the web/ecommerce convention, the profile,
   the discovery binding), and what is not yet true (no engine
   consumption today). Credibility is an adoption asset; a reader who
   discovers A3 themselves stops trusting the rest of the claims.

Exit: a merchant who installs this, publishes, and is never fetched by
a single engine still has (a) structured data on their site that
current engines use, (b) a report showing measured answerability lift,
and (c) an MCP endpoint their own team can query.

### R3 — Honest defaults and a shorter first run

Closes: **A5, A7**; unblocks **A9**.

1. **Distinguish bulk attestation from human review.** A separate
   actor prefix (and trust tier) for `batch-approve`, surfaced in the
   scorecard and the published concept, so "5,000 mechanically ingested
   facts" and "a person read this" stop sharing a label. Keep
   batch-approve exactly as fast.
2. **Report the phrasing gap.** Add a paraphrased question variant to
   the evaluation (or a second scorecard column) so the headline hit
   rate reflects shopper vocabulary, not curated vocabulary. If the
   number drops, that is the finding — it is what a merchant's
   customers will experience, and it is the argument for the semantic
   retriever.
3. **Cut the first run to one command.** A guided `okf-web init` that
   takes a store URL or a feed, runs ingest → lint → batch-approve
   (with the new tier) → publish → report, and ends by printing the
   report path and the MCP config block. The USER-GUIDE's "no
   programming background needed" claim should be true of a single
   command, not of a nine-command sequence.

Exit: a first run is one command and a few minutes; the numbers a
merchant sees are the numbers their shoppers will get.

### R4 — Scale headroom (deferrable, and honest about it)

Closes: **A6**.

Only worth building when a real catalog demands it, and listed so the
ceiling is a known quantity rather than a surprise: a concept-level
parse cache keyed by mtime+size to kill the fixed load tax, an
inverted index for `okf_search`, and streaming publish so memory does
not track catalog size. Until a tenant with 50,000 SKUs exists, the
correct action is to document the measured ceiling (§A6) in
DESIGN.md's efficiency budget and move on.

## 5. Sequencing note

R1 before anything else, because it is dated. R2 before R3, because
R3's polish is wasted on a proposition that has not been fixed. R2
before **any** distribution push (A9) — PyPI registration, MCP
directory listings, and the first outreach all spend a
first-impression, and the version of this project that arrives after
R2 is a categorically stronger pitch than the one that arrives before
it. R4 on demand.

The hosted edition's commercial readiness is reviewed separately, in
that repository; its central finding depends on **A3** and is
sequenced behind R2 for the same reason.
