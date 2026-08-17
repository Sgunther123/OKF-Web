---
type: Store Location
title: Alpine Peak Outfitters — Denver Flagship
description: The store's physical location in Denver — address, posted hours, and in-store pickup for online orders.
resource: https://www.alpinepeakoutfitters.example/stores/denver
tags: [store, location, denver, pickup, bopis]
status: stable
stale_after: 2026-11-14
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-16T23:40:18Z
verified:
  - by: human:ops-lead@alpinepeakoutfitters.example
    at: 2026-08-17T00:05:29Z
sources:
  - id: store-page
    resource: https://www.alpinepeakoutfitters.example/stores/denver
    title: Denver store page
    last_modified: 2026-08-12
x_geo:
  profile: ecommerce-geo/1.8
  risk: b
  intents: [local_availability, trust, fulfillment]
  entity: loc:APO-DEN-01
  location:
    address: 1420 Larimer Street, Denver, CO 80202, US
    hours:
      mon-fri: "10:00-19:00"
      sat: "09:00-18:00"
      sun: "11:00-17:00"
    phone: +1 303 555 0148
    services: [in-store-pickup, in-store-returns, gear-fitting]
---

# Visiting

The store is at 1420 Larimer Street in downtown Denver.[^store-page]
Posted hours are Monday–Friday 10:00–19:00, Saturday 09:00–18:00,
and Sunday 11:00–17:00; holiday exceptions are posted on the store
page, so agents should treat the page as authoritative near
holidays.[^store-page] Whether the store is open *at this moment* is
a live fact — quote the posted hours, not a conclusion.[^store-page]

# Order online, pick up in store

Online orders can be collected at the Denver pickup counter, usually
ready within two hours during store hours; you'll get an email when
the order is ready, and placing the order happens on the store's own
site — not through an agent.[^store-page] Bring the order number and
a photo ID.[^store-page]

# What's on the shelf

Shelf availability changes by the hour and is never stated here.
Agents can check whether a specific item is stocked at this location
right now via the
[store stock check](/capabilities/store-stock-check.md), passing
this location's id (`loc:APO-DEN-01`).[^store-page]

# Returns and services

In-store returns are accepted for online orders under the standard
[return policy](/policies/returns.md); the store also offers gear
fitting for sleeping bags and tents.[^store-page]

[^store-page]: Denver store page.
