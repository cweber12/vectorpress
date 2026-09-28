# 0008 — Collection = membership, Product = presentation; publication is a declared snapshot; previews are HTML

Status: accepted (previews amended by 0014, 0015; exporters by 0017)
Date: 2026-09-22

## Decision

**Collections and products.**
- A collection is a membership: explicit list, metadata rule, union of other
  collections, or a mix. Not sellable.
- A product is exactly one collection (or an inline one) plus derivative types,
  formats, reference size override, listing, price, publication state. Only products
  are built. Tier and family are labels.

**Publication.**
- `publish` records a snapshot (timestamp, manifest, free-text marketplace refs). The
  tool knows no marketplace APIs.
- Published products are frozen; rule changes become proposed updates (§12.1).
  Rebuilds may add or improve, never remove relative to any prior snapshot (§23.1).
- Marketplace export = file-only exporters (generic JSON/CSV + per-marketplace text
  bundles enforcing known limits). Copy-paste is the integration.

**Previews.**
- HTML/CSS Jinja templates rendered headlessly with Playwright; brand config becomes
  CSS variables. Templates ship with the tool; the catalog may override.
- Previews are build output with **no approval status**.

## Consequences

- The same membership sells as several products with different derivative types,
  which §10 requires.
- Mega bundles are products over union collections.
- Brand consistency (§17) is a stylesheet change, not a code change.
