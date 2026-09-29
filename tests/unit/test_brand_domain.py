"""Domain-layer tests for Brand: pure validation, no I/O."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.brand import Brand, BrandCardStyle, BrandTypography

VALID_DATA = {
    "name": "Tide Pool Studio",
    "mark_file": "mark.png",
    "typography": {"heading_font": "Quicksand", "body_font": "Nunito Sans"},
    "card_style": {
        "background_color": "#F4F1EC",
        "accent_color": "#C45D26",
        "text_color": "#1F2A24",
    },
    "standard_wording": "Hand-illustrated, scientifically accurate cut files.",
    "license_name": "Tide Pool Studio Personal & Small Business Use License",
    "license_file": "license_template.txt",
    "copyright_wording": "© Tide Pool Studio. All rights reserved.",
    "readme_text": "Thank you for your purchase!",
}


def test_valid_brand_parses() -> None:
    brand = Brand.model_validate(VALID_DATA)

    assert brand.name == "Tide Pool Studio"
    assert brand.mark_file == "mark.png"
    assert brand.typography == BrandTypography(heading_font="Quicksand", body_font="Nunito Sans")
    assert brand.card_style == BrandCardStyle(
        background_color="#F4F1EC", accent_color="#C45D26", text_color="#1F2A24"
    )
    assert brand.license_name == "Tide Pool Studio Personal & Small Business Use License"
    assert brand.license_file == "license_template.txt"


def test_unknown_key_is_rejected() -> None:
    data = {**VALID_DATA, "not_a_field": True}

    with pytest.raises(ValidationError) as exc_info:
        Brand.model_validate(data)

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("not_a_field",) for error in errors)


@pytest.mark.parametrize("field", list(VALID_DATA))
def test_each_required_field_is_rejected_when_missing(field: str) -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != field}

    with pytest.raises(ValidationError) as exc_info:
        Brand.model_validate(data)

    errors = exc_info.value.errors()
    assert any(error["loc"] == (field,) for error in errors)


def test_typography_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        BrandTypography.model_validate(
            {"heading_font": "Quicksand", "body_font": "Nunito Sans", "extra": True}
        )


def test_card_style_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        BrandCardStyle.model_validate(
            {
                "background_color": "#F4F1EC",
                "accent_color": "#C45D26",
                "text_color": "#1F2A24",
                "extra": True,
            }
        )


def test_typography_requires_both_fonts() -> None:
    with pytest.raises(ValidationError):
        BrandTypography.model_validate({"heading_font": "Quicksand"})


def test_card_style_requires_all_colors() -> None:
    with pytest.raises(ValidationError):
        BrandCardStyle.model_validate({"background_color": "#F4F1EC"})


def test_typography_font_files_default_to_none() -> None:
    typography = BrandTypography.model_validate({"heading_font": "Inter", "body_font": "Inter"})

    assert typography.heading_font_file is None
    assert typography.body_font_file is None


def test_typography_accepts_a_catalog_font_file_per_role() -> None:
    typography = BrandTypography.model_validate(
        {
            "heading_font": "Brand Sans",
            "body_font": "Brand Sans",
            "heading_font_file": "fonts/brand-sans.woff2",
            "body_font_file": "fonts/brand-sans.woff2",
        }
    )

    assert typography.heading_font_file == "fonts/brand-sans.woff2"
    assert typography.body_font_file == "fonts/brand-sans.woff2"
