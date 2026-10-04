---
type: Attested Computation
title: Store Shelf Stock Check
description: Returns whether a SKU is currently stocked at a specific physical store location, as an availability class rather than a count.
resource: https://www.alpinepeakoutfitters.example/api/v1/store-stock
tags: [capability, stock, stores, pickup, api]
status: stable
stale_after: 2028-02-01T00:00:00Z
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-16T23:44:51Z
verified:
  - by: human:platform-lead@alpinepeakoutfitters.example
    at: 2026-08-17T00:08:13Z
sources:
  - id: api-docs
    resource: https://www.alpinepeakoutfitters.example/developers/api
    title: Public storefront API documentation
    last_modified: 2026-08-01T00:00:00Z
x_geo:
  profile: ecommerce-geo/1.12
  risk: a
  intents: [capability, local_availability]
  rate_limit: 60 requests/minute per client
  auth: none (public, read-only)
runtime: http
parameters:
  - { name: sku, type: string, required: true }
  - { name: location, type: string, required: true }
executor:
  resource: https://www.alpinepeakoutfitters.example/api/v1/store-stock?sku={sku}&location={location}
  receipt: [sku, location, availability, as_of]
attester:
  resource: /attesters/http_refetch.py
---

# Purpose

Shelf stock at a physical store changes by the hour, so it is never
stored in this bundle. Agents answering "is it in the store right
now?" execute this lookup instead of quoting anything
static.[^api-docs] `location` takes a location entity id from a
[Store Location](/locations/denver-flagship.md) concept, e.g.
`loc:APO-DEN-01`.[^api-docs]

# Computation

```http
GET /api/v1/store-stock?sku={sku}&location={location}
Host: www.alpinepeakoutfitters.example
Accept: application/json
```

Example response:

```json
{
  "sku": "APO-TENT-A2",
  "location": "loc:APO-DEN-01",
  "availability": "in_stock",
  "as_of": "2026-08-16T23:50:07Z"
}
```

`availability` is a class, not a count: `in_stock`, `low_stock`, or
`out_of_stock` — the store deliberately does not expose shelf
quantities.[^api-docs]

# Attestation

The endpoint is idempotent and read-only: verify a receipt by
re-executing the same lookup.[^api-docs] Agents quoting availability
to a shopper should include `as_of` and treat responses older than
one hour as stale — shelf stock moves faster than warehouse
stock.[^api-docs]

[^api-docs]: Public storefront API documentation.
