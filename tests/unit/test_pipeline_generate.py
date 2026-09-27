"""pipeline.generate: generation orchestration, provenance, and idempotence
(ADR 0004, §35, §36, issue #23).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`) rather than the fixture
catalog: this module's job is the generate/current/provenance wiring, not
catalog loading (``tests/integration/test_generate.py`` exercises that end
to end).
"""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from vectorpress.catalog.overrides import override_currency, override_path, read_override_provenance
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance, sha256_bytes
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.recipe import RECIPES
from vectorpress.pipeline import generate as generate_module
from vectorpress.pipeline.generate import (
    GenerationOutcome,
    asset_derivative_statuses,
    generate_asset,
)

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _write_fully_transparent_source_png(path: Path) -> None:
    """A silhouette source with no ink at all: ``silhouette_svg`` has
    nothing to trace and its generator raises (issue #24 review fix round
    1) -- ``transparent_png`` tolerates the same source fine (an empty
    bounding box just means an uncropped, all-transparent output), so this
    is also a source that fails one derivative type but not another."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(path, format="PNG")


def _asset(
    display_name: str = "Ochre Sea Star",
    sources: list[Source] | None = None,
) -> Asset:
    return Asset(
        id="ochre_sea_star",
        common_name="Ochre sea star",
        display_name=display_name,
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


# --- asset_derivative_statuses: impossible / missing / current --------------------


def test_status_is_impossible_for_flatcolor_svg_with_only_a_silhouette_source(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}

    assert statuses[DerivativeType.FLATCOLOR_SVG].state is DerivativeState.IMPOSSIBLE
    assert statuses[DerivativeType.FLATCOLOR_SVG].output_filename is None


def test_status_is_impossible_for_cut_svg_with_no_silhouette_source(tmp_path: Path) -> None:
    """Acceptance criterion 2 (issue #36): ``cut_svg`` accepts only the
    ``silhouette`` role (ADR 0003), so an asset declaring some other role
    but no silhouette source can never produce one -- a constructed asset,
    per the issue's own acceptance criterion."""
    asset_dir = tmp_path / "ochre_sea_star"
    _write_source_png(asset_dir / SOURCES_DIRNAME / "flatcolor.png")
    asset = _asset(sources=[Source(role="flatcolor", file="flatcolor.png")])

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(asset, asset_dir)}
    cut_svg_status = statuses[DerivativeType.CUT_SVG]

    assert cut_svg_status.state is DerivativeState.IMPOSSIBLE
    assert cut_svg_status.output_filename is None
    assert cut_svg_status.reason is not None
    assert "silhouette" in cut_svg_status.reason


def test_status_is_missing_before_anything_is_generated(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}

    assert statuses[DerivativeType.TRANSPARENT_PNG].state is DerivativeState.MISSING
    assert statuses[DerivativeType.SILHOUETTE_SVG].state is DerivativeState.MISSING


def test_status_is_current_after_generation(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}

    png_status = statuses[DerivativeType.TRANSPARENT_PNG]
    assert png_status.state is DerivativeState.CURRENT
    assert png_status.output_filename == "ochre-sea-star-color.png"


# --- generate_asset outcomes ------------------------------------------------------


def test_generate_asset_reports_impossible_with_a_reason(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.FLATCOLOR_SVG]
    assert result.outcome is GenerationOutcome.IMPOSSIBLE
    assert "flatcolor" in result.detail


def test_generate_asset_generates_flatcolor_svg_with_customer_facing_filename(
    tmp_path: Path,
) -> None:
    """Issue #25: ``flatcolor_svg`` now has a landed generator -- with a
    selectable flatcolor source it is generated, not reported ``no
    generator``."""
    asset_dir = _make_asset_dir(tmp_path)
    _write_source_png(asset_dir / SOURCES_DIRNAME / "flatcolor.png")
    asset = _asset(
        sources=[
            Source(role="silhouette", file="silhouette.png"),
            Source(role="flatcolor", file="flatcolor.png"),
        ]
    )

    results = {r.derivative_type: r for r in generate_asset(asset, asset_dir)}

    result = results[DerivativeType.FLATCOLOR_SVG]
    assert result.outcome is GenerationOutcome.GENERATED
    assert result.detail == "ochre-sea-star-color.svg"

    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.svg"
    assert output_path.is_file()
    assert b"<image" not in output_path.read_bytes()


