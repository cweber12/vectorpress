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
         └─ 5 Collections & products
            └─ 6 Product build & packaging
               ├─ 7 Previews, listing & marketplace export
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
  disabled.
- Every build writes a manifest recording each included asset, derivative type, and
  content hash, plus the reference size and tool version.
- A predictable, marketplace-friendly ZIP (§15) containing only the package.
- "Needs rebuild" is computable by comparing the last manifest to current effective
  derivatives (§23).
- Builds are all-or-nothing per product; a failing asset fails the product build with
  a clear message and does not corrupt other products (§35).
- Unapproved or blocked members are excluded, or the build refuses, per product
  configuration (§10); explicit per-build override is possible and recorded.

**Out of scope.** Previews, listing text, exporters, publication.

**Acceptance.** User can build the fixture product, unzip it, and find only customer
files with consistent names; rebuilding with no changes produces the same logical
contents; changing one source makes exactly the containing products report
needs-rebuild; a rejected cut file is excluded from a cut-file product while the same
asset ships in a PNG product.

**Cites.** §7, §10, §14, §15, §20, §23, §35, §36.

---

### PRD 7 — Previews, Listing Metadata, and Marketplace Export

**Goal.** Each built product has marketplace-ready preview images, an authoritative
listing record, and per-marketplace export files.

**Scope.**
- Preview types from §16 (main, included assets, file formats, variants, contents
  overview), rendered from templates driven by brand config (§17, §27).
- Templates ship with the tool; a catalog can override any template.
- Previews are regenerated on every build, are output not state, and have no approval
  status.
- Listing metadata (§18): drafted once from templates and asset metadata into the
  product's hand-authored file on first build, then user-owned.
- Exporters (§19): a generic structured export and per-marketplace text bundles
  (Etsy, Creative Fabrica, Design Bundles, direct store) that enforce known field
  limits.

**Out of scope.** Physical product mockups (§16, future), publication.

**Acceptance.** User can build a product and get consistent preview images, a listing
record, and marketplace files that can be pasted into a listing form. Changing brand
config changes every product's previews without touching products. Editing the
listing text is preserved across rebuilds.

**Cites.** §16, §17, §18, §19, §27.

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
