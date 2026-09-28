# 0014 — Previews render in headless Chromium from font files, never system or web fonts, and are not byte-identical

Status: accepted (amends 0008's preview section)
Date: 2026-09-28

## Context

ADR 0008 chose HTML/CSS Jinja templates rendered headlessly with Playwright. Settling
PRD 7, that choice was re-examined against its costs: a separately installed
Chromium (~150 MB, needed on both CI runners), output that differs by OS and Chromium
version (font rasterizing, antialiasing), and silent font fallback when a brand font
is not installed.

## Decision

- Keep ADR 0008: previews are Jinja HTML/CSS templates screenshotted by Playwright's
  Chromium. Chromium draws SVG derivatives natively, so cut and silhouette variants
  are shown as vectors, not through a PNG stand-in.
- Rendering uses **no network and no system fonts**. The tool ships two default fonts
  under the SIL Open Font License, Inter and Space Grotesk, with their license.
  `[typography]` may name a font file (`heading_font_file`, `body_font_file`, relative
  to the catalog root, `.ttf`/`.otf`/`.woff2`); without one, the family name must be
  a font the tool ships, else it is a brand metadata problem naming the missing
  field. A build refuses on an invalid brand (PRD 6), so a font never silently falls
  back. A template cannot pull a web font or remote asset. The mark (`mark_file`) may
  be PNG or SVG; replacing the file needs no config change.
- Previews are **not held to byte-identical output**. §36 promises the same *logical*
  contents; previews are therefore kept out of what repeatability compares.
- Previews live **beside the package, never in it**: `builds/<slug>/previews/`. They
  are marketing, not customer files (§14). They render inside the build's temporary
  directory, so the existing all-or-nothing swap covers them: a rendering failure
  (no Chromium, a missing font file) fails the whole build, and a new ZIP never sits
  beside old previews. There is no `--no-previews` escape hatch.
- The manifest records preview file names and a **presentation hash**, never image
  hashes: the hash of every template file used (shipped or catalog override), the
  brand's presentation fields (`name`, `typography`, `card_style`), the mark and
  font file bytes, and the listing fields templates print. As with provenance
  (ADR 0004), inputs are hashed, not output.
- Needs-rebuild gains a reason, **previews out of date**, when the presentation hash
  differs. A brand edit therefore reaches every product as "needs rebuild" without
  touching any `product.toml`.

## Rejected alternatives

- **Pure Python drawing (Pillow).** Deterministic and browser-free, but it cannot
  draw SVGs without cairo (painful on Windows), so every preview would show PNGs; text
  layout is hand-coded; and a catalog could only override a template by writing
  Python, which defeats "a catalog can override any template".

## Consequences

- `playwright` is added by PRD 7 via `uv add`; CI installs Chromium on both runners.
- Preview tests assert structure (which files, their pixel size, the rendered HTML),
  not image bytes.
