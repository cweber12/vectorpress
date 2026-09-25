"""pipeline.override_resolution: keep, discard, and the stale override count
(§22.2, ADR 0004).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`), the same fixture-free
shape ``tests/unit/test_pipeline_review.py`` and ``tests/unit/
test_catalog_overrides.py`` use -- this module's job is the keep/discard/count
wiring, not catalog loading (``tests/integration/test_overrides.py``
exercises the CLI end to end).
"""

from pathlib import Path

from PIL import Image

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.overrides import (
    ensure_override_provenance,
    override_path,
    read_override_provenance,
    read_override_status,
    write_override_status,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME, sha256_bytes
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.recipe import RECIPES
from vectorpress.domain.status import Status, StatusRecord
from vectorpress.pipeline.generate import generate_asset
from vectorpress.pipeline.override_resolution import (
    DiscardOutcome,
    KeepOutcome,
    count_stale_overrides,
    discard_override,
    keep_override,
)
from vectorpress.pipeline.review import approve_derivative

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(asset_id: str = "ochre_sea_star") -> Asset:
    return Asset(
        id=asset_id,
        common_name="Ochre sea star",
        display_name="Ochre Sea Star",
        description="A test asset.",
        subject_category="Echinoderm",
        taxonomic_group="Echinoderm",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=[Source(role="silhouette", file="silhouette.png")],
    )


def _make_asset_dir(tmp_path: Path) -> Path:
    asset_dir_path = tmp_path / "ochre_sea_star"
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    return asset_dir_path


def _write_override(asset_dir_path: Path, filename: str, data: bytes) -> Path:
    path = override_path(asset_dir_path, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


FILENAME = derivative_filename("Ochre Sea Star", DerivativeType.CUT_SVG)


def _staled_override(asset_dir_path: Path) -> bytes:
    """A generated, then overridden, cut_svg whose source has since
    changed -- the shared starting point for the keep/discard tests below."""
    generate_asset(_asset(), asset_dir_path)
    override_bytes = b"<svg>hand-edited</svg>"
    _write_override(asset_dir_path, FILENAME, override_bytes)
    ensure_override_provenance(
        _asset(), asset_dir_path, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png", rgba=(1, 2, 3, 255))
    return override_bytes


# --- keep_override --------------------------------------------------------------------


def test_keep_clears_the_stale_flag_without_touching_bytes_or_status(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    override_bytes = _staled_override(asset_dir_path)
    approve_derivative(_asset(), asset_dir_path, DerivativeType.CUT_SVG, "clean")

    result = keep_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG)

    assert result.outcome is KeepOutcome.KEPT
    assert result.error is None
    assert override_path(asset_dir_path, FILENAME).read_bytes() == override_bytes
    status = read_override_status(asset_dir_path / DERIVED_DIRNAME, DerivativeType.CUT_SVG)
    assert status is not None
    assert status.status is Status.APPROVED
    assert status.note == "clean"

    new_source_hash = sha256_bytes(
        (asset_dir_path / SOURCES_DIRNAME / "silhouette.png").read_bytes()
    )
    provenance = read_override_provenance(asset_dir_path / DERIVED_DIRNAME, FILENAME)
    assert provenance is not None
    assert provenance.source_hash == new_source_hash


def test_a_second_keep_is_a_noop_that_rewrites_nothing(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    _staled_override(asset_dir_path)
    keep_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG)
    provenance_path = asset_dir_path / DERIVED_DIRNAME / f"{FILENAME}.override_provenance.json"
    mtime_before = provenance_path.stat().st_mtime_ns
    bytes_before = provenance_path.read_bytes()

    result = keep_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG)

    assert result.outcome is KeepOutcome.NOT_STALE
    assert provenance_path.stat().st_mtime_ns == mtime_before
    assert provenance_path.read_bytes() == bytes_before


def test_keeping_a_non_stale_override_is_a_noop(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)
    _write_override(asset_dir_path, FILENAME, b"<svg>hand-edited</svg>")

    result = keep_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG)

    assert result.outcome is KeepOutcome.NOT_STALE
    assert result.error is None


def test_keeping_a_type_with_no_override_is_an_error(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)

    result = keep_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG)

    assert result.outcome is KeepOutcome.ERROR
    assert result.error is not None


