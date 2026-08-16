---
type: GEO Scorecard
title: Answerability evaluation — 2026-08-16
description: Machine-generated answerability scorecard for this bundle; see x_geo.metrics for the numbers.
tags: [evaluation, geo]
status: stable
stale_after: 2026-09-15
generated:
  by: okf-web-evaluator/claude-sonnet-5
  at: 2026-08-16T21:40:19Z
x_geo:
  profile: ecommerce-geo/1.5
  risk: c
  metrics:
    questions: 30
    retrieval_hit_rate: 1.0
    context_tokens_mean: 2162
    coverage: 0.933
    groundedness: 0.933
    citability: 0.9
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
  baseline:
    condition: raw site HTML (15 pages, same questions)
    context_tokens_mean: 41780
    coverage: 0.633
---

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

# Baseline comparison

Answering the same 30 questions from raw site HTML consumed a mean of
41,780 context tokens per question versus 2,162 from this bundle
(19× reduction) and covered 19/30 questions versus 28/30. The largest
raw-HTML failures were capability questions (no API surface is
described in page HTML), policy edge cases buried in accordion UI,
and fit questions needing facts joined across a PDF spec sheet and
the size guide. Care questions (own-1/own-2) were answerable from
the care page in both conditions; the claim-status lookup (own-3)
only from the bundle.
