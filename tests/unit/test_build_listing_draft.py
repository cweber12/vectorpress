"""build.listing_draft: computing a product's drafted ``[listing]`` from its
collection, resolved members and brand config (§18, ADR 0016).

The pure helpers (``_format_phrase``, ``_draft_tags``, ``_draft_intended_uses``,
``_draft_region``, ``_draft_species_names``) and :func:`draft_listing` run
against hand-built domain objects -- no catalog needed. :func:`draft_listing_for_product`
resolves membership for real, so it runs against the committed fixture
catalog directly (read-only, like ``test_build_product_resolution.py``): no
draft is ever written here, this module only computes the values.
"""

from pathlib import Path

from vectorpress.build.listing_draft import (
    ListingDraftOutcome,
    _draft_intended_uses,  # pyright: ignore[reportPrivateUsage]
    _draft_region,  # pyright: ignore[reportPrivateUsage]
    _draft_species_names,  # pyright: ignore[reportPrivateUsage]
    _draft_tags,  # pyright: ignore[reportPrivateUsage]
    _format_phrase,  # pyright: ignore[reportPrivateUsage]
    _title_cased_slug,  # pyright: ignore[reportPrivateUsage]
    draft_listing,
    draft_listing_for_product,
)
from vectorpress.build.template_lookup import template_environment
from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.asset import Asset
from vectorpress.domain.brand import Brand, BrandCardStyle, BrandTypography
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.membership import Membership
from vectorpress.domain.product import Product

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def _asset(
    asset_id: str,
    display_name: str,
    *,
    product_use_categories: tuple[str, ...] = (),
    regions: tuple[str, ...] = (),
    scientific_name: str | None = None,
) -> Asset:
    return Asset(
        id=asset_id,
        common_name=display_name,
        display_name=display_name,
        scientific_name=scientific_name,
        description="A test subject.",
        subject_category="Test",
        tags=["member-only-tag"],
        regions=list(regions),
        ecosystems=[],
        taxonomic_group="Test",
        product_use_categories=list(product_use_categories),
        rights_status="original_artwork",  # type: ignore[arg-type]
        accuracy_status="not_reviewed",  # type: ignore[arg-type]
    )


def _brand(**overrides: object) -> Brand:
    fields: dict[str, object] = {
        "name": "Test Brand",
        "mark_file": "mark.png",
        "typography": BrandTypography(heading_font="A", body_font="B"),
        "card_style": BrandCardStyle(
            background_color="#000000", accent_color="#111111", text_color="#222222"
        ),
        "standard_wording": "Standard wording text.",
        "license_name": "Test License",
        "license_file": "LICENSE.txt",
        "copyright_wording": "(c) Test Brand",
        "readme_text": "Thanks!",
    }
    fields.update(overrides)
    return Brand(**fields)  # type: ignore[arg-type]


def _collection(**overrides: object) -> Collection:
    fields: dict[str, object] = {
        "slug": "test_collection",
        "name": "Test Collection",
        "description": "A pitch for the test collection.",
        "tags": ["collection-tag"],
        "marketplace_category": "Nature & Wildlife",
        "membership": Membership(asset_ids=["a"]),
    }
    fields.update(overrides)
    return Collection(**fields)  # type: ignore[arg-type]


def _product(**overrides: object) -> Product:
    fields: dict[str, object] = {
        "slug": "test_product",
        "collection_slug": "test_collection",
        "derivative_types": [DerivativeType.CUT_SVG],
        "formats": [Format.SVG],
        "tier": "individual",
        "price": 1.0,
    }
    fields.update(overrides)
    return Product(**fields)  # type: ignore[arg-type]


# --- pure helpers -------------------------------------------------------


def test_format_phrase_with_one_format() -> None:
    assert _format_phrase([Format.SVG]) == "SVG Cut Files"


def test_format_phrase_with_two_formats() -> None:
    assert _format_phrase([Format.SVG, Format.PNG]) == "SVG & PNG Cut Files"


def test_format_phrase_with_three_formats_has_no_oxford_comma() -> None:
    assert _format_phrase([Format.SVG, Format.PNG, Format.DXF]) == "SVG, PNG & DXF Cut Files"


