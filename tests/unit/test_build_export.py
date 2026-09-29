"""build.export: the generic marketplace export's own contents summary and
assembly, and the marketplace text bundles built from it (§18, §19, ADR
0015, ADR 0016, ADR 0017).

Everything here runs against hand-built domain objects, the same style
``test_build_previews.py`` and ``test_build_listing_draft.py`` already use --
no catalog, no build. Writing ``export/listing.json`` and the bundle files
themselves, and locking their full shape with a snapshot, is
``test_build.py``'s job (it needs a real build's manifest and ZIP).
"""

from pathlib import Path

import pytest

from vectorpress.build.export import (
    MARKETPLACE_BUNDLES,
    ContentsSummary,
    ExportRenderError,
    ListingExport,
    _preview_names_by_canvas,  # pyright: ignore[reportPrivateUsage]
    build_listing_export,
    contents_summary,
    measure_export_limits,
    render_contents_summary_text,
    render_marketplace_bundles,
)
from vectorpress.build.marketplace_limits import ETSY_TAG_MAX_COUNT, ETSY_TITLE_MAX_CHARS
from vectorpress.build.product_resolution import MemberEligibility, ProductMember
from vectorpress.domain.asset import Asset
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.listing import Listing
from vectorpress.domain.manifest import (
    Manifest,
    ManifestDxfMember,
    ManifestMember,
    ManifestMemberSource,
)
from vectorpress.domain.membership import Membership
from vectorpress.domain.product import Product


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
        "price": 12.5,
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


def _manifest(**overrides: object) -> Manifest:
    fields: dict[str, object] = {
        "product_slug": "test_product",
        "reference_size_in": 3.0,
        "license_year": 2026,
        "tool_version": "0.0.0",
        "license_template_hash": "hash",
        "readme_wording_hash": "hash",
        "allow_unapproved": False,
        "members": [],
        "dxf_members": [],
        "excluded_members": [],
        "admitted_unapproved_members": [],
        "asset_rights_statuses": [],
        "cleanup_size_warnings": [],
        "byte_identical_derivatives": [],
        "previews": [],
        "presentation_hash": "hash",
        "listing_hash": "hash",
        "export_limit_warnings": [],
        "export_does_not_fit": [],
    }
    fields.update(overrides)
    return Manifest(**fields)  # type: ignore[arg-type]


def _manifest_member(asset_id: str, package_path: str) -> ManifestMember:
    return ManifestMember(
        asset_id=asset_id,
        derivative_type=DerivativeType.CUT_SVG,
        source=ManifestMemberSource.GENERATED,
        content_hash="hash",
        package_path=package_path,
    )


# --- contents_summary ----------------------------------------------------


def test_contents_summary_counts_distinct_assets_not_member_rows() -> None:
    manifest = _manifest(
        members=[
            _manifest_member("a", "SVG/a-cut.svg"),
            _manifest_member("a", "SVG/a-outline.svg"),
            _manifest_member("b", "SVG/b-cut.svg"),
        ]
    )
    summary = contents_summary(manifest, _product())
    assert summary.member_count == 2


def test_contents_summary_lists_every_file_name_sorted_including_dxf() -> None:
    manifest = _manifest(
        members=[_manifest_member("b", "SVG/b-cut.svg"), _manifest_member("a", "SVG/a-cut.svg")],
        dxf_members=[
            ManifestDxfMember(
                asset_id="a",
                source_derivative_type=DerivativeType.CUT_SVG,
                source_content_hash="hash",
                content_hash="hash",
                package_path="DXF/a-cut.dxf",
            )
        ],
    )
    summary = contents_summary(manifest, _product())
    assert summary.file_names == ["DXF/a-cut.dxf", "SVG/a-cut.svg", "SVG/b-cut.svg"]


def test_contents_summary_uses_the_products_own_formats_in_declared_order() -> None:
    manifest = _manifest()
    product = _product(
        formats=[Format.PNG, Format.SVG],
        derivative_types=[DerivativeType.CUT_SVG, DerivativeType.TRANSPARENT_PNG],
    )
    summary = contents_summary(manifest, product)
    assert summary.formats == ["png", "svg"]


