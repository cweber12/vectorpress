# vectorpress — Repo Setup, Scaffolding, and PRD Roadmap

Source of truth for requirements: `docs/requirements.md` (the SVG Asset Production
System requirements, rev 2). PRDs cite it by section number (e.g. §9.1).

This document has three parts:

1. **Decisions** — what was settled in the planning interview and why.
2. **Repo setup and scaffolding** — what exists before the first PRD starts.
3. **PRD roadmap** — the sequence of implementation chunks. Each PRD states *what*,
   not *how*, so it can be expanded into issues against whatever the codebase looks
   like when its turn comes.

---

## Part 1 — Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Python 3.12+ for the entire core.** | Tracing (potrace, vtracer), geometry validation (shapely), DXF (ezdxf), image cleanup (Pillow/OpenCV), and SVG rasterization all have first-class Python libraries. Any other language shells out to half of them. |
| D2 | **CLI first; local browser UI later.** UI holds no logic and calls the same functions the CLI calls. | The pipeline is where the unknowns are. A logic-free UI can be inserted at any point after review exists. |
| D3 | **The catalog is a separate directory (its own git repo) that the tool is pointed at.** The tool repo carries only a small fixture catalog for tests. | Keeps binary artwork out of code history; makes a second catalog free; keeps the tool honest about generality (§38). |
| D4 | **Generated derivatives and overrides are committed in the catalog repo.** Product ZIPs and previews are output, not committed. | Approval applies to specific file content (§22.1). Committing makes "approved" refer to a real file. |
| D5 | **Three-level asset model: Asset → Source Image (with a *role*) → Derivative (with a *type*).** Recipes declare which source roles each derivative type can be built from, in preference order. | The spec never says which source produces which derivative. Making it declarative lets "missing" vs. "impossible" derivatives be computed (§34) and isolates tracing from the catalog. |
| D6 | **Derivative status is per (asset, derivative type).** Alternate color variants inherit their parent derivative's status. | Color variants are mechanical recolors; separate approval is bookkeeping with no decision behind it. |
| D7 | **Content-addressed provenance; no manually bumped version numbers.** Staleness, "output changed", stale overrides, and "product current" are all hash comparisons. Tracing parameters are part of the recipe hash. | Version numbers drift from reality. Hashes make §22–23 exact and §36 repeatability free. |
| D8 | **Every product build writes a manifest** listing exactly which asset/derivative hashes it contains. | Enables "is this product current" and enforces the no-removal rule (§23.1) against the last published manifest. |
| D9 | **TOML for hand-authored files, JSON for machine-written files. The tool never rewrites a hand-authored file.** Exception: one-time drafting of a product's listing text on first build. | Preserves user comments and ordering; prevents CLI and UI from clobbering each other. |
| D10 | **Rights status and accuracy status live in `asset.toml`; all generated-thing status lives in tool-owned state files.** | Rights/accuracy are human judgments about the subject; review status is about a specific generated file (D6). |
| D11 | **Schema validation on load (pydantic); typos fail loudly with file and field.** | A silently blank product is worse than an error. |
| D12 | **Cut file = silhouette source + aggressive deterministic cleanup at the reference size + a findings report with geometry.** Overrides are the primary path for cut files, not the exception. **No auto-bridging of disconnected fragments.** | No tracer knows what an "identifying detail" is. Automation produces a good draft and locates the problems; the human fixes them in Inkscape. |
| D13 | **Collection = membership (explicit list, metadata rule, or union of other collections). Product = one collection + presentation (derivative types, formats, listing, price, publication state).** Only products are built. Products may declare an inline collection for the single-asset case. Tier and family are labels, not mechanisms. | The same membership sells as several products (full / cut-only / PNG-only); §10 requires that. Mega bundles are union collections. |
| D14 | **Previews are HTML/CSS templates rendered headlessly (Playwright).** Brand config becomes CSS variables. Templates ship with the tool; the catalog may override them. **Previews have no approval state.** | Layout and typography become a design task, not a programming task. Previews are pure functions of approved inputs; fixing one means fixing a template or an asset. |
| D15 | **Publication is a user-declared snapshot** (timestamp + built manifest hash + free-text marketplace notes). The tool knows no marketplace APIs. | Consistent with §37. Marketplace APIs are where solo tools die. |
| D16 | **Marketplace export = file-only exporters** projecting one authoritative listing record into a generic JSON/CSV plus per-marketplace text bundles (encoding known limits, e.g. Etsy tag rules). | Copy-paste is the integration. |
| D17 | **Review UI = FastAPI + Jinja + HTMX, no JS build step. Organized as an inbox, not a file browser.** No in-browser vector editing; "open in editor" launches Inkscape. | A handful of pages of forms and images does not justify a second toolchain. Empty inbox = publishable catalog, and the CLI prints the same inbox. |
| D18 | **Single package with layers enforced by import direction** (`domain ← catalog ← pipeline/validate ← build ← cli/ui`), checked in CI. | Cheap to enforce, and the only thing that keeps D2 true after several PRDs. |
| D19 | **Snapshot (golden-file) tests of SVG output and findings JSON against the fixture catalog.** | Tracer output can't be unit-asserted; snapshots catch regressions on library upgrades and show the blast radius of parameter changes. |
| D20 | **Package name `vectorpress`, CLI `vpress`.** GitHub for repo and issues. | Descriptive, unique, cheap to rename now. |

---

## Part 2 — Repo Setup and Scaffolding

This is done once, before PRD 1, and is not itself a PRD. It should take a day.

### 2.1 Repository

- `git init`, default branch `main`, hosted on GitHub.
- Conventional commits. Squash-merge PRs so `main` history is one commit per PR.
- Branch protection on `main`: CI must pass.

### 2.2 Layout

```
vectorpress/
  pyproject.toml            uv-managed; package metadata, tool config
  uv.lock
  .pre-commit-config.yaml
  .github/
    workflows/ci.yml        lint, type-check, test on push and PR
    ISSUE_TEMPLATE/         feature / bug / prd-task templates
    PULL_REQUEST_TEMPLATE.md
  docs/
    requirements.md         the requirements doc, moved here verbatim
    PLAN.md                 this file
    prds/                   one file per PRD, NN-name.md, created as each PRD is expanded
    adr/                    architecture decision records for anything that changes Part 1
  src/vectorpress/
    __init__.py
    domain/                 pydantic models only; no I/O
    catalog/                on-disk layout, loading, state files, provenance
    pipeline/               derivative generators, one module per derivative type
    validate/               findings; pure functions over geometry
    build/                  collection resolution, product build, manifest, zip, previews, exporters
    cli/                    typer app; thin
  tests/
    fixtures/catalog/       a tiny, real catalog (3–4 subjects, hand-made PNGs, one collection, one product)
    unit/
    integration/
    __snapshots__/          syrupy golden files
  CLAUDE.md                 conventions for agents working in this repo
  README.md
```

Not every directory has content at scaffold time; empty layer packages exist so the
import-linter contract can be declared on day one.

### 2.3 Toolchain

| Concern | Tool | Notes |
|---|---|---|
| Environment / lockfile | `uv` | `uv sync`, `uv run` |
| Lint + format | `ruff` | strict-ish ruleset; format on commit |
| Types | `pyright` strict | CI-blocking |
| Tests | `pytest`, `syrupy` | snapshots for SVG and findings output |
| Layering | `import-linter` | contract encoding D18 |
| Hooks | `pre-commit` | ruff, pyright, import-linter |
| CLI | `typer` | |
| Schemas | `pydantic` v2 | |
| CI | GitHub Actions | ubuntu + windows matrix (the tool runs on Windows) |

Heavy runtime dependencies (potrace, vtracer, shapely, ezdxf, Pillow, Playwright) are
**added by the PRD that first needs them**, not at scaffold time. The scaffold adds
only the toolchain above.

### 2.4 Scaffold deliverables

- `vpress --version` works from a fresh `uv sync`.
- CI is green on an empty package.
- `CLAUDE.md` states: the layering rule, "never write hand-authored files", TOML/JSON
  split, snapshot-test expectations, and how to add a PRD and expand it into issues.
- Issue template `prd-task` links back to the PRD file and section.

### 2.5 PRD → issues process

1. Each PRD is `docs/prds/NN-name.md` with: Goal, Scope, Out of scope, Acceptance
   criteria (in the "user can…" style of §39), Dependencies, Requirements sections cited.
2. A PRD is expanded into GitHub issues **only when it is next**, against the codebase as
   it exists then. Issues are vertical slices, each independently mergeable.