def test_title_cased_slug_replaces_underscores_and_capitalizes_each_word() -> None:
    assert _title_cased_slug("kelp_forest_mini_pack") == "Kelp Forest Mini Pack"


def test_draft_tags_combines_collection_tags_type_words_and_format_words_deduplicated() -> None:
    tags = _draft_tags(
        ["tide pool", "svg"],
        [DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG],
        [Format.SVG],
    )
    # "svg" (a collection tag) and the format word "svg" collide -- first
    # occurrence wins, so it appears once, in its earlier position.
    assert tags == ["tide pool", "svg", "cut file", "silhouette"]


def test_draft_intended_uses_orders_most_common_first_ties_by_first_seen() -> None:
    members = [
        _asset("a", "A", product_use_categories=("apparel", "wall art")),
        _asset("b", "B", product_use_categories=("apparel", "stickers")),
    ]
    # apparel: 2, wall art: 1, stickers: 1 -- ties keep first-seen order.
    assert _draft_intended_uses(members) == ["apparel", "wall art", "stickers"]


def test_draft_region_returns_the_one_region_every_member_shares() -> None:
    members = [
        _asset("a", "A", regions=("California", "Pacific Coast")),
        _asset("b", "B", regions=("Pacific Coast", "Oregon")),
    ]
    assert _draft_region(members) == "Pacific Coast"


def test_draft_region_is_unset_when_members_share_nothing() -> None:
    members = [_asset("a", "A", regions=("California",)), _asset("b", "B", regions=("Oregon",))]
    assert _draft_region(members) is None


def test_draft_region_is_unset_when_more_than_one_region_is_shared() -> None:
    members = [
        _asset("a", "A", regions=("California", "Oregon")),
        _asset("b", "B", regions=("California", "Oregon")),
    ]
    assert _draft_region(members) is None


def test_draft_region_is_unset_with_no_members() -> None:
    assert _draft_region([]) is None


def test_draft_species_names_deduplicates_sorts_and_skips_unset() -> None:
    members = [
        _asset("a", "A", scientific_name="Zeta zeta"),
        _asset("b", "B", scientific_name="Alpha alpha"),
        _asset("c", "C", scientific_name=None),
        _asset("d", "D", scientific_name="Alpha alpha"),
    ]
    assert _draft_species_names(members) == ["Alpha alpha", "Zeta zeta"]


# --- draft_listing (hand-built inputs) -----------------------------------


def test_draft_listing_from_a_referenced_collection() -> None:
    environment = template_environment(FIXTURE_CATALOG_ROOT, "listing")
    collection = _collection()
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG],
    )
    members = [
        _asset("a", "Asset A", product_use_categories=("apparel",), regions=("Pacific Coast",)),
        _asset("b", "Asset B", product_use_categories=("apparel",), regions=("Pacific Coast",)),
    ]
    brand = _brand()

    listing = draft_listing(product, collection, members, brand, environment)

    assert listing.title == "Test Collection \u2013 SVG & PNG Cut Files"
    assert listing.short_title == "Test Collection"
    assert listing.description == "A pitch for the test collection.\n\nStandard wording text."
    assert listing.tags == ["collection-tag", "cut file", "color png", "svg", "png"]
    assert listing.search_terms == ["asset a", "asset b"]
    assert listing.intended_uses == ["apparel"]
    assert listing.region == "Pacific Coast"
    assert listing.species_names == []
    assert listing.category == "Nature & Wildlife"
    assert listing.license_type == "Test License"
    assert listing.marketplace_notes == ""


def test_draft_listing_for_an_inline_membership_uses_title_cased_slug_and_empty_category() -> None:
    environment = template_environment(FIXTURE_CATALOG_ROOT, "listing")
    product = _product(
        slug="kelp_forest_mini_pack",
        collection_slug=None,
        membership=Membership(asset_ids=["a"]),
        derivative_types=[DerivativeType.CUT_SVG],
        formats=[Format.SVG],
    )
    brand = _brand()

    listing = draft_listing(product, None, [], brand, environment)

    assert listing.short_title == "Kelp Forest Mini Pack"
    assert listing.title == "Kelp Forest Mini Pack \u2013 SVG Cut Files"
    assert listing.category == ""
    # No collection description to lead with -- just the brand's own wording.
    assert listing.description == "Standard wording text."