def test_keeping_a_type_with_no_recipe_yet_is_an_error(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)

    result = keep_override(_asset(), asset_dir_path, DerivativeType.OUTLINE_SVG)

    assert result.outcome is KeepOutcome.ERROR
    assert result.error is not None


# --- discard_override -------------------------------------------------------------------


def test_discard_without_confirmation_removes_nothing(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)
    _write_override(asset_dir_path, FILENAME, b"<svg>hand-edited</svg>")

    result = discard_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG, confirmed=False)

    assert result.outcome is DiscardOutcome.WOULD_DISCARD
    assert result.override_file == override_path(asset_dir_path, FILENAME)
    assert override_path(asset_dir_path, FILENAME).is_file()


def test_discard_with_confirmation_removes_the_override_and_its_state(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)
    override_bytes = b"<svg>hand-edited</svg>"
    _write_override(asset_dir_path, FILENAME, override_bytes)
    ensure_override_provenance(
        _asset(), asset_dir_path, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )
    write_override_status(
        asset_dir_path / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash=sha256_bytes(override_bytes)),
    )

    result = discard_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG, confirmed=True)

    assert result.outcome is DiscardOutcome.DISCARDED
    assert not override_path(asset_dir_path, FILENAME).is_file()
    assert read_override_provenance(asset_dir_path / DERIVED_DIRNAME, FILENAME) is None
    assert read_override_status(asset_dir_path / DERIVED_DIRNAME, DerivativeType.CUT_SVG) is None
    # the generated file itself is untouched by discarding its override.
    assert (asset_dir_path / DERIVED_DIRNAME / FILENAME).is_file()


def test_discarding_a_type_with_no_override_is_an_error(tmp_path: Path) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)

    result = discard_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG, confirmed=True)

    assert result.outcome is DiscardOutcome.ERROR
    assert result.error is not None


def test_discarding_with_no_confirmation_on_a_type_with_no_override_is_still_an_error(
    tmp_path: Path,
) -> None:
    asset_dir_path = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir_path)

    result = discard_override(_asset(), asset_dir_path, DerivativeType.CUT_SVG, confirmed=False)

    assert result.outcome is DiscardOutcome.ERROR


# --- count_stale_overrides ---------------------------------------------------------------


def test_count_stale_overrides_counts_only_stale_ones(tmp_path: Path) -> None:
    config = CatalogConfig(name="test")
    stale_id, current_id = "stale_asset", "current_asset"

    stale_dir = asset_dir(tmp_path, config, stale_id)
    _write_source_png(stale_dir / SOURCES_DIRNAME / "silhouette.png")
    stale_asset = _asset(stale_id)
    _staled_override(stale_dir)

    current_dir = asset_dir(tmp_path, config, current_id)
    _write_source_png(current_dir / SOURCES_DIRNAME / "silhouette.png")
    current_asset = _asset(current_id)
    generate_asset(current_asset, current_dir)
    _write_override(current_dir, FILENAME, b"<svg>hand-edited, still current</svg>")

    count = count_stale_overrides([stale_asset, current_asset], tmp_path, config)

    assert count == 1


def test_count_stale_overrides_ignores_an_override_with_no_provenance_yet(
    tmp_path: Path,
) -> None:
    config = CatalogConfig(name="test")
    asset_dir_path = asset_dir(tmp_path, config, "ochre_sea_star")
    _write_source_png(asset_dir_path / SOURCES_DIRNAME / "silhouette.png")
    asset = _asset()
    generate_asset(asset, asset_dir_path)
    _write_override(asset_dir_path, FILENAME, b"<svg>hand-dropped, never touched</svg>")

    count = count_stale_overrides([asset], tmp_path, config)

    assert count == 0
