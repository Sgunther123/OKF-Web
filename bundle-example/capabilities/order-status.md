---
type: Attested Computation
title: Order Status Lookup
description: Returns the fulfillment status of an order to a requester holding the order's access token.
resource: https://www.alpinepeakoutfitters.example/api/v1/orders
tags: [capability, orders, api]
status: stable
stale_after: 2027-02-01
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-04T09:36:02Z
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
  - { name: order_id, type: string, required: true }
  - { name: access_token, type: string, required: true }
executor:
  resource: https://www.alpinepeakoutfitters.example/api/v1/orders/{order_id}/status
  receipt: [order_id, status, carrier, tracking_url, as_of]
attester:
  resource: /attesters/http_refetch.py
x_geo:
  profile: ecommerce-geo/1.10
  risk: a
  intents: [capability, fulfillment, trust]
  rate_limit: 10 requests/minute per token
  auth: per-order access token from the confirmation email
---

# Purpose

Lets a shopper's agent answer "where is my order?" without screen
scraping. The endpoint returns nothing without the per-order access
token from the confirmation email, so the bundle exposes the
capability while the store's API enforces that only the order's owner
can use it.[^api-docs]

# Computation

```http
GET /api/v1/orders/{order_id}/status
Host: www.alpinepeakoutfitters.example
Authorization: Bearer {access_token}
Accept: application/json
```

Example response:

```json
{
  "order_id": "A2-118203",
  "status": "shipped",
  "carrier": "UPS",
  "tracking_url": "https://www.ups.com/track?tracknum=1Z...",
  "as_of": "2026-08-05T15:47:22Z"
}
```

`status` is one of `received`, `packing`, `shipped`, `delivered`,
`return_in_progress`, or `refunded`.[^api-docs]

# Privacy

Responses contain no name, address, or payment data — only
fulfillment state; the bundle itself never stores order
data.[^api-docs]

[^api-docs]: Public storefront API documentation.
