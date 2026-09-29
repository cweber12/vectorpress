"""build.previews: every preview type's context and Jinja rendering (§16,
ADR 0014, ADR 0015).

Everything here runs against hand-built domain objects and a bare
``tmp_path`` catalog root -- no generated derivative, no catalog fixture,
and (this module's own point) no Chromium: :func:`render_preview_html` is
pure Jinja, so an undefined-variable problem is a plain Python exception,
never a browser launch. Rendering the resulting HTML into an actual PNG
(:func:`~vectorpress.build.previews.render_previews`) is covered by
``tests/integration/test_previews.py`` instead, against the real fixture
catalog, since that needs Chromium installed.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from syrupy.assertion import SnapshotAssertion

from vectorpress.build.previews import (
    CONTENTS_PAGE_SIZE,
    PREVIEW_TYPES,
    Canvas,
    PreviewPage,
    PreviewRenderError,
    PreviewType,
    _DisallowedRequestError,  # pyright: ignore[reportPrivateUsage]
    _featured_asset_ids,  # pyright: ignore[reportPrivateUsage]
    _pages,  # pyright: ignore[reportPrivateUsage]
    _renders,  # pyright: ignore[reportPrivateUsage]
    _screenshot,  # pyright: ignore[reportPrivateUsage]
    preview_members,
    render_preview_html,
)
from vectorpress.build.product_resolution import MemberEligibility, ProductMember
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.brand import Brand, BrandCardStyle, BrandTypography
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.listing import Listing
from vectorpress.domain.product import Previews, Product

_SQUARE = Canvas("square", 2000, 2000)

_PREVIEW_TYPES_BY_NAME: dict[str, PreviewType] = {t.name: t for t in PREVIEW_TYPES}
_MAIN = _PREVIEW_TYPES_BY_NAME["main"]
_INCLUDED = _PREVIEW_TYPES_BY_NAME["included"]
_FORMATS = _PREVIEW_TYPES_BY_NAME["formats"]
_VARIANTS = _PREVIEW_TYPES_BY_NAME["variants"]
_CONTENTS = _PREVIEW_TYPES_BY_NAME["contents"]


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


# --- render_preview_html: the fixed context, and template-render failures --


def _render(
    tmp_path: Path,
    *,
    preview_type: PreviewType = _MAIN,
    canvas: Canvas = _SQUARE,
    product: Product | None = None,
    brand: Brand | None = None,
    members: list[ProductMember] | None = None,
    assets_by_id: dict[AssetId, Asset] | None = None,
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]] | None = None,
    files_by_folder: dict[str, list[str]] | None = None,
    page: PreviewPage | None = None,
) -> str:
    (tmp_path / "mark.png").write_bytes(b"MARKBYTES")
    return render_preview_html(
        tmp_path,
        preview_type,
        canvas,
        product or _product(),
        brand or _brand(),
        members if members is not None else [_member("a")],
        assets_by_id or {"a": _asset("a", "Ochre Sea Star")},
        content_by_member
        if content_by_member is not None
        else {"a": {DerivativeType.TRANSPARENT_PNG: b"PNGBYTES"}},
        files_by_folder if files_by_folder is not None else {"PNG": ["ochre-sea-star-color.png"]},
        page,
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


# --- `featured`: `[previews] featured` order (§16, CONTEXT.md "Featured member") --


def test_featured_asset_ids_leads_with_listed_ids_then_the_rest_by_display_name() -> None:
    product = _product(previews=Previews(featured=["z", "a"]))
    # Already in display-name order, as `_preview_context` would pass it.
    members_by_display_name = [_member("a"), _member("m"), _member("z")]

    result = _featured_asset_ids(product, members_by_display_name)

    assert result == ["z", "a", "m"]


def test_featured_asset_ids_drops_a_listed_id_absent_from_this_builds_members() -> None:
    """A featured ID resolved but excluded from this build is simply
    missing from ``members_by_display_name`` (product resolution already
    filtered it out) -- dropped here without error, never its own
    preview (§16)."""
    product = _product(previews=Previews(featured=["excluded_elsewhere", "a"]))
    members_by_display_name = [_member("a")]

    result = _featured_asset_ids(product, members_by_display_name)

    assert result == ["a"]


def test_featured_asset_ids_without_a_previews_table_is_plain_display_name_order() -> None:
    """A product without ``[previews]`` behaves as before: display-name
    order, unchanged by any featured list."""
    product = _product()
    members_by_display_name = [_member("a"), _member("m"), _member("z")]

    result = _featured_asset_ids(product, members_by_display_name)

    assert result == ["a", "m", "z"]


def test_render_main_html_leads_with_featured_members_in_listed_order(tmp_path: Path) -> None:
    assets_by_id = {
        "a": _asset("a", "Anemone"),
        "m": _asset("m", "Mid"),
        "z": _asset("z", "Zebra"),
    }
    members = [_member("a"), _member("m"), _member("z")]
    product = _product(previews=Previews(featured=["z", "a"]))

    html = _render(tmp_path, product=product, members=members, assets_by_id=assets_by_id)

    assert html.index("Zebra") < html.index("Anemone") < html.index("Mid")


def test_render_main_html_with_featured_order_is_locked_by_snapshot(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    assets_by_id = {
        "a": _asset("a", "Anemone"),
        "m": _asset("m", "Mid"),
        "z": _asset("z", "Zebra"),
    }
    members = [_member("a"), _member("m"), _member("z")]
    product = _product(previews=Previews(featured=["z", "a"]))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(tmp_path, product=product, members=members, assets_by_id=assets_by_id)

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


# --- brand.css names only shipped fonts, never a system font (ADR 0014) ----


def test_brand_naming_space_grotesk_uses_it_verbatim(tmp_path: Path) -> None:
    brand = _brand(
        typography=BrandTypography(heading_font="Space Grotesk", body_font="Space Grotesk")
    )

    html = _render(tmp_path, brand=brand)

    assert "sans-serif" not in html
    assert '--heading-font: "Space Grotesk"' in html
    assert '--body-font: "Space Grotesk"' in html


# --- a catalog font file (ADR 0014): its own @font-face rule ---------------


def test_a_catalog_heading_font_file_renders_an_at_font_face_rule_pointing_at_it_locked_by_snapshot(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "brand-heading.woff2").write_bytes(b"CUSTOMFONTBYTES")
    brand = _brand(
        typography=BrandTypography(
            heading_font="Brand Display",
            body_font="Inter",
            heading_font_file="fonts/brand-heading.woff2",
        )
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(tmp_path, brand=brand)

    assert 'font-family: "Brand Display"' in html
    assert '--heading-font: "Brand Display"' in html
    assert "data:font/woff2;base64,Q1VTVE9NRk9OVEJZVEVT" in html  # brand-heading.woff2's own bytes
    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


def test_a_catalog_font_file_serves_both_weights_from_the_one_file(tmp_path: Path) -> None:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "brand-heading.otf").write_bytes(b"ONEFILEBYTES")
    brand = _brand(
        typography=BrandTypography(
            heading_font="Brand Display",
            body_font="Inter",
            heading_font_file="fonts/brand-heading.otf",
        )
    )

    html = _render(tmp_path, brand=brand)

    # Both the regular and bold @font-face rules for the heading role embed
    # the same one file's bytes (a brand supplies only one file per role).
    heading_uri = "data:font/otf;base64,T05FRklMRUJZVEVT"
    assert html.count(heading_uri) == 2
    assert 'format("opentype")' in html


def test_each_allowed_font_file_extension_resolves_its_own_css_format_keyword(
    tmp_path: Path,
) -> None:
    """A rejected extension is ``load_brand`` (catalog layer)'s own job,
    before a build ever reaches this module -- this only proves every
    allowed extension resolves to its own correct CSS ``format()`` keyword,
    never a hardcoded one."""
    for extension, css_format in (("ttf", "truetype"), ("otf", "opentype"), ("woff2", "woff2")):
        (tmp_path / "fonts").mkdir(exist_ok=True)
        (tmp_path / "fonts" / f"brand.{extension}").write_bytes(b"BYTES")
        brand = _brand(
            typography=BrandTypography(
                heading_font="Brand Display",
                body_font="Inter",
                heading_font_file=f"fonts/brand.{extension}",
            )
        )

        html = _render(tmp_path, brand=brand)

        assert f'format("{css_format}")' in html


# --- an SVG mark_file renders the same way a PNG one does (ADR 0014) -------


def test_an_svg_mark_file_embeds_as_an_svg_data_uri_in_main(tmp_path: Path) -> None:
    (tmp_path / "mark.svg").write_bytes(b"<svg>MARK</svg>")
    brand = _brand(mark_file="mark.svg")

    html = _render(tmp_path, brand=brand)

    match = re.search(r'<img class="brand-mark" src="([^"]+)"', html)
    assert match is not None
    assert match.group(1).startswith("data:image/svg+xml;base64,")


def test_catalog_override_cannot_read_anything_outside_the_documented_context(
    tmp_path: Path,
) -> None:
    """ADR 0015: "reading anything else fails the build" -- including a
    name that used to be a shipped-template implementation detail
    (``shipped_fonts``, before this reached templates through
    ``brand.heading_font``/``body_font`` instead). Nothing is ever added to
    the environment's or a template's own globals, so a catalog override
    has no back door around the fixed context's own undefined check."""
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "brand.css").write_text(
        "body { font: {{ shipped_fonts.inter_regular }}; }\n", encoding="utf-8"
    )

    with pytest.raises(PreviewRenderError) as excinfo:
        _render(tmp_path)

    assert excinfo.value.template_name == "brand.css"
    assert "shipped_fonts" in str(excinfo.value)


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


