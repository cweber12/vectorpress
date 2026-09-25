# 0011 — Collection resolution's pure decision lives in domain, its wiring in catalog

Status: accepted
Date: 2026-09-25

## Context

ADR 0006 lists "collection resolution" under the `build` layer. Building #73 (turning
a collection's declared membership into its current members) found that `vpress
status` and `vpress attention` -- both in `pipeline` -- need to surface the same
reference problems (an asset ID a membership names that no loaded asset has) that
resolving a collection produces. The layering contract (`domain ← catalog ←
pipeline/validate ← build ← cli/ui`) forbids `pipeline` from importing `build`, so a
resolver living in `build` could not be called from `pipeline.attention` without
either moving the attention report itself into `build` (a much larger change than
this tracer bullet) or duplicating the resolution logic.

Resolving a membership's explicit list is also, in its core, a pure decision over
already-loaded data (declared asset IDs, and the set of asset IDs that actually
loaded) -- no different in kind from `domain.eligibility`, which ADR 0006 already
places in `domain` for the same reason. The only non-pure part is turning an unknown
ID into a problem that names a real file and field, which needs the same loaded
inventories `catalog.assets.lookup_asset` and `catalog.products.lookup_product`
already work with.

## Decision

- The pure resolution decision lives in `domain` (`domain/collection_resolution.py`):
  given a membership's declared asset IDs and the set of asset IDs that loaded, it
  decides current members and unknown IDs. No I/O, no catalog awareness, consistent
  with every other `domain` module.
- The catalog↔domain wiring lives in `catalog` (`catalog/collection_resolution.py`):
  it supplies the loaded assets and collections, calls the domain decision, and turns
  an unknown ID into a `MetadataProblem` naming the collection's file and field --
  alongside `catalog.assets.lookup_asset` and `catalog.products.lookup_product`, the
  same kind of loaded-inventory lookup.
- This supersedes ADR 0006's "collection resolution" line under `build`, for this
  mechanism only. `build` keeps everything else ADR 0006 assigned it: product build,
  manifest, ZIP, previews, exporters. A later slice's product-level resolution (which
  breaks members into eligible/excluded/missing, needing `pipeline`'s eligibility
  logic) still belongs in `build`, calling into `catalog.collection_resolution` the
  same way `cli` and `pipeline` do.

## Consequences

- `pipeline.attention.build_attention_report` calls
  `catalog.collection_resolution.resolve_collections` directly, so `vpress status`
  and `vpress attention` can report reference problems without `pipeline` depending
  on `build`.
- `cli` calls the same catalog-layer functions for `vpress collection` and `vpress
  collections`, the pattern `_lookup_asset_or_exit`/`_lookup_product_or_exit` already
  use.
- Rules and unions (extending the same reference-problem mechanism to unknown
  collection slugs and cycles) stay in `domain`/`catalog` by this same split.
