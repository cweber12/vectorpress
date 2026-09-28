# vectorpress domain context

The vocabulary the code, tests, issues and docs use. When a term here has an
"avoid" note, do not use the avoided synonym.

## Glossary

**Catalog** — A directory (its own git repo, outside the tool) holding everything for
one brand: assets, collections, products, brand config, and tool-owned state. Located
by a root `catalog.toml`. The tool is *pointed at* a catalog; it never lives inside one.

**Asset** — The identity of one design subject (`ochre_sea_star`). Owns metadata,
rights status and accuracy status. Has one or more source images. Avoid: "design",
"subject" (in code; "subject" is fine in prose about the artwork).

**Asset ID** — The stable snake_case identifier of an asset, also its folder name.
Never customer-facing.

**Source image** — A preserved input file under an asset's `sources/`. Each has a
**role**. Never modified by the tool. Avoid: "master file", "original" (say "source").

**Role** — What kind of artwork a source image is: `silhouette`, `lineart`,
`flatcolor`, `detailed` (extensible). Recipes select sources by role.

**Derivative** — A generated (or overridden) output file for one asset and one
**derivative type**. Has status and provenance. Avoid: "variant" (reserved for color
variants), "output" (ambiguous with build output).

**Derivative type** — One of the standardized outputs: `transparent_png`,
`silhouette_svg`, `cut_svg`, `flatcolor_svg`, `outline_svg`, `detailed_mono_svg`,
`layered_svg`. Each has a **recipe**.

**Recipe** — The declaration of how a derivative type is produced: which roles it
accepts in preference order, the generator, and its parameters. The recipe identity
(including parameters) is part of provenance.

**Color variant** — A mechanical recolor of a parent derivative (black, white,
palette). Inherits the parent's status; not separately approved.

**Provenance** — Tool-owned record for a derivative: source hash, recipe identity,
generator versions, output hash. Content-addressed; no version numbers.

**Stale** — A derivative with a provenance record that no longer matches what it was
built from or what is on disk, for one of three reasons: `source changed` (the
recorded source hash no longer matches the content of the currently selected
source — either the source itself changed, or a pin changed which source is
selected), `recipe changed` (the recorded recipe identity no longer matches the
current recipe — a parameter or generator change), or `output changed on disk` (the
output file's hash no longer matches the recorded output hash — hand-edited or
replaced; a hand edit belongs under `overrides/`, not `derived/`). A derivative
whose output file is gone is **missing**, not stale. An **override** is stale when
the source it was edited against has changed.

**Override** — A hand-edited derivative placed under `overrides/`. It is the
**effective derivative** for that type, is validated and approved like any other, is
never overwritten, and can be discarded to revert to the generated version.
`vpress open --override` may create one, on that explicit request only, by
copying the current generated file into `overrides/`: create-only, never
overwriting an override already there. `vpress override discard --yes` removes
one, on that explicit, confirmed request only. Creating and discarding are the
only two writes the tool ever makes under `overrides/`. Discarding also clears
the override's own provenance, status and findings, so a later override at the
same path starts fresh rather than inheriting them.

**Effective derivative** — The file a product actually uses for a given asset and
derivative type: the override if present, else the generated file.

**Status** — Per (asset, derivative type): `generated`, `needs_review`, `approved`,
`rejected`, `regenerate`. Lives in tool-owned state.

**Derivative state** — Per (asset, derivative type), whether a derivative can exist
at all and whether it does yet: `impossible` (no declared source has a role its
recipe accepts), `missing` (a source is selectable but no derivative exists, or its
file has been deleted), `current` (the derivative exists and matches its selected
source and recipe), or `stale` (it exists but does not — see **Stale** for its three
reasons). Not "status" — status is about review of a derivative that exists,
derivative state is about whether one can and does exist.

**Findings** — Structured cut-file quality problems (§9) with locations. A cut file
resolves to **pass** or **needs review** from its findings. Tool-owned JSON state
beside the effective derivative under `derived/` (ADR 0005, ADR 0007) — never inside
the SVG, never in hand-authored TOML. Not **Status**: a findings result is a
mechanical roll-up from validation, not a human review decision.

**Reference size** — The physical size (e.g. 3 in on the longest side) at which
cut-file thresholds are evaluated. Catalog default; product override; recorded with
findings. A product override changes validation only (ADR 0012).

**Cleanup size** — The reference size an asset's one cut file is cleaned at: the
asset's own setting, else the catalog default (ADR 0012). A product sold larger than
a member's cleanup size gets a build warning, since removed detail cannot surface as
findings.

