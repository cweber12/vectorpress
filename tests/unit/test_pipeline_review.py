"""pipeline.review: the approve action and status counts (§10, §22.1, ADR
0004).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`), the same fixture-free
shape ``tests/unit/test_pipeline_generate.py`` uses -- this module's job is
the approve/count wiring, not catalog loading
(``tests/integration/test_review.py`` exercises the CLI end to end).
"""

from pathlib import Path

from PIL import Image

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.catalog.status import read_status
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.status import Status
from vectorpress.pipeline.generate import generate_asset
from vectorpress.pipeline.review import (
    ApproveOutcome,
    RegenerateOutcome,
    RejectOutcome,
    SkippedTarget,
    approve_derivative,
    count_derivative_statuses,
    regenerate_derivative,
    reject_derivative,
    select_review_targets,
)

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(asset_id: str = "ochre_sea_star", sources: list[Source] | None = None) -> Asset:
    return Asset(
        id=asset_id,
        common_name="Ochre sea star",
        display_name="Ochre Sea Star",
        description="A test asset.",
        subject_category="Echinoderm",
        taxonomic_group="Echinoderm",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=sources
        if sources is not None
        else [Source(role="silhouette", file="silhouette.png")],
    )


def _make_asset_dir(tmp_path: Path) -> Path:
    asset_dir = tmp_path / "ochre_sea_star"
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png")
    return asset_dir


def _make_catalog_asset(tmp_path: Path, config: CatalogConfig, asset_id: str) -> tuple[Asset, Path]:
    """An asset laid out under ``tmp_path`` at the path
    :func:`~vectorpress.catalog.assets.asset_dir` computes for it --
    :func:`select_review_targets` and :func:`count_derivative_statuses`
    look assets up that way, unlike the single-asset helpers above which
    take an explicit directory."""
    asset = _asset(asset_id)
    asset_dir_path = asset_dir(tmp_path, config, asset_id)
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    return asset, asset_dir_path


# --- approve_derivative --------------------------------------------------------------


def test_approve_writes_an_approved_status_record_with_the_note(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = approve_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, "clean")

    assert result.outcome is ApproveOutcome.APPROVED
    assert result.error is None
    record = read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.TRANSPARENT_PNG)
    assert record is not None
    assert record.status is Status.APPROVED
    assert record.note == "clean"


def test_a_second_identical_approve_rewrites_nothing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    approve_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, "clean")
    state_file = asset_dir / DERIVED_DIRNAME / "_state.json"
    mtime_before = state_file.stat().st_mtime_ns
    bytes_before = state_file.read_bytes()

    result = approve_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, "clean")

    assert result.outcome is ApproveOutcome.APPROVED
    assert state_file.stat().st_mtime_ns == mtime_before
    assert state_file.read_bytes() == bytes_before


def test_approving_a_missing_derivative_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    """Nothing has been generated yet: transparent_png is missing, not
    current or stale."""
    asset_dir = _make_asset_dir(tmp_path)

    result = approve_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, None)

    assert result.outcome is ApproveOutcome.ERROR
    assert result.error is not None
    assert not (asset_dir / DERIVED_DIRNAME).exists()


def test_approving_an_impossible_derivative_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    """This asset has only a silhouette source, so flatcolor_svg can never
    be produced."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = approve_derivative(_asset(), asset_dir, DerivativeType.FLATCOLOR_SVG, None)

    assert result.outcome is ApproveOutcome.ERROR
    assert read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.FLATCOLOR_SVG) is None


def test_approving_a_stale_derivative_succeeds(tmp_path: Path) -> None:
    """A stale derivative still exists on disk (its bytes are still there
    to review), so it can be approved the same way a current one can."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    # A different display name changes the recipe-selected filename's
    # provenance target, so re-running under the *original* name with a
    # changed source marks the existing derivative stale instead.
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    result = approve_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, None)

    assert result.outcome is ApproveOutcome.APPROVED


# --- reject_derivative ----------------------------------------------------------------