def test_contents_summary_uses_the_manifests_own_reference_size() -> None:
    manifest = _manifest(reference_size_in=4.5)
    summary = contents_summary(manifest, _product())
    assert summary.reference_size_in == 4.5


# --- _preview_names_by_canvas ---------------------------------------------


def test_preview_names_by_canvas_splits_preserving_upload_order() -> None:
    previews = [
        "previews/01-main-square.png",
        "previews/01-main-landscape.png",
        "previews/02-included-square.png",
        "previews/02-included-landscape.png",
    ]
    assert _preview_names_by_canvas(previews) == {
        "square": ["previews/01-main-square.png", "previews/02-included-square.png"],
        "landscape": ["previews/01-main-landscape.png", "previews/02-included-landscape.png"],
    }


def test_preview_names_by_canvas_is_empty_for_an_unrendered_canvas() -> None:
    assert _preview_names_by_canvas(["previews/01-main-square.png"]) == {
        "square": ["previews/01-main-square.png"],
        "landscape": [],
    }


# --- build_listing_export --------------------------------------------------


def test_build_listing_export_uses_the_referenced_collections_own_name() -> None:
    collection = _collection(name="Pacific Coast Tide Pool")
    export = build_listing_export(
        _product(),
        _manifest(),
        [collection],
        [_member("a")],
        {"a": _asset("a", "A")},
        zip_name="Test-Product.zip",
        zip_size_bytes=100,
    )
    assert export.collection_name == "Pacific Coast Tide Pool"


def test_build_listing_export_title_cases_the_slug_for_an_inline_membership() -> None:
    product = _product(
        collection_slug=None,
        membership=Membership(asset_ids=["a"]),
    )
    export = build_listing_export(
        product,
        _manifest(),
        [],
        [_member("a")],
        {"a": _asset("a", "A")},
        zip_name="Test-Product.zip",
        zip_size_bytes=100,
    )
    assert export.collection_name == "Test Product"


def test_build_listing_export_asset_names_are_sorted_display_names() -> None:
    export = build_listing_export(
        _product(),
        _manifest(),
        [_collection()],
        [_member("z"), _member("a")],
        {"z": _asset("z", "Zebra"), "a": _asset("a", "Anemone")},
        zip_name="Test-Product.zip",
        zip_size_bytes=100,
    )
    assert export.asset_names == ["Anemone", "Zebra"]


def test_build_listing_export_carries_listing_price_zip_name_and_size() -> None:
    product = _product(price=9.99)
    export = build_listing_export(
        product,
        _manifest(),
        [_collection()],
        [_member("a")],
        {"a": _asset("a", "A")},
        zip_name="Test-Product.zip",
        zip_size_bytes=4321,
    )
    assert export.listing is product.listing
    assert export.price == 9.99
    assert export.zip_name == "Test-Product.zip"
    assert export.zip_size_bytes == 4321


def test_build_listing_export_member_count_is_the_eligible_member_count() -> None:
    export = build_listing_export(
        _product(),
        _manifest(),
        [_collection()],
        [_member("a"), _member("b")],
        {"a": _asset("a", "A"), "b": _asset("b", "B")},
        zip_name="Test-Product.zip",
        zip_size_bytes=100,
    )
    assert export.member_count == 2


def test_build_listing_export_contents_summary_is_the_contents_summary_function_result() -> None:
    manifest = _manifest(members=[_manifest_member("a", "SVG/a-cut.svg")], reference_size_in=6.0)
    product = _product()
    export = build_listing_export(
        product,
        manifest,
        [_collection()],
        [_member("a")],
        {"a": _asset("a", "A")},
        zip_name="Test-Product.zip",
        zip_size_bytes=100,
    )
    assert export.contents_summary == contents_summary(manifest, product)
    assert isinstance(export.contents_summary, ContentsSummary)


# --- render_contents_summary_text ------------------------------------------


