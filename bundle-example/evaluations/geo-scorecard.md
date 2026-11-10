---
type: GEO Scorecard
title: Answerability evaluation — 2026-08-17
description: Example answerability scorecard for the fictional store; its judged figures were written with the example, not measured (see the note in the body).
tags: [evaluation, geo]
status: stable
stale_after: 2027-09-16T00:00:00Z
generated:
  by: okf-web-evaluator/claude-sonnet-5
  at: 2026-08-17T00:20:44Z
x_geo:
  profile: ecommerce-geo/1.13
  risk: c
  metrics:
    questions: 39
    retrieval_hit_rate: 1.0
    context_tokens_mean: 2407
    coverage: 0.949
    groundedness: 0.949
    citability: 0.923
    freshness: 1.0
    by_archetype:
      discovery: { questions: 3, answered: 3 }
      product_fact: { questions: 3, answered: 3 }
      comparison: { questions: 3, answered: 3 }
      policy: { questions: 3, answered: 2 }
      fulfillment: { questions: 3, answered: 3 }
      trust: { questions: 3, answered: 3 }
      capability: { questions: 3, answered: 2 }
      promotion: { questions: 3, answered: 3 }
      fit_compatibility: { questions: 3, answered: 3 }
      ownership: { questions: 3, answered: 3 }
      compliance: { questions: 3, answered: 3 }
      local_availability: { questions: 3, answered: 3 }
      procurement: { questions: 3, answered: 3 }
---

This scorecard belongs to the fictional example store and shows what a
judged scorecard contains. Its retrieval figures are reproduced by
`okf-web evaluate bundle-example --dry-run`. Its judged figures
(coverage, groundedness, citability and the verdicts below) were
written with the example and are not the record of a run. It carries
no comparison with the store's own pages: a fictional store has none
to read. On a real store, `okf-web evaluate --baseline` measures one.

# Results

| id | archetype | retrieved | answered | cited |
| --- | --- | --- | --- | --- |
| disc-1 | discovery | 4 | yes | /catalog/products/alpine-2-tent.md, /catalog/tents.md |
| disc-2 | discovery | 4 | yes | /catalog/products/ridgeline-20-sleeping-bag.md |
| disc-3 | discovery | 4 | yes | /catalog/tents.md |
| fact-1 | product_fact | 4 | yes | /catalog/products/alpine-2-tent.md |
| fact-2 | product_fact | 4 | yes | /catalog/products/ridgeline-20-sleeping-bag.md |
| fact-3 | product_fact | 4 | yes | /catalog/products/alpine-2-tent.md |
| comp-1 | comparison | 4 | yes | /guides/tent-buying-guide.md, /catalog/products/alpine-2-tent.md |
| comp-2 | comparison | 4 | yes | /guides/tent-buying-guide.md |
| comp-3 | comparison | 4 | yes | /catalog/products/ridgeline-20-sleeping-bag.md, /faq/general.md |
| pol-1 | policy | 4 | yes | /policies/returns.md |
| pol-2 | policy | 4 | yes | /policies/returns.md |
| pol-3 | policy | 4 | no | — |
| ful-1 | fulfillment | 4 | yes | /policies/shipping.md |
| ful-2 | fulfillment | 4 | yes | /policies/shipping.md |
| ful-3 | fulfillment | 4 | yes | /policies/shipping.md |
| tru-1 | trust | 4 | yes | /store.md |
| tru-2 | trust | 4 | yes | /faq/general.md |
| tru-3 | trust | 4 | yes | /faq/general.md |
| cap-1 | capability | 4 | yes | /capabilities/price-check.md |
| cap-2 | capability | 4 | yes | /capabilities/stock-check.md |
| cap-3 | capability | 4 | no | — |
| promo-1 | promotion | 4 | yes | /promotions/fall-clearance.md |
| promo-2 | promotion | 4 | yes | /promotions/fall-clearance.md |
| promo-3 | promotion | 4 | yes | /promotions/fall-clearance.md |
| fit-1 | fit_compatibility | 4 | yes | /compatibility/fit-and-pairing.md |
| fit-2 | fit_compatibility | 4 | yes | /compatibility/fit-and-pairing.md, /catalog/products/alpine-2-tent.md |
| fit-3 | fit_compatibility | 4 | yes | /compatibility/fit-and-pairing.md |
| own-1 | ownership | 4 | yes | /ownership/ridgeline-20-care.md |
| own-2 | ownership | 4 | yes | /ownership/ridgeline-20-care.md |
| own-3 | ownership | 4 | yes | /ownership/ridgeline-20-care.md, /capabilities/warranty-claim-status.md |
| pass-1 | compliance | 4 | yes | /passports/ridgeline-20.md |
| pass-2 | compliance | 4 | yes | /passports/ridgeline-20.md |
| pass-3 | compliance | 4 | yes | /passports/ridgeline-20.md, /ownership/ridgeline-20-care.md |
| loc-1 | local_availability | 4 | yes | /locations/denver-flagship.md |
| loc-2 | local_availability | 4 | yes | /locations/denver-flagship.md |
| loc-3 | local_availability | 4 | yes | /locations/denver-flagship.md, /capabilities/store-stock-check.md |
| rfq-1 | procurement | 4 | yes | /trade/wholesale-program.md |
| rfq-2 | procurement | 4 | yes | /trade/wholesale-program.md |
| rfq-3 | procurement | 4 | yes | /trade/wholesale-program.md, /catalog/products/ridgeline-20-sleeping-bag.md |

Note on disc-3: the bundle answers correctly that the store does
*not* sell four-season tents — an explicit negative sourced from
/catalog/tents.md, which prevents generative engines from guessing.

# Knowledge gaps

* `pol-3` (policy): What warranty does the store offer on its own-brand
  gear? — /policies/warranty.md exists but is a draft withheld from
  publication pending legal review; the published bundle cannot answer.
* `cap-3` (capability): Order-status lookup was retrieved but the
  judge marked the answer incomplete: the concept does not say where in
  the confirmation email the access token lives. Suggested fix queued
  for the next survey pass.
