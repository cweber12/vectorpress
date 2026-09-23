# PRD 8 — Publication Lifecycle

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** The catalog knows which products are live and protects them from silent
change.

**Scope.**
- Publish action records a snapshot: timestamp, the built manifest, and free-text
  marketplace references. Multiple snapshots per product.
- Published products have frozen membership (§12.1); rule changes surface as proposed
  additions/removals the user accepts or rejects individually.
- Rebuilds of published products may add or improve, never remove, relative to any
  prior snapshot (§23.1); removal requires a new product.
- The attention report (PRD 4) gains proposed updates and published-but-stale
  products.

**Out of scope.** Any marketplace API interaction.

**Acceptance.** §39.17: after publishing, adding a matching asset does not change the
product; it appears as a proposed update; accepting it rebuilds; an attempt to remove
a previously shipped asset is refused with an explanation.

**Cites.** §12.1, §23, §23.1, §37.
