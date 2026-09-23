# 0001 — Python core, CLI first, logic-free UI later

Status: accepted
Date: 2026-09-22

## Context

The hard parts of the system are raster→vector tracing, geometry validation at a
physical reference size, DXF export, and rendering previews. The judgment steps of the
workflow (§24) need eyes; the batch steps do not.

## Decision

- Python 3.12+ for the whole core. Tracing (potrace/vtracer), geometry (shapely),
  DXF (ezdxf), imaging (Pillow/OpenCV) are all first-class there.
- The CLI (`vpress`, typer) is the first and, for several PRDs, only interface.
- A local browser UI (FastAPI + Jinja + HTMX, no JS build step) is added by its own
  PRD. It holds no logic and calls the same functions the CLI calls. No in-browser
  vector editing; hand edits happen in an external editor (Inkscape).

## Consequences

- The core must be a clean library from day one; the CLI is a thin adapter.
- Layering is enforced by import-linter (see 0006).
- A second toolchain (Node) is deliberately avoided.