def test_catalog_override_with_a_syntax_error_fails_naming_the_template(tmp_path: Path) -> None:
    """A catalog override's own Jinja syntax error (an unclosed ``{% if %}``,
    here) is a build refusal naming the template, never an uncaught
    ``TemplateSyntaxError`` -- the same :class:`PreviewRenderError` an
    undefined variable already raises."""
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n{% block content %}{% if %}broken{% endblock %}\n',
        encoding="utf-8",
    )

    with pytest.raises(PreviewRenderError) as excinfo:
        _render(tmp_path)

    assert excinfo.value.template_name == "main.html.j2"


def test_catalog_override_extending_a_missing_template_fails_naming_it(tmp_path: Path) -> None:
    """A catalog override's own ``{% extends %}`` naming a file that does
    not exist -- neither a catalog override nor a shipped template of that
    name -- is a build refusal naming the missing file, never an uncaught
    ``TemplateNotFound``."""
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "does-not-exist.html.j2" %}\n', encoding="utf-8"
    )

    with pytest.raises(PreviewRenderError) as excinfo:
        _render(tmp_path)

    assert "does-not-exist.html.j2" in str(excinfo.value)


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


# --- acceptance: a catalog brand.css override changes the rendered HTML (ADR 0015) --


def test_catalog_override_of_brand_css_changes_the_rendered_html_locked_by_snapshot(
    tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """A catalog ``templates/previews/brand.css`` override is reached only
    through ``_base.html.j2``'s own ``{% include %}`` (ADR 0015), never a
    top-level lookup of its own -- the rendered ``<style>`` block is the
    override's own text, not the shipped stylesheet, once it exists."""
    override_dir = tmp_path / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "brand.css").write_text("body { background: hotpink; }\n", encoding="utf-8")

    html = _render(tmp_path)

    assert "body { background: hotpink; }" in html
    assert html == snapshot


