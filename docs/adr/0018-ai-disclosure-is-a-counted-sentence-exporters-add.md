# 0018 — AI disclosure is a counted sentence exporters add; licensing notes never leave the catalog

Status: accepted
Date: 2026-09-28

## Context

§26 keeps `ai_generated` so listings can disclose AI use. As checked on 2026-09-28,
Etsy requires disclosure in the listing description (seller-prompted AI art is
"Designed by a seller"), Design Bundles requires it in the product information, and
Creative Fabrica requires AI designs to go in its AI category. Shopify and Gumroad
state no rule. §26 also keeps licensing notes (the AI tool and its terms) internal.

## Decision

- A build discloses when any **included** asset's rights status is `ai_generated`
  (overrides do not clear it; excluded members do not count), read from the
  manifest's `asset_rights_statuses`.
- The text comes from an overridable template, `templates/export/ai_disclosure.j2`.
  The shipped default states only what the tool knows: how many of the included
  designs were made with generative AI image tools and that they were converted to
  vector files ("20 of 20 designs…"). It never claims hand-drawing or review.
- Licensing notes are never exported, printed or rendered.
- Every marketplace bundle ends its description with the sentence, the direct store
  included though no rule requires it. Etsy's bundle also gives who-made as "I did
  (Designed by a seller)". Creative Fabrica's gives the category as its AI category,
  with the listing's own category as a note. `listing.json` carries the count, total
  and text. No AI member means no disclosure section and no category change.
- Disclosure never appears on previews (ADR 0015) or in README/LICENSE (PRD 6).
- Marketplace AI rules are entries in the cited limits table (ADR 0017).
