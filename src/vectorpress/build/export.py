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
reassembling them. :func:`render_contents_summary_text` is that one text
rendering; :func:`render_marketplace_bundles` drops it, verbatim, after
each bundle's own listing description.

**Marketplace bundles.** One pasteable plain-text file per marketplace
(:data:`MARKETPLACE_BUNDLES`), also under ``export/``, never in the ZIP: a
labeled section per form field, in that marketplace's own form order. Their
layout comes from shipped ``templates/export/*.txt.j2`` (ADR 0015,
overridable by file name); the fixed context every bundle template renders
against is documented on :func:`render_marketplace_bundles`. No limits
enforcement and no AI disclosure here -- both are later exporter work
(ADR 0017, ADR 0018); this module never writes a placeholder for either.
"""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, TemplateError, TemplateNotFound, TemplateSyntaxError, UndefinedError

from vectorpress.build.listing_draft import collection_for_product, collection_name
from vectorpress.build.previews import CANVASES
from vectorpress.build.product_resolution import ProductMember
from vectorpress.build.template_lookup import (
    template_environment,
    template_name_from_traceback,
    used_overrides,
)
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.collection import Collection
from vectorpress.domain.listing import Listing
from vectorpress.domain.manifest import Manifest
from vectorpress.domain.numeric_format import format_number
from vectorpress.domain.product import Product

#: ``export/``'s own directory and file name, under the build directory
#: (never the package or the ZIP -- this module's own docstring).
EXPORT_DIRNAME = "export"
LISTING_EXPORT_FILENAME = "listing.json"

#: The template lookup "kind" marketplace bundles render through (ADR 0015):
#: catalog ``templates/export/`` first, then the shipped folder of the same
#: name.
EXPORT_KIND = "export"


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


# --- marketplace bundles (§19, ADR 0015, ADR 0017) --------------------------


def render_contents_summary_text(summary: ContentsSummary) -> str:
    """The one plain-text rendering of a :class:`ContentsSummary` (ADR
    0016's "assemble... then a contents summary"): member count, formats
    and every included file name, at the reference size those files were
    checked at. Every marketplace bundle's DESCRIPTION appends this
    verbatim after the listing description -- computed once, here, so no
    bundle ever reassembles the same facts into slightly different wording.
    """
    member_word = "member" if summary.member_count == 1 else "members"
    formats = ", ".join(fmt.upper() for fmt in summary.formats)
    lines = [
        f"What's included: {summary.member_count} {member_word}, {formats} files, "
        f"checked to cut cleanly at {format_number(summary.reference_size_in)}in.",
        "",
        "Files:",
        *(f"- {name}" for name in summary.file_names),
    ]
    return "\n".join(lines)


#: Etsy's own WHO MADE answer for a solo-designed digital pack, with no
#: included member's rights status yet weighed in (a later exporter slice
#: adds the AI-generated wording, ADR 0018) -- the value only
#: ``etsy.txt.j2`` reads.
_ETSY_WHO_MADE = "I did"


@dataclass(frozen=True)
class MarketplaceBundle:
    """One marketplace's own pasteable text bundle (§19, ADR 0017): the
    file :func:`render_marketplace_bundles` writes under ``export/``, its
    shipped template (ADR 0015, overridable by file name under
    ``templates/export/``), and which :data:`~vectorpress.build.previews.
    CANVASES` name its IMAGES section lists -- Etsy and the direct store
    use ``square``, Creative Fabrica and Design Bundles use ``landscape``
    (§16's two fixed canvases; marketplaces differ in image shape, not
    content)."""

    name: str
    filename: str
    template_name: str
    canvas: str


#: Every marketplace bundle a build writes (§19, ADR 0017), in no
#: particular order -- each is its own file, so nothing depends on this
#: tuple's own ordering.
MARKETPLACE_BUNDLES: tuple[MarketplaceBundle, ...] = (
    MarketplaceBundle("etsy", "etsy.txt", "etsy.txt.j2", "square"),
    MarketplaceBundle(
        "creative_fabrica", "creative-fabrica.txt", "creative-fabrica.txt.j2", "landscape"
    ),
    MarketplaceBundle("design_bundles", "design-bundles.txt", "design-bundles.txt.j2", "landscape"),
    MarketplaceBundle("direct_store", "direct-store.txt", "direct-store.txt.j2", "square"),
)


class ExportRenderError(Exception):
    """One marketplace bundle failed to render (ADR 0017): a template
    syntax error, a missing template (a catalog override's own
    ``{% extends %}``/``{% include %}`` naming a file that does not exist),
    or an undefined template variable. ``template_name`` is set whenever
    the failure traces to one template file."""

    def __init__(self, message: str, template_name: str | None = None) -> None:
        super().__init__(message)
        self.template_name = template_name


@dataclass(frozen=True)
class ExportRenderFailure:
    """One marketplace bundle rendering failure (§19, ADR 0017), as a plain
    value: the template it traces to, when the failure names one, and the
    underlying error's own message. Mirrors :class:`~vectorpress.build.
    previews.PreviewRenderFailure` -- :func:`~vectorpress.build.
    product_build.build_product` turns either into a whole-build refusal
    the same way."""

    template_name: str | None
    message: str


def _render_bundle_text(
    environment: Environment, root: Path, template_name: str, **context: object
) -> str:
    """One marketplace bundle's rendered text -- Jinja only, no Chromium.
    Mirrors :func:`~vectorpress.build.previews._render_html`'s single
    try/except: every way a template render can fail (a syntax error, a
    missing file, an undefined variable) becomes a named
    :class:`ExportRenderError`, never an uncaught Jinja exception."""
    try:
        template = environment.get_template(template_name)
        return template.render(**context)
    except TemplateSyntaxError as exc:
        raise ExportRenderError(str(exc), template_name=exc.name or template_name) from exc
    except TemplateNotFound as exc:
        name = exc.name if isinstance(exc.name, str) else template_name
        raise ExportRenderError(str(exc), template_name=name) from exc
    except UndefinedError as exc:
        name = template_name_from_traceback(exc, root, EXPORT_KIND) or template_name
        raise ExportRenderError(str(exc), template_name=name) from exc
    except TemplateError as exc:
        name = template_name_from_traceback(exc, root, EXPORT_KIND) or template_name
        raise ExportRenderError(str(exc), template_name=name) from exc


@dataclass(frozen=True)
class MarketplaceBundleResult:
    """:func:`render_marketplace_bundles`'s own result: the rendered bundle
    files (``export/<name>``, text bytes) and the catalog
    ``templates/export/`` overrides this render actually used (ADR 0015's
    build report list) -- drawn from the one environment every bundle
    shares, so the override list reflects exactly this build's own
    renders."""

    files: list[tuple[str, bytes]]
    template_overrides: list[str]


def render_marketplace_bundles(root: Path, export: ListingExport) -> MarketplaceBundleResult:
    """Every :data:`MARKETPLACE_BUNDLES` entry's own pasteable text file
    (§19, ADR 0017), rendered from ``export`` -- the same
    :class:`ListingExport` :func:`build_listing_export` already assembled,
    so nothing about a product's listing or a build's contents is resolved
    twice.

    Every bundle renders against the identical fixed context (ADR 0015):
    ``title``, ``description`` (the listing description, then
    :func:`render_contents_summary_text`'s own text, verbatim -- ADR 0016),
    ``tags``, ``price``, ``category``, ``who_made`` (``None`` except for
    Etsy's own shipped template, the only one that reads it -- "WHO MADE
    where the form asks"), ``images`` (this bundle's own
    :attr:`MarketplaceBundle.canvas`, upload order, file names only, no
    ``previews/`` prefix) and ``zip_name``. Reading anything else fails the
    build naming the template (StrictUndefined), the same as a preview
    render.

    Raises :class:`ExportRenderError` naming the offending template --
    :func:`~vectorpress.build.product_build.build_product` turns it into a
    whole-build refusal, never an uncaught Jinja exception, the same way a
    preview render failure does.
    """
    environment = template_environment(root, EXPORT_KIND)
    description = "\n\n".join(
        (export.listing.description, render_contents_summary_text(export.contents_summary))
    )
    files: list[tuple[str, bytes]] = []
    for bundle in MARKETPLACE_BUNDLES:
        images = [Path(name).name for name in export.previews.get(bundle.canvas, [])]
        context: dict[str, object] = {
            "title": export.listing.title,
            "description": description,
            "tags": export.listing.tags,
            "price": export.price,
            "category": export.listing.category,
            "who_made": _ETSY_WHO_MADE if bundle.name == "etsy" else None,
            "images": images,
            "zip_name": export.zip_name,
        }
        text = _render_bundle_text(environment, root, bundle.template_name, **context)
        files.append((f"{EXPORT_DIRNAME}/{bundle.filename}", text.encode("utf-8")))
    return MarketplaceBundleResult(files=files, template_overrides=used_overrides(environment))
