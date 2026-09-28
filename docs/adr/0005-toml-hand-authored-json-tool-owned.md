# 0005 — TOML for hand-authored files, JSON for tool-owned; the tool never rewrites hand-authored files

Status: accepted (listing-draft exception amended by 0016)
Date: 2026-09-22

## Context

§41 requires human-readable files. A CLI and a UI will both change state. Users will
add comments to their metadata files.

## Decision

- Hand-authored: `catalog.toml`, `asset.toml`, `collection.toml`, `product.toml`,
  `brand.toml`. Validated on load with pydantic; errors name file and field.
- Tool-owned: JSON (`_state.json`, provenance, findings, manifests, publication
  snapshots).
- Rights status and accuracy status are asset metadata (hand-authored). All
  generated-thing status is tool-owned.
- The tool **never rewrites a hand-authored file**. Single exception: it drafts a
  product's `[listing]` section once, on first build, and never touches it again.

## Consequences

- Comments and key order survive; CLI and UI cannot clobber each other.
- Per-asset layout: `asset.toml`, `sources/`, `derived/` (+ `_state.json`),
  `overrides/`.
