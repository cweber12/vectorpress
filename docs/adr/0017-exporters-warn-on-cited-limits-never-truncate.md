# 0017 — Exporters enforce only cited marketplace limits, and warn rather than truncate or refuse

Status: accepted (amends 0008's "generic JSON/CSV")
Date: 2026-09-28

## Context

§19 and ADR 0008 ask for exporters that "enforce known field limits". Researching
the four target channels (2026-09-28) confirmed hard limits for Etsy and a few file
and image rules elsewhere, but no primary source for most title, description or tag
limits on Creative Fabrica and Design Bundles. A listing is user-owned text
(ADR 0016), and one marketplace's form should not decide whether a package builds.

## Decision

- Exporters run inside `vpress build` and write `builds/<slug>/export/` in the same
  all-or-nothing swap: `listing.json` (the generic export; no CSV) and one pasteable
  text bundle per marketplace (`etsy.txt`, `creative-fabrica.txt`,
  `design-bundles.txt`, `direct-store.txt`), one labeled section per form field.
- Limits live in one table in code. Every entry cites its source URL and the date it
  was checked. A limit with no primary source is not enforced; no number is guessed.
- A field over a limit is **reported, never truncated, never refused**: the build
  reports marketplace, field and measure, the manifest records it, and the bundle
  flags the field inline. Items past a count limit (Etsy's 14th tag) are listed as
  "does not fit", not dropped.
- Needs-rebuild gains a reason, **listing changed**, from a hash of the `[listing]`
  table.

## Rejected alternatives

- **Truncate to fit.** Silently changes user-owned text; a cut title reads worse
  than a warning.
- **Refuse the build.** Blocks a correct package over one marketplace's form.

## Consequences

- Marketplace limits change without notice; updating one is a code change with a new
  source date. Stale limits make warnings wrong, never text wrong.
