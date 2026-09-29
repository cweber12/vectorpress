"""build.previews: the ``main`` preview's context and Jinja rendering (§16,
ADR 0014, ADR 0015).

Everything here runs against hand-built domain objects and a bare
``tmp_path`` catalog root -- no generated derivative, no catalog fixture,
and (this module's own point) no Chromium: :func:`render_main_html` is pure
Jinja, so an undefined-variable problem is a plain Python exception, never a
browser launch. Rendering the resulting HTML into an actual PNG
(:func:`~vectorpress.build.previews.render_main_previews`) is covered by
``tests/integration/test_previews.py`` instead, against the real fixture
catalog, since that needs Chromium installed.
"""

import re
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from vectorpress.build.previews import (
    Canvas,
    PreviewRenderError,
    preview_members,
    render_main_html,
)
from vectorpress.build.product_resolution import MemberEligibility, ProductMember
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.brand import Brand, BrandCardStyle, BrandTypography
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.listing import Listing
from vectorpress.domain.product import Product

_SQUARE = Canvas("square", 2000, 2000)


def _asset(asset_id: str, display_name: str) -> Asset:
    return Asset(
        id=asset_id,
        common_name=display_name,
        display_name=display_name,
        scientific_name=None,
        description="A test subject.",
        subject_category="Test",
        tags=[],
        regions=[],
        ecosystems=[],
        taxonomic_group="Test",
        product_use_categories=[],
        rights_status="original_artwork",  # type: ignore[arg-type]
        accuracy_status="not_reviewed",  # type: ignore[arg-type]
    )


def _member(asset_id: str) -> ProductMember:
    return ProductMember(
        asset_id=asset_id,
        ways_in=(),
        eligibility=MemberEligibility.ELIGIBLE,
        blocking_reasons=[],
        warnings=[],
        admitted_unapproved=[],
    )


def _brand(**overrides: object) -> Brand:
    fields: dict[str, object] = {
        "name": "Test Brand",
        "mark_file": "mark.png",
        "typography": BrandTypography(heading_font="Inter", body_font="Inter"),
        "card_style": BrandCardStyle(
            background_color="#ffffff", accent_color="#111111", text_color="#222222"
        ),
        "standard_wording": "Standard wording text.",
        "license_name": "Test License",
        "license_file": "LICENSE.txt",
        "copyright_wording": "(c) Test Brand",
        "readme_text": "Thanks!",
    }
    fields.update(overrides)
    return Brand(**fields)  # type: ignore[arg-type]


def _product(**overrides: object) -> Product:
    fields: dict[str, object] = {
        "slug": "test_product",
        "collection_slug": "test_collection",
        "derivative_types": [DerivativeType.TRANSPARENT_PNG],
        "formats": [Format.PNG],
        "tier": "individual",
        "price": 1.0,
        "listing": Listing(
            title="Test Product",
            short_title="Test Product",
            description="A test pitch.",
            category="",
            license_type="Test License",
        ),
    }
    fields.update(overrides)
    return Product(**fields)  # type: ignore[arg-type]


# --- preview_members: ordering and the §16 stand-in preference order -------


def test_preview_members_sorts_by_display_name() -> None:
    assets_by_id = {"z": _asset("z", "Zebra"), "a": _asset("a", "Anemone")}
    members = [_member("z"), _member("a")]

    result = preview_members(members, assets_by_id, {})

    assert [member.display_name for member in result] == ["Anemone", "Zebra"]


def test_preview_members_picks_the_first_stand_in_type_in_fixed_preference_order() -> None:
    """§16: flatcolor_svg, then transparent_png, then silhouette_svg, then
    cut_svg -- whichever of those a member actually has, first one wins,
    regardless of dict insertion order."""
    assets_by_id = {"a": _asset("a", "A")}
    members = [_member("a")]
    content_by_member = {
        "a": {
            DerivativeType.CUT_SVG: b"<svg>cut</svg>",
            DerivativeType.TRANSPARENT_PNG: b"PNGBYTES",
        }
    }

    result = preview_members(members, assets_by_id, content_by_member)

    assert result[0].image_url.startswith("data:image/png;base64,")


def test_preview_members_falls_back_to_svg_mime_for_every_non_png_type() -> None:
    assets_by_id = {"a": _asset("a", "A")}
    members = [_member("a")]
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]] = {
        "a": {DerivativeType.SILHOUETTE_SVG: b"<svg>silhouette</svg>"}
    }

    result = preview_members(members, assets_by_id, content_by_member)

    assert result[0].image_url.startswith("data:image/svg+xml;base64,")


