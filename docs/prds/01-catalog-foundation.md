# PRD 1 — Catalog Foundation

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** A catalog directory on disk can be described, loaded, validated, and
inspected. Nothing is generated yet.

**Scope.**
- A catalog root is identified by a root config file and located from the working
  directory or an explicit flag.
- Each master asset is a folder with a hand-authored metadata file and one or more
  preserved source images, each tagged with a role (§4, §5, §41).
- Hand-authored schemas exist for assets, collections, products, brand, and catalog
  config, with the metadata fields in §5, §11, §18, §27 at minimum.
- Rights status (§26) and accuracy status (§25) are asset metadata.
- Loading validates every file and reports errors with file and field.
- The user can list assets, see each asset's sources and roles, and see metadata
  problems (missing required fields, unknown roles, duplicate IDs).
- A fixture catalog exists in the tool repo and every later PRD extends it.

**Out of scope.** Generation, status, collections resolution, products.

**Acceptance.** User can create a catalog with several assets and metadata, run a
status command, and see a correct inventory and a list of metadata problems.
Malformed files fail with actionable errors. Source images are never modified.

**Cites.** §4, §5, §11, §18, §21, §25, §26, §27, §34 (inventory items), §41.
