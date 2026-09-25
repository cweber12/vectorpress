"""Resolving a loaded collection into its current members (§11, §12, §13,
§34, ADR 0011).

Reads nothing beyond what catalog loading already read, and writes nothing
(ADR 0005): this wires the domain's pure :func:`~vectorpress.domain.
collection_resolution.resolve_membership` to the assets and collections the
``catalog`` layer already loaded, and turns an unknown explicit asset ID, an
unknown collection slug, or a cycle into a :class:`~vectorpress.catalog.
metadata_problem.MetadataProblem` naming the collection's file and the
``membership.asset_ids`` or ``membership.collection_slugs`` field -- a
reference problem does not stop the rest of the collection's members from
resolving. A rule matching no asset, or a union contributing no members, is
not a reference problem.

A reference problem is just a :class:`~vectorpress.catalog.metadata_problem.
MetadataProblem`: file, field, message. Any other unresolved reference a
membership or a product can name renders the same way, under whatever field
it names.
"""

from dataclasses import dataclass
from pathlib import Path

from vectorpress.catalog.collections import CollectionInventory, find_collection
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.products import product_toml_path
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection, CollectionSlug
from vectorpress.domain.collection_resolution import (
    MembershipResolution,
    ResolvedMember,
    resolve_membership,
)
from vectorpress.domain.product import Product

COLLECTION_CONFIG_SUFFIX = ".toml"

#: The field a reference problem in a membership's explicit list is
#: attributed to -- the same dotted path a pydantic-shape problem for this
#: field would use.
MEMBERSHIP_ASSET_IDS_FIELD = "membership.asset_ids"

#: Likewise, for a reference problem (unknown slug, or a cycle) in a
#: membership's collection union.
MEMBERSHIP_COLLECTION_SLUGS_FIELD = "membership.collection_slugs"

#: The field a product's reference problem on its own ``collection_slug`` is
#: attributed to (distinct from ``MEMBERSHIP_COLLECTION_SLUGS_FIELD``, which
#: is about an inline membership's *union*, not a product's single
#: collection reference).
PRODUCT_COLLECTION_SLUG_FIELD = "collection_slug"


@dataclass(frozen=True)
class ResolvedCollection:
    """One collection's current members plus every reference problem found
    resolving it.

    ``members`` is sorted by asset ID (:func:`~vectorpress.domain.
    collection_resolution.resolve_membership`'s own order). ``membership.
    asset_ids``, ``membership.rule`` and ``membership.collection_slugs`` are
    all resolved here.
    """

    collection: Collection
    members: list[ResolvedMember]
    reference_problems: list[MetadataProblem]


def collection_toml_path(config: CatalogConfig, slug: CollectionSlug) -> Path:
    """The on-disk path (relative to the catalog root) a collection's slug
    would have loaded from, whether or not it did -- used to attribute a
    reference problem, or a failed-to-load lookup, to the right file.
    """
    return Path(config.collections_dir) / f"{slug}{COLLECTION_CONFIG_SUFFIX}"


def membership_reference_problems(
    path: Path, resolution: MembershipResolution
) -> list[MetadataProblem]:
    """Every reference problem in one membership resolution -- unknown
    explicit asset IDs, unknown collection slugs, cycles -- attributed to
    ``path`` under :data:`MEMBERSHIP_ASSET_IDS_FIELD`/
    :data:`MEMBERSHIP_COLLECTION_SLUGS_FIELD`. The one place a
    :class:`~vectorpress.domain.collection_resolution.MembershipResolution`
    becomes reference problems, shared by :func:`resolve_collection` (a
    collection's own membership) and ``build.product_resolution`` (a
    product's inline membership) rather than duplicated between them.
    """
    problems = [
        MetadataProblem(path, MEMBERSHIP_ASSET_IDS_FIELD, f"unknown asset ID: {asset_id!r}")
        for asset_id in resolution.unknown_asset_ids
    ]
    problems.extend(
        MetadataProblem(path, MEMBERSHIP_COLLECTION_SLUGS_FIELD, f"unknown collection: {slug!r}")
        for slug in resolution.unknown_collection_slugs
    )
    problems.extend(
        MetadataProblem(path, MEMBERSHIP_COLLECTION_SLUGS_FIELD, f"cycle: {' -> '.join(cycle)}")
        for cycle in resolution.cycles
    )
    return problems