def test_preview_members_with_no_stand_in_type_included_has_a_blank_image_url() -> None:
    """No fixture product hits this (every one includes at least one of the
    four stand-in types); documented as a blank image rather than a raised
    error."""
    assets_by_id = {"a": _asset("a", "A")}
    members = [_member("a")]
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]] = {
        "a": {DerivativeType.OUTLINE_SVG: b"<svg>outline</svg>"}
    }

    result = preview_members(members, assets_by_id, content_by_member)

    assert result[0].image_url == ""


def test_preview_members_images_by_type_covers_every_included_type() -> None:
    assets_by_id = {"a": _asset("a", "A")}
    members = [_member("a")]
    content_by_member = {
        "a": {
            DerivativeType.TRANSPARENT_PNG: b"PNGBYTES",
            DerivativeType.CUT_SVG: b"<svg>cut</svg>",
        }
    }

    result = preview_members(members, assets_by_id, content_by_member)

    assert set(result[0].images_by_type) == {"transparent_png", "cut_svg"}


# --- render_main_html: the fixed context, and template-render failures -----


def _render(
    tmp_path: Path,
    *,
    product: Product | None = None,
    members: list[ProductMember] | None = None,
    assets_by_id: dict[AssetId, Asset] | None = None,
) -> str:
    (tmp_path / "mark.png").write_bytes(b"MARKBYTES")
    return render_main_html(
        tmp_path,
        _SQUARE,
        product or _product(),
        _brand(),
        members if members is not None else [_member("a")],
        assets_by_id or {"a": _asset("a", "Ochre Sea Star")},
        {"a": {DerivativeType.TRANSPARENT_PNG: b"PNGBYTES"}},
        {"PNG": ["ochre-sea-star-color.png"]},
    )


def test_render_main_html_shows_the_title_member_count_and_format_badges(tmp_path: Path) -> None:
    html = _render(tmp_path)

    assert "Test Product" in html
    assert "1 designs" in html
    assert "PNG (1)" in html
    assert "Ochre Sea Star" in html


def test_render_main_html_embeds_the_brand_mark_and_member_image_as_data_uris(
    tmp_path: Path,
) -> None:
    html = _render(tmp_path)

    assert "data:image/png;base64," in html  # the brand mark
    # the one member's own transparent_png stand-in image.
    assert html.count("data:image/png;base64,") >= 2


def test_render_main_html_shows_at_most_nine_featured_members(tmp_path: Path) -> None:
    assets_by_id = {str(i): _asset(str(i), f"Member {i}") for i in range(12)}
    members = [_member(str(i)) for i in range(12)]

    html = _render(tmp_path, members=members, assets_by_id=assets_by_id)

    assert sum(f"Member {i}" in html for i in range(12)) == 9


def test_catalog_override_reading_an_undefined_variable_fails_naming_the_template(
    tmp_path: Path,
) -> None:
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        "{% block content %}{{ this_is_not_in_the_context }}{% endblock %}\n",
        encoding="utf-8",
    )

    with pytest.raises(PreviewRenderError) as excinfo:
        _render(tmp_path)

    assert excinfo.value.template_name == "main.html.j2"
    assert "this_is_not_in_the_context" in str(excinfo.value)


def test_catalog_override_of_an_included_template_names_that_template(tmp_path: Path) -> None:
    """The failing file, not the top-level ``main.html.j2`` that was
    requested, is the one named -- here the override is ``brand.css``,
    reached only through ``_base.html.j2``'s own ``{% include %}``."""
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "brand.css").write_text(
        "body { color: {{ this_is_not_in_the_context }}; }\n", encoding="utf-8"
    )

    with pytest.raises(PreviewRenderError) as excinfo:
        _render(tmp_path)

    assert excinfo.value.template_name == "brand.css"


#: ``data:`` URIs (the brand mark, every member image) are real but
#: arbitrary bytes in these tests -- collapsed to a fixed placeholder before
#: snapshotting so the locked file stays a readable diff of *structure*,
#: never a base64 blob that changes size with whatever test fixture bytes
#: happen to be passed in.
_DATA_URI_RE = re.compile(r"data:[a-z+/]+;base64,[A-Za-z0-9+/=]+")


def test_render_main_html_is_locked_by_snapshot(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        # Real package data (§16, ADR 0014) would make the locked snapshot
        # depend on which font bytes happen to ship -- irrelevant to what
        # this test locks (the HTML's own structure and text).
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(tmp_path)

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot
