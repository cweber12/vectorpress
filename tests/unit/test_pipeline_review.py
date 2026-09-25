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
    approve_derivative,
    count_derivative_statuses,
)

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(sources: list[Source] | None = None) -> Asset:
    return Asset(
        id="ochre_sea_star",
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