def resolve_collection(
    collection: Collection,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
) -> ResolvedCollection:
    """Resolve one loaded collection's membership into its current members.

    ``known_assets`` is every asset that actually loaded (never a failed
    one) -- the catalog layer's ``loaded_assets`` -- supplying both the ID
    set the explicit list resolves against and the classification values a
    rule matches against. ``known_collections`` is every other collection
    that actually loaded (never a failed one -- the same rule as
    ``known_assets``), for resolving a union's ``collection_slugs``; pass an
    empty list for a collection whose membership declares no union, so a
    future caller cannot forget it and silently lose union resolution.
    """
    collections_by_slug = {c.slug: c.membership for c in known_collections}
    resolution = resolve_membership(
        collection.membership, known_assets, collections_by_slug, own_slug=collection.slug
    )
    path = collection_toml_path(config, collection.slug)
    reference_problems = membership_reference_problems(path, resolution)
    return ResolvedCollection(
        collection=collection, members=resolution.members, reference_problems=reference_problems
    )


def resolve_collections(
    collections: list[Collection], config: CatalogConfig, known_assets: list[Asset]
) -> list[ResolvedCollection]:
    """Resolve every loaded collection (``vpress status``'s and ``vpress
    attention``'s catalog-wide reference problems; ``vpress collections``'
    member-count column), each against every other loaded collection so a
    union resolves regardless of which one is requested."""
    return [resolve_collection(c, config, known_assets, collections) for c in collections]


@dataclass(frozen=True)
class CollectionResolutionLookup:
    """The result of resolving one collection slug against a loaded
    catalog, mirroring :class:`~vectorpress.catalog.products.ProductLookup`.

    Three outcomes, told apart here rather than in ``cli``: the collection
    loaded and resolved (``resolved`` set, ``problems`` empty); no
    ``<slug>.toml`` exists at all (both empty -- genuinely unknown slug); or
    that file exists but failed to load (``resolved`` is ``None``,
    ``problems`` non-empty).
    """

    resolved: ResolvedCollection | None
    problems: list[MetadataProblem]


def lookup_and_resolve_collection(
    inventory: CollectionInventory,
    config: CatalogConfig,
    known_assets: list[Asset],
    slug: CollectionSlug,
) -> CollectionResolutionLookup:
    """Resolve one collection slug, distinguishing "no such file" from
    "file exists but failed to load" -- the same two-outcome split
    :func:`~vectorpress.catalog.products.lookup_product` already makes for
    product slugs.
    """
    collection = find_collection(inventory, slug)
    if collection is None:
        path = collection_toml_path(config, slug)
        problems = [problem for problem in inventory.problems if problem.path == path]
        return CollectionResolutionLookup(resolved=None, problems=problems)

    return CollectionResolutionLookup(
        resolved=resolve_collection(collection, config, known_assets, inventory.collections),
        problems=[],
    )


def all_reference_problems(
    collections: list[Collection],
    products: list[Product],
    config: CatalogConfig,
    known_assets: list[Asset],
) -> list[MetadataProblem]:
    """Every reference problem in a loaded catalog, collections and
    products together (§34): each collection's own (via
    :func:`resolve_collections`) plus each product's own unknown
    ``collection_slug`` (via :func:`product_collection_slug_reference_problem`).
    The one place this pair of loops runs, called by both ``vpress status``
    and ``pipeline.attention.build_attention_report`` so the two can never
    drift apart (ADR 0011).
    """
    problems = [
        problem
        for resolved in resolve_collections(collections, config, known_assets)
        for problem in resolved.reference_problems
    ]
    problems.extend(
        problem
        for product in products
        if (problem := product_collection_slug_reference_problem(product, config, collections))
        is not None
    )
    return problems


def product_collection_slug_reference_problem(
    product: Product, config: CatalogConfig, known_collections: list[Collection]
) -> MetadataProblem | None:
    """The reference problem on one product's ``collection_slug`` (§7, ADR
    0011): unknown, or naming a collection whose file failed to load --
    told apart no further here, since either way ``known_collections`` (the
    catalog layer's own loaded, never-failed inventory -- the same rule
    :func:`resolve_collection`'s own ``known_collections`` follows) does not
    have it. A pure catalog-level fact living beside a collection's own
    reference problems, reused by ``build.product_resolution`` (which needs
    ``pipeline.eligibility`` for the rest of product resolution, ADR 0011)
    rather than duplicated there. ``None`` for a product with no
    ``collection_slug`` (an inline membership instead) or one that names a
    collection that did load.
    """
    if product.collection_slug is None:
        return None
    if any(collection.slug == product.collection_slug for collection in known_collections):
        return None
    path = product_toml_path(config, product.slug)
    return MetadataProblem(
        path, PRODUCT_COLLECTION_SLUG_FIELD, f"unknown collection: {product.collection_slug!r}"
    )