3. The PRD file is not edited during implementation. If reality diverges, the change is
   recorded as an ADR and the *next* PRD adapts.
4. Anything in Part 1 that gets overturned gets an ADR.

---

## Part 3 — PRD Roadmap

Ten PRDs, sequential. PRDs 1–8 cover every item in the initial-release acceptance
criteria (§39). PRDs 9–10 complete the spec's derivative types and add the UI.
Each is written as *what*, not *how*.

Dependency graph:

```
1 Catalog foundation
└─ 2 Derivative generation & provenance
   └─ 3 Cut files & validation
      └─ 4 Review, approval & overrides
         └─ 5 Collections & products   (complete)
            └─ 6 Product build & packaging   (complete)
               ├─ 7 Previews, listing & marketplace export   (complete, #129 pending)
               └─ 8 Publication lifecycle
                  └─ 9 Review UI
   └─ 10 Remaining derivative types   (needs 2 and 4; independent of 5–9)
```

### PRD 1 — Catalog Foundation

**Goal.** A catalog directory on disk can be described, loaded, validated, and
inspected. Nothing is generated yet.

**Scope.**
- A catalog root is identified by a root config file and located from the working
  directory or an explicit flag.
- Each master asset is a folder with a hand-authored metadata file and one or more
  preserved source images, each tagged with a role (§4, §5, §41).
- Hand-authored schemas exist for assets, collections, products, brand, and catalog
  config, with the metadata fields in §5, §11, §18, §27 at minimum.
- Rights status (§26) and accuracy status (§25) are asset metadata.
- Loading validates every file and reports errors with file and field.
- The user can list assets, see each asset's sources and roles, and see metadata
  problems (missing required fields, unknown roles, duplicate IDs).
- A fixture catalog exists in the tool repo and every later PRD extends it.

**Out of scope.** Generation, status, collections resolution, products.

**Acceptance.** User can create a catalog with several assets and metadata, run a
status command, and see a correct inventory and a list of metadata problems.
Malformed files fail with actionable errors. Source images are never modified.

**Cites.** §4, §5, §11, §18, §21, §25, §26, §27, §34 (inventory items), §41.

---

### PRD 2 — Derivative Generation and Provenance

**Goal.** Approved-quality derivatives are produced from source images, and every
derivative knows exactly what it was built from.

**Scope.**
- Recipes: each derivative type declares which source roles it accepts, in order of
  preference; the asset may pin a specific source.
- Initial derivative types: transparent PNG (§6.1), solid silhouette SVG (§6.2),
  flat-color SVG (§6.9).
- SVG outputs are true vectors with clean bounds and no stray or invisible content (§8).
- Each derivative has a tool-owned provenance record: source hash, recipe identity
  including parameters, generator versions, output hash.
- Generation is idempotent: unchanged inputs produce byte-identical outputs and no
  state change.
- Staleness is computable: a derivative is stale when its recorded source hash no
  longer matches the source.
- The user can generate for one asset, for all assets, or only for stale derivatives.
- Failures are per-derivative, reported with asset and type, and never leave a
  half-written file or a corrupted state file (§35).
- Customer-facing filenames follow §20.
- "Expected but missing" and "impossible (no acceptable source)" derivatives are
  distinguished in status output (§34).

**Out of scope.** Cut files, validation findings, approval status, overrides.

**Acceptance.** User can generate the three derivative types for the fixture
catalog; regenerating without changes is a no-op; changing a source marks exactly
the affected derivatives stale; a deliberately broken source fails visibly without
touching anything else. Snapshot tests lock output.

**Cites.** §6.1, §6.2, §6.9, §8, §20, §21, §22 (first half), §23, §35, §36.

---

### PRD 3 — Cut-File Derivative and Quality Validation

**Goal.** A cut-file derivative is produced as a manufacturable draft, and every
cut-file problem the spec names is detected and located.

**Scope.**
- A simplified cut-file SVG derivative type (§6.3) built from the silhouette role,
  cleaned deterministically relative to a physical reference size (§9.1).
- Reference size: catalog default, product override; validation thresholds expressed
  in physical units; reference size recorded in the result.
