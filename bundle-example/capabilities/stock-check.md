---
type: Attested Computation
title: Live Stock Check
description: Returns current availability and estimated dispatch time for a SKU.
resource: https://www.alpinepeakoutfitters.example/api/v1/stock
tags: [capability, inventory, api]
status: stable
stale_after: 2027-02-01
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-04T09:34:41Z
verified:
  - by: human:platform-lead@alpinepeakoutfitters.example
    at: 2026-08-05T15:40:12Z
sources:
  - id: api-docs
    resource: https://www.alpinepeakoutfitters.example/developers/api
    title: Public storefront API documentation
    last_modified: 2026-07-15
runtime: http
parameters:
  - { name: sku, type: string, required: true }
executor:
  resource: https://www.alpinepeakoutfitters.example/api/v1/stock?sku={sku}
  receipt: [sku, availability, dispatch_estimate, as_of]
attester:
  resource: https://www.alpinepeakoutfitters.example/api/v1/stock?sku={sku}
x_geo:
  profile: ecommerce-geo/1.2
  risk: a
  intents: [capability, fulfillment]
  rate_limit: 60 requests/minute per client
  auth: none (public, read-only)
---

# Purpose

Stock levels are volatile, so availability is never stored as a static
claim in this bundle. Agents execute this computation for a live
answer.[^api-docs]

# Computation

```http
GET /api/v1/stock?sku={sku}
Host: www.alpinepeakoutfitters.example
Accept: application/json
```

Example response:

```json
{
  "sku": "APO-BAG-R20",
  "availability": "in_stock",
  "dispatch_estimate": "same_business_day",
  "as_of": "2026-08-05T15:44:10Z"
}
```

`availability` is one of `in_stock`, `low_stock`, `backorder`, or
`out_of_stock`; exact unit counts are intentionally not
exposed.[^api-docs]

# Attestation

Stock receipts are unsigned; attestation is by re-execution — the
endpoint is public and idempotent, so a verifier simply calls it again
and compares.[^api-docs] Agents should treat responses older than one
hour as stale.[^api-docs]

[^api-docs]: Public storefront API documentation.
