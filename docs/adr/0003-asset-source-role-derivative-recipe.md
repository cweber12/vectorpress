# 0003 — Asset → Source image (role) → Derivative (type), joined by recipes

Status: accepted
Date: 2026-09-22

## Context

§4 and §6 never say which source image produces which derivative type. Some
derivatives are impossible without a particular kind of source (outline needs line
art). Status must be per file (§10) but color variants are mechanical recolors.

## Decision

- **Asset** owns identity, metadata, rights status, accuracy status.
- **Source image** is a preserved file with a **role** (`silhouette`, `lineart`,
  `flatcolor`, `detailed`, extensible).
- **Derivative** is one file for one (asset, derivative type).
- A **recipe** per derivative type declares acceptable roles in preference order; an
  asset may pin a specific source. "Missing" (acceptable source exists, not generated)
  and "impossible" (no acceptable source) are distinct states.
- Status is per (asset, derivative type). **Color variants inherit** their parent
  derivative's status.
- The cut-file derivative is built from the silhouette role, not from detailed art.

## Consequences

- Tracing implementations can be swapped per recipe without touching the catalog.
- §34's "missing expected derivatives" is computable.