def test_generate_asset_generates_silhouette_svg_with_customer_facing_filename(
    tmp_path: Path,
) -> None:
    """Issue #24: ``silhouette_svg`` now has a landed generator."""
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.SILHOUETTE_SVG]
    assert result.outcome is GenerationOutcome.GENERATED
    assert result.detail == "ochre-sea-star-silhouette.svg"

    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-silhouette.svg"
    assert output_path.is_file()
    assert b"<image" not in output_path.read_bytes()


def test_generate_asset_generates_cut_svg_with_customer_facing_filename(tmp_path: Path) -> None:
    """Issue #36: ``cut_svg`` now has a landed generator."""
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.CUT_SVG]
    assert result.outcome is GenerationOutcome.GENERATED
    assert result.detail == "ochre-sea-star-cut.svg"

    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-cut.svg"
    assert output_path.is_file()
    assert b"<image" not in output_path.read_bytes()


def test_generate_asset_records_the_effective_reference_size_in_provenance(
    tmp_path: Path,
) -> None:
    """Issue #36's "reference size in the recipe identity": the catalog's
    ``reference_size_in`` -- not part of ``RECIPES``' own static
    declaration -- is merged into ``cut_svg``'s recorded parameters and
    recipe hash. With no config at all (as every other test in this file
    calls ``generate_asset``), it falls back to the documented catalog
    default."""
    asset_dir = _make_asset_dir(tmp_path)

    generate_asset(_asset(), asset_dir)

    provenance = read_provenance(asset_dir / DERIVED_DIRNAME, "ochre-sea-star-cut.svg")
    assert provenance is not None
    assert provenance.parameters["reference_size_in"] == 3.0

    config = CatalogConfig(name="Test Catalog", reference_size_in=5.0)
    other_asset_dir = tmp_path / "other_asset"
    _write_source_png(other_asset_dir / SOURCES_DIRNAME / "silhouette.png")
    generate_asset(_asset(), other_asset_dir, config=config)

    other_provenance = read_provenance(other_asset_dir / DERIVED_DIRNAME, "ochre-sea-star-cut.svg")
    assert other_provenance is not None
    assert other_provenance.parameters["reference_size_in"] == 5.0
    assert other_provenance.recipe_hash != provenance.recipe_hash