# --- `included` (§16 nn=02): up to 12 members, labeled with display names --


def test_included_html_shows_every_members_display_name_up_to_twelve(tmp_path: Path) -> None:
    assets_by_id = {str(i): _asset(str(i), f"Member {i}") for i in range(15)}
    members = [_member(str(i)) for i in range(15)]

    html = _render(tmp_path, preview_type=_INCLUDED, members=members, assets_by_id=assets_by_id)

    assert sum(f"Member {i}" in html for i in range(15)) == 12


def test_included_html_is_locked_by_snapshot(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(tmp_path, preview_type=_INCLUDED)

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


# --- `formats` (§16 nn=03): a badge per format with its file count and use -


def test_formats_html_shows_each_formats_file_count(tmp_path: Path) -> None:
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG, Format.DXF],
    )
    files_by_folder = {
        "SVG": ["a-cut.svg", "a-silhouette.svg", "b-cut.svg", "b-silhouette.svg"],
        "PNG": ["a-color.png"],
        "DXF": ["a-cut.dxf"],
    }

    html = _render(
        tmp_path, preview_type=_FORMATS, product=product, files_by_folder=files_by_folder
    )

    assert "SVG" in html and "4 files" in html
    assert "PNG" in html
    assert "DXF" in html
    assert html.count("1 files") == 2  # PNG's and DXF's own one-file counts


def test_formats_html_shows_a_one_line_use_per_format(tmp_path: Path) -> None:
    product = _product(derivative_types=[DerivativeType.CUT_SVG], formats=[Format.DXF])
    files_by_folder = {"DXF": ["a-cut.dxf"]}

    html = _render(
        tmp_path, preview_type=_FORMATS, product=product, files_by_folder=files_by_folder
    )

    assert "laser cutters" in html


