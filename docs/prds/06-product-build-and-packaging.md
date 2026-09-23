# PRD 6 — Product Build and Packaging

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** A product resolves into a complete, repeatable, customer-ready package and
ZIP.

**Scope.**
- A build produces the customer package structure (§14) from eligible members'
  effective derivatives (override wins), organized by format, with brand README and
  LICENSE (§27).
- Format conversion for included formats: SVG, PNG, DXF (§7). PDF/EPS remain
  disabled.
- Every build writes a manifest recording each included asset, derivative type, and
  content hash, plus the reference size and tool version.
- A predictable, marketplace-friendly ZIP (§15) containing only the package.
- "Needs rebuild" is computable by comparing the last manifest to current effective
  derivatives (§23).
- Builds are all-or-nothing per product; a failing asset fails the product build with
  a clear message and does not corrupt other products (§35).
- Unapproved or blocked members are excluded, or the build refuses, per product
  configuration (§10); explicit per-build override is possible and recorded.

**Out of scope.** Previews, listing text, exporters, publication.

**Acceptance.** User can build the fixture product, unzip it, and find only customer
files with consistent names; rebuilding with no changes produces the same logical
contents; changing one source makes exactly the containing products report
needs-rebuild; a rejected cut file is excluded from a cut-file product while the same
asset ships in a PNG product.

**Cites.** §7, §10, §14, §15, §20, §23, §35, §36.
