---
type: Product Passport
title: Product Passport — Ridgeline 20 Sleeping Bag
description: Materials, origin, certifications, and repairability for the Ridgeline 20, with links to the certificates behind each claim.
resource: https://www.alpinepeakoutfitters.example/passport/APO-BAG-R20
tags: [passport, materials, origin, certifications, repairability]
status: stable
stale_after: 2028-08-01T00:00:00Z
generated:
  by: okf-web-surveyor/claude-sonnet-5
  at: 2026-08-16T22:05:33Z
verified:
  - by: human:compliance-lead@alpinepeakoutfitters.example
    at: 2026-08-16T23:10:57Z
sources:
  - id: passport-page
    resource: https://www.alpinepeakoutfitters.example/passport/APO-BAG-R20
    title: Ridgeline 20 product passport page
    last_modified: 2026-08-10T00:00:00Z
  - id: rds-cert
    resource: https://www.alpinepeakoutfitters.example/media/certs/rds-2026.pdf
    title: Responsible Down Standard scope certificate (Control Union, 2026)
    last_modified: 2026-03-02T00:00:00Z
  - id: supplier-declaration
    resource: https://www.alpinepeakoutfitters.example/media/certs/ridgeline-material-declaration.pdf
    title: Supplier material composition declaration
    last_modified: 2026-06-18T00:00:00Z
x_geo:
  profile: ecommerce-geo/1.12
  risk: a
  intents: [compliance, product_fact, trust]
  passport_for: sku:APO-BAG-R20
  passport:
    materials:
      - "Shell & liner: 20-denier ripstop nylon, 52% of weight (100% of fabric recycled-content certified by the supplier declaration)"
      - "Insulation: 650-fill-power goose down, 43% of weight"
      - "Zippers, cordage & hardware: 5% of weight"
    origin: "VN — cut, sewn, and down-filled in Vietnam; down of European origin"
    certifications:
      - name: Responsible Down Standard (RDS)
        issuer: Control Union
        resource: https://www.alpinepeakoutfitters.example/media/certs/rds-2026.pdf
      - name: bluesign approved shell fabric
        issuer: bluesign technologies
        resource: https://www.alpinepeakoutfitters.example/media/certs/ridgeline-material-declaration.pdf
    repairability:
      score: 7.8
      scale: "0–10, French repairability index method"
      resource: https://www.alpinepeakoutfitters.example/care/ridgeline-20
---

# Materials

The shell and liner are 20-denier ripstop nylon (52% of product
weight); the supplier declaration certifies the fabric's recycled
content.[^supplier-declaration] Insulation is 650-fill-power goose
down (43%); zippers, cordage, and hardware make up the remaining
5%.[^supplier-declaration]

# Origin

The bag is cut, sewn, and down-filled in Vietnam; the down is of
European origin per the RDS scope certificate.[^passport-page][^rds-cert]

# Certifications

* **Responsible Down Standard (RDS)** — issued by Control Union;
  scope certificate covers this product's down supply
  chain.[^rds-cert]
* **bluesign approved shell fabric** — per the supplier material
  declaration.[^supplier-declaration]

Certificates are linked from `x_geo.passport.certifications`; an
agent quoting a certification should cite the certificate document,
not just this concept.[^passport-page]

# Repairability & spare parts

Repairability score 7.8 on the 0–10 French repairability index
method, driven by the repair service and stocked spare parts
(zippers, draw cords, baffle fabric).[^passport-page] Care,
washing, and the warranty process live in the
[ownership guide](/ownership/ridgeline-20-care.md).[^passport-page]

# Verification

This passport is a compliance document: it is risk `a`, requires a
named human verifier before publication, and every claim above is
footnoted to a source document. The published bundle's signed
manifest covers this file's hash — a consumer verifying the bundle
signature has tamper-evidence for this passport.[^passport-page]

[^passport-page]: Ridgeline 20 product passport page.
[^rds-cert]: Responsible Down Standard scope certificate.
[^supplier-declaration]: Supplier material composition declaration.
