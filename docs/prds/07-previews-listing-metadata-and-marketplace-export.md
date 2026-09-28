# PRD 7 — Previews, Listing Metadata, and Marketplace Export

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

**Goal.** Each built product has marketplace-ready preview images, an authoritative
listing record, and per-marketplace export files.

**Decisions.** ADR 0014 (rendering, fonts, placement, presentation hash), ADR 0015
(templates), ADR 0016 (listing drafting), ADR 0017 (exporters and limits), ADR 0018
(AI disclosure). Settled 2026-09-28 against the real catalog.

**Scope.**

*Build outputs.* `vpress build <slug>` still writes `builds/<slug>/` in one
all-or-nothing swap, now also containing `previews/` and `export/` beside the
package, ZIP and `manifest.json`. Neither is ever inside the package or ZIP (§14). A
preview or export failure fails the whole build; there is no `--no-previews`.

*Rendering (ADR 0014).* Jinja HTML/CSS templates screenshotted by Playwright's
Chromium (`uv add playwright`; CI installs Chromium on ubuntu and windows). SVG
derivatives are drawn as SVG. No network, no system fonts: every request outside the
build's temporary directory and the catalog fails the build. Previews are not held to
byte-identical output; tests assert file set, pixel size and rendered HTML, not image
bytes.

*Canvases and format.* Every preview type renders at two fixed canvases, `square`
2000×2000 and `landscape` 2400×1600 (3:2), as PNG. Names are
`previews/<nn>-<type>-<canvas>.png`; `nn` is fixed per type and sets upload order.

*Preview types (§16).* Drawn only from the manifest's included members (admitted-
unapproved yes, excluded never), using each member's effective derivative.

| nn | Type | Shows | Rendered when |
| --- | --- | --- | --- |
| 01 | `main` | title, member count, format badges, up to 9 featured members | always |
| 02 | `included` | up to 12 members, labeled with display names | always |
| 03 | `formats` | a badge per format folder with its file count and a one-line use | always |
| 04 | `variants` | the first featured member once per included derivative type, labeled | 2+ derivative types |
| 05 | `contents` | every member, labeled; pages `05-contents-1`, `-2`… at 48 per page | more than 12 members |

A left-out type leaves its number unused. Where one image stands for a member
(`main`, `included`, `contents`), it is the first included type in the order
`flatcolor_svg`, `transparent_png`, `silhouette_svg`, `cut_svg`. Featured members come
from an optional hand-authored `[previews] featured = [asset IDs]` in `product.toml`,
then the rest in `display_name` order; a featured ID that is not a resolved member is
a product metadata problem at load time.

*Templates (ADR 0015).* Shipped as package data under
`vectorpress/build/templates/{previews,listing,export}/`. Previews: `_base.html.j2`,
`brand.css`, and one `<type>.html.j2` per preview type. A file at
`<catalog>/templates/<kind>/<same name>` replaces the shipped one (catalog searched
first; `{% extends %}` works across both). The preview context is exactly `canvas`
(name, width, height), `brand` (name, mark_url, heading_font, body_font, colors),
`product` (slug, title, short_title, tier, family, member_count, derivative_types
with labels, formats with file counts), `members` (display_name, image_url,
images_by_type), `featured`, and `page` (number, count; `contents` only). An undefined
variable fails the build naming the template. The build report lists every catalog
override in use. Rights status is not in the preview context.

*Brand (§17, §27).* `brand.name`, `typography`, `card_style` and `mark_file` become
CSS variables and `@font-face` rules in `_base.html.j2`. The tool ships Inter and
Space Grotesk (SIL OFL, license included). `[typography]` gains optional
`heading_font_file` and `body_font_file` (catalog-relative, `.ttf`/`.otf`/`.woff2`);
without one, the family name must be a shipped font, else it is a brand metadata
problem naming the field. `mark_file` may be PNG or SVG.