def test_generate_asset_generates_transparent_png_with_customer_facing_filename(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.GENERATED
    assert result.detail == "ochre-sea-star-color.png"

    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    assert output_path.is_file()
    with Image.open(output_path) as image:
        assert image.mode == "RGBA"


def test_generate_asset_writes_a_provenance_record_with_every_required_field(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    generate_asset(_asset(), asset_dir)

    provenance = read_provenance(asset_dir / DERIVED_DIRNAME, "ochre-sea-star-color.png")
    assert provenance is not None
    assert provenance.source_file == "silhouette.png"
    source_bytes = (asset_dir / SOURCES_DIRNAME / "silhouette.png").read_bytes()
    assert provenance.source_hash == sha256_bytes(source_bytes)
    assert provenance.derivative_type == "transparent_png"
    assert provenance.generator == "transparent_png"
    assert provenance.recipe_hash  # non-empty
    assert provenance.generator_versions["vectorpress"]
    assert provenance.generator_versions["Pillow"]
    assert provenance.output_file == "ochre-sea-star-color.png"
    output_bytes = (asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png").read_bytes()
    assert provenance.output_hash == sha256_bytes(output_bytes)


# --- generator failure isolation (issue #24 review fix round 1) -------------------


def test_generate_asset_reports_failed_when_the_generator_raises(tmp_path: Path) -> None:
    """A fully transparent silhouette source leaves ``silhouette_svg``
    with no geometry to trace: its generator raises, and ``generate_asset``
    reports ``failed`` with a reason instead of letting the exception
    propagate and stop the rest of the asset (controller ruling: this is a
    per-derivative failure, not ``impossible`` -- CONTEXT.md reserves
    ``impossible`` for "no acceptable source", and a source was selected
    here)."""
    asset_dir = tmp_path / "ochre_sea_star"
    _write_fully_transparent_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png")

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.SILHOUETTE_SVG]
    assert result.outcome is GenerationOutcome.FAILED
    assert result.detail  # a non-empty reason

    assert not (asset_dir / DERIVED_DIRNAME).exists() or not any(
        (asset_dir / DERIVED_DIRNAME).glob("*silhouette*")
    )


def test_generate_asset_continues_past_a_failed_derivative_to_the_next(tmp_path: Path) -> None:
    """One derivative failing does not stop the rest of the same asset:
    ``transparent_png`` still generates from the same (fully transparent)
    source that made ``silhouette_svg`` fail."""
    asset_dir = tmp_path / "ochre_sea_star"
    _write_fully_transparent_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png")

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    assert results[DerivativeType.SILHOUETTE_SVG].outcome is GenerationOutcome.FAILED
    assert results[DerivativeType.TRANSPARENT_PNG].outcome is GenerationOutcome.GENERATED
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    assert output_path.is_file()


def test_generate_asset_reports_a_flatcolor_source_that_is_not_flat_color_as_failed(
    tmp_path: Path,
) -> None:
    """Issue #83, §35: a flatcolor-role source whose pixels are every one
    their own color fails ``flatcolor_svg`` alone, with a reason that says
    what is wrong with the source -- ``transparent_png`` still generates
    from the very same file, and nothing is written for the failed type."""
    asset_dir = tmp_path / "ochre_sea_star"
    source_path = asset_dir / SOURCES_DIRNAME / "flatcolor.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.random.default_rng(83).integers(0, 256, size=(300, 300, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    Image.fromarray(pixels, mode="RGBA").save(source_path, format="PNG")
    asset = _asset(sources=[Source(role="flatcolor", file="flatcolor.png")])

    results = {r.derivative_type: r for r in generate_asset(asset, asset_dir)}

    failed = results[DerivativeType.FLATCOLOR_SVG]
    assert failed.outcome is GenerationOutcome.FAILED
    assert failed.source_file == "flatcolor.png"
    assert "source is not flat-color" in failed.detail
    assert "fragments in color #" in failed.detail
    assert results[DerivativeType.TRANSPARENT_PNG].outcome is GenerationOutcome.GENERATED
    assert not any((asset_dir / DERIVED_DIRNAME).glob("*.svg*"))


# --- idempotence (§36) -------------------------------------------------------------


def test_status_is_stale_source_changed_when_the_source_changes(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}
    png_status = statuses[DerivativeType.TRANSPARENT_PNG]
    assert png_status.state is DerivativeState.STALE
    assert png_status.reason == "source changed"
    assert png_status.output_filename == "ochre-sea-star-color.png"


def test_second_generate_reports_current_and_rewrites_nothing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    provenance_file = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png.provenance.json"
    output_mtime = output_path.stat().st_mtime_ns
    provenance_mtime = provenance_file.stat().st_mtime_ns

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.CURRENT
    assert result.detail == "ochre-sea-star-color.png"
    assert output_path.stat().st_mtime_ns == output_mtime
    assert provenance_file.stat().st_mtime_ns == provenance_mtime


def test_regenerates_when_the_source_file_changes(tmp_path: Path) -> None:
    """§22: "If an approved master asset is updated, the user should be able
    to regenerate its derivatives" -- and issue #23 acceptance criterion 4's
    "a different source changes the source hash"."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    first_provenance = read_provenance(asset_dir / DERIVED_DIRNAME, "ochre-sea-star-color.png")
    assert first_provenance is not None

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}
    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.GENERATED

    second_provenance = read_provenance(asset_dir / DERIVED_DIRNAME, "ochre-sea-star-color.png")
    assert second_provenance is not None
    assert second_provenance.source_hash != first_provenance.source_hash


# --- overrides: generate baselines an untouched override before rewriting (§22.2) --


def test_generate_baselines_a_hand_dropped_override_before_rewriting_the_generated_file(
    tmp_path: Path,
) -> None:
    """A hand-dropped override with no provenance of its own yet -- no
    command has touched it -- must still be flagged stale after a source
    change and a regenerate: its baseline has to be the source hash the
    generated file had *before* this generate rewrote it, not the new one,
    or the two would trivially match and the override would never look
    stale at all."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    filename = derivative_filename(_asset().display_name, DerivativeType.CUT_SVG)
    old_source_hash = sha256_bytes((asset_dir / SOURCES_DIRNAME / "silhouette.png").read_bytes())

    override_path(asset_dir, filename).parent.mkdir(parents=True, exist_ok=True)
    override_path(asset_dir, filename).write_bytes(b"<svg>hand-dropped, never touched</svg>")
    assert read_override_provenance(asset_dir / DERIVED_DIRNAME, filename) is None

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))
    generate_asset(_asset(), asset_dir)

    provenance = read_override_provenance(asset_dir / DERIVED_DIRNAME, filename)
    assert provenance is not None
    assert provenance.source_hash == old_source_hash

    currency = override_currency(_asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], filename)
    assert currency is not None
    assert currency.state is DerivativeState.STALE
    assert currency.reason == "source changed"