def _summary(**overrides: object) -> ContentsSummary:
    fields: dict[str, object] = {
        "member_count": 2,
        "formats": ["svg", "png"],
        "file_names": ["PNG/a-color.png", "SVG/a-cut.svg"],
        "reference_size_in": 3.0,
    }
    fields.update(overrides)
    return ContentsSummary(**fields)  # type: ignore[arg-type]


def test_render_contents_summary_text_uses_singular_member_for_one() -> None:
    text = render_contents_summary_text(_summary(member_count=1))
    assert "1 member," in text
    assert "1 members," not in text


def test_render_contents_summary_text_uses_plural_members_for_more_than_one() -> None:
    text = render_contents_summary_text(_summary(member_count=2))
    assert "2 members," in text


def test_render_contents_summary_text_uppercases_every_format() -> None:
    text = render_contents_summary_text(_summary(formats=["svg", "png"]))
    assert "SVG, PNG" in text


def test_render_contents_summary_text_prints_the_formatted_reference_size() -> None:
    text = render_contents_summary_text(_summary(reference_size_in=1.5))
    assert "1.5in" in text


def test_render_contents_summary_text_lists_every_file_name() -> None:
    text = render_contents_summary_text(_summary(file_names=["DXF/a-cut.dxf", "SVG/a-cut.svg"]))
    assert "- DXF/a-cut.dxf" in text
    assert "- SVG/a-cut.svg" in text


# --- render_marketplace_bundles ---------------------------------------------


def _listing_export(**overrides: object) -> ListingExport:
    fields: dict[str, object] = {
        "listing": Listing(
            title="Test Product",
            short_title="Test Product",
            description="A test pitch.",
            tags=["cut file", "svg"],
            category="Nature & Wildlife",
            license_type="Test License",
        ),
        "member_count": 2,
        "formats": ["svg"],
        "asset_names": ["A", "B"],
        "collection_name": "Test Collection",
        "contents_summary": _summary(),
        "price": 12.5,
        "previews": {
            "square": ["previews/01-main-square.png", "previews/02-included-square.png"],
            "landscape": ["previews/01-main-landscape.png"],
        },
        "zip_name": "Test-Product.zip",
        "zip_size_bytes": 1000,
    }
    fields.update(overrides)
    return ListingExport(**fields)  # type: ignore[arg-type]


def _bundle_texts(tmp_path: Path, export: ListingExport | None = None) -> dict[str, str]:
    result = render_marketplace_bundles(tmp_path, export or _listing_export())
    return {rel_path: data.decode("utf-8") for rel_path, data in result.files}


def test_render_marketplace_bundles_writes_all_four_under_export() -> None:
    assert {bundle.filename for bundle in MARKETPLACE_BUNDLES} == {
        "etsy.txt",
        "creative-fabrica.txt",
        "design-bundles.txt",
        "direct-store.txt",
    }


def test_render_marketplace_bundles_writes_one_file_per_bundle_under_export(
    tmp_path: Path,
) -> None:
    texts = _bundle_texts(tmp_path)
    assert set(texts) == {
        "export/etsy.txt",
        "export/creative-fabrica.txt",
        "export/design-bundles.txt",
        "export/direct-store.txt",
    }


def test_render_marketplace_bundles_description_is_listing_description_then_contents_summary(
    tmp_path: Path,
) -> None:
    export = _listing_export()
    expected = (
        f"{export.listing.description}\n\n{render_contents_summary_text(export.contents_summary)}"
    )
    texts = _bundle_texts(tmp_path, export)
    for text in texts.values():
        assert expected in text


def test_render_marketplace_bundles_etsy_and_direct_store_list_square_previews(
    tmp_path: Path,
) -> None:
    texts = _bundle_texts(tmp_path)
    for path in ("export/etsy.txt", "export/direct-store.txt"):
        assert "01-main-square.png" in texts[path]
        assert "02-included-square.png" in texts[path]
        assert "01-main-landscape.png" not in texts[path]


def test_render_marketplace_bundles_creative_fabrica_and_design_bundles_list_landscape_previews(
    tmp_path: Path,
) -> None:
    texts = _bundle_texts(tmp_path)
    for path in ("export/creative-fabrica.txt", "export/design-bundles.txt"):
        assert "01-main-landscape.png" in texts[path]
        assert "01-main-square.png" not in texts[path]


