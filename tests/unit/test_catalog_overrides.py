"""catalog.overrides: the effective derivative, override provenance and
override status (§6.8, ADR 0003, ADR 0004, ADR 0005, ADR 0007).

Builds a real asset folder on disk under ``tmp_path`` (a source PNG plus a
fabricated :class:`~vectorpress.domain.asset.Asset`), the same fixture-free
shape ``tests/unit/test_pipeline_review.py`` uses -- this module's job is
the resolution/provenance/status wiring, not catalog loading
(``tests/integration/test_review.py`` exercises the CLI end to end).
"""

from pathlib import Path

from PIL import Image

from vectorpress.catalog.overrides import (
    OVERRIDES_DIRNAME,
    EffectiveDerivative,
    OverrideProvenance,
    asset_override_status,
    effective_derivative,
    effective_derivative_status,
    ensure_override_provenance,
    list_unrecognized_overrides,
    override_path,
    override_provenance_path,
    override_state_path,
    read_override_bytes,
    read_override_provenance,
    read_override_status,
    write_override_provenance,
    write_override_status,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME, sha256_bytes
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES
from vectorpress.domain.status import Status, StatusRecord

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
    asset_dir = tmp_path / "ochre_sea_star"
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png")
    return asset_dir


def _write_override(asset_dir: Path, filename: str, data: bytes = b"<svg>override</svg>") -> Path:
    path = override_path(asset_dir, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


FILENAME = "ochre-sea-star-cut.svg"


# --- effective_derivative: override present / absent / generated missing -----------


def test_effective_derivative_is_none_when_neither_override_nor_generated_exists(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    assert effective_derivative(asset_dir, FILENAME) is None


def test_effective_derivative_is_the_generated_file_when_no_override_exists(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)

    effective = effective_derivative(asset_dir, FILENAME)

    assert effective is not None
    assert effective.is_override is False
    assert effective.bytes == (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()


def test_effective_derivative_is_the_override_when_one_exists(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    _write_override(asset_dir, FILENAME, b"<svg>hand-edited</svg>")

    effective = effective_derivative(asset_dir, FILENAME)

    assert effective == EffectiveDerivative(bytes=b"<svg>hand-edited</svg>", is_override=True)


def test_effective_derivative_is_the_override_even_with_no_generated_counterpart(
    tmp_path: Path,
) -> None:
    """An override dropped in before the type was ever generated is still
    the effective derivative (§6.8: nothing requires generation first)."""
    asset_dir = _make_asset_dir(tmp_path)
    _write_override(asset_dir, FILENAME, b"<svg>hand-authored</svg>")

    effective = effective_derivative(asset_dir, FILENAME)

    assert effective == EffectiveDerivative(bytes=b"<svg>hand-authored</svg>", is_override=True)


# --- overrides/ is read-only: nothing here ever writes to it ------------------------


def test_nothing_in_this_module_writes_under_overrides(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    override_bytes = b"<svg>hand-edited</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)

    effective = effective_derivative(asset_dir, FILENAME)
    assert effective is not None
    ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, effective.bytes
    )
    write_override_status(
        asset_dir / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash=sha256_bytes(override_bytes)),
    )

    overrides_dir = asset_dir / OVERRIDES_DIRNAME
    assert [p.name for p in overrides_dir.iterdir()] == [FILENAME]
    assert (overrides_dir / FILENAME).read_bytes() == override_bytes


# --- list_unrecognized_overrides: reported, never an error --------------------------


def test_list_unrecognized_overrides_is_empty_with_no_overrides_dir(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    assert list_unrecognized_overrides(asset_dir, [FILENAME]) == []


def test_list_unrecognized_overrides_names_a_file_that_matches_no_known_filename(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    _write_override(asset_dir, "not-a-derivative.svg")

    assert list_unrecognized_overrides(asset_dir, [FILENAME]) == ["not-a-derivative.svg"]


def test_list_unrecognized_overrides_excludes_a_recognized_override(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    _write_override(asset_dir, FILENAME)
    _write_override(asset_dir, "stray.svg")

    assert list_unrecognized_overrides(asset_dir, [FILENAME]) == ["stray.svg"]


# --- override provenance: source hash recorded once, output hash follows the bytes --


def test_ensure_override_provenance_uses_the_generated_derivatives_source_hash(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.catalog.provenance import read_provenance
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    generated_provenance = read_provenance(asset_dir / DERIVED_DIRNAME, FILENAME)
    assert generated_provenance is not None
    override_bytes = b"<svg>hand-edited</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)

    record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    assert record.source_hash == generated_provenance.source_hash
    assert record.output_hash == sha256_bytes(override_bytes)
    assert read_override_provenance(asset_dir / DERIVED_DIRNAME, FILENAME) == record


def test_ensure_override_provenance_uses_the_selected_source_with_no_generated_counterpart(
    tmp_path: Path,
) -> None:
    """No generated cut_svg exists at all: the override's source hash falls
    back to the currently selected source's own hash."""
    asset_dir = _make_asset_dir(tmp_path)
    override_bytes = b"<svg>hand-authored</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)
    source_bytes = (asset_dir / SOURCES_DIRNAME / "silhouette.png").read_bytes()

    record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    assert record.source_hash == sha256_bytes(source_bytes)


def test_ensure_override_provenance_keeps_the_source_hash_across_repeated_edits(
    tmp_path: Path,
) -> None:
    """The source hash is fixed at first sight; a later edit only refreshes
    the output hash (§22.2's staleness check needs a fixed point)."""
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    first_bytes = b"<svg>first edit</svg>"
    _write_override(asset_dir, FILENAME, first_bytes)
    first_record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, first_bytes
    )

    second_bytes = b"<svg>second edit</svg>"
    _write_override(asset_dir, FILENAME, second_bytes)
    second_record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, second_bytes
    )

    assert second_record.source_hash == first_record.source_hash
    assert second_record.output_hash == sha256_bytes(second_bytes)
    assert second_record.output_hash != first_record.output_hash


def test_ensure_override_provenance_does_not_rewrite_when_unchanged(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    override_bytes = b"<svg>hand-edited</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)
    ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )
    path = override_provenance_path(asset_dir / DERIVED_DIRNAME, FILENAME)
    mtime_before = path.stat().st_mtime_ns

    ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    assert path.stat().st_mtime_ns == mtime_before


def test_override_provenance_lives_under_derived_never_overrides(tmp_path: Path) -> None:
    derived_dir = tmp_path / DERIVED_DIRNAME
    write_override_provenance(
        derived_dir, FILENAME, OverrideProvenance(source_hash="a" * 64, output_hash="b" * 64)
    )

    path = override_provenance_path(derived_dir, FILENAME)
    assert path.parent == derived_dir
    assert read_override_provenance(derived_dir, FILENAME) == OverrideProvenance(
        source_hash="a" * 64, output_hash="b" * 64
    )


# --- override status: needs_review when new, follows the bytes, own store -----------


def test_asset_override_status_is_needs_review_for_a_newly_seen_override(tmp_path: Path) -> None:
    record = asset_override_status(tmp_path, DerivativeType.CUT_SVG, b"<svg>edited</svg>")

    assert record.status is Status.NEEDS_REVIEW
    assert record.note is None


def test_asset_override_status_keeps_an_approved_status_when_bytes_are_unchanged(
    tmp_path: Path,
) -> None:
    override_bytes = b"<svg>edited</svg>"
    write_override_status(
        tmp_path,
        DerivativeType.CUT_SVG,
        StatusRecord(
            status=Status.APPROVED, note="clean", output_hash=sha256_bytes(override_bytes)
        ),
    )

    record = asset_override_status(tmp_path, DerivativeType.CUT_SVG, override_bytes)

    assert record.status is Status.APPROVED
    assert record.note == "clean"


def test_asset_override_status_returns_to_needs_review_when_bytes_change(tmp_path: Path) -> None:
    write_override_status(
        tmp_path,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note="clean", output_hash="a" * 64),
    )

    record = asset_override_status(tmp_path, DerivativeType.CUT_SVG, b"<svg>edited again</svg>")

    assert record.status is Status.NEEDS_REVIEW
    assert record.note is None


def test_override_status_lives_in_its_own_file_never_the_generated_ones(tmp_path: Path) -> None:
    write_override_status(
        tmp_path,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash="a" * 64),
    )

    path = override_state_path(tmp_path)
    assert path.name != "_state.json"
    assert read_override_status(tmp_path, DerivativeType.CUT_SVG) is not None
    # the generated file's own store is untouched.
    assert not (tmp_path / "_state.json").exists()


# --- effective_derivative_status: the one answer every consumer uses ----------------


def test_effective_derivative_status_reads_the_override_store_when_overridden(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    override_bytes = b"<svg>edited</svg>"
    write_override_status(
        asset_dir / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash=sha256_bytes(override_bytes)),
    )
    effective = EffectiveDerivative(bytes=override_bytes, is_override=True)

    record = effective_derivative_status(asset_dir, DerivativeType.CUT_SVG, effective)

    assert record.status is Status.APPROVED


def test_effective_derivative_status_reads_the_generated_store_when_not_overridden(
    tmp_path: Path,
) -> None:
    from vectorpress.catalog.status import write_status

    asset_dir = _make_asset_dir(tmp_path)
    generated_bytes = b"<svg>generated</svg>"
    write_status(
        asset_dir / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.REJECTED, note=None, output_hash=sha256_bytes(generated_bytes)),
    )
    effective = EffectiveDerivative(bytes=generated_bytes, is_override=False)

    record = effective_derivative_status(asset_dir, DerivativeType.CUT_SVG, effective)

    assert record.status is Status.REJECTED


def test_read_override_bytes_is_none_with_no_override_file(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)

    assert read_override_bytes(asset_dir, FILENAME) is None
