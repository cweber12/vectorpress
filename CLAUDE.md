# vectorpress — agent guide

Local Python tool: master artwork (PNG) → SVG/cut-file **derivatives** → **collections**
→ **products** → marketplace-ready ZIPs. Single user, single machine. The tool is pointed
at a **catalog** directory that lives outside this repo.

## Pointers

- **Vocabulary** — `CONTEXT.md`. Use its terms in code, tests, issue titles and docs;
  it names the synonyms each term replaces.
- **Decisions** — `docs/adr/`. Before changing a layer, a file format, provenance,
  status, cut-file generation, or product/publication behavior, read the ADR that owns
  it. A change that contradicts one gets a new ADR that supersedes it.
- **Roadmap** — `docs/PLAN.md` Part 3 and `docs/prds/`. A PRD says *what*; expanding it
  into tracer-bullet issues (`/to-issues`) happens only when it is next, against the
  code as it exists then.
- **Running a PRD** — `/run-prd docs/prds/NN-name.md`. A controller agent works the PRD's
  open issues in blocked-by order: fresh implementer per issue, reviewed PR, squash-merge,
  with the issue thread as ledger. It merges on its own; it stops for ADR conflicts.
- **Requirements** — `docs/requirements.md`, cited by § number in PRDs, ADRs and issues.

## Guardrails

- **Layering** `domain ← catalog ← pipeline/validate ← build ← cli/ui`, enforced by
  `uv run lint-imports` (ADR 0006). `cli` and `ui` are thin: they call the same
  functions.
- **Hand-authored TOML is read-only to the tool; the tool writes only JSON state**
  (ADR 0005). The one sanctioned write is drafting a product's `[listing]` on first build.
- **`sources/` is read-only.** Generation writes under `derived/`; a human's edit lives
  under `overrides/` and is the **effective derivative** (ADR 0003, 0007).
- **Provenance is content-addressed** (ADR 0004): staleness and "current" are hash
  comparisons, and tracing parameters are part of the recipe hash.

## Testing

Snapshot tests (syrupy) against `tests/fixtures/catalog/` lock SVG output and findings
JSON; accept an intended change with `uv run pytest --snapshot-update` and explain the
diff in the PR. Heavy runtime dependencies (tracing, geometry, DXF, Playwright) are added
by the PRD that first needs them, via `uv add`.

CLI output assertions strip ANSI escapes and Rich box-drawing before matching: CI
runners detect color support and split words across escape codes (see
`_normalized_output` in `tests/integration/test_validate.py`).

## Conventions

Conventional commits; squash-merge to `main`; CI runs on ubuntu and windows.

The dev machine is Windows. Write multi-line issue, PR and comment bodies to a file
with the Write tool and pass `--body-file`; heredocs break on quoting here.
