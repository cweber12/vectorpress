# SVG Asset Production System — Functional Requirements

> **Revision 2.** Adds manual cut-file overrides (6.8, 22), a flat-color SVG definition (6.9), per-file approval (10), publication blocking rules (10, 26), a reference cut size (9), frozen collection membership at publish (12), a past-buyer update policy (23), v1 format scope (7), v1 preview scope (16), storage approach (41), and moves composition-based products to future work (29, 33, 37, 40).

## 1. Purpose

Build a local tool that converts source artwork, especially PNG images created as master templates, into organized, reusable digital design assets and complete marketplace-ready product packs.

The system is intended to support a scalable digital-product business selling SVG assets, Cricut/Silhouette cut files, PNG graphics, themed collections, and larger bundles.

The primary goal is to reduce repetitive production work after the original artwork has been created.

The system should treat source artwork as reusable master assets that can appear in multiple products and collections without requiring the user to manually recreate, rename, reorganize, or repackage the same files.

## 2. Primary Use Case

A user creates or obtains clean source artwork for a subject such as:

- Ochre sea star
- Purple sea urchin
- Giant green anemone
- California mussel
- Gumboot chiton
- Giant kelp
- Rockhounding specimen
- Native plant
- Freediver

The user adds the source images and descriptive metadata to the project.

The system then produces standardized derivative assets, validates them, organizes them into appropriate collections, creates customer-facing product packages, and produces the supporting files needed for marketplace listings.

A single master asset should be reusable across multiple products.

Example:

`ochre_sea_star`

may belong to:

- California Tide Pool Collection
- Pacific Northwest Tide Pool Collection
- Sea Star SVG Pack
- Echinoderm Collection
- Rocky Intertidal Collection
- Pacific Coast Marine Life Mega Bundle

The user should not have to manually duplicate or maintain separate copies of the asset for each collection.

## 3. Scope

The system must support:

- Individual design assets
- Small packs
- Themed collections
- Large bundles
- Cut-file variants
- Outline variants
- Solid silhouette variants
- Layered-color variants
- High-resolution PNG assets
- Marketplace preview images
- Product ZIP packages
- Product metadata
- Collection metadata
- Quality validation
- Regeneration of products after source assets change

The system is not intended to create the original artistic concept automatically.

The original artwork remains a creative input.

## 4. Source Asset Requirements

### 4.1 Master Asset

Each design subject must have a unique asset identity.

Example identities:

- `ochre_sea_star`
- `purple_sea_urchin`
- `giant_kelp`
- `california_poppy`

Each asset must support one or more source images.

Typical source variants may include:

- silhouette
- line art
- flat color
- detailed illustration

Not every asset must include every source variant.

### 4.2 Preferred Master Artwork Characteristics

The production workflow should be optimized for source artwork that has:

- A single isolated subject
- A transparent or easily removable background
- The full subject visible
- No accidental cropping
- Strong, recognizable silhouette
- Clean edges
- Limited visual noise
- Minimal unnecessary micro-detail
- Clearly separated visual regions
- No text unless the text is intentionally part of the design
- No unrelated background elements

For flat-color artwork, the preferred source has a limited number of distinct colors.

For cut-file artwork, the preferred source emphasizes clean, manufacturable shapes.

## 5. Asset Metadata

Each master asset must support descriptive metadata.

Metadata must be stored separately from the artwork so that it can be reused for collection building, packaging, search terms, and product generation.

Supported metadata should include at minimum:

- Unique asset ID
- Common name
- Display name
- Scientific name when applicable
- Description
- Subject category
- Tags
- Regions
- Ecosystems or environments
- Taxonomic or conceptual group
- Product-use categories
- Source status
- Review status
- Licensing status
- Notes

Example classifications for a marine animal might include:

- California
- Oregon
- Washington
- Pacific Coast
- Tide pool
- Rocky intertidal
- Echinoderm
- Sea star
- Marine life

An asset may belong to multiple classifications.

## 6. Derivative Asset Types

