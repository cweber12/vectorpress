# 0013 — Format folders are filled from a fixed derivative-type table; no rasterizing

Status: accepted
Date: 2026-09-27

## Context

A product declares derivative types and formats independently (ADR 0008, §7). Read as
a cross product, `[cut_svg, silhouette_svg, transparent_png] × [svg, png, dxf]` would
vectorize a PNG, rasterize cut files, and produce several DXFs per asset, most of which
a buyer cannot use well.

## Decision

The package's format folders are filled by a fixed table in code, not per-product
configuration:

| Folder | Filled from | How |
|---|---|---|
| `SVG/` | every included `*_svg` type | copied |
| `PNG/` | `transparent_png` | copied |
| `DXF/` | `cut_svg`, else `silhouette_svg` if `cut_svg` is not included | converted |

- SVGs are never rasterized; PNGs are never vectorized; color, outline and detailed
  types never become DXF.
- A listed format no included type fills, or an included type no listed format
  carries, is a product metadata problem at load time, not a build failure.

## Consequences

- Every file in a package is either an effective derivative with its own status, or
  a mechanical format conversion of one (DXF). Nothing customer-facing escapes review.
- A new customer file kind (say, a PNG render of the cut design) is a new derivative
  type with its own recipe and status, not a hidden conversion.
