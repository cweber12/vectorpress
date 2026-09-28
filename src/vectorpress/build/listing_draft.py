"""Draft a product's ``[listing]`` values from its collection, resolved
members and brand config (§18, ADR 0016).

Pure computation over already-resolved inputs -- :func:`draft_listing` reads
no files itself, so it is unit-testable with hand-built domain objects.
:func:`draft_listing_for_product` is the orchestration entry point ``cli``
calls: membership resolves through :func:`~vectorpress.build.
product_resolution.resolve_product`, the identical decision ``vpress
product`` and ``vpress build`` already use (ADR 0011, no second resolution
path), so a product whose membership does not fully resolve refuses here the
same way a build would.

``title`` and ``description`` render through ``templates/listing/`` (ADR
0015): a catalog override replaces the shipped template by file name. Their
context is exactly ``name`` and ``format_phrase`` for ``title.txt.j2``, and
``collection_description`` and ``standard_wording`` for
``description.txt.j2`` -- reading anything else fails the draft, naming the
template (``StrictUndefined``, :mod:`vectorpress.build.template_lookup`).

Every other field is plain Python, with no template involved: §18 calls for
prose and choices to come from templates, not the mechanically assembled
tag list, search terms, or the one region every member shares.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jinja2 import Environment

from vectorpress.build.product_resolution import resolve_product
from vectorpress.build.template_lookup import template_environment
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.asset import Asset
from vectorpress.domain.brand import Brand
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.listing import Listing
from vectorpress.domain.product import Product

#: §20's customer-facing label for each format in a drafted title's format
#: phrase (e.g. "SVG, PNG & DXF Cut Files").
_FORMAT_LABELS: dict[Format, str] = {
    Format.SVG: "SVG",
    Format.PNG: "PNG",
    Format.DXF: "DXF",
    Format.PDF: "PDF",
    Format.EPS: "EPS",
}

#: One fixed tag word per included derivative type, added to a drafted
#: listing's ``tags`` (never a member's own tags -- ADR 0016).
_DERIVATIVE_TYPE_TAG_WORDS: dict[DerivativeType, str] = {
    DerivativeType.TRANSPARENT_PNG: "color png",
    DerivativeType.SILHOUETTE_SVG: "silhouette",
    DerivativeType.CUT_SVG: "cut file",
    DerivativeType.FLATCOLOR_SVG: "flat color svg",
    DerivativeType.OUTLINE_SVG: "outline svg",
    DerivativeType.DETAILED_MONO_SVG: "detailed svg",
    DerivativeType.LAYERED_SVG: "layered svg",
}

#: One fixed tag word per listed format, added to a drafted listing's ``tags``.
_FORMAT_TAG_WORDS: dict[Format, str] = {
    Format.SVG: "svg",
    Format.PNG: "png",
    Format.DXF: "dxf",
    Format.PDF: "pdf",
    Format.EPS: "eps",
}


def _title_cased_slug(slug: str) -> str:
    """The stand-in for "collection name" an inline membership has none of
    (§18's short_title row): the slug with underscores turned to spaces and
    every word capitalized -- ``"kelp_forest_mini_pack"`` becomes ``"Kelp
    Forest Mini Pack"``."""
    return slug.replace("_", " ").title()


def _format_phrase(formats: list[Format]) -> str:
    """The drafted title's format phrase (§18): every listed format's label,
    in the product's own declared order, joined with commas and a final
    "&", plus the fixed suffix -- one format reads ``"SVG Cut Files"``, two
    ``"SVG & PNG Cut Files"``, three or more ``"SVG, PNG & DXF Cut
    Files"``."""
    labels = [_FORMAT_LABELS[fmt] for fmt in formats]
    if len(labels) == 1:
        joined = labels[0]
    elif len(labels) == 2:
        joined = f"{labels[0]} & {labels[1]}"
    else:
        joined = ", ".join(labels[:-1]) + f" & {labels[-1]}"
    return f"{joined} Cut Files"


def _draft_tags(
    collection_tags: list[str],
    derivative_types: list[DerivativeType],
    formats: list[Format],
) -> list[str]:
    """§18's ``tags``: the collection's own tags, then one fixed word per
    included derivative type, then one per listed format -- deduplicated,
    first occurrence wins, never a member's own tags."""
    words = [
        *collection_tags,
        *(_DERIVATIVE_TYPE_TAG_WORDS[derivative_type] for derivative_type in derivative_types),
        *(_FORMAT_TAG_WORDS[fmt] for fmt in formats),
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for word in words:
        if word not in seen:
            seen.add(word)
            deduped.append(word)
    return deduped


def _draft_intended_uses(members: list[Asset]) -> list[str]:
    """§18's ``intended_uses``: the union of every member's own
    ``product_use_categories``, most common first; ties keep the order the
    value was first seen in, for a deterministic draft."""
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for member in members:
        for use in member.product_use_categories:
            counts[use] = counts.get(use, 0) + 1
            first_seen.setdefault(use, len(first_seen))
    return sorted(counts, key=lambda use: (-counts[use], first_seen[use]))


def _draft_region(members: list[Asset]) -> str | None:
    """§18's ``region``: the one region every member's own ``regions``
    shares, else unset -- an empty member list, or a shared set of anything
    but exactly one region, both draft unset rather than guess."""
    if not members:
        return None
    shared = set(members[0].regions)
    for member in members[1:]:
        shared &= set(member.regions)
    if len(shared) == 1:
        return next(iter(shared))
    return None


def _draft_species_names(members: list[Asset]) -> list[str]:
    """§18's ``species_names``: every member's non-empty ``scientific_name``,
    deduplicated and sorted."""
    return sorted({member.scientific_name for member in members if member.scientific_name})


def draft_listing(
    product: Product,
    collection: Collection | None,
    members: list[Asset],
    brand: Brand,
    environment: Environment,
) -> Listing:
    """Draft ``product``'s ``[listing]`` (§18, ADR 0016) from its
    collection (``None`` for an inline membership -- CONTEXT.md
    "Membership"), its resolved members' own metadata, and the catalog's
    brand config.

    ``members`` is every resolved member, eligible or not: a listing is
    drafted from what the product declares, not from what happens to be
    approved yet. ``environment`` renders ``title.txt.j2`` and
    ``description.txt.j2`` (:mod:`vectorpress.build.template_lookup`);
    every other field is computed directly, never templated.
    """
    name = collection.name if collection is not None else _title_cased_slug(product.slug)
    format_phrase = _format_phrase(product.formats)
    title = environment.get_template("title.txt.j2").render(name=name, format_phrase=format_phrase)

    collection_description = collection.description.strip() if collection is not None else None
    description = environment.get_template("description.txt.j2").render(
        collection_description=collection_description,
        standard_wording=brand.standard_wording.strip(),
    )

    return Listing(
        title=title.strip(),
        short_title=name,
        description=description.strip(),
        tags=_draft_tags(
            collection.tags if collection is not None else [],
            product.derivative_types,
            product.formats,
        ),
        search_terms=[member.display_name.lower() for member in members],
        intended_uses=_draft_intended_uses(members),
        region=_draft_region(members),
        species_names=_draft_species_names(members),
        category=collection.marketplace_category if collection is not None else "",
        license_type=brand.license_name,
        marketplace_notes="",
    )


class ListingDraftOutcome(StrEnum):
    """One :func:`draft_listing_for_product` outcome: drafted, or refused
    because the product's own membership does not fully resolve (the same
    refusal ``vpress build`` reports -- no second resolution path)."""

    DRAFTED = "drafted"
    REFUSED_REFERENCE_PROBLEMS = "refused_reference_problems"


@dataclass(frozen=True)
class ListingDraftResult:
    """The outcome of one :func:`draft_listing_for_product` call: exactly
    one of ``listing`` or ``reference_problems`` is set, matching
    ``outcome``."""

    outcome: ListingDraftOutcome
    listing: Listing | None = None
    reference_problems: list[MetadataProblem] | None = None


def _collection_for_product(
    product: Product, known_collections: list[Collection]
) -> Collection | None:
    """The collection a product references, or ``None`` for an inline
    membership. Only reached once :func:`resolve_product` has already
    confirmed a named ``collection_slug`` resolves, so the lookup here never
    misses."""
    if product.collection_slug is None:
        return None
    return next(c for c in known_collections if c.slug == product.collection_slug)


def draft_listing_for_product(
    product: Product,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
    brand: Brand,
) -> ListingDraftResult:
    """Resolve ``product``'s current membership and draft its ``[listing]``
    (§18, ADR 0016), or refuse when that membership does not fully resolve
    -- the orchestration entry point ``cli`` calls.

    Resolves through :func:`~vectorpress.build.product_resolution.
    resolve_product` (ADR 0011): the identical membership ``vpress
    product``/``vpress build`` already show, not a second resolution path.
    """
    resolved = resolve_product(product, root, config, known_assets, known_collections)
    if resolved.reference_problems:
        return ListingDraftResult(
            ListingDraftOutcome.REFUSED_REFERENCE_PROBLEMS,
            reference_problems=resolved.reference_problems,
        )

    assets_by_id = {asset.id: asset for asset in known_assets}
    members = [assets_by_id[member.asset_id] for member in resolved.members]
    collection = _collection_for_product(product, known_collections)
    environment = template_environment(root, "listing")
    listing = draft_listing(product, collection, members, brand, environment)
    return ListingDraftResult(ListingDraftOutcome.DRAFTED, listing=listing)