The system must be able to produce standardized derivatives from approved master artwork.

### 6.1 Transparent PNG

Produce a clean high-resolution PNG with transparent background.

The PNG must preserve the intended visual quality of the source.

### 6.2 Solid Silhouette

Produce a single-color silhouette version suitable for:

- Vinyl cutting
- Cricut
- Silhouette
- Stencils
- Simple laser cutting
- Single-color printing

The silhouette must remain recognizable at typical craft-project sizes.

### 6.3 Simplified Cut File

Produce a simplified design intended specifically for physical cutting.

The cut-file version should preserve meaningful identifying details while avoiding unnecessary complexity.

The output must not contain impractically small decorative elements.

### 6.4 Outline Version

Produce a clean outline or line-art version when the source material supports it.

This output should be suitable for:

- Engraving
- Single-line visual applications
- Coloring
- Decorative craft work
- Plotter-style uses where appropriate

### 6.5 Detailed Single-Color Version

Produce a more detailed monochrome version where appropriate.

This version may retain internal markings and recognizable details that are omitted from the simplified cut file.

### 6.6 Layered Color Version

Where source artwork contains multiple clearly separated colors, produce a layered-color vector product.

Each major color or design region should remain independently usable by the customer.

### 6.7 Alternate Color Variants

The system should support optional standard color variants without modifying the master asset.

Examples may include:

- Black
- White
- Single-color
- Limited palette

### 6.8 Manual Overrides

The user must be able to hand-edit any generated derivative, whether or not it passed validation. Cut files are the primary case, but the rule applies to every derivative type.

A hand-edited file becomes an **override**:

- The system keeps both the auto-generated version and the override.
- The override is the version used in products.
- The override is never overwritten by regeneration.
- The override goes through the same validation and approval as generated files.
- The user can discard an override and revert to the auto-generated version at any time.

### 6.9 Flat Color SVG

Produce a full-color vector version traced from flat-color source artwork.

This is the standard decorative SVG. It differs from the layered color version (6.6) in that colors do not need to be separated into independently usable layers.

## 7. Supported Customer Deliverables

A product may contain one or more of the following deliverable formats:

- SVG
- PNG
- DXF
- PDF
- EPS if enabled for the product

The initial release must support SVG, PNG, and DXF. PDF and EPS are disabled by default and added only when a product or marketplace requires them.

DXF is included primarily for Silhouette Studio users, whose basic edition does not import SVG.

The exact included formats must be configurable per product or collection.

The product metadata must clearly identify which formats are included.

## 8. SVG Requirements

SVG outputs must be true vector files.

They must not rely on an embedded raster image as the visual content of the design.

SVG assets must:

- Open successfully in common vector design applications
- Be usable in common consumer cutting workflows
- Maintain intended proportions
- Preserve transparency where applicable
- Contain only intended artwork
- Avoid invisible or accidental elements
- Avoid unnecessary off-canvas objects
- Use clean document bounds
- Use predictable naming

Cut-file SVGs must prioritize manufacturability and usability over preservation of tiny visual details.

## 9. Cut-File Quality Requirements

Cut files are a core product type and require explicit quality validation.

The system must detect or flag common problems including:

- Open paths where closed paths are expected
- Tiny isolated shapes
- Accidental dots
- Very small holes
- Extremely narrow features
- Excessive geometric complexity
- Stray objects
- Duplicate geometry
- Unintended overlaps
- Disconnected fragments
- Raster content inside a vector deliverable

### 9.1 Reference Cut Size

Cut-file validation must be performed relative to a physical reference size, because an SVG has no inherent size and thresholds such as "very small hole" or "extremely narrow feature" are only meaningful at a known output size.

- The catalog must define a default minimum cut size (for example, 3 inches on the longest side).
- Each product may override the default.
- Validation thresholds must be expressed in physical units at that reference size.
- The reference size used should be recorded with the validation result.

### 9.2 Pass or Review

The system must be able to determine whether a cut file passes or requires manual review.

