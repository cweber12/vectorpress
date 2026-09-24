# vectorpress

Turn master artwork into organized, reusable SVG and cut-file products and
marketplace-ready packs. A local, single-user production tool.

- Requirements: [`docs/requirements.md`](docs/requirements.md)
- Plan, decisions and PRD roadmap: [`docs/PLAN.md`](docs/PLAN.md)
- Domain vocabulary: [`CONTEXT.md`](CONTEXT.md)
- Architecture decisions: [`docs/adr/`](docs/adr/)

## Status

PRDs 1–3 are done: load and check a catalog (`vpress status`, `assets`, `asset`,
`collections`, `products`), generate derivatives with provenance (`vpress generate`),
and validate cut files into findings (`vpress validate`). Review, products and builds
come next; see the PRD roadmap in `docs/PLAN.md`.

## Development

```
uv sync
uv run pre-commit install
uv run vpress --version
uv run pytest
```

The tool operates on a **catalog directory that lives outside this repo**. A tiny
fixture catalog under `tests/fixtures/catalog/` exists for tests only.
