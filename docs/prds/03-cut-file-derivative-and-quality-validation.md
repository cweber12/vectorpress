# PRD 3 — Cut-File Derivative and Quality Validation

Status: complete
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** A cut-file derivative is produced as a manufacturable draft, and every
cut-file problem the spec names is detected and located.

**Scope.**
- A simplified cut-file SVG derivative type (§6.3) built from the silhouette role,
  cleaned deterministically relative to a physical reference size (§9.1).
- Reference size: catalog default, product override; validation thresholds expressed
  in physical units; reference size recorded in the result.
- A findings report per cut file covering the §9 list (open paths, tiny shapes,
  dots, small holes, narrow features, excessive complexity, stray objects, duplicate
  geometry, overlaps, disconnected fragments, raster content). Each finding carries a
  location (bounding box or path reference) so it can be drawn or navigated to.
- Findings are classified so a cut file resolves to *pass* or *needs review* (§9.2).
- Validation runs on any SVG derivative, not only generated ones, so overrides can be
  checked (needed by PRD 4).
- No automatic bridging or joining of fragments.

**Out of scope.** Status changes driven by findings (PRD 4), the UI overlay (PRD 9).

**Acceptance.** User can generate cut files, see a findings report with locations for
each, and see pass / needs-review per file. Fixture catalog includes subjects that
deliberately trip each finding type. Snapshot tests lock findings output.

**Cites.** §6.3, §8, §9, §32.
