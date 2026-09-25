"""pipeline.attention: the attention report model (§34, §24, CONTEXT.md
"Attention report / Inbox").

Builds real asset folders on disk under ``tmp_path`` (fabricated
:class:`~vectorpress.domain.asset.Asset` objects plus source PNGs), the same
fixture-free shape ``tests/unit/test_pipeline_review.py`` and
``tests/unit/test_pipeline_eligibility.py`` use -- catalog loading and the
CLI's own rendering are exercised end to end by
``tests/integration/test_attention.py`` and the PRD 4 acceptance walkthrough
instead.
"""

from pathlib import Path
from typing import cast

from PIL import Image

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.load import LoadedCatalog
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.overrides import ensure_override_provenance, override_path
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.eligibility import BlockingReasonKind
from vectorpress.domain.finding import ValidationOutcome
from vectorpress.domain.recipe import RECIPES
from vectorpress.domain.status import Status
from vectorpress.pipeline.attention import AssetPublicationState, build_attention_report
from vectorpress.pipeline.generate import generate_asset
from vectorpress.pipeline.review import approve_derivative, reject_derivative
from vectorpress.validate.validate_asset import validate_asset_cut_file

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(asset_id: str = "ochre_sea_star", **overrides: object) -> Asset:
    fields: dict[str, object] = {
        "id": asset_id,
        "common_name": "Ochre sea star",
        "display_name": "Ochre Sea Star",
        "description": "A test asset.",
        "subject_category": "Echinoderm",
        "taxonomic_group": "Echinoderm",
        "rights_status": RightsStatus.ORIGINAL_ARTWORK,
        "accuracy_status": AccuracyStatus.APPROVED,
        "scientific_name": "Pisaster ochraceus",
        "tags": ["sea star"],
        "regions": ["California"],
        "ecosystems": ["Tide pool"],
        "product_use_categories": ["stickers"],
        "notes": "Some notes.",
        "sources": [Source(role="silhouette", file="silhouette.png")],
    }
    fields.update(overrides)
    return Asset(**fields)  # type: ignore[arg-type]


def _config() -> CatalogConfig:
    return CatalogConfig(name="test")


def _make_catalog_asset(
    root: Path, config: CatalogConfig, asset_id: str, **overrides: object
) -> tuple[Asset, Path]:
    asset = _asset(asset_id, **overrides)
    asset_dir_path = asset_dir(root, config, asset_id)
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    return asset, asset_dir_path


def _catalog(
    root: Path,
    config: CatalogConfig | None,
    assets: list[Asset],
    problems: list[MetadataProblem] | None = None,
) -> LoadedCatalog:
    return LoadedCatalog(
        root=root,
        config=config,
        assets=assets,
        collections=[],
        products=[],
        brand=None,
        problems=problems or [],
    )


def _replace_source(asset_dir_path: Path) -> None:
    """Change a source PNG's content (its hash) without changing its
    silhouette shape -- the same "flip one corner pixel's alpha" edit
    ``tests/integration/test_overrides.py`` uses to make an override stale."""
    path = asset_dir_path / SOURCES_DIRNAME / "silhouette.png"
    image = Image.open(path).convert("RGBA")
    r, g, b, a = cast(tuple[int, int, int, int], image.getpixel((0, 0)))
    image.putpixel((0, 0), (r, g, b, 0 if a else 255))
    image.save(path, format="PNG")


# --- needs_review: unapproved current/stale derivatives, cut_svg findings -----------


