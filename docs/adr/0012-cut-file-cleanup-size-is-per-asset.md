# 0012 — Cut-file cleanup size is per asset, defaulting to the catalog reference size

Status: accepted (supersedes 0009)
Date: 2026-09-27

## Context

ADR 0009 cleans each asset's one cut file at the catalog's default reference size and
lets a product's reference size change validation only. It argued that anything
cleanup should have handled at a product's size "surfaces as findings". That holds
only for a product *smaller* than the cleanup size: leftover fine detail is present in
the file and validation flags it.

For a product *larger* than the cleanup size it fails silently. Cleanup removed detail
(islands, holes, thin necks under the opening width) that would have cut fine at the
larger size, and findings describe what is in the file, not what was taken out. The
first real catalog hit this: detailed climbing line art cleaned at the 3in default
loses most of its interior cut lines, and a 6in cut pack of the same set would ship
the thinned 3in geometry and could validate as a pass.

The customer SVG carries no physical units; a product's reference size is a promise
that the file cuts cleanly at that size, not a size stamped in the file.

## Decision

- Each asset still has **one** cut file, and status, overrides, findings, eligibility
  and manifests stay keyed on (asset, derivative type), as in ADR 0009.
- The size that cut file is cleaned at is the asset's **cleanup size**:
  `[derivatives.cut_svg] reference_size_in` in `asset.toml` if set, else the catalog
  default. It is already a `cut_svg` recipe parameter, so changing it retraces the cut
  file and changes its recipe hash (ADR 0004). The `[derivatives.<type>]` table
  therefore holds per-asset derivative settings, of which a source pin is one; `source`
  becomes optional.
- A product's reference size still affects **validation only**.
- A build **warns**, without blocking, for each member whose cut file's cleanup size is
  smaller than the product's reference size: detail may have been removed that would
  cut at the product's size. The warning is recorded in the manifest.
- ADR 0010's rule reads "measured at the cut file's cleanup size" in place of "at the
  catalog's default reference size"; with no per-asset setting these are the same.

## Rejected alternatives

- **Raise the catalog default.** One setting, but catalog-wide: simple icons sold at
  3in would all be cleaned at a larger size and need overrides.
- **Per-size cut files** (ADR 0009's escape hatch). Correct in general, but adds a size
  to every key. Still available if one asset must sell at very different sizes.
- **Block instead of warn.** A simple icon cleaned at 3in is often fine at 6in; the
  person building decides.

## Consequences

- Assets that sell large set their cleanup size once; selling them smaller produces
  findings at that size, fixed in overrides as ADR 0009 describes.
- An asset sold both much smaller and much larger than its cleanup size still gets
  only one of the two directions checked. That case is the trigger for per-size cut
  files.
