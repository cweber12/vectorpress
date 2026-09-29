"""build.export: the generic marketplace export's own contents summary and
assembly (§18, §19, ADR 0016, ADR 0017).

Everything here runs against hand-built domain objects, the same style
``test_build_previews.py`` and ``test_build_listing_draft.py`` already use --
no catalog, no build. Writing ``export/listing.json`` itself, and locking
its full shape with a snapshot, is ``test_build.py``'s job (it needs a real
build's manifest and ZIP).
"""

from vectorpress.build.export import (
    ContentsSummary,
    _preview_names_by_canvas,  # pyright: ignore[reportPrivateUsage]
    build_listing_export,
    contents_summary,
)
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
