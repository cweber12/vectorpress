"""Resolving a loaded collection into its current members (§11, §34).

Reads nothing beyond what catalog loading already read, and writes nothing
(ADR 0005): this wires the domain's pure :func:`~vectorpress.domain.
collection_resolution.resolve_explicit` to the assets and collections the
``catalog`` layer already loaded, and turns an unknown asset ID into a
:class:`~vectorpress.catalog.metadata_problem.MetadataProblem` naming the
collection's file and the ``membership.asset_ids`` field -- a reference
problem does not stop the rest of the collection's members from resolving.

Built as the one mechanism a metadata rule (unknown classification value is
never a reference problem, so nothing to add there), a union (unknown
collection slug, a cycle), and a product (unknown ``collection_slug``) can
each extend by adding another message under the same file + field + message
shape, not by restructuring :class:`ResolvedCollection`.
"""

from dataclasses import dataclass
from pathlib import Path

from vectorpress.catalog.collections import CollectionInventory, find_collection
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.asset import AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection, CollectionSlug
from vectorpress.domain.collection_resolution import ResolvedMember, resolve_explicit

COLLECTION_CONFIG_SUFFIX = ".toml"

#: The field a reference problem in a membership's explicit list is
#: attributed to -- the same dotted path a pydantic-shape problem for this
#: field would use.
MEMBERSHIP_ASSET_IDS_FIELD = "membership.asset_ids"


@dataclass(frozen=True)
class ResolvedCollection:
    """One collection's current members plus every reference problem found
    resolving it.

    ``members`` is sorted by asset ID (:func:`~vectorpress.domain.
    collection_resolution.resolve_explicit`'s own order). This slice
    resolves only ``membership.asset_ids``; a rule or union member
    contributes nothing yet.
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


def resolve_collection(
    collection: Collection, config: CatalogConfig, known_asset_ids: set[AssetId]
) -> ResolvedCollection:
    """Resolve one loaded collection's membership into its current members.

    ``known_asset_ids`` is every asset ID that actually loaded (never a
    failed one, per ``resolve_explicit``'s own contract) -- the catalog
    layer's ``{asset.id for asset in loaded_assets}``.
    """
    explicit = resolve_explicit(collection.membership.asset_ids, known_asset_ids)
    path = collection_toml_path(config, collection.slug)
    reference_problems = [
        MetadataProblem(path, MEMBERSHIP_ASSET_IDS_FIELD, f"unknown asset ID: {asset_id!r}")
        for asset_id in explicit.unknown_asset_ids
    ]
    return ResolvedCollection(
        collection=collection, members=explicit.members, reference_problems=reference_problems
    )


def resolve_collections(
    collections: list[Collection], config: CatalogConfig, known_asset_ids: set[AssetId]
) -> list[ResolvedCollection]:
    """Resolve every loaded collection (``vpress status``'s and ``vpress
    attention``'s catalog-wide reference problems; ``vpress collections``'
    member-count column)."""
    return [resolve_collection(c, config, known_asset_ids) for c in collections]


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
    known_asset_ids: set[AssetId],
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
        resolved=resolve_collection(collection, config, known_asset_ids), problems=[]
    )
