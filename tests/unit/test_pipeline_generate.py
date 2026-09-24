"""pipeline.generate: generation orchestration, provenance, and idempotence
(ADR 0004, §35, §36, issue #23).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`) rather than the fixture
catalog: this module's job is the generate/current/provenance wiring, not
catalog loading (``tests/integration/test_generate.py`` exercises that end
to end).
"""

from pathlib import Path

from PIL import Image

from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance, sha256_bytes
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
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
