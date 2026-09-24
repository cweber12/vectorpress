# Reviewer dispatch

Fill the angle-bracket fields. Give the reviewer file paths, not pasted content.

---

You are reviewing one pull request of the vectorpress tool. You review; you do not
edit code.

**Inputs.**
- Issue: `gh issue view <K>` — the requirements.
- Implementer's report: `<absolute path to report.md>`.
- Diff package: `<absolute path to review-N.diff>` — commit list, stat, full diff
  with context. Read this file; do not re-derive the diff.
- Standards: `CLAUDE.md` (guardrails), `CONTEXT.md` (vocabulary), the ADRs the issue
  cites under `docs/adr/`.

**Method.** Read the issue first and write down what a complete implementation
must contain. Then read the diff against that list, criterion by criterion. Then
read the diff again for quality. Trust the report's test evidence; do not re-run
the suite. Check the tests themselves: a test that cannot fail is a defect.

**Verdict A — Spec.** For every acceptance criterion: met (cite the file and test),
unmet, or "cannot verify from diff" (lives in unchanged code). Anything built that
the issue did not ask for is a finding. ✅ only when every criterion is met.

**Verdict B — Standards.** Findings for: a hand-authored TOML file written by the
tool; an import against the layering rule; a source image touched; vocabulary that
CONTEXT.md avoids; a behavior an ADR forbids; provenance or status kept outside
tool-owned JSON; missing or asserting-nothing tests; snapshot updates without
explanation in the PR; comments or docstrings that narrate history ("issue #N",
"review fix round") instead of explaining the code (Minor), or that leak into a CLI
command's `--help` (Important). ✅ only with no Critical or Important finding.

**Severity.** Critical: wrong behavior, data loss, guardrail broken. Important:
criterion unmet, missing test, layering or vocabulary violation. Minor: style,
naming, small duplication.

**Reply format.**

```
SPEC: ✅ | ❌
STANDARDS: ✅ | ❌
FINDINGS:
- [Critical|Important|Minor] <file:line> — <one sentence: what is wrong and what right looks like>
CANNOT VERIFY:
- <criterion> — <why>
STRENGTHS: <one line>
```
