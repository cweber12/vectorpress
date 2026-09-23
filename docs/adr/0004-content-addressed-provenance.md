# 0004 — Content-addressed provenance and build manifests; no version numbers

Status: accepted
Date: 2026-09-22

## Context

§22–23 need: did the source change, did the output change, is the override stale, is
the product current, and (§23.1) did a rebuild drop anything a buyer received.

## Decision

- Every derivative has a tool-owned provenance record: source hash, recipe identity
  **including parameters**, generator versions, output hash.
- Stale derivative = source hash mismatch. Output changed = output hash changed
  (→ `needs_review`; unchanged keeps status). Stale override = the source hash it was
  edited against has changed.
- Every product build writes a **manifest** of asset / derivative type / content
  hashes. Product current = manifest matches current effective derivatives.
- No manually bumped version numbers in tool logic. The product's marketing `version`
  field is display-only.

## Consequences

- A global parameter change makes every affected derivative stale and re-triggers
  review. This is correct: the output genuinely changed.
- §36 repeatability follows: a build is a pure function of its manifest inputs.
