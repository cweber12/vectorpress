# 0009 — Cut-file cleanup uses the catalog reference size; products change validation only

Status: accepted
Date: 2026-09-24

## Context

The cut file's cleanup thresholds are physical (§9.1, ADR 0007): a speck, hole or
sliver is only "too small" at a known output size. The reference size has a catalog
default and a per-product override. Validation already honours the override (a
findings report is per cut file and reference size). Generation does not: each asset
has one `cut_svg`, cleaned at the catalog default.

That means a product smaller than the default gets a cut file whose cleanup kept
detail too small to cut at the product's size, and a larger product gets one whose
cleanup removed detail that would have cut fine. Cleaning per product size instead
would make the cut file one derivative per (asset, reference size), and every layer
keyed on (asset, derivative type) — status, overrides, findings, eligibility,
manifests — would have to carry the size too.

## Decision

- Each asset has **one** cut file, cleaned at the catalog's default reference size.
  A product's reference size override never changes generation, provenance or the
  recipe hash.
- A product's reference size affects **validation only**. Anything cleanup should have
  handled at that size surfaces as findings, resolves to needs review, and is fixed
  in an override.
- Status, overrides and eligibility stay keyed on (asset, derivative type).

## Consequences

- PRD 4 attaches status to (asset, derivative type), with no size dimension.
- A catalog whose products span very different sizes will produce more needs-review
  cut files and more overrides at the sizes furthest from the default. Choosing a
  catalog default near the most common product size keeps that small.
- If that override load proves too high, per-size cut files are the escape hatch.
  That change supersedes this ADR and adds the size to the derivative's identity
  everywhere it is keyed.
