# 0010 — Excessive complexity is measured at the catalog reference size

Status: accepted (amends 0009)
Date: 2026-09-24

## Context

ADR 0009 traces each asset's one cut file at the catalog's default reference size and
lets a product's reference size change validation only. §9.1 says validation
thresholds are physical and are judged "at that reference size".

`excessive_complexity` measures nodes per inch of perimeter. Under a product override
the perimeter shrinks in inches, but the node count stays the same because the
geometry was traced at the catalog default. Density therefore rises by exactly the
size ratio. At `kelp_forest_mini_pack`'s 1in the real-art sea star, anemone and urchin
read about 13.7–14.1 nodes/in and are flagged, although they pass at 3in (about 4.6).
The `min_perimeter_in` exemption also shifts with the size, so it exempts different
pieces at different sizes (issue #52).

## Decision

- `excessive_complexity`'s density and its `min_perimeter_in` exemption are measured at
  the **catalog's default reference size**, whatever reference size the validation run
  uses. The absolute node-count cap is a count and needs no size.
- Every other detector (dot, tiny shape, small hole, narrow feature, stray-object
  tolerance) keeps judging at the reference size being validated, product override
  included.
- We read §9.1 this way: a threshold is judged at the size where the thing it measures
  is decided. Whether a hole, sliver or neck can be physically cut is decided by the
  product's size. How complex the geometry is was decided when it was traced, at the
  catalog size. Complexity is a property of that geometry, not of how large it is cut.
- A findings report records the size this kind was measured at as
  `excessive_complexity_reference_size_in`, next to `reference_size_in`. The CLI's
  `--product` line says so when the two sizes differ.
- Threshold values are unchanged (11.0 nodes/in, 0.75in minimum perimeter, 300-node
  cap).

## Rejected alternatives

- **Retune the limit.** Density at 1in is exactly 3× density at 3in, so no single limit
  both catches `coralline_algae` at 3in (13.4) and passes the urchin at 1in (14.1).
- **A scale-free measure** (for example turning per node). This gains nothing:
  `reference_size_in` is already one of `cut_svg`'s recipe parameters, so changing the
  catalog default retraces the cut file and changes its recipe hash (ADR 0004, 0009).
  The catalog size is always the size the geometry was produced at. It would also give
  up nodes/in, a unit a person can read and reason about.

## Consequences

- With no product override in play (catalog size = validation size), results are
  unchanged.
- A small product no longer gets complexity false positives. A large product no longer
  hides complexity that was visible at the catalog size.
- If per-size cut files are ever adopted (ADR 0009's escape hatch), each cut file's
  complexity would be measured at the size it was traced at, which is the same rule.
