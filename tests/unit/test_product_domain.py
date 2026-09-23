"""domain.product: the Product metadata model (ADR 0008, issue #7)."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.product import Format, Product, ProductTier

VALID_WITH_COLLECTION_SLUG = {
    "slug": "pacific_coast_tide_pool_standard_pack",
    "collection_slug": "pacific_coast_tide_pool",
    "derivative_types": ["cut_svg", "silhouette_svg"],
    "formats": ["svg", "png"],
    "tier": "standard_pack",
    "price": 12.0,
}

VALID_WITH_INLINE_MEMBERSHIP = {
    "slug": "kelp_forest_mini_pack",
    "membership": {"rule": {"field": "ecosystems", "values": ["Kelp forest"]}},
    "derivative_types": ["cut_svg"],
    "formats": ["svg"],
    "tier": "mini_pack",
    "price": 6.0,
}


def test_product_over_a_collection_slug_parses() -> None:
    product = Product.model_validate(VALID_WITH_COLLECTION_SLUG)

    assert product.collection_slug == "pacific_coast_tide_pool"
    assert product.membership is None
    assert product.derivative_types == [DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG]
    assert product.formats == [Format.SVG, Format.PNG]
    assert product.tier is ProductTier.STANDARD_PACK
    assert product.listing is None


def test_product_with_an_inline_membership_parses() -> None:
    product = Product.model_validate(VALID_WITH_INLINE_MEMBERSHIP)

    assert product.collection_slug is None
    assert product.membership is not None
    assert product.membership.rule is not None
    assert product.membership.rule.values == ["Kelp forest"]


def test_product_with_both_a_collection_slug_and_inline_membership_is_rejected() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "membership": {"asset_ids": ["ochre_sea_star"]},
    }

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_product_with_neither_a_collection_slug_nor_inline_membership_is_rejected() -> None:
    data = {k: v for k, v in VALID_WITH_COLLECTION_SLUG.items() if k != "collection_slug"}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_unknown_derivative_type_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "derivative_types": ["not_a_real_type"]}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_format_outside_section_7_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": ["webp"]}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_pdf_format_without_enablement_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": ["svg", "pdf"]}

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("formats",) for error in errors)


def test_eps_format_without_enablement_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": ["eps"]}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_pdf_format_with_explicit_enablement_is_accepted() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": ["svg", "pdf"], "enable_pdf_eps": True}

    product = Product.model_validate(data)

    assert Format.PDF in product.formats


def test_empty_derivative_types_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "derivative_types": []}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_empty_formats_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": []}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_negative_price_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "price": -1.0}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_family_defaults_to_none() -> None:
    product = Product.model_validate(VALID_WITH_COLLECTION_SLUG)

    assert product.family is None


def test_reference_size_override_defaults_to_none() -> None:
    product = Product.model_validate(VALID_WITH_COLLECTION_SLUG)

    assert product.reference_size_in is None


def test_reference_size_override_is_accepted() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "reference_size_in": 4.5}

    product = Product.model_validate(data)

    assert product.reference_size_in == 4.5


def test_unknown_key_is_rejected() -> None:
    data = {**VALID_WITH_COLLECTION_SLUG, "not_a_field": True}

    with pytest.raises(ValidationError):
        Product.model_validate(data)


def test_listing_is_optional() -> None:
    product = Product.model_validate(VALID_WITH_INLINE_MEMBERSHIP)

    assert product.listing is None


def test_unknown_listing_key_is_rejected() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "listing": {
            "title": "t",
            "short_title": "st",
            "description": "d",
            "category": "c",
            "suggested_price": 1.0,
            "license_type": "l",
            "not_a_field": True,
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("listing", "not_a_field") for error in errors)


def test_full_listing_is_accepted() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "listing": {
            "title": "Pacific Coast Tide Pool Cut File Collection",
            "short_title": "Tide Pool Collection",
            "description": "d",
            "tags": ["tide pool"],
            "search_terms": ["tide pool svg"],
            "intended_uses": ["vinyl cutting"],
            "region": "Pacific Coast",
            "species_names": ["Ochre Sea Star"],
            "category": "Nature & Wildlife",
            "suggested_price": 12.0,
            "license_type": "Personal & Small Business Use",
            "marketplace_notes": "n",
        },
    }

    product = Product.model_validate(data)

    assert product.listing is not None
    assert product.listing.title == "Pacific Coast Tide Pool Cut File Collection"


def test_product_tier_has_exactly_the_documented_tiers() -> None:
    assert {member.value for member in ProductTier} == {
        "individual",
        "mini_pack",
        "standard_pack",
        "collection",
        "mega_bundle",
    }


def test_format_has_exactly_the_documented_formats() -> None:
    assert {member.value for member in Format} == {"svg", "png", "dxf", "pdf", "eps"}


def test_derivative_type_has_exactly_the_documented_types() -> None:
    assert {member.value for member in DerivativeType} == {
        "transparent_png",
        "silhouette_svg",
        "cut_svg",
        "flatcolor_svg",
        "outline_svg",
        "detailed_mono_svg",
        "layered_svg",
    }
