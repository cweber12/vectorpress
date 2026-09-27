# PRD 6 — Product Build and Packaging

Status: not started
Depends on: see `docs/PLAN.md` Part 3 dependency graph

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
