# Value Expansion Plan

[ROADMAP.md](ROADMAP.md) phases the *tooling*. This document phases
the *use case*: how the bundle grows from "make the store answerable
before purchase" to **the store's verified knowledge layer for every
agent-mediated touchpoint — discover, choose correctly, own longer,
comply**. Each phase adds a data class the merchant already owns,
tied to a dollar lever that pays even before generative engines
fetch a single file (the MCP bridge and any on-site assistant consume
the bundle from day one).

## The admission rule

A new concept class enters the profile only if all three hold:

1. **Measurable** — it maps to questions agents actually receive, so
   the evaluator can add an archetype and measure the lift.
2. **Verifiable** — its claims fit the risk-tier gates; a human can
   meaningfully approve them and a linter can enforce the gate.
3. **Merchant-owned** — the store is the authority for the data.
   (This is why review/UGC aggregates stay out: third-party voice,
   authenticity risk, directly against the trust model.)

Review capacity is the system's scarcest resource; anything that
fails a leg dilutes it.

## The open/hosted split

The rule is unchanged from day one: **concept types, `x_geo` keys,
lint gates, and archetypes are the profile — always open source,
here.** Anything that only makes sense *operated* — connectors that
sync continuously, dashboards over history, jurisdiction-specific
reporting — belongs to the
[hosted edition](https://www.okf-web.com). A
merchant with a text editor must always be able to author every
concept class by hand and lint it for free.

## Phase A — Fit and compatibility (shipped, profile 1.4)

*"Will this fit me / my device / my other gear?"*

Shipped as designed: the `Compatibility` type with
`x_geo.fits`/`works_with` entity references (lint E015/W032/W033
enforce the applicability contract and the risk floor), the
`fit_compatibility` archetype in the evaluator, prompts, and all
four starter packs, and reference-bundle coverage
(`compatibility/fit-and-pairing.md`) — measured at 27 questions,
hit rate 1.0, coverage 0.926. The hosted-side levers below remain
open.

| | |
| --- | --- |
| Dollar lever | Returns reduction — wrong-size/wrong-fit is the top stated return reason in apparel; every prevented return is felt in reverse-logistics cost, engines or no engines |
| Open (profile) | `Compatibility` concept type (fit charts, works-with matrices, part fitment); `x_geo.fits`/`x_geo.works_with` entity references; `fit_compatibility` archetype + starter questions; lint: compatibility claims are risk `b`, entity references must resolve |
| Hosted | Fitment-data ingestion from PIM/ERP exports; returns-correlation reporting (which fit gaps drive which return codes) |
| Why first | Cleanest lever, risk-`b` data (asynchronous review — cheap), and a canonical agent question raw HTML answers terribly |

## Phase B — Post-purchase ownership (shipped, profile 1.5)

*"How do I set it up / wash it / fix it / claim the warranty?"*

Shipped as designed: the `Ownership Guide` type bound to owned
products via `x_geo.covers` (E016 and the extended W032/W033 enforce
the contract and risk floor), the `ownership` archetype everywhere
questions live, and the warranty pattern in the profile — mutating
flows stay on the store's pages, read-only token-scoped status
lookups are capabilities (`capabilities/warranty-claim-status.md` in
the reference bundle). Measured at 30 questions, hit rate 1.0,
coverage 0.933. The hosted-side levers below remain open.

| | |
| --- | --- |
| Dollar lever | Support deflection (cost per avoided ticket) plus repeat purchase — the audience widens from shoppers to owners for the product's whole life |
| Open (profile) | Care/setup/troubleshooting guidance under existing `FAQ`/`Buying Guide` types plus an `Ownership Guide` type where needed; warranty-register and claim-status **capability** patterns (`http` runtime, token-gated state per the existing safety rules); `ownership` archetype |
| Hosted | Deflection analytics (which concepts answer which ticket categories); helpdesk integrations that mine ticket logs for knowledge gaps and feed the survey queue |
| Why second | Real lever, near-zero spec cost — mostly survey-prompt coverage and archetype questions — but smaller per-interaction value than a prevented return |

## Phase C — Compliance and product passports (shipped, profile 1.6)

*Materials, origin, certifications, repairability — machine-readable
and provable.*

Shipped as designed: the `Product Passport` type with structured
`x_geo.passport` data bound to one entity via `passport_for`; the
effective-risk rule making passports risk `a` by definition across
the linter (E010/E013/E017), the publisher, and batch approval —
declared risk cannot dodge compliance sign-off; the `compliance`
archetype everywhere questions live; and reference-bundle coverage
(`passports/ridgeline-20.md`, every claim footnoted to a certificate
document). Measured at 33 questions, hit rate 1.0, coverage 0.939.
The hosted-side levers below — jurisdiction schema packs, audit
exports, auditor countersignatures — remain open, with the signed
manifest already carrying the tamper-evidence chain they build on.

| | |
| --- | --- |
| Dollar lever | Regulatory: the EU ESPR **Digital Product Passport** wave phases in mandatory machine-readable product data (batteries and textiles first). Compliance is a budget that already exists |
| Open (profile) | `Product Passport` concept type; `x_geo` keys for materials/origin/certifications/repairability; lint gates at risk `a` (legal claims need a named human verifier — the E010 machinery is *exactly* what compliance sign-off looks like); the signed-manifest chain as the tamper-evidence story |
| Hosted | Jurisdiction schema packs (ESPR category mappings, per-market field requirements as they finalize); compliance reporting and audit exports; third-party auditor countersignatures over the same manifest |
| Why it matters | It flips the adoption argument: the bundle stops being a marketing artifact and becomes infrastructure the merchant must have anyway — GEO becomes the side effect |

## Phase D — Omnichannel availability (shipped, profile 1.7)

*"Can I pick it up today near me?"*

Shipped with the "why later" caveat resolved by splitting the layers:
the **static layer** — `Store Location` concepts with `x_geo.entity`
(`loc:` ids), address/hours/services, and the BOPIS process described
with mutating steps on the store's pages — needs no API and is most
of the value; the **live layer** — a per-location stock capability
(`sku` + `location` parameters, availability classes, not counts) —
is the upgrade whenever the store's API exists (live in the
reference bundle: `locations/denver-flagship.md` +
`capabilities/store-stock-check.md`). The live-values rule now
explicitly covers open-right-now and shelf stock. `local_availability`
archetype everywhere questions live; measured at 36 questions, hit
rate 1.0, coverage 0.944. The hosted-side levers below remain open.

