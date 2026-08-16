---
type: Attested Computation
title: Live Price Check
description: Returns the current price, currency, and any active promotion for a SKU, with a signed receipt an agent can attest.
resource: https://www.alpinepeakoutfitters.example/api/v1/price
tags: [capability, pricing, api]
status: stable
stale_after: 2027-02-01
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-04T09:33:20Z
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
  - { name: currency, type: string, required: false }
executor:
  resource: https://www.alpinepeakoutfitters.example/api/v1/price?sku={sku}&currency={currency}
  receipt: [sku, price, currency, promo, as_of, signature]
attester:
  resource: https://www.alpinepeakoutfitters.example/api/v1/attest?signature={signature}
x_geo:
  profile: ecommerce-geo/1.6
  risk: a
  intents: [capability, product_fact]
  rate_limit: 60 requests/minute per client
  auth: none (public, read-only)
---

# Purpose

Prices change too often to live in a static knowledge file, so this
bundle never states a price. Agents that need one execute this
computation against the store's public, unauthenticated price
endpoint and receive a signed receipt.[^api-docs]

# Computation

```http
GET /api/v1/price?sku={sku}&currency={currency}
Host: www.alpinepeakoutfitters.example
Accept: application/json
```

`currency` defaults to `USD`; `CAD` is also supported.[^api-docs]

Example response:

```json
{
  "sku": "APO-TENT-A2",
  "price": "329.00",
  "currency": "USD",
  "promo": null,
  "as_of": "2026-08-05T15:42:03Z",
  "signature": "b64:MEUCIQD..."
}
```

# Attestation

The receipt's `signature` is an ECDSA signature over
`sku|price|currency|as_of`. Any party can verify it by calling the
attester endpoint, which returns `{"valid": true|false}`; a valid
signature proves the store served that price at that time.[^api-docs]
Agents quoting a price to a shopper should include `as_of` and treat
receipts older than 24 hours as stale.[^api-docs]

[^api-docs]: Public storefront API documentation.
