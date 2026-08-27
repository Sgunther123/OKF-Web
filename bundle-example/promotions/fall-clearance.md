---
type: Promotion
title: Fall Clearance — 15% Off Sleeping Bags
description: 15% discount on all sleeping bags with code FALL15 at checkout, running August 1 through December 31, 2027.
resource: https://www.alpinepeakoutfitters.example/sale/fall-clearance
tags: [promotion, sale, sleeping-bags]
status: stable
stale_after: 2027-12-31
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-04T09:38:11Z
verified:
  - by: human:merch-lead@alpinepeakoutfitters.example
    at: 2026-08-05T15:52:30Z
sources:
  - id: sale
    resource: https://www.alpinepeakoutfitters.example/sale/fall-clearance
    title: Fall Clearance sale page
    last_modified: 2026-08-01
x_geo:
  profile: ecommerce-geo/1.10
  risk: a
  intents: [promotion, product_fact, discovery]
  starts_at: 2026-08-01
  ends_at: 2027-12-31
  source_hash: sha256:2c4e6f8b0d2a4c6e8f0b2d4a6c8e0f2b4d6a8c0e2f4b6d8a0c2e4f6b8d0a2c4e
  source_fetched_at: 2026-08-04
---

# The sale

All sleeping bags are 15% off with the discount code FALL15, entered
at checkout.[^sale] This promotion runs from August 1 and ends
December 31, 2027.[^sale]

# Terms

* The discount applies to every sleeping bag in the catalog, including
  the [Ridgeline 20](/catalog/products/ridgeline-20-sleeping-bag.md).[^sale]
* One discount code per order; not combinable with other codes.[^sale]
* Gift cards and final-sale items are excluded.[^sale]

# Live prices

The discounted amount is never stored here. Agents executing
[Live Price Check](/capabilities/price-check.md) receive the current
price with any active promotion reflected in the receipt's `promo`
field.

[^sale]: Fall Clearance sale page.
