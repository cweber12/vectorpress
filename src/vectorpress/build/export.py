"""A product's generic marketplace export (§18, §19, ADR 0016, ADR 0017).

``vpress build`` writes this module's own :class:`ListingExport`, serialized
to JSON, at ``builds/<slug>/export/listing.json`` -- beside the package and
ZIP, never inside either (ADR 0017's "exporters run inside vpress build...
never in the package or the ZIP"). It carries the product's hand-authored
``[listing]`` fields, the §18 derived values a build computes from its own
manifest (member count, formats, asset names, collection name), the
**contents summary** (:func:`contents_summary`), ``product.price``, the
ordered preview file names per canvas, and the ZIP's own name and size.
There is no CSV (ADR 0017); no AI disclosure field either -- a later
exporter slice adds one, never a placeholder here.

:func:`contents_summary` is its own function because it is not only
``listing.json``'s: ADR 0016's "assemble the customer-facing description as
the pitch, then a contents summary... then any disclosure" means every
marketplace text bundle (Etsy, Creative Fabrica, Design Bundles, a direct
store) builds its own DESCRIPTION from the identical facts, never
reassembling them.
"""

from dataclasses import dataclass

from vectorpress.build.listing_draft import collection_for_product, collection_name
from vectorpress.build.previews import CANVASES
from vectorpress.build.product_resolution import ProductMember
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.collection import Collection
from vectorpress.domain.listing import Listing
from vectorpress.domain.manifest import Manifest
from vectorpress.domain.product import Product

#: ``export/``'s own directory and file name, under the build directory
#: (never the package or the ZIP -- this module's own docstring).
EXPORT_DIRNAME = "export"
LISTING_EXPORT_FILENAME = "listing.json"


@dataclass(frozen=True)
class ContentsSummary:
    """The "what's included" facts built from one build's manifest
    (CONTEXT.md "Contents summary"): member count, included formats, every
    customer file name the build shipped, and the reference size those
    files were checked at. Never stored in the listing (ADR 0016), so it
    cannot go stale -- always rebuilt from the manifest that just built."""

    member_count: int
    formats: list[str]
    file_names: list[str]
    reference_size_in: float


@dataclass(frozen=True)
class ListingExport:
    """``export/listing.json``'s own shape: the product's hand-authored
    ``listing``, the §18 derived values (``member_count``, ``formats``,
    ``asset_names``, ``collection_name``), the :class:`ContentsSummary`,
    ``price``, the ordered preview file names keyed by canvas name, and the
    ZIP's own ``zip_name``/``zip_size_bytes``."""

    listing: Listing
    member_count: int
    formats: list[str]
    asset_names: list[str]
    collection_name: str
    contents_summary: ContentsSummary
    price: float
    previews: dict[str, list[str]]
    zip_name: str
    zip_size_bytes: int


def contents_summary(manifest: Manifest, product: Product) -> ContentsSummary:
    """The build's own :class:`ContentsSummary`: member count and every
    customer file name from ``manifest``'s ``members``/``dxf_members``
    (sorted for a deterministic export), ``product``'s own declared
    ``formats``, and the reference size ``manifest`` was built at."""
    member_asset_ids = {member.asset_id for member in manifest.members}
    file_names = sorted(
        {member.package_path for member in manifest.members}
        | {member.package_path for member in manifest.dxf_members}
    )
    return ContentsSummary(
        member_count=len(member_asset_ids),
        formats=[fmt.value for fmt in product.formats],
        file_names=file_names,
        reference_size_in=manifest.reference_size_in,
    )


def _preview_names_by_canvas(previews: list[str]) -> dict[str, list[str]]:
    """``manifest.previews`` (already upload-order: type number, page,
    canvas) split into one ordered list per :data:`~vectorpress.build.
    previews.CANVASES` name -- filtering preserves each preview's own
    relative type/page order, so no re-sort is needed."""
    return {
        canvas.name: [name for name in previews if name.endswith(f"-{canvas.name}.png")]
        for canvas in CANVASES
    }


def build_listing_export(
    product: Product,
    manifest: Manifest,
    known_collections: list[Collection],
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    zip_name: str,
    zip_size_bytes: int,
) -> ListingExport:
    """Assemble ``export/listing.json``'s own :class:`ListingExport` from
    ``product``'s ``[listing]``, this build's ``manifest``, and the same
    eligible-members/collection inputs :func:`~vectorpress.build.
    product_build.build_product` already resolved -- no second resolution
    path. ``known_collections`` is only used to look up the collection
    ``product`` references, the same way :func:`~vectorpress.build.
    listing_draft.draft_listing_for_product` already does.
    """
    assert product.listing is not None  # build_product's own listing gate already refused
    collection = collection_for_product(product, known_collections)
    asset_names = sorted(assets_by_id[member.asset_id].display_name for member in eligible_members)
    return ListingExport(
        listing=product.listing,
        member_count=len(eligible_members),
        formats=[fmt.value for fmt in product.formats],
        asset_names=asset_names,
        collection_name=collection_name(product, collection),
        contents_summary=contents_summary(manifest, product),
        price=product.price,
        previews=_preview_names_by_canvas(manifest.previews),
        zip_name=zip_name,
        zip_size_bytes=zip_size_bytes,
    )