def test_reject_writes_a_rejected_status_record_with_the_note(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = reject_derivative(_asset(), asset_dir, DerivativeType.CUT_SVG, "fragment")

    assert result.outcome is RejectOutcome.REJECTED
    assert result.error is None
    record = read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.CUT_SVG)
    assert record is not None
    assert record.status is Status.REJECTED
    assert record.note == "fragment"


def test_a_reject_with_no_note_clears_a_previous_note(tmp_path: Path) -> None:
    """A transition with no --note clears it (§10, §24)."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    approve_derivative(_asset(), asset_dir, DerivativeType.CUT_SVG, "clean")

    result = reject_derivative(_asset(), asset_dir, DerivativeType.CUT_SVG, None)

    assert result.outcome is RejectOutcome.REJECTED
    record = read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.CUT_SVG)
    assert record is not None
    assert record.note is None


def test_rejecting_a_missing_derivative_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    result = reject_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, None)

    assert result.outcome is RejectOutcome.ERROR
    assert result.error is not None
    assert not (asset_dir / DERIVED_DIRNAME).exists()


def test_rejecting_an_impossible_derivative_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = reject_derivative(_asset(), asset_dir, DerivativeType.FLATCOLOR_SVG, None)

    assert result.outcome is RejectOutcome.ERROR
    assert read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.FLATCOLOR_SVG) is None


# --- regenerate_derivative -------------------------------------------------------------


def test_regenerate_writes_a_regenerate_status_record_with_the_note(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = regenerate_derivative(_asset(), asset_dir, DerivativeType.SILHOUETTE_SVG, "too rough")

    assert result.outcome is RegenerateOutcome.REGENERATE
    assert result.error is None
    record = read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.SILHOUETTE_SVG)
    assert record is not None
    assert record.status is Status.REGENERATE
    assert record.note == "too rough"


def test_regenerate_does_not_touch_the_output_file(tmp_path: Path) -> None:
    """Marking for regeneration is a status write only -- the derivative's
    bytes are untouched until ``vpress generate`` actually regenerates it."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-silhouette.svg"
    bytes_before = output_path.read_bytes()

    regenerate_derivative(_asset(), asset_dir, DerivativeType.SILHOUETTE_SVG, None)

    assert output_path.read_bytes() == bytes_before


def test_regenerating_a_missing_derivative_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    result = regenerate_derivative(_asset(), asset_dir, DerivativeType.TRANSPARENT_PNG, None)

    assert result.outcome is RegenerateOutcome.ERROR
    assert result.error is not None
    assert not (asset_dir / DERIVED_DIRNAME).exists()