- A findings report per cut file covering the §9 list (open paths, tiny shapes,
  dots, small holes, narrow features, excessive complexity, stray objects, duplicate
  geometry, overlaps, disconnected fragments, raster content). Each finding carries a
  location (bounding box or path reference) so it can be drawn or navigated to.
- Findings are classified so a cut file resolves to *pass* or *needs review* (§9.2).
- Validation runs on any SVG derivative, not only generated ones, so overrides can be
  checked (needed by PRD 4).
- No automatic bridging or joining of fragments.

**Out of scope.** Status changes driven by findings (PRD 4), the UI overlay (PRD 9).

**Acceptance.** User can generate cut files, see a findings report with locations for
each, and see pass / needs-review per file. Fixture catalog includes subjects that
deliberately trip each finding type. Snapshot tests lock findings output.

**Cites.** §6.3, §8, §9, §32.

---

### PRD 4 — Review, Approval, and Overrides

**Goal.** Every derivative has an explicit status, humans control it, hand edits are
first-class, and the catalog can say what needs attention.

**Scope.**
- Per-derivative status with the §10 states; status is tool-owned state, never in
  hand-authored files.
- Regeneration rules (§22.1): changed output returns to needs-review; unchanged output
  keeps status.
- Newly generated cut files enter needs-review or an equivalent state determined by
  PRD 3's pass/review result; other types enter needs-review.
- The user can approve, reject, and mark-for-regeneration one or many derivatives,
  with optional notes.
- Overrides (§6.8): a hand-edited file in the override location is detected, becomes
  the effective version, is validated like any generated file, carries its own status
  and provenance (including the source hash it was edited against), is never
  overwritten, and can be discarded to revert.
- Stale overrides (§22.2) are flagged when the source changes; the user can re-edit,
  keep, or discard.
- Publication eligibility (§10.1) is computable per asset per set of derivative types,
  distinguishing blocking conditions from warnings.
- An "attention" report (the inbox, §34): needs-review derivatives, stale overrides,
  blocked assets with reasons, missing expected derivatives, missing metadata. An
  "open in editor" command launches the configured external editor on a derivative.

**Out of scope.** Collections, products, proposed-update queue (PRD 8), the UI.

**Acceptance.** User can review and approve every fixture derivative from the CLI;
a hand-edited cut file survives regeneration (§39.16); a source change flags the
override stale; blocked assets are listed with reasons; the attention report is
empty when everything is approved.

**Cites.** §6.8, §10, §22, §24, §34, §35.

---

### PRD 5 — Collections and Products

**Goal.** Assets are grouped into collections by rule or list, and products define
what is sold from a collection, without building anything yet.

**Scope.**
- Collection definitions: explicit asset list, metadata rules over asset
  classifications, union of other collections, or a mix (§11, §12).
- Product definitions: exactly one collection (or an inline one), included derivative
  types, included formats (§7), reference cut size override, tier and family labels,
  listing metadata fields (§18), price.
- Resolution: the user can see a collection's current members and a product's
  effective contents, including which members are eligible, which are excluded and
  why (§10.1), and which are missing required derivatives.
- The same asset appearing in many collections and products is the normal case and is
  visible from both directions (§33, §34).
- Products are unfrozen in this PRD; membership follows the rule.

**Out of scope.** Building, packaging, previews, publication.

**Acceptance.** User can define a rule-based collection and an explicit one, define
several products over the same collection with different derivative types, resolve
each, and see the correct eligible/excluded/missing breakdown. Adding a matching
asset to the catalog appears in the rule-based collection without editing it.

**Cites.** §7, §10.1, §11, §12, §13, §28, §33, §34.

---

### PRD 6 — Product Build and Packaging

**Goal.** A product resolves into a complete, repeatable, customer-ready package and
ZIP.

**Scope.**
- A build produces the customer package structure (§14) from eligible members'
  effective derivatives (override wins), organized by format, with brand README and
  LICENSE (§27).
- Format conversion for included formats: SVG, PNG, DXF (§7). PDF/EPS remain
  disabled. Folders are filled by ADR 0013's fixed table: `SVG/` from every included
  `*_svg` type, `PNG/` from `transparent_png`, `DXF/` converted from `cut_svg` (else
  `silhouette_svg`). No rasterizing, no vectorizing. A format/type mismatch is a
  product metadata problem at load time.
- Every build writes a manifest recording each included asset, derivative type, and
  content hash, plus the reference size and tool version.
