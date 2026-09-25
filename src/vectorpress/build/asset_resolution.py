"""The asset's own view of reuse (§33, §34, ADR 0008): every collection
containing one asset and how it got in, and every product containing it
along with its own per-product eligibility.

This is the reverse of what ``vpress collection`` and ``vpress product``
already show -- from the collection's or product's own side, which member
it currently has -- computed here by running the identical resolution each
of those already calls and keeping only the member that matches the
requested asset. No second resolution path (ADR 0011): a collection's
membership always goes through :func:`~vectorpress.catalog.
collection_resolution.resolve_collection`, a product's through
:func:`~vectorpress.build.product_resolution.resolve_product`.

Lives in ``build``, not ``catalog``, for the same reason ADR 0011 gives for
:mod:`vectorpress.build.product_resolution`: it needs product resolution,
and ``catalog`` cannot depend on ``build`` (CLAUDE.md's layering
guardrail).
"""

from dataclasses import dataclass
from pathlib import Path

from vectorpress.build.product_resolution import MemberEligibility, resolve_product
from vectorpress.catalog.collection_resolution import resolve_collection
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.collection_resolution import WayIn
from vectorpress.domain.eligibility import BlockingReason
from vectorpress.domain.product import Product


@dataclass(frozen=True)
class AssetCollectionMembership:
    """One collection the requested asset currently belongs to, and every
    way it got in -- the same ``ways_in`` :func:`~vectorpress.catalog.
    collection_resolution.resolve_collection` already computes for that
    collection's own members."""

    collection: Collection
    ways_in: tuple[WayIn, ...]


@dataclass(frozen=True)
class AssetProductMembership:
    """One product the requested asset currently belongs to, with its
    eligibility for that product's own ``derivative_types`` -- the same
    per-member fields :class:`~vectorpress.build.product_resolution.
    ProductMember` already carries."""

    product: Product
    ways_in: tuple[WayIn, ...]
    eligibility: MemberEligibility
    blocking_reasons: list[BlockingReason]
    warnings: list[str]


@dataclass(frozen=True)
class AssetReuse:
    """Every collection and product one asset currently belongs to (§33,
    §34): reuse made visible from the asset's own side."""

    collections: list[AssetCollectionMembership]
    products: list[AssetProductMembership]


def resolve_asset_reuse(
    asset_id: AssetId,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
    known_products: list[Product],
) -> AssetReuse:
    """Every collection and product ``asset_id`` currently belongs to
    (§33, §34), each found by resolving every loaded collection and
    product through the same functions their own commands call and keeping
    only the member matching ``asset_id`` -- so this can never disagree
    with ``vpress collection``/``vpress product`` about who is a member.

    ``known_assets``, ``known_collections`` and ``known_products`` are the
    catalog layer's own loaded, never-failed inventories, the same contract
    :func:`~vectorpress.build.product_resolution.resolve_product` already
    requires.
    """
    collections: list[AssetCollectionMembership] = []
    for collection in known_collections:
        resolved_collection = resolve_collection(
            collection, config, known_assets, known_collections
        )
        member = next((m for m in resolved_collection.members if m.asset_id == asset_id), None)
        if member is not None:
            collections.append(AssetCollectionMembership(collection, member.ways_in))

    products: list[AssetProductMembership] = []
    for product in known_products:
        resolved_product = resolve_product(product, root, config, known_assets, known_collections)
        product_member = next((m for m in resolved_product.members if m.asset_id == asset_id), None)
        if product_member is not None:
            products.append(
                AssetProductMembership(
                    product=product,
                    ways_in=product_member.ways_in,
                    eligibility=product_member.eligibility,
                    blocking_reasons=product_member.blocking_reasons,
                    warnings=product_member.warnings,
                )
            )

    return AssetReuse(collections=collections, products=products)