def test_regenerating_an_impossible_derivative_is_an_error_and_writes_nothing(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    result = regenerate_derivative(_asset(), asset_dir, DerivativeType.FLATCOLOR_SVG, None)

    assert result.outcome is RegenerateOutcome.ERROR
    assert read_status(asset_dir / DERIVED_DIRNAME, DerivativeType.FLATCOLOR_SVG) is None


# --- select_review_targets (the shape approve/reject/regenerate share) -----------------


def test_select_review_targets_for_one_asset_picks_every_existing_derivative(
    tmp_path: Path,
) -> None:
    """``<asset_id> --all-types``: ``assets`` holding just the one asset,
    no filters -- every current/stale derivative is targeted, flatcolor_svg
    (impossible, no flatcolor source) is named as skipped."""
    config = CatalogConfig(name="test")
    asset, asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")
    generate_asset(asset, asset_dir_path)

    selection = select_review_targets([asset], tmp_path, config)

    assert {target.derivative_type for target in selection.targets} == {
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
    }
    assert all(target.asset is asset for target in selection.targets)
    assert selection.skipped == [
        SkippedTarget("ochre_sea_star", DerivativeType.FLATCOLOR_SVG, "impossible")
    ]


def test_select_review_targets_names_missing_derivatives_before_anything_is_generated(
    tmp_path: Path,
) -> None:
    config = CatalogConfig(name="test")
    asset, _asset_dir_path = _make_catalog_asset(tmp_path, config, "ochre_sea_star")

    selection = select_review_targets([asset], tmp_path, config)

    assert selection.targets == []
    reasons = {(s.derivative_type, s.reason) for s in selection.skipped}
    assert (DerivativeType.TRANSPARENT_PNG, "missing") in reasons
    assert (DerivativeType.FLATCOLOR_SVG, "impossible") in reasons


def test_select_review_targets_across_the_catalog_narrowed_by_type(tmp_path: Path) -> None:
    """``--all --type transparent_png``: every asset's transparent_png is
    targeted; every other derivative type is left out silently (not a
    skip -- narrowing is not a problem)."""
    config = CatalogConfig(name="test")
    asset_a, asset_dir_a = _make_catalog_asset(tmp_path, config, "asset_a")
    asset_b, asset_dir_b = _make_catalog_asset(tmp_path, config, "asset_b")
    generate_asset(asset_a, asset_dir_a)
    generate_asset(asset_b, asset_dir_b)

    selection = select_review_targets(
        [asset_a, asset_b], tmp_path, config, derivative_type=DerivativeType.TRANSPARENT_PNG
    )

    assert sorted((t.asset.id, t.derivative_type) for t in selection.targets) == [
        ("asset_a", DerivativeType.TRANSPARENT_PNG),
        ("asset_b", DerivativeType.TRANSPARENT_PNG),
    ]
    assert selection.skipped == []


def test_select_review_targets_across_the_catalog_narrowed_by_status(tmp_path: Path) -> None:
    """``--all --type transparent_png --status needs_review``: an asset
    whose transparent_png was already approved is excluded, silently, the
    same as a type-filtered-out derivative."""
    config = CatalogConfig(name="test")
    asset_a, asset_dir_a = _make_catalog_asset(tmp_path, config, "asset_a")
    asset_b, asset_dir_b = _make_catalog_asset(tmp_path, config, "asset_b")
    generate_asset(asset_a, asset_dir_a)
    generate_asset(asset_b, asset_dir_b)
    approve_derivative(asset_a, asset_dir_a, DerivativeType.TRANSPARENT_PNG, None)

    selection = select_review_targets(
        [asset_a, asset_b],
        tmp_path,
        config,
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        status=Status.NEEDS_REVIEW,
    )

    assert [(t.asset.id, t.derivative_type) for t in selection.targets] == [
        ("asset_b", DerivativeType.TRANSPARENT_PNG)
    ]
    assert selection.skipped == []


def test_select_review_targets_names_a_type_filter_with_no_recipe_yet_per_asset(
    tmp_path: Path,
) -> None:
    """A bulk ``--type`` naming a type with no recipe yet (e.g.
    outline_svg) is skipped like missing/impossible, not an error -- named
    once per asset in scope, the bulk equivalent of the single-target "has
    no recipe yet" error."""
    config = CatalogConfig(name="test")
    asset_a, asset_dir_a = _make_catalog_asset(tmp_path, config, "asset_a")
    asset_b, asset_dir_b = _make_catalog_asset(tmp_path, config, "asset_b")
    generate_asset(asset_a, asset_dir_a)
    generate_asset(asset_b, asset_dir_b)

    selection = select_review_targets(
        [asset_a, asset_b], tmp_path, config, derivative_type=DerivativeType.OUTLINE_SVG
    )

    assert selection.targets == []
    assert selection.skipped == [
        SkippedTarget("asset_a", DerivativeType.OUTLINE_SVG, "has no recipe yet"),
        SkippedTarget("asset_b", DerivativeType.OUTLINE_SVG, "has no recipe yet"),
    ]


# --- count_derivative_statuses --------------------------------------------------------


def test_count_derivative_statuses_counts_only_existing_derivatives(tmp_path: Path) -> None:
    config = CatalogConfig(name="test")
    asset = _asset()
    asset_dir_path = asset_dir(tmp_path, config, asset.id)
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    generate_asset(asset, asset_dir_path)
    approve_derivative(asset, asset_dir_path, DerivativeType.TRANSPARENT_PNG, None)

    counts = count_derivative_statuses([asset], tmp_path, config)

    # flatcolor_svg is impossible for this asset (no flatcolor source), so
    # it contributes nothing; transparent_png is approved, silhouette_svg
    # and cut_svg were generated but never approved, so needs_review.
    assert counts.approved == 1
    assert counts.needs_review == 2
