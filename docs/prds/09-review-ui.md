# PRD 9 — Review UI

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** The judgment steps of the workflow can be done in a browser instead of a
terminal, with no new logic.

**Scope.**
- Local web app served by the tool; every action calls the same functions as the CLI.
- Home page is the attention inbox (PRD 4 + PRD 8) with every item linking to where
  it is resolved.
- Derivative review page: generated vs. override side by side, findings drawn over
  the SVG, approve / reject / regenerate, open in external editor, discard override.
- Asset page: metadata, sources, all derivatives with status, products containing it.
- Product page: effective contents with eligibility, previews, needs-rebuild,
  proposed updates with accept/reject, build and publish actions.
- No in-browser vector editing.

**Acceptance.** User can complete the full §24 workflow from the browser for the
fixture catalog without using the CLI, and the CLI attention report agrees with the
inbox at every step.

**Cites.** §9.2, §10, §12.1, §22.2, §24, §34, §38.
