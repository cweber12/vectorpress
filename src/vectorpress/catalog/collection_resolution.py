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
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection, CollectionSlug
from vectorpress.domain.collection_resolution import ResolvedMember, resolve_membership

COLLECTION_CONFIG_SUFFIX = ".toml"

#: The field a reference problem in a membership's explicit list is
#: attributed to -- the same dotted path a pydantic-shape problem for this
#: field would use.
MEMBERSHIP_ASSET_IDS_FIELD = "membership.asset_ids"

#: Likewise, for a reference problem (unknown slug, or a cycle) in a
#: membership's collection union.
MEMBERSHIP_COLLECTION_SLUGS_FIELD = "membership.collection_slugs"


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
    reference_problems = [
        MetadataProblem(path, MEMBERSHIP_ASSET_IDS_FIELD, f"unknown asset ID: {asset_id!r}")
        for asset_id in resolution.unknown_asset_ids
    ]
    reference_problems.extend(
        MetadataProblem(path, MEMBERSHIP_COLLECTION_SLUGS_FIELD, f"unknown collection: {slug!r}")
        for slug in resolution.unknown_collection_slugs
    )
    reference_problems.extend(
        MetadataProblem(path, MEMBERSHIP_COLLECTION_SLUGS_FIELD, f"cycle: {' -> '.join(cycle)}")
        for cycle in resolution.cycles
    )
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