**Brand config** — The catalog's `brand.toml`: name, mark, typography, card style,
wording, and the license template shipped as every package's `LICENSE.txt` (§27).
Required to build; optional to load a catalog.

**Rights status** — Asset-level licensing state (§26). Hand-authored. Mixes origin
(`original_artwork`, `licensed_source`, `public_domain_source`, `ai_generated`) with
verification (`rights_verified`, `rights_review_required`, `do_not_publish`).

**AI-generated** — The rights status of an asset whose artwork came from an AI image
tool whose terms permit commercial use. Not blocking, but requires licensing notes
naming the tool and terms. Permanent: hand edits (overrides) do not remove it.

**AI disclosure** — The sentence, and any marketplace category choice, telling buyers
how many of a build's included designs are AI-generated. Added by exporters only;
never on previews, never in the package. Never names the AI tool.

**Accuracy status** — Asset-level scientific-accuracy state (§25). Hand-authored.

**Blocked** — An asset excluded from sellable packages by a publication blocking rule
(§10.1). Distinct from a **warning**, which does not block.

**Eligible** — An asset that, for a given set of derivative types, has every included
effective derivative approved and is not blocked.

**Excluded member** — A member of a product's collection left out of its build
because it is not eligible, under a product set to `exclude`. A product set to
`refuse` (the default) fails to build instead. Recorded with reasons in the manifest.

**Collection** — A named membership of assets: explicit list, metadata rule, union of
other collections, or a mix. Not sellable; has no formats or price.

**Product** — One collection (or an inline one) plus presentation: included derivative
types, formats, reference size override, listing, price, publication state. The only
thing that is built. Avoid: "pack", "bundle" (those are **tier** labels).

**Tier** — A label on a product (`individual`, `mini_pack`, `standard_pack`,
`collection`, `mega_bundle`) used for badges and categories. Not a mechanism.

**Family** — A label grouping related products for shared branding and related-product
references. Not a mechanism.

**Build** — Producing a product's package, ZIP, previews, listing and exports from
effective derivatives. Writes a **manifest**.

**Manifest** — Tool-owned record of exactly which assets, derivative types and content
hashes a build contained, plus reference size and tool version.

**Needs rebuild** — A product whose last manifest no longer matches current effective
derivatives, brand wording, or what its previews are drawn from (**previews out of
date**).

**Package** — The customer-facing directory structure (§14). **ZIP** is the package
archived.

**Preview** — A marketplace image rendered from an HTML template with brand config.
Build output beside the package, never inside it; no status. Avoid: "mockup" (a
future physical-item render, §16), "contact sheet" (the catalog's own review page).

**Preview type** — One of the fixed §16 previews: `main`, `included`, `formats`,
`variants` (only with two or more derivative types), `contents` (only when members
outnumber what `included` shows). Each has a fixed number that sets upload order.

**Canvas** — A fixed preview image size every preview type is rendered at: `square`
(2000×2000) or `landscape` (3:2, 2400×1600). Marketplaces differ in image shape, not
content.

**Featured member** — A member a product names, in `[previews] featured`, to lead its
main and variants previews. Without the list, members lead in display-name order.

**Listing** — The authoritative marketing metadata for a product (§18): the
`[listing]` table of its `product.toml`. Drafted by the tool only on explicit request
and only when none exists (create-only), then user-owned. A product without one
cannot build.

**Contents summary** — The "what's included" facts (member count, formats, file
names, reference size) built from a build's manifest and placed after a listing's
description by exporters. Never stored in the listing, so it cannot go stale.

**Exporter** — A file-only projection of a listing into a marketplace's shape.

**Publish / Publication snapshot** — A user-declared record that a build was uploaded
somewhere: timestamp, manifest, free-text references. Freezes membership.

**Frozen** — A published product whose membership no longer follows its collection
rule automatically.

**Proposed update** — A membership change a rule would make to a frozen product,
awaiting accept/reject.

**Attention report / Inbox** — The single list of everything needing a human:
needs-review derivatives, stale overrides, blocked assets, missing derivatives,
missing metadata, proposed updates, needs-rebuild products. Empty inbox = publishable
catalog. The CLI and UI show the same one.

## Layers (import direction)

```
domain  ← catalog  ← pipeline / validate  ← build  ← cli / ui
```

## Status lifecycle

```
generated ──► needs_review ──► approved
                  │               │
                  ▼               ▼ (source or output changes)
              rejected        needs_review
                  │
                  ▼
              regenerate ──► (regeneration) ──► generated
```

Unchanged output on regeneration keeps its status (§22.1), except a derivative marked
`regenerate`: a human asked for a new take, so it returns to `needs_review` either way.
