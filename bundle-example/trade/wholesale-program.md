---
type: Trade Program
title: Alpine Peak Trade — Wholesale Program
description: Who qualifies for wholesale, the opening-order minimum, payment terms, lead times, and how to request a quote.
resource: https://www.alpinepeakoutfitters.example/trade
tags: [wholesale, trade, b2b, procurement]
status: stable
stale_after: 2028-02-01T00:00:00Z
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-17T01:12:40Z
verified:
  - by: human:sales-lead@alpinepeakoutfitters.example
    at: 2026-08-17T02:01:15Z
sources:
  - id: trade-page
    resource: https://www.alpinepeakoutfitters.example/trade
    title: Trade program page
    last_modified: 2026-08-05T00:00:00Z
x_geo:
  profile: ecommerce-geo/1.11
  risk: a
  intents: [procurement, trust, fulfillment]
  trade:
    payment_terms: "First order prepaid; Net 30 after credit approval"
    min_order: "USD 1,000 opening order; USD 500 reorders"
    lead_time: "In-stock gear ships in 5-10 business days; 4-6 weeks for volume beyond stock"
---

# Who qualifies

The trade program serves guide services, outdoor-education programs,
and specialty retailers; a resale certificate (or program
documentation for non-resale institutional buyers) is required at
application.[^trade-page]

# Terms

* Opening order minimum USD 1,000; reorders USD 500.[^trade-page]
* First order prepaid; Net 30 terms after credit
  approval.[^trade-page]
* In-stock gear ships in 5–10 business days; volume beyond stock is
  4–6 weeks.[^trade-page]
* Quotes are valid for 30 days from issue.[^trade-page]

# Prices are quoted, never published

Wholesale pricing is quoted per request and is not stated here or
anywhere in this bundle — a published wholesale price would be wrong
the day the tier changes.[^trade-page] Agents helping a buyer should
gather quantities and dates, then direct the buyer to the quote
request below.

# Applying and requesting quotes

Applications and quote requests happen on the store's trade page —
both change account state, so they are done by the buyer there, not
by an agent.[^trade-page] Quotes arrive by email with a reference
number the buyer can use with the sales team.[^trade-page]

# Per-product trade facts

Case packs, per-SKU minimums, and lead times appear on product
concepts under `x_geo.procurement` where stated — see the
[Ridgeline 20](/catalog/products/ridgeline-20-sleeping-bag.md) for
an example.[^trade-page]

[^trade-page]: Trade program page.