# --- stale_only (issue #26's --stale) ----------------------------------------------


def test_stale_only_regenerates_stale_but_leaves_current_untouched(tmp_path: Path) -> None:
    """Issue #26 acceptance criterion 2: ``--stale`` regenerates exactly the
    stale derivatives and reports the rest untouched -- here, only the
    silhouette source changes, so ``silhouette_svg`` (the only type that
    selects it -- ``transparent_png`` and ``flatcolor_svg`` both prefer the
    flatcolor source) goes stale and is regenerated, while the other two
    stay current and untouched."""
    asset_dir = _make_asset_dir(tmp_path)
    _write_source_png(asset_dir / SOURCES_DIRNAME / "flatcolor.png")
    asset = _asset(
        sources=[
            Source(role="silhouette", file="silhouette.png"),
            Source(role="flatcolor", file="flatcolor.png"),
        ]
    )
    generate_asset(asset, asset_dir)
    png_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    flatcolor_svg_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.svg"
    png_mtime = png_path.stat().st_mtime_ns
    flatcolor_svg_mtime = flatcolor_svg_path.stat().st_mtime_ns

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    results = {r.derivative_type: r for r in generate_asset(asset, asset_dir, stale_only=True)}

    assert results[DerivativeType.SILHOUETTE_SVG].outcome is GenerationOutcome.GENERATED
    assert results[DerivativeType.TRANSPARENT_PNG].outcome is GenerationOutcome.CURRENT
    assert results[DerivativeType.FLATCOLOR_SVG].outcome is GenerationOutcome.CURRENT
    assert png_path.stat().st_mtime_ns == png_mtime
    assert flatcolor_svg_path.stat().st_mtime_ns == flatcolor_svg_mtime


def test_stale_only_reports_missing_as_missing_and_does_not_generate_it(tmp_path: Path) -> None:
    """``--stale`` never generates a derivative that has not been generated
    yet -- "not missing ones" -- and reports it as ``missing`` rather than
    silently dropping it from the report."""
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir, stale_only=True)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.MISSING
    assert not (asset_dir / DERIVED_DIRNAME).exists()


def test_stale_only_reports_current_as_current_and_does_not_regenerate_it(tmp_path: Path) -> None:
    """``--stale`` never regenerates an already-current derivative -- "not
    current ones"."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    mtime_before = output_path.stat().st_mtime_ns

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir, stale_only=True)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.CURRENT
    assert output_path.stat().st_mtime_ns == mtime_before


def test_second_stale_only_run_regenerates_nothing(tmp_path: Path) -> None:
    """Issue #26 acceptance criterion 2: a second ``--stale`` run finds
    nothing stale left and regenerates nothing."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))
    generate_asset(_asset(), asset_dir, stale_only=True)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    mtime_after_first_stale_run = output_path.stat().st_mtime_ns

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir, stale_only=True)}

    for result in results.values():
        assert result.outcome is not GenerationOutcome.GENERATED
    assert output_path.stat().st_mtime_ns == mtime_after_first_stale_run


