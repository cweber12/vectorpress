# PRD 5 — Collections and Products

Status: complete
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Assets are grouped into collections by rule or list, and products define
what is sold from a collection, without building anything yet.

**Scope.**
- Collection definitions: explicit asset list, metadata rules over asset
  classifications, union of other collections, or a mix (§11, §12).
- Product definitions: exactly one collection (or an inline one), included derivative
  types, included formats (§7), reference cut size override, tier and family labels,
  listing metadata fields (§18), price.
- Resolution: the user can see a collection's current members and a product's
  effective contents, including which members are eligible, which are excluded and
  why (§10.1), and which are missing required derivatives.
- The same asset appearing in many collections and products is the normal case and is
  visible from both directions (§33, §34).
- Products are unfrozen in this PRD; membership follows the rule.

**Out of scope.** Building, packaging, previews, publication.

**Acceptance.** User can define a rule-based collection and an explicit one, define
several products over the same collection with different derivative types, resolve
each, and see the correct eligible/excluded/missing breakdown. Adding a matching
asset to the catalog appears in the rule-based collection without editing it.

**Cites.** §7, §10.1, §11, §12, §13, §28, §33, §34.
