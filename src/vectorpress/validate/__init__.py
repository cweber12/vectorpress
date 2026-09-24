"""``vectorpress.validate``: pure functions from an effective derivative's
own SVG bytes to a findings report (ADR 0006, ADR 0007, CONTEXT.md
"Findings", §9, issue #37).

A sibling of :mod:`vectorpress.pipeline`, not a caller or a callee of it
(CLAUDE.md's layering guardrail, ``pyproject.toml``'s import-linter
contract): a check here takes bytes, never a generator's in-memory geometry,
so the exact same code validates a generated derivative and a hand-edited
override (PRD 4) alike. :mod:`vectorpress.catalog.findings` is the only
place a check's result is written to disk (ADR 0006's "catalog... the only
layer touching catalog files").
"""