*Manifest and needs-rebuild.* The manifest gains the preview file names, a
**presentation hash** (every template file used, shipped or override; brand `name`,
`typography`, `card_style`; mark and font file bytes; the listing fields templates
print) and a **listing hash** (the `[listing]` table), and the export warnings. Never
image hashes. Needs-rebuild gains two reasons: **previews out of date** (presentation
hash differs) and **listing changed** (listing hash differs).

*Listing drafting (ADR 0016).* `vpress listing draft <slug>` appends a `[listing]`
table to `products/<slug>.toml` only when the file has no `listing` at all; any
listing present, valid or not, makes it refuse and write nothing. It appends raw text
(never round-trips the TOML), keeps the file's line endings, re-parses and validates
the result as a product before an atomic replace, and opens the table with a comment
naming the command, the date, and that the tool never rewrites it. `vpress build`
never writes `product.toml` and refuses a product with no `[listing]`, naming the
command. Drafted values (title and description text from overridable
`templates/listing/*.j2`):

| Field | Drafted from |
| --- | --- |
| `title` | collection name + format phrase ("Rock Climbing Icons – SVG, PNG & DXF Cut Files"); never a count |
| `short_title` | collection name; for an inline membership, the slug title-cased |
| `description` | collection description, then brand `standard_wording`; never a count |
| `tags` | collection tags + fixed words for included types and formats, deduplicated; never member tags |
| `search_terms` | members' display names, lower-cased |
| `intended_uses` | union of members' `product_use_categories`, most common first |
| `region` | the one region every member shares, else unset |
| `species_names` | members' non-empty `scientific_name`, sorted |
| `category` | collection `marketplace_category`; `""` for an inline membership |
| `license_type` | brand `license_name` |
| `marketplace_notes` | `""` |

The draft enforces no marketplace limit.

*Price.* `Listing.suggested_price` is removed; `product.price` is the one price and
every export prints it. A `[listing]` that still has `suggested_price` is a metadata
problem. The fixture product is updated.

*Exporters (ADR 0017).* Written to `builds/<slug>/export/`:

- `listing.json`: the listing, §18's derived values (member count, formats, asset
  names, collection name), the contents summary, price, AI disclosure
  (`count`, `total`, `text`, or absent), the ordered preview file names per canvas,
  and the ZIP name and size. No CSV.
- `etsy.txt`, `creative-fabrica.txt`, `design-bundles.txt`, `direct-store.txt`: plain
  text, one labeled section per form field in form order (TITLE, DESCRIPTION, TAGS in
  that marketplace's separator, PRICE, CATEGORY, WHO MADE where asked, IMAGES naming
  the preview files to upload in order from the marketplace's canvas, FILES naming
  the ZIP). Etsy and direct store use `square`; Creative Fabrica and Design Bundles
  use `landscape`.
- Every DESCRIPTION is the listing description, then the **contents summary** (member
  count, formats, file names, the reference size files are checked at) built from
  the manifest, then the AI disclosure if any.

*Limits (ADR 0017).* One table in code; each entry cites a source URL and "checked
2026-09-28". Enforced, and only these:

| Marketplace | Limit | Source |
| --- | --- | --- |
| Etsy | title ≤ 140 chars; `%`, `:`, `&`, `+` at most once each | help.etsy.com/hc/en-us/articles/115015628707; etsy.com/openapi/generated/oas/3.0.0.json |
| Etsy | ≤ 13 tags, each ≤ 20 chars, only letters, digits, space, `-`, `'`, ™©® | same |
| Etsy | ZIP ≤ 20 MB; ≤ 20 images | help.etsy.com/hc/en-us/articles/115015628347; …/115015628707 |
| Creative Fabrica | one ZIP, no ZIP inside it; images 3:2, ≥ 600×400 | help.creativefabrica.com/hc/en-us/articles/25796577543196; …/360021068439 |
| Design Bundles | ZIP < 1 GB, no ZIP inside it | fontbundles.freshdesk.com/en/support/solutions/articles/42000103843 |
| Direct store | ≤ 250 tags, each ≤ 255 chars (Shopify); ≤ 8 cover images (Gumroad) | shopify.dev/docs/api/admin-rest/latest/resources/product; gumroad.com/help/article/60-adding-a-cover-image |

