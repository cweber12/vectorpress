"""domain.product: the Product metadata model (ADR 0008, issue #7)."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.metadata_field_error import MetadataFieldError, MetadataFieldsError
from vectorpress.domain.product import Format, Product, ProductTier

VALID_WITH_COLLECTION_SLUG = {
    "slug": "pacific_coast_tide_pool_standard_pack",
    "collection_slug": "pacific_coast_tide_pool",
    # Both types are *_svg, so "svg" alone carries them (ADR 0013); no
    # transparent_png here, so a "png" format would be an unfilled mismatch.
    "derivative_types": ["cut_svg", "silhouette_svg"],
    "formats": ["svg"],
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
    assert product.formats == [Format.SVG]
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

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    # loc is empty (this is a cross-field check on Product itself), so the
    # raised MetadataFieldError is how catalog.metadata_problem attributes
    # the resulting problem to a field (issue #16).
    assert errors[0]["loc"] == ()
    raised = errors[0].get("ctx", {}).get("error")
    assert isinstance(raised, MetadataFieldError)
    assert raised.field == "collection_slug/membership"


def test_product_with_neither_a_collection_slug_nor_inline_membership_is_rejected() -> None:
    data = {k: v for k, v in VALID_WITH_COLLECTION_SLUG.items() if k != "collection_slug"}

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    raised = errors[0].get("ctx", {}).get("error")
    assert isinstance(raised, MetadataFieldError)
    assert raised.field == "collection_slug/membership"


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


def test_pdf_format_with_explicit_enablement_is_still_a_format_type_mismatch() -> None:
    """ADR 0013: no type fills pdf in this PRD, so enabling it does not
    make it valid -- a product still cannot claim a format the build will
    never produce."""
    data = {**VALID_WITH_COLLECTION_SLUG, "formats": ["svg", "pdf"], "enable_pdf_eps": True}

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    raised = exc_info.value.errors()[0].get("ctx", {}).get("error")
    assert isinstance(raised, MetadataFieldsError)
    assert any(field == "formats" and "pdf" in message for field, message in raised.problems)


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


# --- ADR 0013 format/derivative-type mismatch is a load-time problem ------


def test_dxf_format_without_a_dxf_source_type_is_rejected_naming_dxf() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "derivative_types": ["flatcolor_svg"],
        "formats": ["dxf"],
    }

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    raised = errors[0].get("ctx", {}).get("error")
    assert isinstance(raised, MetadataFieldsError)
    assert any(field == "formats" and "dxf" in message for field, message in raised.problems)


def test_transparent_png_without_png_format_is_rejected_naming_both_fields() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "derivative_types": ["transparent_png"],
        "formats": ["svg"],
    }

    with pytest.raises(ValidationError) as exc_info:
        Product.model_validate(data)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    raised = errors[0].get("ctx", {}).get("error")
    assert isinstance(raised, MetadataFieldsError)
    assert any(
        field == "derivative_types" and "transparent_png" in message
        for field, message in raised.problems
    )
    assert any(field == "formats" and "svg" in message for field, message in raised.problems)


def test_matching_formats_and_derivative_types_load_cleanly() -> None:
    data = {
        **VALID_WITH_COLLECTION_SLUG,
        "derivative_types": ["cut_svg", "silhouette_svg", "transparent_png"],
        "formats": ["svg", "png", "dxf"],
    }

    product = Product.model_validate(data)

    assert product.formats == [Format.SVG, Format.PNG, Format.DXF]


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