def test_draft_listing_catalog_template_override_changes_the_title(tmp_path: Path) -> None:
    """ADR 0015: a file at ``<catalog>/templates/listing/title.txt.j2``
    replaces the shipped one by file name."""
    override_dir = tmp_path / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "title.txt.j2").write_text("Custom: {{ name }}\n", encoding="utf-8")
    environment = template_environment(tmp_path, "listing")

    collection = _collection()
    product = _product(formats=[Format.SVG])

    listing = draft_listing(product, collection, [], _brand(), environment)

    assert listing.title == "Custom: Test Collection"


def test_draft_listing_catalog_template_override_changes_the_description(tmp_path: Path) -> None:
    override_dir = tmp_path / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "description.txt.j2").write_text("Overridden pitch.\n", encoding="utf-8")
    environment = template_environment(tmp_path, "listing")

    collection = _collection()
    product = _product(formats=[Format.SVG])

    listing = draft_listing(product, collection, [], _brand(), environment)

    assert listing.description == "Overridden pitch."


def test_draft_listing_catalog_template_can_extend_the_shipped_template_it_overrides(
    tmp_path: Path,
) -> None:
    """ADR 0015: ``{% extends %}`` and blocks give partial overrides. A
    plain ``{% extends "title.txt.j2" %}`` from a catalog override of that
    same name would resolve back to itself (self-recursion); the fixed
    ``shipped/`` prefix reaches the shipped file underneath it instead."""
    override_dir = tmp_path / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "title.txt.j2").write_text(
        '{% extends "shipped/title.txt.j2" %}\n'
        "{% block title %}Custom: {{ super() }}{% endblock %}\n",
        encoding="utf-8",
    )
    environment = template_environment(tmp_path, "listing")

    collection = _collection()
    product = _product(formats=[Format.SVG])

    listing = draft_listing(product, collection, [], _brand(), environment)

    assert listing.title == "Custom: Test Collection \u2013 SVG Cut Files"


# --- draft_listing_for_product (real membership resolution) --------------


def test_draft_listing_for_product_refuses_on_an_unknown_collection_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    product = _product(collection_slug="does_not_exist")

    result = draft_listing_for_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections, _brand()
    )

    assert result.outcome is ListingDraftOutcome.REFUSED_REFERENCE_PROBLEMS
    assert result.listing is None
    assert result.reference_problems


def test_draft_listing_for_product_drafts_from_the_tide_pool_collection() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    collection = next(c for c in known_collections if c.slug == "pacific_coast_tide_pool")
    product = _product(
        slug="test_tide_pool_product",
        collection_slug="pacific_coast_tide_pool",
        derivative_types=[DerivativeType.CUT_SVG],
        formats=[Format.SVG],
    )

    brand = _brand()
    result = draft_listing_for_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections, brand
    )

    assert result.outcome is ListingDraftOutcome.DRAFTED
    assert result.listing is not None
    listing = result.listing
    assert listing.title == "Pacific Coast Tide Pool \u2013 SVG Cut Files"
    assert listing.short_title == "Pacific Coast Tide Pool"
    assert listing.description == f"{collection.description.strip()}\n\n{brand.standard_wording}"
    assert listing.tags == ["tide pool", "pacific coast", "cut file", "svg"]
    # Members sorted by asset ID: giant_green_anemone, ochre_sea_star, purple_sea_urchin.
    assert listing.search_terms == ["giant green anemone", "ochre sea star", "purple sea urchin"]
    assert listing.intended_uses == ["apparel", "wall art", "stickers"]
    # No single region every member shares (their regions overlap on three).
    assert listing.region is None
    assert listing.species_names == [
        "Anthopleura xanthogrammica",
        "Pisaster ochraceus",
        "Strongylocentrotus purpuratus",
    ]
    assert listing.category == "Nature & Wildlife"
    assert listing.license_type == "Test License"
    assert listing.marketplace_notes == ""