# --- force (issue #26's --force) -----------------------------------------------------


def test_force_regenerates_a_current_derivative(tmp_path: Path) -> None:
    """Issue #26 acceptance criterion 5: ``--force`` regenerates a current
    derivative (reported ``generated`` -- the generator actually ran)."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir, force=True)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.GENERATED


def test_force_does_not_rewrite_output_bytes_when_they_are_unchanged(tmp_path: Path) -> None:
    """Issue #26 acceptance criterion 5: when the freshly generated bytes
    equal the recorded output hash, ``--force`` still does not rewrite the
    file (bytes and mtime unchanged) -- §36 idempotence, unaffected by
    forcing the generator to actually run. The provenance record beside it
    is equally unchanged (issue #26 review fix round 1): ``write_derivative``
    now skips that write too when its serialized payload already matches
    what is on disk, not just the output file."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    provenance_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png.provenance.json"
    output_bytes_before = output_path.read_bytes()
    output_mtime_before = output_path.stat().st_mtime_ns
    provenance_bytes_before = provenance_path.read_bytes()
    provenance_mtime_before = provenance_path.stat().st_mtime_ns

    generate_asset(_asset(), asset_dir, force=True)

    assert output_path.read_bytes() == output_bytes_before
    assert output_path.stat().st_mtime_ns == output_mtime_before
    assert provenance_path.read_bytes() == provenance_bytes_before
    assert provenance_path.stat().st_mtime_ns == provenance_mtime_before


def test_force_regenerates_a_stale_derivative_same_as_default(tmp_path: Path) -> None:
    """``--force`` also regenerates stale and missing derivatives -- it
    only changes the treatment of current ones."""
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir, force=True)}

    assert results[DerivativeType.TRANSPARENT_PNG].outcome is GenerationOutcome.GENERATED


# --- widened failure catch: read/write, not just the generator (issue #27, §35) ---


def test_generate_asset_reports_failed_when_the_source_cannot_be_read(tmp_path: Path) -> None:
    """The widened catch covers ``read_source_bytes`` too, not only the
    generator call: a selected source that vanishes out from under
    generation (here, deleted right before ``generate_asset`` runs) is
    reported ``failed``, not left to crash the rest of the run."""
    asset_dir = _make_asset_dir(tmp_path)
    (asset_dir / SOURCES_DIRNAME / "silhouette.png").unlink()

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.FAILED
    assert result.detail  # a non-empty cause
    assert not (asset_dir / DERIVED_DIRNAME).exists()


