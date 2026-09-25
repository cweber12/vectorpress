# Implementer dispatch

Fill the angle-bracket fields. Send nothing else: no session history, no PRD text.

---

You are implementing one issue of the vectorpress tool in an isolated worktree.

**Where this fits.** <one line: which PRD and which slice this is, e.g. "PRD 1, slice 3 of 7: sources with roles, after asset inventory merged in #2">

**Worktree.** `<absolute path to .runs/prd-NN/issue-K/wt>`. Work only there. Run
`uv sync` first.

**Requirements.** Read issue #<K> with `gh issue view <K>`. Its "What to build" and
"Acceptance criteria" are your requirements, verbatim; the PRD it names is the
authority behind them. Before writing code read `CLAUDE.md`, `CONTEXT.md`, and the
ADRs under `docs/adr/` that the issue cites. Use CONTEXT.md vocabulary in every
identifier, test name and message.

**Decided before you.** <one to three lines of interfaces, file shapes or rulings
from earlier merged issues that the issue body cannot know; "none" if none>

**How to work.**
- Test-first: write the failing test for an acceptance criterion, make it pass,
  refactor. Snapshot changes are accepted with `uv run pytest --snapshot-update`
  and explained in the PR.
- Every acceptance criterion accounted for: a test, or a sentence in your report
  saying why a test is impossible.
- Every new or changed test must be seen failing without the change that makes it
  pass. Your report quotes that failing run per test (the red step, or a revert of
  the fix); a test with no red evidence is treated as one that cannot fail.
- Comments and docstrings say what the code does and why, briefly. They never
  narrate history: no "issue #N", no "review fix round", no "before this issue".
  Git and the issue thread already hold that. Cite a § or an ADR only where it
  explains a rule. A CLI command's docstring is its `--help` text: keep it
  user-facing, and put maintainer notes after a `\f` line.
- Before opening the PR: `uv run ruff format`, `uv run ruff check`, `uv run pyright`,
  `uv run lint-imports`, `uv run pytest` all green.
- Conventional commits. Push the branch and open a PR with `gh pr create` using the
  repo's PR template; the What section ends with `Closes #<K>`.
- You dispatch no subagents: no helpers, no reviewer. Review arrives from the
  controller after your report.
- If you need a decision the issue does not make, ask the controller before
  guessing; a wrong guess costs a fix round.

**Report.** Write the full report to `<absolute path to report.md>`: what you built,
how each acceptance criterion is covered, test commands and their output, anything
you decided that the issue left open, and concerns. Then reply with exactly:

```
STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
PR: <url>
COMMITS: <first7>..<last7>
TESTS: <one line, e.g. "pytest 41 passed; ruff, pyright, lint-imports clean">
CONCERNS: <one line or "none">
```