def test_formats_html_is_locked_by_snapshot(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG, Format.DXF],
    )
    files_by_folder = {
        "SVG": ["a-cut.svg", "a-silhouette.svg"],
        "PNG": ["a-color.png"],
        "DXF": ["a-cut.dxf"],
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(
            tmp_path, preview_type=_FORMATS, product=product, files_by_folder=files_by_folder
        )

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


# --- `_renders`: §16's own condition per conditional preview type ----------


def test_variants_renders_only_with_two_or_more_derivative_types() -> None:
    one_type = _product(derivative_types=[DerivativeType.CUT_SVG], formats=[Format.SVG])
    two_types = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG],
    )

    assert _renders(_VARIANTS, one_type, member_count=5) is False
    assert _renders(_VARIANTS, two_types, member_count=5) is True


def test_contents_renders_only_past_twelve_members() -> None:
    product = _product()

    assert _renders(_CONTENTS, product, member_count=12) is False
    assert _renders(_CONTENTS, product, member_count=13) is True


def test_main_included_and_formats_always_render() -> None:
    product = _product(derivative_types=[DerivativeType.CUT_SVG], formats=[Format.SVG])

    for preview_type in (_MAIN, _INCLUDED, _FORMATS):
        assert _renders(preview_type, product, member_count=0) is True


# --- `_pages`: contents paginates at CONTENTS_PAGE_SIZE per page -----------


def test_pages_is_a_single_none_page_for_every_type_but_contents() -> None:
    assert _pages(_MAIN, member_count=100) == [None]
    assert _pages(_VARIANTS, member_count=100) == [None]


def test_pages_splits_contents_at_the_page_size_with_the_remainder_on_its_own_page() -> None:
    member_count = CONTENTS_PAGE_SIZE + 1  # 49: one full page, one remainder page

    pages = _pages(_CONTENTS, member_count)

    assert pages == [PreviewPage(number=1, count=2), PreviewPage(number=2, count=2)]


def test_pages_is_one_page_at_exactly_the_page_size() -> None:
    assert _pages(_CONTENTS, CONTENTS_PAGE_SIZE) == [PreviewPage(number=1, count=1)]


# --- `variants` (§16 nn=04): the first featured member, once per type ------


def test_variants_html_shows_one_card_per_derivative_type_labeled_with_its_label(
    tmp_path: Path,
) -> None:
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG],
    )
    content_by_member = {
        "a": {
            DerivativeType.CUT_SVG: b"<svg>cut</svg>",
            DerivativeType.TRANSPARENT_PNG: b"PNGBYTES",
        }
    }

    html = _render(
        tmp_path, preview_type=_VARIANTS, product=product, content_by_member=content_by_member
    )

    assert "Cut File SVG" in html
    assert "Transparent PNG" in html


def test_variants_html_never_labels_with_the_members_own_display_name(tmp_path: Path) -> None:
    """§16: labeled with the type's own label -- never the member's display
    name, unlike every other type's own card labels."""
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG],
    )
    content_by_member = {
        "a": {
            DerivativeType.CUT_SVG: b"<svg>cut</svg>",
            DerivativeType.TRANSPARENT_PNG: b"PNGBYTES",
        }
    }

    html = _render(
        tmp_path, preview_type=_VARIANTS, product=product, content_by_member=content_by_member
    )

    assert "Ochre Sea Star" not in html