The user must be able to review quality findings before a product is treated as final.

## 10. Quality Status

Each generated asset must have an explicit status.

Recommended statuses:

- Generated
- Needs review
- Approved
- Rejected
- Regenerate

Status applies to each individual derivative file, not to the subject as a whole. For example, a sea star's silhouette may be approved while its cut file is rejected.

A subject is eligible for a product when every derivative that product includes is approved. The same sea star can therefore ship in a PNG-only product while its cut file is still being fixed.

Only approved derivatives should be eligible for final customer packages unless the user explicitly overrides the status.

### 10.1 Publication Blocking Rules

A subject must be excluded from final sellable packages if any of the following apply:

- Rights status is `Do not publish`
- Rights status is `Rights review required`
- Accuracy status is `Accuracy issue found`
- Any included derivative is not approved (unless explicitly overridden)

The following produce warnings but do not block packaging:

- Accuracy status is `Accuracy not reviewed`
- Missing optional metadata

## 11. Collections

The system must support named collections.

Examples:

- Pacific Coast Tide Pool
- California Tide Pool Animals
- Pacific Northwest Tide Pool
- Giant Kelp Collection
- Kelp Forest Ecosystem
- Rockhound Mineral Specimens
- California Native Wildflowers
- Freediving Poses

Each collection must have metadata including:

- Collection name
- Slug or unique identifier
- Description
- Included assets
- Included variants
- Included formats
- Product tier
- Intended marketplace category
- Tags
- Optional price field
- Version

## 12. Dynamic Membership

Collections must be able to include assets through explicit selection or metadata-driven grouping.

A single asset may appear in multiple collections.

Adding a new eligible asset should not require manually copying it into every applicable product.

The system should support rebuilding affected products when collection membership changes.

### 12.1 Frozen Membership After Publication

Once a product is marked as published, its membership must be frozen.

If a metadata rule would add or remove assets from a published product, the system must present this as a proposed update rather than changing the product automatically. The user accepts or rejects each proposed update.

This prevents a live listing's stated asset count or contents from silently diverging from the actual package.

Unpublished products may continue to update their membership automatically.

## 13. Product Tiers

The system must support multiple product sizes derived from the same asset library.

Typical examples:

### Individual Asset

One subject.

### Mini Pack

Approximately 3–8 related assets.

### Standard Pack

Approximately 8–15 related assets.

### Full Collection

Approximately 15–30 related assets.

### Mega Bundle

Multiple related collections combined into a larger product.

These are examples rather than fixed limits.

The user must be able to define the exact membership of each product.

## 14. Product Packaging

Each customer-facing product must be exportable as a complete package.

A package should contain only files intended for the customer.

Example structure:

```text
Pacific-Coast-Tide-Pool-Collection/

    SVG/
    PNG/
    DXF/
    PDF/

    README.txt
    LICENSE.txt
```

The package structure should remain consistent across products.

Unnecessary development files, source files, temporary files, or internal metadata must not be included in customer packages unless intentionally configured.

## 15. ZIP Products

The system must produce a final ZIP archive for each completed digital product.

The ZIP filename must be predictable and marketplace friendly.

The archive must contain the final customer package and nothing unrelated to the product.

Products should be rebuildable without requiring manual reconstruction of the archive.

## 16. Product Preview Images

The system must generate marketplace-ready preview images from approved assets.

Preview imagery should be based on reusable layouts or product presentation templates.

Required preview types should include:

### Main Collection Preview

Shows a representative view of the assets included in the product.

It should clearly communicate the visual style and quantity of content.

### Included Assets Preview

Shows multiple included designs in an organized layout.

### File Format Preview

Communicates which file formats are included.

### Variant Preview

When relevant, shows examples such as:

- Color
- Outline
- Silhouette
- Cut file

### Contents Overview

For larger collections, provide a visual overview of the full pack.

The generated previews must be suitable for use as marketplace listing images after review.

For the initial release, previews are flat branded layouts only (assets arranged on a styled background with text and badges). Product mockups showing designs applied to physical items such as shirts, mugs, or tumblers are future work.

## 17. Preview Consistency

Products from the same brand or catalog should use consistent:

- Image dimensions
- Typography
- Margins
- Product-name placement
- Badge styling
- Format indicators
- Layout language
- Branding treatment

The visual presentation should make separate products feel like parts of the same store.

## 18. Listing Metadata

Each product must have structured listing metadata.

Metadata should support at minimum:

- Product title
- Short title
- Product description
- Included asset count
- Included file formats
- Tags
- Search terms
- Collection name
- Asset names
- Intended uses
- Region when applicable
- Species names when applicable
- Category
- Product version
- Suggested price
- License type
- Creation/update date
- Marketplace notes

The listing information should remain editable by the user before publication.

## 19. Marketplace Export Data

The system should generate marketplace-supporting data in a reusable structured form.

The output should make it easy to transfer product information into marketplaces such as:

- Etsy
- Creative Fabrica
- Design Bundles
- A direct digital-download store

Marketplace exports should reuse the same authoritative product metadata rather than requiring the user to rewrite product information independently.

## 20. Naming Standards

All generated assets must follow consistent naming.

Human-readable filenames should be preferred.

Example:

```text
ochre-sea-star.svg
ochre-sea-star-cut.svg
ochre-sea-star-outline.svg
ochre-sea-star-color.png
```

Collection packages should follow the same naming philosophy.

Filenames must avoid accidental duplicates, ambiguous names, and meaningless generated identifiers in customer-facing outputs.

## 21. Source Preservation

Original master artwork must remain preserved.

Generating derivatives must never silently overwrite or destructively modify the original source image.

Generated content must be clearly distinguishable from master artwork.

## 22. Regeneration

The system must support rebuilding derivative assets after a source image changes.

If an approved master asset is updated, the user should be able to regenerate its derivatives.

Products containing that asset should be identifiable as needing an update.

The user should be able to rebuild affected collections without recreating the collection from scratch.

### 22.1 Approval After Regeneration

When derivatives are regenerated:

- A derivative whose output changed must return to `Needs review`.
- A derivative whose output is unchanged keeps its existing status.

### 22.2 Overrides After a Master Change

Regeneration never overwrites an override (6.8). When the master asset behind an override changes, the override must be flagged as stale, and the user chooses to:

- Re-edit the override against the new generated version
- Keep the override unchanged
- Discard the override and use the new generated version

Products containing a stale override should be identifiable as needing attention.

## 23. Version Awareness

The system must track enough version information to identify:

- Which master asset version produced a derivative
- Which asset versions are included in a product
- Whether a generated product is current
- Whether a product should be rebuilt

Version tracking does not need to be visible to marketplace customers.

### 23.1 Updates to Sold Products

Rebuilds of a published product may add assets or improve existing files. They must not remove assets that past buyers received. Removing an asset requires creating a new product rather than updating the existing one.

## 24. Manual Review Workflow

Automation must not eliminate human review.

The expected workflow is:

1. Add source artwork.
2. Add or verify metadata.
3. Generate derivatives.
4. Review visual quality.
5. Review cut-file quality.
6. Approve or reject assets.
7. Build collections.
8. Review product previews.
9. Build marketplace package.
10. Publish externally.

The system must make it easy to identify which assets have and have not been reviewed.

## 25. Scientific and Subject Accuracy

For products marketed using scientific, biological, geographic, or species-specific claims, factual accuracy matters.

The system must allow an asset to be marked as:

- Accuracy not reviewed
- Accuracy reviewed
- Accuracy approved
- Accuracy issue found

Scientific names and other factual metadata should remain editable.

No generated design should automatically be considered scientifically accurate merely because it has been assigned a species name.

## 26. Licensing and Rights Status

Each source asset must support a rights or licensing status.

Suggested states:

- Original artwork
- Licensed source
- Public-domain source
- Rights verified
- Rights review required
- Do not publish
- AI-generated

An asset marked `Do not publish` must not be included in final sellable packages.

`AI-generated` states origin: the artwork was made with an AI image tool whose terms
permit commercial use. It does not block publication, but the asset's licensing notes
must name the tool and its terms; an `AI-generated` asset with empty licensing notes is
blocked. Hand edits to its derivatives do not change it: the source and any unedited
derivatives remain AI output, and marketplaces ask about AI use anywhere in creation.
The status is kept so listings can disclose AI use and license wording does not
overstate copyright.

The system must keep licensing notes available internally.

## 27. Brand Consistency

The catalog should support a recognizable brand style.

A brand configuration should be able to define product-level presentation requirements such as:

- Brand name
- Logo or mark
- Preview typography
- Product-card styling
- Standard wording
- License naming
- License text (the terms shipped as `LICENSE.txt`)
- Copyright wording
- Standard README text

Individual products should not require these elements to be recreated manually.

## 28. Product Families

The catalog should support groups of related products.

Example:

### Pacific Coast Naturalist

- Tide Pool Species
- Kelp Forest
- Sea Stars
- Echinoderms
- Coastal Birds
- Native Plants

A product family can share visual presentation, tags, brand language, and related-product references.

## 29. Initial Target Catalog

The first supported catalog should focus on natural-history and hobby-oriented digital design products.

Initial product concepts include:

1. Pacific Coast Tide Pool Species SVG Collection
2. Giant Kelp Anatomy SVG Pack
3. California Tide Pool Animals Cut Files
4. West Coast Kelp Forest Ecosystem Scene Builder *(future work; see 40)*
5. Rockhound Mineral Specimen SVG Collection
6. Pacific Northwest Tide Pool Species Pack
7. Accurate Freediving Pose Silhouette Pack
8. Rockhounding Field Gear SVG Pack
9. California Native Wildflowers Collection
10. Pacific Coast Sea Anemone Mini Pack

The system should remain general enough to support unrelated future categories.

Products that require composing multiple assets into a single scene at consistent relative scale are not part of the initial release.

## 30. First Reference Collection

The first reference collection should be a Pacific Coast tide-pool collection.

Candidate subjects include:

- Ochre sea star
- Bat star
- Purple sea urchin
- Giant green anemone
- Aggregating anemone
- California mussel
- Acorn barnacle
- Gumboot chiton
- Owl limpet
- Hermit crab
- Shore crab
- California sea cucumber
- Nudibranch
- Tidepool sculpin
- Two-spot octopus
- Turban snail
- Abalone
- Keyhole limpet
- Sea lettuce
- Coralline algae

The initial collection may use a subset of these subjects.

## 31. Source Artwork Style for the Reference Collection

The reference collection should use a consistent natural-history visual language.

Desired characteristics:

- Accurate real-world proportions
- Species-recognizable anatomy
- Strong silhouettes
- Clean contours
- Minimal visual clutter
- Consistent orientation and scale treatment
- Limited disconnected micro-details
- Isolated subjects
- No background
- No text in the artwork
- No drop shadows
- No unnecessary gradients
- Suitable for conversion into both decorative and cut-file products

The collection should look intentionally designed as one cohesive family.

## 32. Separate Decorative and Cut-File Intent

The system must recognize that a decorative illustration and a physical cut file have different requirements.

A detailed illustration may preserve more identifying features.

A cut-file variant should prioritize:

- Clean shapes
- Structural integrity
- Fewer tiny components
- Fewer fragile connections
- Practical manufacturability
- Recognizability at smaller sizes

The system should not assume that the most visually detailed version is also the best cut file.

## 33. Product Reuse

The core business requirement is maximum responsible reuse of approved master artwork.

For example, one approved sea-star asset may contribute to:

- An individual sea-star listing
- A three-sea-star mini pack
- A tide-pool animals bundle
- A California coast collection
- A Pacific Northwest collection
- An echinoderm bundle
- A marine-life mega bundle
- A future scientific poster
- A future print-on-demand design

