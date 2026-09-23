# vectorpress — agent guide

Local Python tool that turns master artwork (PNG) into SVG/cut-file derivatives,
groups them into collections and products, validates cut quality, and packages
marketplace-ready ZIPs. Single user, single machine.

Read first: `CONTEXT.md` (vocabulary), `docs/PLAN.md` (decisions + PRD roadmap),
`docs/requirements.md` (source of truth, cited by § number), `docs/adr/`.

## Commands

```
uv sync                      # install
uv run vpress --help         # the CLI
uv run pytest                # tests (syrupy snapshots: --snapshot-update to accept)
uv run ruff format && uv run ruff check --fix
uv run pyright               # strict
uv run lint-imports          # layering contract
```

## Rules that must survive every PRD

1. **Layering.** `domain ← catalog ← pipeline/validate ← build ← cli/ui`. Nothing
   imports upward. `domain` has no I/O. `catalog` is the only layer that touches the
   filesystem for catalog state. `validate` is pure functions over geometry. `cli` and
   `ui` contain no logic; they call the same functions. Enforced by import-linter.
2. **The tool never rewrites a hand-authored file.** Hand-authored = TOML
   (`catalog.toml`, `asset.toml`, `collection.toml`, `product.toml`, `brand.toml`).
   Tool-owned = JSON (state, provenance, findings, manifests). One exception: drafting
   a product's `[listing]` section once on first build.
3. **Sources are sacred.** Never modify, move or delete a file under an asset's
   `sources/`.
4. **Provenance is content-addressed.** Staleness, "output changed", stale override,
   and "product current" are hash comparisons. No manually bumped version numbers in
   tool logic. Tracing parameters are part of the recipe hash.
5. **Status is per (asset, derivative type).** It lives in tool-owned state, never in
   `asset.toml`. Color variants inherit their parent's status. Previews have no status.
6. **Overrides win and are never overwritten.** A file under `overrides/` is the
   effective derivative; regeneration writes only under `derived/`.
7. **Failures are per item.** A failing asset or derivative reports asset + type and
   never leaves a half-written file or corrupts unrelated state.
8. **Deterministic output.** Same inputs → byte-identical outputs. Snapshot tests
   against `tests/fixtures/catalog/` lock SVG output and findings JSON; a snapshot diff
   in a PR must be explained.
9. **Vocabulary.** Use `CONTEXT.md` terms in code, tests, issues and docs. Don't
   introduce synonyms (e.g. "variant" for derivative type, "pack" for product).

## Adding dependencies

Heavy runtime deps (potrace/vtracer, shapely, ezdxf, Pillow, Playwright) are added by
the PRD that first needs them. Pin with `uv add` so `uv.lock` updates.

## Process

- PRDs live in `docs/prds/NN-name.md`. They say *what*, not *how*, and are not edited
  during implementation. Divergence → ADR in `docs/adr/`, and the *next* PRD adapts.
- A PRD is expanded into GitHub issues (`/to-issues`) only when it is next.
- Conventional commits. Squash-merge to `main`.
- Anything overturning a decision in `docs/PLAN.md` Part 1 gets an ADR.
