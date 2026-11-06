# Comproof roadmap

Phase 1 (released) covers text comparison for every packaging type with the Part 11 foundation. The phases
below follow the scope agreed for Comproof: all packaging materials, colour from every source, internal QA,
print houses, approvals and production-line checks, for EDA, SFDA, the UAE and Gulf, and EU / export markets.

## Phase 2 — Cartons, labels, foil and tubes in depth

- **Dielines and panels** — read the die-cut layer of the PDF, name panels (front, back, sides, flaps, glue
  area) and compare panel by panel; flag text crossing a fold or into the glue or bleed zone.
- **Barcodes and codes** — decode and grade GS1 DataMatrix, EAN-13 and QR (content, GTIN check digit, quiet
  zone, ISO/IEC 15415 / 15416 grade from scanner input); check the GTIN against the product record and the
  serialisation fields (batch, expiry, serial) against the market format.
- **Market rule packs** — required statements and their order per market (EDA, SFDA, UAE MOHAP / EDE, other
  GCC, EU QRD template); mandatory Arabic, price field, registration number, storage and pharmacovigilance
  contacts; Braille presence and translation (EU) and dot height / pitch from the artwork.
- **Font size checks** — minimum x-height / point size per market and per statement, from vector PDFs.
- **Images and symbols** — logos, pictograms, warning symbols and their position compared visually
  (perceptual hash and keypoint matching) alongside the text.
- **Version-to-version change review** — compare the new master with the previous master to produce the
  change list that the change control must explain.

## Phase 3 — Colour (ΔE)

- **Measurement sources** — spectrophotometer import (CxF3 and CGATS / IT8 text, X-Rite and Konica Minolta
  exports), PDF spot and process colours from the artwork, flatbed scans with a colour target
  (IT8.7/2 or ColorChecker) for calibrated L\*a\*b\*, phone or tablet photos for screening only, and
  *scan vs scan* (approved printed sample against new printed sample, both scanned on the same station).
- **Metrics** — ΔE2000 (default), ΔE76 and ΔE94, per patch and per named ink; tolerance per company, per
  customer and per ink (for example ΔE00 ≤ 2.0 for brand colours, ≤ 3.0 elsewhere), with pass / warn / fail.
- **Confidence by source** — spectro results are decisive; calibrated scans are indicative; phone photos never
  pass or fail on their own and are labelled *screening*.
- **Ink correction advisory** — for each failing ink, the direction of the error (lighter / darker,
  more / less red-green, yellow-blue, chroma and hue angle) with a plain suggestion to the printer (for example
  *reduce magenta slightly, increase density*), never an automatic recipe.
- **Colour report** — swatch pairs, ΔE table, a*b* plot per ink, and the same signature and audit controls.

## Phase 4 — Workflow and the print-house portal

- Supplier accounts limited to their own jobs: upload proofs, see findings marked for them, reply and
  re-submit; every round kept as a revision of the same comparison.
- Configurable routes: QA review → regulatory review → approval, with parallel or serial signers, due dates,
  reminders and escalation.
- Change-control links, comments on findings, and email notifications.
- Dashboards: first-pass yield per print house, findings by type, time to approval.

## Phase 5 — Production line checks

- **Tablet or phone camera station** — capture the printed item on the line with framing guides, check it
  against the effective master in seconds, show pass / stop, and sign the line clearance.
- **Flatbed scanner station** — fixed-resolution scans for the first-off and in-process checks, with the
  colour target for Phase 3.
- Batch and line linkage, first-off / in-process / last-off sampling plans, and an offline queue that syncs
  when the device reconnects.

## Engine improvements (continuous)

- AI reading on by default for scanned approved files once validated per provider.
- Table structure comparison (row / column aware) for SmPC tables.
- Visual diff overlay (pixel and edge difference) for vector-to-vector proofs.
- Learning from *not a deviation* decisions to propose company exclusion phrases (never applied silently).
