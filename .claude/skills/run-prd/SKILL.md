---
name: run-prd
description: Drive one PRD to completion as the controller — dispatch an implementer per issue, review each PR, merge, repeat. Usage — /run-prd docs/prds/NN-name.md
disable-model-invocation: true
---

# Run a PRD

You are the **controller** for one PRD. You coordinate; you never edit code, run
tests, or fix findings yourself. Every issue gets a fresh **implementer** subagent
and a fresh **reviewer** subagent, each with only the context its task needs. Your
own context holds the PRD, the issue order, and the ledger.

Invoking this skill authorizes you to merge a PR whose review is clean and whose CI
is green. Stop and ask only for: a destructive or irreversible operation beyond a
squash-merge; a security-sensitive action; a finding that contradicts an ADR (that
needs a new ADR, a human decision); or a PRD so broken every path forward is a guess.
Everything else you **rule** on: decide, record the ruling, keep going.

## Setup

1. Read the PRD once. Note Goal, Scope, Out of scope, Acceptance. The PRD is the
   binding authority; each issue is its argument.
2. List its issues by exact title prefix; `--search` is fuzzy and has missed issues:
   `gh issue list --state open --limit 200 --json number,title,body --jq '[.[] | select(.title | startswith("[PRD NN]"))]'`.
   Build the order from each body's **Blocked by** section. If no open issues exist,
   stop: the PRD has not been expanded (`/to-issues`).
3. Recover state from GitHub, never from memory: an issue with an open PR is in
   progress; a closed issue is done; the last controller comment on an issue says
   where its loop stands. Resume there.
4. Ensure `.runs/` exists (git-ignored). Hand-off files for issue K live under
   `.runs/prd-NN/issue-K/`; its worktree at `.runs/prd-NN/issue-K/wt`.

## Ledger

The **ledger** is the issue thread on GitHub. Post a comment at every transition:
dispatched (branch, model), CI result, review verdict, each fix round, every
`Ruling: <decision> — <why> — <cost if wrong>`, merged (commit). Compaction erases
your memory; the ledger and `git log` do not. Post with `gh issue comment K --body-file`.

## Per issue

Run issues **sequentially** unless two issues' bodies name no shared command,
module, or fixture file. Parallel issues each get their own worktree; merge one,
then have the other rebase before its review.

1. **Branch.** From current `main`: `git worktree add .runs/prd-NN/issue-K/wt -b prd-NN/issue-K main`.
   Record BASE = `git rev-parse main`.
2. **Dispatch the implementer** with [implementer.md](implementer.md), model `sonnet`.
   The prompt carries: the issue number, the worktree path, the report path
   (`.runs/prd-NN/issue-K/wt/.runs/report.md`: inside the worktree, so the
   implementer may write it, and git-ignored there), and one to three lines of interfaces or
   rulings from earlier merged issues the issue body cannot know. Nothing else: no
   session history, no pasted PRD. Keep the implementer's agent id; fix rounds 1–3
   resume it. Never dispatch two implementers into one worktree.
3. **Handle the report.** `DONE` → step 4. `DONE_WITH_CONCERNS` → read the concerns;
   correctness or scope concerns go back to the implementer before review.
   `NEEDS_CONTEXT` → supply it, re-dispatch. `BLOCKED` → change something: more
   context, a stronger model (`opus`), a split, or a ruling on a defective issue.
   Never retry unchanged.
4. **CI gate.** `gh pr checks <pr> --watch`. Red on either OS goes back to the
   implementer; review waits for green.
5. **Review package.** Write the diff to a file the reviewer reads in one call:
   `git -C <wt> log --oneline main..HEAD`, `git diff --stat main...HEAD`, and
   `git diff -U10 main...HEAD` concatenated into `.runs/prd-NN/issue-K/review-1.diff`.
   The diff never enters your context.
6. **Dispatch the reviewer** with [reviewer.md](reviewer.md), model `sonnet`
   (`opus` when the diff crosses three or more layers or touches provenance,
   status, or cut-file generation). It returns two verdicts, **Spec** and
   **Standards**, with findings by severity. Never pre-judge a finding for it.
7. **Fix loop.** Minor findings are ledgered as deferred and never enter the loop.
   Any Critical or Important finding, or a ❌ verdict, starts a round: one fix
   dispatch plus one scoped re-review with [re-review.md](re-review.md) over the fix
   range only. Rounds 1–3 resume the same implementer with the findings verbatim.
   Rounds 4–5 dispatch a fresh implementer on `opus` with the report path and
   "a prior implementer attempted this K times; you own it now". Round 5 still
   open → adjudicate each finding yourself, post a ruling, and either park it or
   carry the smallest unblocking change into the next issue's dispatch.
8. **PRD gate.** With review clean and CI green, read the PR description and the
   report against the PRD's Scope and Out-of-scope. Ask one question: does `main`
   plus this PR still lead to the PRD's Acceptance paragraph? If the PR narrows,
   widens, or contradicts the PRD, that is a Spec finding: back to step 7.
9. **Merge.** `gh pr merge <pr> --squash --delete-branch`. Copy the report to
   `.runs/prd-NN/issue-K/report.md` so it survives, then
   `git worktree remove .runs/prd-NN/issue-K/wt`. On Windows a busy or
   permission-denied failure is common: run `git worktree remove --force <wt>`, then
   `git worktree prune`, and if the directory still stands, note it in the ledger and
   move on rather than retrying unchanged. Ledger the merge commit. Next issue.

## Finish

1. After the last issue merges, dispatch one **acceptance reviewer** on `opus`:
   give it the PRD path and the fixture catalog, and have it perform the PRD's
   Acceptance paragraph literally with `uv run vpress …` commands, reporting each
   sentence as met or unmet with evidence. Unmet sentences become new issues
   (`/to-issues` format, parent PRD, label `ready-for-agent`) and go through the
   per-issue loop.
2. Open one small PR that changes the PRD's `Status:` line to `complete`; merge it.
3. Report to the user: issues merged with commits, deferred minors, and every
   `Ruling:` from the ledgers in the order made, each with its cost if wrong. A
   ruling absent from this list was a decision made in secret. End with **Try it**:
   the acceptance reviewer's `uv run vpress …` commands against the fixture
   catalog, in order, each with one line on what it shows.