- A predictable, marketplace-friendly ZIP (§15) containing only the package.
- Customer file names come from the asset's `display_name`, slugified, plus the §20
  type suffix (`carabiner-cut.svg`), never from the asset ID. Two members whose names
  collide in one package fail the build naming both assets; no numeric suffixes.
  The ZIP and its top-level folder are named from the listing's `short_title`, else
  the product slug, in Title-Case-Hyphen form (`Rock-Climbing-Icons.zip`), with no
  version or date, so a rebuild replaces it in place.
- "Needs rebuild" is computable by comparing the last manifest to current effective
  derivatives (§23).
- Builds are all-or-nothing per product; a failing asset fails the product build with
  a clear message and does not corrupt other products (§35).
- Unapproved or blocked members are excluded, or the build refuses, per product
  configuration (§10): `ineligible_members = "refuse" | "exclude"` in
  `product.toml`, default `refuse`. Eligibility considers only the product's
  included derivative types. `exclude` ships the eligible members, reports and
  records each excluded member with its reasons, and still refuses when none are
  eligible.
- Per-build override `--allow-unapproved` admits included derivatives that are not
  approved (generated, needs review) and records each in the manifest. It never
  admits a `rejected` derivative and never overrides a rights or accuracy block
  (§10.1's "unless explicitly overridden" covers approval only). Whether `exclude`
  may drop a member of a published product (§23.1) is PRD 8's, not this PRD's.
- A build requires a valid `brand.toml` and refuses without one, naming what is
  missing; there is no default brand, since a default would ship as the customer's
  license terms. `Brand` gains a required `license_file` (relative to the catalog
  root): a hand-written license template the build copies to `LICENSE.txt`,
  substituting `{brand}`, `{product}`, `{copyright}` and `{year}`. `README.txt` is
  composed from `readme_text`, `standard_wording`, the included files and formats,
  and `copyright_wording`. Other brand fields stay required though only PRD 7 uses
  them. The tool never varies brand wording by rights status.
- Per-asset cut-file cleanup size (ADR 0012, superseding 0009):
  `[derivatives.cut_svg] reference_size_in` in `asset.toml`, defaulting to the catalog
  size; `source` in that table becomes optional. Excessive complexity is measured at
  the cleanup size (ADR 0010 as amended). A build warns, recorded in the manifest,
  for each member whose cleanup size is smaller than the product's reference size.
  The packaged SVG carries no physical units; the product's reference size is what
  the README states the files are checked at.
- A build warns, and records in the manifest, when two included derivatives of one
  member are byte-identical (e.g. a one-color asset's `silhouette_svg` and
  `flatcolor_svg`), since shipping both is an accidental duplicate (§20). It does
  not drop either: package contents follow the product definition, not file
  contents. The fix is catalog-side (declare no `flatcolor` source for one-color
  art, making `flatcolor_svg` impossible).
- Rights status gains `ai_generated` (§26): not blocking, but an `ai_generated`
  asset with empty `licensing_notes` is blocked with its own reason. The manifest
  records each included asset's rights status so PRD 7 can disclose AI use.

**Out of scope.** Previews, listing text, exporters, publication.

**Acceptance.** User can build the fixture product, unzip it, and find only customer
files with consistent names; rebuilding with no changes produces the same logical
contents; changing one source makes exactly the containing products report
needs-rebuild; a rejected cut file is excluded from a cut-file product while the same
asset ships in a PNG product. Also: a build without a valid `brand.toml` refuses;
a `refuse` product with an ineligible member fails while an `exclude` one ships the
rest; an `ai_generated` asset with empty licensing notes is blocked; a product whose
reference size exceeds a member's cleanup size warns; a format/type mismatch is
reported at load.

**Cites.** §7, §10, §14, §15, §20, §23, §26, §35, §36.

---

### PRD 7 — Previews, Listing Metadata, and Marketplace Export

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

---

### PRD 8 — Publication Lifecycle

**Goal.** The catalog knows which products are live and protects them from silent
change.

**Scope.**
- Publish action records a snapshot: timestamp, the built manifest, and free-text
  marketplace references. Multiple snapshots per product.
- Published products have frozen membership (§12.1); rule changes surface as proposed
  additions/removals the user accepts or rejects individually.
- Rebuilds of published products may add or improve, never remove, relative to any
  prior snapshot (§23.1); removal requires a new product.
- The attention report (PRD 4) gains proposed updates and published-but-stale
  products.
- Handed over by PRD 7: §18's product version and creation/update date, derived
  from publication snapshots and added to exports; needs-rebuild products (with
  PRD 7's "previews out of date" and "listing changed" reasons) in the attention
  report; and whether export limit warnings (ADR 0017) block publishing.

**Out of scope.** Any marketplace API interaction.

**Acceptance.** §39.17: after publishing, adding a matching asset does not change the
product; it appears as a proposed update; accepting it rebuilds; an attempt to remove
a previously shipped asset is refused with an explanation.

**Cites.** §12.1, §23, §23.1, §37.

---

### PRD 9 — Review UI

**Goal.** The judgment steps of the workflow can be done in a browser instead of a
terminal, with no new logic.

**Scope.**
- Local web app served by the tool; every action calls the same functions as the CLI.
- Home page is the attention inbox (PRD 4 + PRD 8) with every item linking to where
  it is resolved.
- Derivative review page: generated vs. override side by side, findings drawn over
  the SVG, approve / reject / regenerate, open in external editor, discard override.
- Asset page: metadata, sources, all derivatives with status, products containing it.
- Product page: effective contents with eligibility, previews, needs-rebuild,
  proposed updates with accept/reject, build and publish actions.
- No in-browser vector editing.

**Acceptance.** User can complete the full §24 workflow from the browser for the
fixture catalog without using the CLI, and the CLI attention report agrees with the
inbox at every step.

**Cites.** §9.2, §10, §12.1, §22.2, §24, §34, §38.

---

### PRD 10 — Remaining Derivative Types

**Goal.** Complete the derivative catalog from §6.

**Scope.**
- Outline / line-art SVG (§6.4), from the line-art role.
- Detailed single-color SVG (§6.5).
- Layered-color SVG with independently usable regions (§6.6).
- Standard alternate color variants (§6.7) as recolors that inherit the parent
  derivative's status.
- Each new type plugs into recipes, provenance, validation where applicable, status,
  products, and previews with no changes to those subsystems.

**Acceptance.** Each type generates for suitable fixture subjects, is correctly
reported as impossible for unsuitable ones, and can be included in a product and
shown in a variant preview.

**Cites.** §6.4–§6.7, §32.

---

### After PRD 10

The first real deliverable is the Pacific Coast tide-pool reference collection
(§29–§31, §39.15). That is catalog work, not tool work, and it lives in the catalog
repo. It is the acceptance test for the whole roadmap: if building it exposes tool
gaps, those become ADRs and a PRD 11.

Explicitly deferred (§37, §40): scene composition, physical mockups, PDF/EPS,
marketplace APIs, any database.

### Candidate — Catalog import (not yet scheduled)

**Goal.** `vpress import <folder|zip>` turns a set of PNGs into assets and a
collection in one command.

**Why it isn't a PRD yet.** It has to write `asset.toml` and collection TOML, and
ADR 0005 makes hand-authored TOML read-only to the tool, with one exception:
drafting a product's `[listing]`. It therefore needs a new ADR amending ADR 0005
before a PRD can be written.

**Prior art.** A catalog-side script, `tools/import_set.py` in the catalog repo, does
this today and serves as the working spec. For each PNG it:

- derives an asset ID from the file name, dropping ordering prefixes like `01-`
  and numbering generic names like "ChatGPT Image…" or "IMG_1234";
- takes an optional `--id-prefix`, since asset IDs are catalog-global;
- keeps the untouched file under `_originals/`;
- writes a silhouette copy and a flat-color copy with near-identical shades
  merged (the workaround for issue #83);
- writes `asset.toml` defaulting to `rights_status = "rights_review_required"`.

It then creates the collection, or appends to an existing collection's explicit
`asset_ids`. It runs generate and validate for only the new assets, and writes an
HTML contact sheet for the whole collection.

**Real-catalog lessons it encodes:**

- One file cannot serve two source roles, so each role gets its own copy.
- AI-generated sources are not truly flat-color (issue #83).
- On Windows, piped `vpress` output uses the legacy code page, and findings text
  contains `in²`.
- Detailed line art loses most of its cut lines at the 3in catalog reference size.