def test_variants_html_is_locked_by_snapshot(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    product = _product(
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
        formats=[Format.SVG, Format.PNG],
    )
    content_by_member = {
        "a": {
            DerivativeType.CUT_SVG: b"<svg>cut</svg>",
            DerivativeType.TRANSPARENT_PNG: b"PNGBYTES",
        }
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(
            tmp_path, preview_type=_VARIANTS, product=product, content_by_member=content_by_member
        )

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


# --- `contents` (§16 nn=05): every member, labeled, 48 per page ------------


def test_contents_html_shows_only_this_pages_members(tmp_path: Path) -> None:
    member_count = CONTENTS_PAGE_SIZE + 1  # 49: page 1 gets 48, page 2 gets the remaining one
    assets_by_id = {str(i): _asset(str(i), f"Member {i}") for i in range(member_count)}
    members = [_member(str(i)) for i in range(member_count)]

    page_one_html = _render(
        tmp_path,
        preview_type=_CONTENTS,
        members=members,
        assets_by_id=assets_by_id,
        page=PreviewPage(number=1, count=2),
    )
    page_two_html = _render(
        tmp_path,
        preview_type=_CONTENTS,
        members=members,
        assets_by_id=assets_by_id,
        page=PreviewPage(number=2, count=2),
    )

    assert sum(f"Member {i}" in page_one_html for i in range(member_count)) == CONTENTS_PAGE_SIZE
    assert sum(f"Member {i}" in page_two_html for i in range(member_count)) == 1
    assert "Page 1 of 2" in page_one_html
    assert "Page 2 of 2" in page_two_html


def test_contents_html_is_locked_by_snapshot(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    assets_by_id = {str(i): _asset(str(i), f"Member {i}") for i in range(3)}
    members = [_member(str(i)) for i in range(3)]
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "vectorpress.build.previews._shipped_font_data_uris",
            lambda: {
                "inter_regular": "data:font/woff2;base64,AAAA",
                "inter_bold": "data:font/woff2;base64,AAAA",
                "space_grotesk_regular": "data:font/woff2;base64,AAAA",
                "space_grotesk_bold": "data:font/woff2;base64,AAAA",
            },
        )
        html = _render(
            tmp_path,
            preview_type=_CONTENTS,
            members=members,
            assets_by_id=assets_by_id,
            page=PreviewPage(number=1, count=1),
        )

    assert _DATA_URI_RE.sub("data:<omitted>", html) == snapshot


# --- `_screenshot`: retries one transient Chromium failure, nothing else ---


def test_screenshot_retries_once_after_a_transient_chromium_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI has hit ``Page.screenshot: Protocol error (Page.captureScreenshot):
    Unable to capture screenshot`` once, with nothing wrong in the rendered
    page -- a dropped DevTools connection or killed render target, not a
    reason to refuse a real build. One retry on a fresh page recovers it."""
    attempts: list[int] = []

    def flaky_render_screenshot(html: str, canvas: Canvas) -> bytes:
        attempts.append(1)
        if len(attempts) == 1:
            raise PlaywrightError(
                "Page.screenshot: Protocol error (Page.captureScreenshot): "
                "Unable to capture screenshot"
            )
        return b"PNGBYTES"

    monkeypatch.setattr("vectorpress.build.previews._render_screenshot", flaky_render_screenshot)

    result = _screenshot("<html></html>", _SQUARE, "main.html.j2")

    assert result == b"PNGBYTES"
    assert len(attempts) == 2


def test_screenshot_surfaces_a_second_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def always_transient(html: str, canvas: Canvas) -> bytes:
        attempts.append(1)
        raise PlaywrightError("Protocol error (Page.captureScreenshot): still broken")

    monkeypatch.setattr("vectorpress.build.previews._render_screenshot", always_transient)

    with pytest.raises(PreviewRenderError) as excinfo:
        _screenshot("<html></html>", _SQUARE, "main.html.j2")

    assert len(attempts) == 2  # the one retry, then it gave up
    assert excinfo.value.template_name == "main.html.j2"


def test_screenshot_never_retries_a_route_guard_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def disallowed(html: str, canvas: Canvas) -> bytes:
        attempts.append(1)
        raise _DisallowedRequestError("https://example.invalid/remote.png")

    monkeypatch.setattr("vectorpress.build.previews._render_screenshot", disallowed)

    with pytest.raises(PreviewRenderError) as excinfo:
        _screenshot("<html></html>", _SQUARE, "main.html.j2")

    assert len(attempts) == 1  # never retried
    assert "disallowed URL" in str(excinfo.value)
    assert "https://example.invalid/remote.png" in str(excinfo.value)


def test_screenshot_never_retries_a_non_transient_chromium_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Chromium failure that does not look transient (no Chromium
    installed, say) fails the render on its first attempt -- retrying it
    would only double the time a real, non-transient failure takes to
    report."""
    attempts: list[int] = []

    def unrelated_failure(html: str, canvas: Canvas) -> bytes:
        attempts.append(1)
        raise PlaywrightError("Executable doesn't exist, run playwright install")

    monkeypatch.setattr("vectorpress.build.previews._render_screenshot", unrelated_failure)

    with pytest.raises(PreviewRenderError):
        _screenshot("<html></html>", _SQUARE, "main.html.j2")

    assert len(attempts) == 1