def test_needs_review_lists_every_unapproved_existing_derivative(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    types = {item.derivative_type for item in report.needs_review}
    # flatcolor_svg is impossible (no flatcolor source): never a needs_review item.
    assert types == {
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    }
    for item in report.needs_review:
        assert item.asset_id == "ochre_sea_star"
        assert item.status is Status.NEEDS_REVIEW
        if item.derivative_type is not DerivativeType.CUT_SVG:
            assert item.findings is None


def test_an_approved_derivative_is_not_a_needs_review_item(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    approve_derivative(asset, asset_dir_path, DerivativeType.CUT_SVG, None, config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    types = {item.derivative_type for item in report.needs_review}
    assert DerivativeType.CUT_SVG not in types
    assert DerivativeType.TRANSPARENT_PNG in types  # still unapproved


def test_needs_review_carries_the_note(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    reject_derivative(asset, asset_dir_path, DerivativeType.CUT_SVG, "blurry edge", config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    cut_item = next(
        item for item in report.needs_review if item.derivative_type is DerivativeType.CUT_SVG
    )
    assert cut_item.status is Status.REJECTED
    assert cut_item.note == "blurry edge"


def test_needs_review_carries_the_cut_files_findings_result(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    validated = validate_asset_cut_file(tmp_path, config, asset, config.reference_size_in)
    assert validated.validation is not None

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    cut_item = next(
        item for item in report.needs_review if item.derivative_type is DerivativeType.CUT_SVG
    )
    assert cut_item.findings is validated.validation.outcome
    assert cut_item.findings in (ValidationOutcome.PASS, ValidationOutcome.NEEDS_REVIEW)


def test_a_never_validated_cut_file_has_no_findings_result(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    cut_item = next(
        item for item in report.needs_review if item.derivative_type is DerivativeType.CUT_SVG
    )
    assert cut_item.findings is None


# --- missing_derivatives: missing/stale, never impossible ----------------------------


def test_missing_derivatives_lists_missing_types_never_impossible(tmp_path: Path) -> None:
    config = _config()
    asset, _asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    # nothing generated yet: every recipe-bearing type is missing except
    # flatcolor_svg, which is impossible (no flatcolor source declared).

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    types = {item.derivative_type for item in report.missing_derivatives}
    assert DerivativeType.FLATCOLOR_SVG not in types
    assert DerivativeType.CUT_SVG in types
    assert all(item.state is DerivativeState.MISSING for item in report.missing_derivatives)


def test_missing_derivatives_lists_a_stale_generated_derivative_with_its_reason(
    tmp_path: Path,
) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    _replace_source(asset_dir_path)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    stale_items = [
        item for item in report.missing_derivatives if item.state is DerivativeState.STALE
    ]
    assert stale_items
    assert all(item.reason is not None for item in stale_items)


def test_a_current_derivative_is_not_a_missing_derivative_item(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    types = {item.derivative_type for item in report.missing_derivatives}
    assert types == set()


# --- stale_overrides -------------------------------------------------------------------


def test_stale_overrides_lists_an_override_whose_source_changed(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    filename = derivative_filename(asset.display_name, DerivativeType.CUT_SVG)
    generated_bytes = (asset_dir_path / DERIVED_DIRNAME / filename).read_bytes()
    override_file = override_path(asset_dir_path, filename)
    override_file.parent.mkdir(parents=True, exist_ok=True)
    override_file.write_bytes(generated_bytes + b"<!-- edited -->")
    ensure_override_provenance(
        asset, asset_dir_path, RECIPES[DerivativeType.CUT_SVG], filename, override_file.read_bytes()
    )
    _replace_source(asset_dir_path)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert len(report.stale_overrides) == 1
    item = report.stale_overrides[0]
    assert item.asset_id == "ochre_sea_star"
    assert item.derivative_type is DerivativeType.CUT_SVG
    assert item.reason is not None


def test_no_override_means_no_stale_override_items(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert report.stale_overrides == []


# --- blocked_assets: asset-level rights/accuracy only, not per-derivative -----------


def test_a_rights_blocked_asset_is_a_blocked_item_even_fully_approved(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(
        tmp_path, config, "gumboot_chiton", rights_status=RightsStatus.DO_NOT_PUBLISH
    )
    generate_asset(asset, asset_dir_path, config=config)
    for derivative_type in (
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    ):
        approve_derivative(asset, asset_dir_path, derivative_type, None, config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert len(report.blocked_assets) == 1
    item = report.blocked_assets[0]
    assert item.asset_id == "gumboot_chiton"
    assert all(reason.kind is BlockingReasonKind.RIGHTS_STATUS for reason in item.reasons)
    # no unapproved derivative left -- every existing type is approved.
    assert len(item.reasons) == 1


def test_an_asset_blocked_only_by_unapproved_derivatives_is_not_a_blocked_item(
    tmp_path: Path,
) -> None:
    """acorn_barnacle's own shape (README): blocked from publication only by
    its own derivatives never becoming approved effective derivatives, never
    by rights or accuracy -- distinct from a rights block, and already
    covered by needs_review/missing_derivatives, so it gets no blocked_assets
    line of its own."""
    config = _config()
    asset, _asset_dir_path = _make_catalog_asset(tmp_path, config, "acorn_barnacle")
    # nothing generated: every possible type is missing, so this asset is
    # BLOCKED (§10.1) but only via per-derivative reasons.

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert report.blocked_assets == []


def test_accuracy_issue_found_is_a_blocked_item(tmp_path: Path) -> None:
    config = _config()
    asset, _asset_dir_path = _make_catalog_asset(
        tmp_path, config, "ochre_sea_star", accuracy_status=AccuracyStatus.ISSUE_FOUND
    )

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert len(report.blocked_assets) == 1
    assert report.blocked_assets[0].reasons[0].kind is BlockingReasonKind.ACCURACY_STATUS


# --- warnings: never affect is_empty --------------------------------------------------


def test_warnings_are_reported_separately_and_never_affect_is_empty(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(
        tmp_path,
        config,
        "ochre_sea_star",
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        scientific_name=None,
    )
    generate_asset(asset, asset_dir_path, config=config)
    for derivative_type in (
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    ):
        approve_derivative(asset, asset_dir_path, derivative_type, None, config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert len(report.warnings) == 1
    assert report.warnings[0].asset_id == "ochre_sea_star"
    assert any(
        "accuracy status: not reviewed" in message for message in report.warnings[0].messages
    )
    assert report.is_empty  # a warning alone never makes the inbox non-empty


# --- missing_metadata: passed through from catalog.problems --------------------------


def test_missing_metadata_passes_through_catalog_problems(tmp_path: Path) -> None:
    problem = MetadataProblem(Path("assets/broken/asset.toml"), None, "TOML syntax error")

    report = build_attention_report(_catalog(tmp_path, _config(), [], [problem]), tmp_path)

    assert report.missing_metadata == [problem]
    assert not report.is_empty


# --- is_empty ---------------------------------------------------------------------------


def test_is_empty_when_every_group_but_warnings_is_empty(tmp_path: Path) -> None:
    config = _config()
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path, config=config)
    for derivative_type in (
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    ):
        approve_derivative(asset, asset_dir_path, derivative_type, None, config)

    report = build_attention_report(_catalog(tmp_path, config, [asset]), tmp_path)

    assert report.is_empty


def test_a_broken_catalog_toml_reports_only_missing_metadata(tmp_path: Path) -> None:
    problem = MetadataProblem(Path("catalog.toml"), None, "TOML syntax error")

    report = build_attention_report(_catalog(tmp_path, None, [], [problem]), tmp_path)

    assert report.missing_metadata == [problem]
    assert report.needs_review == []
    assert report.missing_derivatives == []
    assert report.blocked_assets == []
    assert report.stale_overrides == []
    assert report.warnings == []
    assert report.asset_publication_counts.approved == 0


# --- asset_publication_counts: §34's approved/awaiting-review/blocked ---------------


def test_asset_publication_counts_partition_every_loaded_asset(tmp_path: Path) -> None:
    config = _config()
    approved_asset, approved_dir = _make_catalog_asset(tmp_path, config, "approved_asset")
    generate_asset(approved_asset, approved_dir, config=config)
    for derivative_type in (
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    ):
        approve_derivative(approved_asset, approved_dir, derivative_type, None, config)

    awaiting_asset, awaiting_dir = _make_catalog_asset(tmp_path, config, "awaiting_asset")
    generate_asset(awaiting_asset, awaiting_dir, config=config)  # left needs_review

    blocked_asset, _blocked_dir = _make_catalog_asset(
        tmp_path, config, "blocked_asset", rights_status=RightsStatus.DO_NOT_PUBLISH
    )

    report = build_attention_report(
        _catalog(tmp_path, config, [approved_asset, awaiting_asset, blocked_asset]), tmp_path
    )

    counts = report.asset_publication_counts
    assert counts.approved == 1
    assert counts.awaiting_review == 1
    assert counts.blocked == 1
    assert counts.blocked == len(report.blocked_assets)


def test_asset_publication_state_enum_has_exactly_three_members() -> None:
    assert {state.value for state in AssetPublicationState} == {
        "approved",
        "awaiting_review",
        "blocked",
    }