def test_render_marketplace_bundles_images_are_file_names_without_the_previews_prefix(
    tmp_path: Path,
) -> None:
    texts = _bundle_texts(tmp_path)
    assert "previews/01-main-square.png" not in texts["export/etsy.txt"]
    assert "01-main-square.png" in texts["export/etsy.txt"]


def test_render_marketplace_bundles_only_etsy_has_a_who_made_section(tmp_path: Path) -> None:
    texts = _bundle_texts(tmp_path)
    assert "WHO MADE" in texts["export/etsy.txt"]
    assert "WHO MADE" not in texts["export/creative-fabrica.txt"]
    assert "WHO MADE" not in texts["export/design-bundles.txt"]
    assert "WHO MADE" not in texts["export/direct-store.txt"]


def test_render_marketplace_bundles_carries_price_category_title_and_zip_name(
    tmp_path: Path,
) -> None:
    export = _listing_export(price=9.99, zip_name="Some-Product.zip")
    texts = _bundle_texts(tmp_path, export)
    for text in texts.values():
        assert export.listing.title in text
        assert export.listing.category in text
        assert "9.99" in text
        assert "Some-Product.zip" in text


def test_render_marketplace_bundles_carries_edited_listing_text(tmp_path: Path) -> None:
    """Editing the listing (before a rebuild) carries into every bundle --
    nothing about a bundle's own text is cached or drawn from anywhere else."""
    export = _listing_export(
        listing=Listing(
            title="Edited Title",
            short_title="Edited Title",
            description="An edited pitch.",
            category="Edited Category",
            license_type="Test License",
        )
    )
    texts = _bundle_texts(tmp_path, export)
    for text in texts.values():
        assert "Edited Title" in text
        assert "An edited pitch." in text
        assert "Edited Category" in text


def test_render_marketplace_bundles_catalog_override_changes_content_and_is_named(
    tmp_path: Path,
) -> None:
    override_dir = tmp_path / "templates" / "export"
    override_dir.mkdir(parents=True)
    (override_dir / "etsy.txt.j2").write_text("CUSTOM TITLE\n{{ title }}\n", encoding="utf-8")

    result = render_marketplace_bundles(tmp_path, _listing_export())

    files = dict(result.files)
    assert files["export/etsy.txt"] == b"CUSTOM TITLE\nTest Product\n"
    assert result.template_overrides == ["templates/export/etsy.txt.j2"]


def test_render_marketplace_bundles_catalog_override_reading_an_undefined_variable_fails_naming_the_template(
    tmp_path: Path,
) -> None:
    override_dir = tmp_path / "templates" / "export"
    override_dir.mkdir(parents=True)
    (override_dir / "etsy.txt.j2").write_text(
        "{{ this_is_not_in_the_context }}\n", encoding="utf-8"
    )

    with pytest.raises(ExportRenderError) as excinfo:
        render_marketplace_bundles(tmp_path, _listing_export())

    assert excinfo.value.template_name == "etsy.txt.j2"
    assert "this_is_not_in_the_context" in str(excinfo.value)


def test_render_marketplace_bundles_catalog_override_with_a_syntax_error_fails_naming_the_template(
    tmp_path: Path,
) -> None:
    override_dir = tmp_path / "templates" / "export"
    override_dir.mkdir(parents=True)
    (override_dir / "etsy.txt.j2").write_text("{% if %}broken\n", encoding="utf-8")

    with pytest.raises(ExportRenderError) as excinfo:
        render_marketplace_bundles(tmp_path, _listing_export())

    assert excinfo.value.template_name == "etsy.txt.j2"


def test_render_marketplace_bundles_catalog_override_extending_a_missing_template_fails_naming_it(
    tmp_path: Path,
) -> None:
    override_dir = tmp_path / "templates" / "export"
    override_dir.mkdir(parents=True)
    (override_dir / "etsy.txt.j2").write_text(
        '{% extends "does-not-exist.txt.j2" %}\n', encoding="utf-8"
    )

    with pytest.raises(ExportRenderError) as excinfo:
        render_marketplace_bundles(tmp_path, _listing_export())

    assert "does-not-exist.txt.j2" in str(excinfo.value)


