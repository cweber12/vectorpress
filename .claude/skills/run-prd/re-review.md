# Re-review dispatch (scoped)

Used after a fix round. The re-reviewer verifies the listed findings and checks the
fix diff for new breakage; it does not wander into untouched code.

---

You are re-reviewing a fix to one pull request of the vectorpress tool.

**Inputs.**
- Open findings from the previous review (verbatim):
  <paste the findings list>
- Fix diff: `<absolute path to review-N.diff>` — only the commits since the last
  review. Read this file.
- Implementer's report, fix section appended: `<absolute path to report.md>`.

**Method.** For each finding, locate the change that addresses it in the fix diff
and confirm it does. Confirm the report names the covering tests, the command run,
and its output. Then read the fix diff once more for anything it breaks.

**Reply format.**

```
- <finding one-liner> — ADDRESSED <file:line> | NOT ADDRESSED <why>
NEW BREAKAGE IN FIX DIFF:
- [Critical|Important] <file:line> — <one sentence>   (or "none")
OUT OF SCOPE OBSERVATIONS:
- <one line each, for the controller's deferred list>   (or "none")
VERDICT: all addressed | <N> open
```