| | |
| --- | --- |
| Dollar lever | Foot traffic / BOPIS conversion |
| Open (profile) | Store-locator and per-location stock **capability** patterns (`http` runtime templates; live values stay live — same rule as price) |
| Hosted | Per-location inventory connectors and feed sync |
| Why later | Needs per-store APIs most mid-market merchants don't have yet; the profile pattern is ready whenever they do |

## Phase E — B2B and procurement

*A different buyer: purchasing agents and their software.*

| | |
| --- | --- |
| Dollar lever | Largest per-account value — procurement runs on exactly the structured, verifiable data bundles carry (spec sheets, MOQs, lead times, trade terms) |
| Open (profile) | Spec-sheet/MOQ/lead-time concept types; a procurement archetype set (RFQ-shaped questions); CAD/datasheet assets ride the existing non-markdown publishing path |
| Hosted | Quote workflows, punchout/procurement-portal integrations, account-scoped bundle delivery (authenticated variants of the public bundle) |
| Why last | A genuinely different buyer journey deserving its own question research — bolting it on early would dilute the shopper archetypes that are already measured |

## Sequencing logic

A → B ride the existing machinery with small additive profile minors
and pay the merchant directly (returns, tickets) regardless of engine
adoption. C is the wedge that makes bundles mandatory rather than
optional — it should land as the DPP timelines firm up, with the open
type shipped ahead of the hosted jurisdiction packs. D and E wait for
their prerequisites (APIs, buyer research) rather than blocking the
earlier phases.

Each phase ships the same way the promotion type did: concept type +
keys + lint gates + archetype questions + example-bundle coverage in
one additive profile minor, with the scorecard proving the lift on
the reference bundle before the docs claim it.