def test_generate_asset_reports_failed_when_write_derivative_raises_after_the_output_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion 4: simulates a crash between the output write
    and the provenance write -- a ``write_derivative`` that writes the
    output bytes directly (mimicking that first write succeeding) and then
    raises (mimicking the crash before the provenance write). The widened
    catch reports it ``failed`` instead of propagating and crashing the
    run; the derivative reports ``missing`` (never ``current``) until a
    later generate -- with the real ``write_derivative`` back -- completes
    it, writing both files this time.
    """
    asset_dir = _make_asset_dir(tmp_path)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"

    def _crash_after_writing_the_output(
        derived_dir: Path, output_filename: str, output_bytes: bytes, provenance: Any
    ) -> None:
        derived_dir.mkdir(parents=True, exist_ok=True)
        (derived_dir / output_filename).write_bytes(output_bytes)
        raise OSError("simulated crash before the provenance write")

    with monkeypatch.context() as patch:
        patch.setattr(generate_module, "write_derivative", _crash_after_writing_the_output)
        results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.FAILED
    assert output_path.is_file()  # the "first write" landed before the simulated crash
    assert read_provenance(asset_dir / DERIVED_DIRNAME, output_path.name) is None

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}
    assert statuses[DerivativeType.TRANSPARENT_PNG].state is DerivativeState.MISSING

    # the real write_derivative is back outside the ``with`` block: the next
    # generate completes it, writing both files this time.
    completed = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}
    assert completed[DerivativeType.TRANSPARENT_PNG].outcome is GenerationOutcome.GENERATED
    assert output_path.is_file()
    assert read_provenance(asset_dir / DERIVED_DIRNAME, output_path.name) is not None


def test_generate_asset_leaves_no_temp_file_when_the_real_write_fails_to_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #27 review fix round 1: the test above bypasses
    ``catalog.provenance.write_derivative`` entirely (it is replaced with a
    fake), so it never exercises that module's own atomic-write cleanup.
    This one drives a write failure through the *real* ``write_derivative``
    -- ``catalog.atomic_write.atomic_write_bytes``'s rename step (``Path.replace``) is made to
    raise, so its own ``except BaseException: ... unlink(missing_ok=True);
    raise`` cleanup runs for real, not a stand-in for it.

    Asserts the derivative is reported ``failed``, ``derived/`` is left with
    no output file and no stray ``*.tmp`` file (or any other file), no
    provenance record exists, and ``asset_derivative_statuses`` reports it
    ``missing`` -- the same "nothing half-written" guarantee AC2 checks for
    a decode failure (where nothing is ever attempted), now proven for a
    write failure too (where a temp file really was created before the
    failure).
    """
    asset_dir = _make_asset_dir(tmp_path)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"

    def _fail_to_rename(self: Path, target: object) -> Path:
        raise OSError("simulated disk full during rename")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", _fail_to_rename)
        results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.FAILED
    assert result.detail  # a non-empty cause

    derived_dir = asset_dir / DERIVED_DIRNAME
    assert not output_path.exists()
    if derived_dir.exists():
        entries = list(derived_dir.iterdir())
        assert entries == [], f"expected an empty or absent derived/, found: {entries}"
    assert read_provenance(derived_dir, output_path.name) is None

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}
    assert statuses[DerivativeType.TRANSPARENT_PNG].state is DerivativeState.MISSING


def test_generate_asset_after_a_source_change_a_failing_generator_leaves_the_prior_derivative_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion 3: a derivative that generated successfully
    once, whose source then changed (making it stale), fails on the next
    generate when its generator raises. The widened catch still sits
    entirely before the write, so the prior output and provenance are left
    byte-identical, and the derivative is reported ``stale`` -- never
    ``current`` -- both immediately after and on a later, unpatched check.
    """
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    output_path = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png"
    provenance_file = asset_dir / DERIVED_DIRNAME / "ochre-sea-star-color.png.provenance.json"
    output_bytes_before = output_path.read_bytes()
    provenance_bytes_before = provenance_file.read_bytes()

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(10, 20, 30, 255))

    def _always_raise(source_bytes: bytes, parameters: object) -> object:
        raise ValueError("simulated generator failure after a source change")

    def _get_always_raising_generator(name: str) -> Any:
        return _always_raise

    with monkeypatch.context() as patch:
        patch.setattr(generate_module, "get_generator", _get_always_raising_generator)
        results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    result = results[DerivativeType.TRANSPARENT_PNG]
    assert result.outcome is GenerationOutcome.FAILED
    assert output_path.read_bytes() == output_bytes_before
    assert provenance_file.read_bytes() == provenance_bytes_before

    statuses = {s.derivative_type: s for s in asset_derivative_statuses(_asset(), asset_dir)}
    assert statuses[DerivativeType.TRANSPARENT_PNG].state is DerivativeState.STALE
    assert statuses[DerivativeType.TRANSPARENT_PNG].reason == "source changed"


# --- GenerationResult.source_file (issue #27: the stderr diagnostic names it) -----


def test_generation_result_names_the_source_file_for_every_outcome_except_impossible(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    results = {r.derivative_type: r for r in generate_asset(_asset(), asset_dir)}

    assert results[DerivativeType.TRANSPARENT_PNG].source_file == "silhouette.png"
    assert results[DerivativeType.SILHOUETTE_SVG].source_file == "silhouette.png"
    assert results[DerivativeType.FLATCOLOR_SVG].outcome is GenerationOutcome.IMPOSSIBLE
    assert results[DerivativeType.FLATCOLOR_SVG].source_file is None
