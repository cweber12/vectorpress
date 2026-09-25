# PRD 4 — Review, Approval, and Overrides

Status: complete
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Every derivative has an explicit status, humans control it, hand edits are
first-class, and the catalog can say what needs attention.

**Scope.**
- Per-derivative status with the §10 states; status is tool-owned state, never in
  hand-authored files.
- Regeneration rules (§22.1): changed output returns to needs-review; unchanged output
  keeps status.
- Newly generated cut files enter needs-review or an equivalent state determined by
  PRD 3's pass/review result; other types enter needs-review.
- The user can approve, reject, and mark-for-regeneration one or many derivatives,
  with optional notes.
- Overrides (§6.8): a hand-edited file in the override location is detected, becomes
  the effective version, is validated like any generated file, carries its own status
  and provenance (including the source hash it was edited against), is never
  overwritten, and can be discarded to revert.
- Stale overrides (§22.2) are flagged when the source changes; the user can re-edit,
  keep, or discard.
- Publication eligibility (§10.1) is computable per asset per set of derivative types,
  distinguishing blocking conditions from warnings.
- An "attention" report (the inbox, §34): needs-review derivatives, stale overrides,
  blocked assets with reasons, missing expected derivatives, missing metadata. An
  "open in editor" command launches the configured external editor on a derivative.

**Out of scope.** Collections, products, proposed-update queue (PRD 8), the UI.

**Acceptance.** User can review and approve every fixture derivative from the CLI;
a hand-edited cut file survives regeneration (§39.16); a source change flags the
override stale; blocked assets are listed with reasons; the attention report is
empty when everything is approved.

**Cites.** §6.8, §10, §22, §24, §34, §35.