def test_render_marketplace_bundles_with_no_catalog_templates_dir_uses_shipped_only(
    tmp_path: Path,
) -> None:
    result = render_marketplace_bundles(tmp_path, _listing_export())
    assert result.template_overrides == []


# --- measure_export_limits (§19, ADR 0017) -----------------------------------


def test_measure_export_limits_within_every_limit_produces_no_warnings() -> None:
    result = measure_export_limits(_listing_export())
    assert result.warnings == []
    assert result.does_not_fit == []


def test_measure_export_limits_flags_an_over_limit_title_and_lists_the_overflow_tag() -> None:
    """The acceptance scenario: a 141-character title and 14 tags -- the
    title is flagged, the 14th tag is listed as not fitting, and nothing
    about the listing itself is touched (ADR 0017's "warn, never truncate
    or refuse")."""
    title = "x" * (ETSY_TITLE_MAX_CHARS + 1)
    tags = [f"tag{i}" for i in range(1, ETSY_TAG_MAX_COUNT + 2)]  # 14 tags
    export = _listing_export(
        listing=Listing(
            title=title,
            short_title="Short",
            description="A test pitch.",
            tags=tags,
            category="Nature & Wildlife",
            license_type="Test License",
        )
    )
    result = measure_export_limits(export)

    etsy_title_warnings = [
        w for w in result.warnings if w.marketplace == "etsy" and w.field == "title"
    ]
    assert len(etsy_title_warnings) == 1
    assert str(ETSY_TITLE_MAX_CHARS + 1) in etsy_title_warnings[0].measure

    etsy_tag_overflow = [
        item for item in result.does_not_fit if item.marketplace == "etsy" and item.field == "tags"
    ]
    assert [item.item for item in etsy_tag_overflow] == [f"tag{ETSY_TAG_MAX_COUNT + 1}"]


# --- render_marketplace_bundles inline limit flags (§19, ADR 0017) ----------


def test_render_marketplace_bundles_flags_an_over_limit_title_inline_in_etsy(
    tmp_path: Path,
) -> None:
    title = "x" * (ETSY_TITLE_MAX_CHARS + 1)
    export = _listing_export(
        listing=Listing(
            title=title,
            short_title="Short",
            description="A test pitch.",
            tags=["cut file", "svg"],
            category="Nature & Wildlife",
            license_type="Test License",
        )
    )
    texts = _bundle_texts(tmp_path, export)
    assert title in texts["export/etsy.txt"]  # the title itself is never truncated
    assert "LIMIT" in texts["export/etsy.txt"]
    assert str(ETSY_TITLE_MAX_CHARS) in texts["export/etsy.txt"]


def test_render_marketplace_bundles_lists_the_fourteenth_tag_under_does_not_fit_in_etsy(
    tmp_path: Path,
) -> None:
    tags = [f"tag{i}" for i in range(1, ETSY_TAG_MAX_COUNT + 2)]  # 14 tags
    export = _listing_export(
        listing=Listing(
            title="Test Product",
            short_title="Test Product",
            description="A test pitch.",
            tags=tags,
            category="Nature & Wildlife",
            license_type="Test License",
        )
    )
    texts = _bundle_texts(tmp_path, export)
    text = texts["export/etsy.txt"]
    assert ", ".join(tags) in text  # every tag still ships, unchanged
    assert "DOES NOT FIT" in text
    assert f"tag{ETSY_TAG_MAX_COUNT + 1}" in text.split("DOES NOT FIT")[1]


def test_render_marketplace_bundles_within_every_limit_has_no_limit_or_does_not_fit_markers(
    tmp_path: Path,
) -> None:
    texts = _bundle_texts(tmp_path)
    for text in texts.values():
        assert "LIMIT" not in text
        assert "DOES NOT FIT" not in text
