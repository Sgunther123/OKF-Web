---
type: Attested Computation
title: Warranty Claim Status Lookup
description: Returns the current status of a filed warranty claim, given the claim id and the access token from the claim confirmation email.
resource: https://www.alpinepeakoutfitters.example/api/v1/warranty-claim
tags: [capability, warranty, support, api]
status: stable
stale_after: 2028-02-01T00:00:00Z
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-16T09:08:47Z
verified:
  - by: human:platform-lead@alpinepeakoutfitters.example
    at: 2026-08-16T10:35:02Z
sources:
  - id: api-docs
    resource: https://www.alpinepeakoutfitters.example/developers/api
    title: Public storefront API documentation
    last_modified: 2026-08-01T00:00:00Z
x_geo:
  profile: ecommerce-geo/1.12
  risk: a
  intents: [capability, ownership]
  rate_limit: 30 requests/minute per client
  auth: claim-scoped token (from the claim confirmation email); no account login
runtime: http
parameters:
  - { name: claim_id, type: string, required: true }
  - { name: token, type: string, required: true }
executor:
  resource: https://www.alpinepeakoutfitters.example/api/v1/warranty-claim?claim_id={claim_id}&token={token}
  receipt: [claim_id, status, updated_at]
attester:
  resource: /attesters/http_refetch.py
---

# Purpose

Owners who have filed a warranty claim get a claim id and a
claim-scoped access token in the confirmation email; this lookup
returns the claim's current status without an account
login.[^api-docs] Filing the claim itself happens on the store's
warranty page — it changes state, so it is deliberately *not*
exposed as an executable capability; agents link owners there
instead.[^api-docs]

# Computation

```http
GET /api/v1/warranty-claim?claim_id={claim_id}&token={token}
Host: www.alpinepeakoutfitters.example
Accept: application/json
```

Example response:

```json
{
  "claim_id": "WC-20260-1187",
  "status": "awaiting_inspection",
  "updated_at": "2026-08-14T16:20:11Z"
}
```

Statuses: `received`, `awaiting_inspection`, `approved`,
`repair_in_progress`, `replacement_shipped`, `declined`.[^api-docs]

# Attestation

The endpoint is idempotent and read-only: verify a receipt by
re-executing the same lookup.[^api-docs] The token is scoped to one
claim and expires when the claim closes; agents should never ask an
owner for account credentials to check a claim.[^api-docs]

[^api-docs]: Public storefront API documentation.
