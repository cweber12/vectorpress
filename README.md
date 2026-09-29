# vectorpress

Turn master artwork into organized, reusable SVG and cut-file products and
marketplace-ready packs. A local, single-user production tool.

- Requirements: [`docs/requirements.md`](docs/requirements.md)
- Plan, decisions and PRD roadmap: [`docs/PLAN.md`](docs/PLAN.md)
- Domain vocabulary: [`CONTEXT.md`](CONTEXT.md)
- Architecture decisions: [`docs/adr/`](docs/adr/)

## Status

PRDs 1–7 are done:

- **Load and check a catalog:** `vpress status`, `assets`, `asset`.
- **Generate derivatives with provenance:** `vpress generate`.
- **Validate cut files into findings:** `vpress validate`.
- **Review, approve and override derivatives:** `vpress approve`, `reject`,
  `regenerate`, `override`, `open`, `attention`.
- **Resolve collections and products into eligible, excluded and missing members:**
  `vpress collections`, `collection`, `products`, `product`.
- **Draft a product's listing metadata, once, by hand-off:** `vpress listing draft`.
- **Build a product into a customer package, ZIP and manifest, plus marketplace
  previews and per-marketplace export files:** `vpress build`. Writes
  `builds/<slug>/` in one all-or-nothing swap: the package and its ZIP,
  `manifest.json`, `previews/` (marketplace preview PNGs) and `export/`
  (`listing.json` and a pasteable text bundle per marketplace) -- previews and
  exports never inside the package or the ZIP.

Publication lifecycle (PRD 8) comes next; see the PRD roadmap in `docs/PLAN.md`. PRD
7's real-catalog check (issue #129) is still pending with its owner.

There is no import command yet: assets and collections are hand-authored TOML (ADR 0005).
To bring in a folder or zip of PNGs, use a catalog-side script, as described under
"After PRD 10" in `docs/PLAN.md`.

## Development

```
uv sync
uv run pre-commit install
uv run vpress --version
uv run pytest
```

The tool operates on a **catalog directory that lives outside this repo**. A tiny
fixture catalog under `tests/fixtures/catalog/` exists for tests only.
