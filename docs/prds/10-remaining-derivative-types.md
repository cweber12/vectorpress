# PRD 10 — Remaining Derivative Types

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Complete the derivative catalog from §6.

**Scope.**
- Outline / line-art SVG (§6.4), from the line-art role.
- Detailed single-color SVG (§6.5).
- Layered-color SVG with independently usable regions (§6.6).
- Standard alternate color variants (§6.7) as recolors that inherit the parent
  derivative's status.
- Each new type plugs into recipes, provenance, validation where applicable, status,
  products, and previews with no changes to those subsystems.

**Acceptance.** Each type generates for suitable fixture subjects, is correctly
reported as impossible for unsuitable ones, and can be included in a product and
shown in a variant preview.

**Cites.** §6.4–§6.7, §32.