Description length is not enforced anywhere (no primary source). A violation is
reported by the build (marketplace, field, measure), recorded in the manifest, and
flagged inline in the bundle; the text is never truncated and the build never
refuses. Items past a count limit are listed under "does not fit", not dropped.

*AI disclosure (ADR 0018).* When any included asset's rights status (from the
manifest) is `ai_generated`, `templates/export/ai_disclosure.j2` renders a sentence
whose default states the count ("20 of 20 designs in this pack were created with
generative AI image tools and converted to vector files"). It ends every bundle's
DESCRIPTION. Etsy's bundle gives WHO MADE "I did (Designed by a seller)"; Creative
Fabrica's gives CATEGORY as its AI category, the listing category as a note. With no
AI member: no disclosure and no category change. Licensing notes are never exported.
Disclosure is never on previews, README or LICENSE.

**Out of scope.** For PRD 8: §18 product version and creation/update date (from
publication snapshots; exports omit them), publishing, frozen membership, needs-rebuild
in the attention inbox, and whether export warnings block publishing. Future: marketplace
APIs and upload, physical mockups (§16), a catalog-wide CSV, a `vpress template copy`
command, PDF/EPS. The catalog's own `tools/import_set.py` contact sheets are not
replaced or read.

**Real-catalog check.** Settle and demo against `rock-climbing-cut-files` in
`vectorpress-catalog`: `collection_slug = "rock_climbing_icons"` (20 members),
`derivative_types = ["cut_svg", "silhouette_svg", "transparent_png"]`,
`formats = ["svg", "png", "dxf"]`, `tier = "standard_pack"`,
`ineligible_members = "exclude"`. Precondition, owner: catalog: the 20 `rc_*` assets
move from `rights_review_required` (which blocks) to `ai_generated`, with
`licensing_notes` naming the AI tool and its commercial-use terms. No font or mark
work is required first.

**Acceptance.**

- `vpress listing draft` on a fixture product without a listing appends exactly the
  drafted table; every pre-existing byte of the file is unchanged; running it again,
  or on a product with a partial listing, refuses and changes nothing.
- `vpress build` on a product without a listing refuses naming the draft command and
  writes nothing.
- Building the fixture product produces `previews/` with `01`–`05` at both canvases at
  the right pixel sizes, and a product with one derivative type and ≤ 12 members
  produces no `04` or `05`. No preview or export file is inside the ZIP.
- A catalog `templates/previews/brand.css` override changes the rendered HTML and is
  named in the build report; a template reading an undefined variable fails the
  build naming it; a template referencing a remote URL fails the build.
- Changing `card_style` in `brand.toml` makes every built product report needs-rebuild
  with "previews out of date", with no product file changed; rebuilding changes the
  previews. Editing listing text reports "listing changed"; rebuilding carries the
  edit into every export, and the listing is never rewritten.
- The Etsy bundle for a product with a 141-character title and 14 tags flags the
  title, lists the 14th tag under "does not fit", and the build still succeeds with
  the warnings in the manifest.
- A product with one `ai_generated` member of three gets "1 of 3" disclosure in every
  bundle and `listing.json`, Creative Fabrica's AI category, and no licensing notes
  anywhere in `builds/`; a product with none gets no disclosure.
- A brand naming a font the tool does not ship, with no font file, is a brand
  metadata problem and the build refuses.
- The real-catalog product builds and its Etsy bundle can be pasted into Etsy's form
  field by field.

**Cites.** §16, §17, §18, §19, §26, §27, §36.
