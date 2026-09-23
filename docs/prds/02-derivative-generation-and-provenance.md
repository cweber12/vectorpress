# PRD 2 — Derivative Generation and Provenance

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Approved-quality derivatives are produced from source images, and every
derivative knows exactly what it was built from.

**Scope.**
- Recipes: each derivative type declares which source roles it accepts, in order of
  preference; the asset may pin a specific source.
- Initial derivative types: transparent PNG (§6.1), solid silhouette SVG (§6.2),
  flat-color SVG (§6.9).
- SVG outputs are true vectors with clean bounds and no stray or invisible content (§8).
- Each derivative has a tool-owned provenance record: source hash, recipe identity
  including parameters, generator versions, output hash.
- Generation is idempotent: unchanged inputs produce byte-identical outputs and no
  state change.
- Staleness is computable: a derivative is stale when its recorded source hash no
  longer matches the source.
- The user can generate for one asset, for all assets, or only for stale derivatives.
- Failures are per-derivative, reported with asset and type, and never leave a
  half-written file or a corrupted state file (§35).
- Customer-facing filenames follow §20.
- "Expected but missing" and "impossible (no acceptable source)" derivatives are
  distinguished in status output (§34).

**Out of scope.** Cut files, validation findings, approval status, overrides.

**Acceptance.** User can generate the three derivative types for the fixture
catalog; regenerating without changes is a no-op; changing a source marks exactly
the affected derivatives stale; a deliberately broken source fails visibly without
touching anything else. Snapshot tests lock output.

**Cites.** §6.1, §6.2, §6.9, §8, §20, §21, §22 (first half), §23, §35, §36.