The system must make this reuse easy to manage while retaining a single authoritative source asset.

## 34. Internal Catalog View

The user needs a way to understand the current state of the catalog.

At minimum, the system should make it possible to determine:

- Total source assets
- Approved assets
- Assets awaiting review
- Assets blocked from publication
- Collections
- Products
- Assets included in each product
- Products containing a given asset
- Products that need rebuilding
- Missing expected derivatives
- Missing metadata

The system should reduce the risk of losing track of assets as the catalog grows.

## 35. Error Handling Requirements

Failures must be visible and understandable.

If an asset cannot be processed, the system must:

- Identify the affected asset
- Identify the failed output
- Preserve the source asset
- Avoid treating the failed output as approved
- Allow the user to retry after resolving the issue

A failure involving one asset should not silently corrupt unrelated products.

## 36. Repeatability

Given the same approved source artwork, metadata, collection definitions, and product configuration, the system should produce the same logical product contents.

Manual file copying should not be required to reproduce an existing product package.

## 37. Non-Goals

The initial product does not need to:

- Run an online marketplace
- Automatically publish listings
- Handle customer orders
- Handle payments
- Manage marketplace messages
- Generate the original artwork autonomously
- Guarantee scientific accuracy
- Guarantee trademark or copyright clearance
- Replace human review
- Replace artistic judgment
- Decide what products should be sold without user input
- Compose multiple assets into scenes, posters, or scene-builder products
- Generate product mockups on physical items

These may be considered separately in future work.

## 38. User Experience Goals

The system should feel like a production tool rather than a graphics experiment.

The user should be able to think in terms of:

- Assets
- Collections
- Products
- Approval
- Packaging

rather than managing hundreds of individual files manually.

Common workflows should require minimal repetitive data entry.

The user should be able to add new asset categories without redesigning the entire system.

## 39. Acceptance Criteria for Initial Release

The initial release can be considered functionally successful when the user can:

1. Add a set of PNG master assets.
2. Assign metadata to each asset.
3. Generate at least:
   - transparent PNG
   - flat color SVG
   - solid silhouette SVG
   - simplified cut-file SVG
4. Review and approve generated assets.
5. Define a collection containing multiple assets.
6. Reuse the same asset across multiple collections.
7. Produce consistent customer-facing filenames.
8. Generate marketplace preview images.
9. Generate structured listing metadata.
10. Generate a complete ZIP product package.
11. Rebuild a product after one of its source assets changes.
12. Detect or flag common cut-file quality issues.
13. Exclude unapproved or blocked assets from final packages.
14. Preserve all source artwork unchanged.
15. Build the initial Pacific Coast tide-pool reference collection from multiple source assets.
16. Hand-edit a generated cut file and have the edit survive regeneration.
17. Keep a published product's membership unchanged when a new matching asset is added, and surface it as a proposed update.

## 40. Future Direction

The system should be designed conceptually around a growing reusable asset library rather than a one-off conversion utility.

Possible future product categories include:

- Marine biology
- Kelp forests
- Tide pools
- Coastal birds
- Native plants
- Geology
- Fossils
- Rockhounding
- Freediving
- Scuba
- Outdoor recreation
- Scientific illustration
- Educational graphics
- Signage graphics
- Decorative design assets

Possible future capabilities include:

- Scene composition and scene-builder products
- Scientific posters
- Product mockups on physical items
- Print-on-demand designs
- PDF and EPS deliverables where marketplaces require them

The long-term objective is to maintain one high-quality source library from which many distinct sellable digital products can be assembled.

## 41. Storage Approach (Initial Release)

The initial release is intended for a single user on a single machine, with a catalog in the range of tens to hundreds of assets.

- Each master asset lives in its own folder containing its source images and a small human-readable metadata file.
- Collections, products, and brand configuration are also stored as human-readable files.
- Generated derivatives and overrides are stored separately from master artwork.
- The project should be kept under version control (for example, git), which also provides backup and history.

A database may be introduced later if the catalog outgrows this approach.
