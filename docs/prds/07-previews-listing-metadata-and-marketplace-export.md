# PRD 7 — Previews, Listing Metadata, and Marketplace Export

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Each built product has marketplace-ready preview images, an authoritative
listing record, and per-marketplace export files.

**Scope.**
- Preview types from §16 (main, included assets, file formats, variants, contents
  overview), rendered from templates driven by brand config (§17, §27).
- Templates ship with the tool; a catalog can override any template.
- Previews are regenerated on every build, are output not state, and have no approval
  status.
- Listing metadata (§18): drafted once from templates and asset metadata into the
  product's hand-authored file on first build, then user-owned.
- Exporters (§19): a generic structured export and per-marketplace text bundles
  (Etsy, Creative Fabrica, Design Bundles, direct store) that enforce known field
  limits.

**Out of scope.** Physical product mockups (§16, future), publication.

**Acceptance.** User can build a product and get consistent preview images, a listing
record, and marketplace files that can be pasted into a listing form. Changing brand
config changes every product's previews without touching products. Editing the
listing text is preserved across rebuilds.

**Cites.** §16, §17, §18, §19, §27.
