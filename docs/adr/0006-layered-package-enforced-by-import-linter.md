# 0006 — Single package, layered by import direction, enforced in CI

Status: accepted; partly superseded by 0011 (collection resolution lives in domain/catalog, not build)
Date: 2026-09-22

## Decision

One package `vectorpress` with layers:

```
domain ← catalog ← pipeline / validate ← build ← cli / ui
```

- `domain`: pydantic models, no I/O.
- `catalog`: on-disk layout, loading, state, provenance. The only layer touching
  catalog files.
- `pipeline`: derivative generators, one module per derivative type behind a common
  interface. `validate`: pure functions from geometry to findings.
- `build`: collection resolution, product build, manifest, ZIP, previews, exporters.
- `cli`, `ui`: thin.

Enforced by an import-linter "layers" contract run in pre-commit and CI.

## Consequences

- The UI PRD can land at any point without touching lower layers.
- Snapshot tests (syrupy) of SVG output and findings JSON against the fixture catalog
  are the regression net for tracer/library upgrades.
