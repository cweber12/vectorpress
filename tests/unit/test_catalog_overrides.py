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

from vectorpress.catalog.findings import findings_path
from vectorpress.catalog.overrides import (
    OVERRIDES_DIRNAME,
    EffectiveDerivative,
    OverrideCurrency,
    OverrideProvenance,
    asset_override_status,
    create_override_from_generated,
    delete_override_findings,
    delete_override_provenance,
    delete_override_status,
    discard_override_file,
    effective_derivative,
    effective_derivative_status,
    ensure_override_provenance,
    list_unrecognized_overrides,
    override_currency,
    override_is_stale,
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
from vectorpress.domain.asset import AccuracyStatus, Asset, DerivativePin, RightsStatus, Source
from vectorpress.domain.derivative_state import DerivativeState
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


# --- create_override_from_generated: create-only, records provenance immediately ----


def test_create_override_from_generated_copies_the_generated_file_byte_for_byte(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()

    path = create_override_from_generated(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, generated_bytes
    )

    assert path == override_path(asset_dir, FILENAME)
    assert path.read_bytes() == generated_bytes


def test_create_override_from_generated_records_provenance_immediately(tmp_path: Path) -> None:
    """The ruling behind this issue: the override's provenance is written the
    moment it is created, not deferred to a later validate/approve, so a
    source change afterward is detectable as staleness right away."""
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()

    create_override_from_generated(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, generated_bytes
    )

    provenance = read_override_provenance(asset_dir / DERIVED_DIRNAME, FILENAME)
    assert provenance is not None
    assert provenance.output_hash == sha256_bytes(generated_bytes)


def test_create_override_from_generated_never_overwrites_an_existing_override(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()
    hand_edited_bytes = b"<svg>already hand-edited</svg>"
    existing_path = _write_override(asset_dir, FILENAME, hand_edited_bytes)
    mtime_before = existing_path.stat().st_mtime_ns

    path = create_override_from_generated(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, generated_bytes
    )

    assert path == existing_path
    assert existing_path.read_bytes() == hand_edited_bytes
    assert existing_path.stat().st_mtime_ns == mtime_before


def test_create_override_from_generated_is_idempotent_on_a_second_call(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()
    recipe = RECIPES[DerivativeType.CUT_SVG]

    first = create_override_from_generated(_asset(), asset_dir, recipe, FILENAME, generated_bytes)
    mtime_before = first.stat().st_mtime_ns
    second = create_override_from_generated(_asset(), asset_dir, recipe, FILENAME, generated_bytes)

    assert second == first
    assert second.stat().st_mtime_ns == mtime_before


# --- override_is_stale: the pure comparison behind override_currency (§22.2) --------


def test_override_is_stale_is_false_when_the_hashes_match() -> None:
    assert override_is_stale("a" * 64, "a" * 64) is False


def test_override_is_stale_is_true_when_the_hashes_differ() -> None:
    """A changed source's content: the edited-against hash no longer equals
    the hash of what the source now contains."""
    assert override_is_stale("a" * 64, "b" * 64) is True


def test_override_is_stale_is_true_when_a_pin_now_selects_a_different_source() -> None:
    """A pin change lands here exactly like a content change: whichever
    source is now selected, its hash is compared the same way -- the
    override was edited against the hash of the source that used to be
    selected."""
    edited_against_the_old_pin = sha256_bytes(b"first source's bytes")
    now_selected_by_the_new_pin = sha256_bytes(b"second source's bytes")
    assert override_is_stale(edited_against_the_old_pin, now_selected_by_the_new_pin) is True


def test_override_is_stale_is_true_when_the_current_source_is_gone(tmp_path: Path) -> None:
    """The currently selected source file has been deleted from disk:
    ``override_currency`` passes ``None`` here, always a mismatch."""
    assert override_is_stale("a" * 64, None) is True


# --- override_currency: stale (source changed) / current / nothing to compare yet ---


def test_override_currency_is_none_with_no_provenance_recorded_yet(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    _write_override(asset_dir, FILENAME)

    currency = override_currency(_asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME)

    assert currency is None


def test_override_currency_is_current_right_after_the_baseline_is_recorded(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    override_bytes = b"<svg>hand-authored</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)
    ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    currency = override_currency(_asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME)

    assert currency == OverrideCurrency(DerivativeState.CURRENT, None)


def test_override_currency_is_stale_once_the_source_content_changes(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    override_bytes = b"<svg>hand-authored</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)
    ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(1, 2, 3, 255))

    currency = override_currency(_asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME)

    assert currency is not None
    assert currency.state is DerivativeState.STALE
    assert currency.reason == "source changed"


def test_override_currency_is_stale_once_a_pin_selects_a_different_source(
    tmp_path: Path,
) -> None:
    """A pin change alone -- no source's own bytes are touched -- flags the
    override stale too, since a different source is now selected for it."""
    asset_dir = _make_asset_dir(tmp_path)
    _write_source_png(asset_dir / SOURCES_DIRNAME / "second.png", rgba=(9, 9, 9, 255))
    asset = Asset(
        id="ochre_sea_star",
        common_name="Ochre sea star",
        display_name="Ochre Sea Star",
        description="A test asset.",
        subject_category="Echinoderm",
        taxonomic_group="Echinoderm",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=[
            Source(role="silhouette", file="silhouette.png"),
            Source(role="silhouette", file="second.png"),
        ],
    )
    override_bytes = b"<svg>hand-authored</svg>"
    _write_override(asset_dir, FILENAME, override_bytes)
    ensure_override_provenance(
        asset, asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, override_bytes
    )

    pinned = asset.model_copy(
        update={"derivatives": {DerivativeType.CUT_SVG.value: DerivativePin(source="second.png")}}
    )
    currency = override_currency(pinned, asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME)

    assert currency is not None
    assert currency.state is DerivativeState.STALE


# --- re-edit rule: bytes change rebaselines to the *current* source (§22.2) ---------


def test_ensure_override_provenance_rebaselines_to_the_new_source_when_it_actually_changed(
    tmp_path: Path,
) -> None:
    """Distinct from the "keeps the source hash across repeated edits" test
    above: there, the source never changes between edits, so the rebaselined
    hash happens to equal the old one. Here the source really does change
    between two edits, and the second edit's baseline follows it -- the
    re-edit rule (§22.2) that clears a stale flag the moment a human edits
    the override, with no extra command."""
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    first_bytes = b"<svg>first edit</svg>"
    _write_override(asset_dir, FILENAME, first_bytes)
    first_record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, first_bytes
    )

    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png", rgba=(7, 8, 9, 255))
    new_source_hash = sha256_bytes((asset_dir / SOURCES_DIRNAME / "silhouette.png").read_bytes())

    second_bytes = b"<svg>second edit</svg>"
    _write_override(asset_dir, FILENAME, second_bytes)
    second_record = ensure_override_provenance(
        _asset(), asset_dir, RECIPES[DerivativeType.CUT_SVG], FILENAME, second_bytes
    )

    assert second_record.source_hash == new_source_hash
    assert second_record.source_hash != first_record.source_hash


# --- orphaned override state: a newly appearing override starts fresh (§22.2) -------


def test_create_override_from_generated_does_not_inherit_orphaned_provenance_or_status(
    tmp_path: Path,
) -> None:
    """A previous override was approved, then deleted by hand (not through
    ``vpress override discard``), leaving its provenance and status behind
    with nothing to clean them up. A new override created afterward
    (``vpress open --override``'s codepath) must not inherit that leftover
    state: fresh provenance, ``needs_review``, not the old ``approved``."""
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    recipe = RECIPES[DerivativeType.CUT_SVG]
    old_override_bytes = b"<svg>the deleted override</svg>"
    override_file = _write_override(asset_dir, FILENAME, old_override_bytes)
    ensure_override_provenance(_asset(), asset_dir, recipe, FILENAME, old_override_bytes)
    write_override_status(
        asset_dir / DERIVED_DIRNAME,
        DerivativeType.CUT_SVG,
        StatusRecord(
            status=Status.APPROVED, note="clean", output_hash=sha256_bytes(old_override_bytes)
        ),
    )
    # Deleted by hand -- no command ran to clean up its state.
    override_file.unlink()

    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()
    generated_provenance_source_hash = sha256_bytes(
        (asset_dir / SOURCES_DIRNAME / "silhouette.png").read_bytes()
    )
    create_override_from_generated(_asset(), asset_dir, recipe, FILENAME, generated_bytes)

    new_provenance = read_override_provenance(asset_dir / DERIVED_DIRNAME, FILENAME)
    assert new_provenance is not None
    assert new_provenance.source_hash == generated_provenance_source_hash
    assert new_provenance.output_hash == sha256_bytes(generated_bytes)

    new_status = asset_override_status(
        asset_dir / DERIVED_DIRNAME, DerivativeType.CUT_SVG, generated_bytes
    )
    assert new_status.status is Status.NEEDS_REVIEW
    assert new_status.note is None


def test_create_override_from_generated_does_not_inherit_orphaned_findings(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    from vectorpress.pipeline.generate import generate_asset

    generate_asset(_asset(), asset_dir)
    recipe = RECIPES[DerivativeType.CUT_SVG]
    override_file = _write_override(asset_dir, FILENAME, b"<svg>the deleted override</svg>")
    report_path = findings_path(asset_dir / DERIVED_DIRNAME, FILENAME, is_override=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{}", encoding="utf-8")
    override_file.unlink()

    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()
    create_override_from_generated(_asset(), asset_dir, recipe, FILENAME, generated_bytes)

    assert not report_path.is_file()


# --- delete_override_provenance / delete_override_status / delete_override_findings -


def test_delete_override_provenance_removes_the_record(tmp_path: Path) -> None:
    derived_dir = tmp_path / DERIVED_DIRNAME
    write_override_provenance(
        derived_dir, FILENAME, OverrideProvenance(source_hash="a" * 64, output_hash="b" * 64)
    )

    delete_override_provenance(derived_dir, FILENAME)

    assert read_override_provenance(derived_dir, FILENAME) is None


def test_delete_override_provenance_is_a_noop_with_nothing_recorded(tmp_path: Path) -> None:
    delete_override_provenance(tmp_path, FILENAME)  # does not raise


def test_delete_override_status_removes_only_the_named_type(tmp_path: Path) -> None:
    write_override_status(
        tmp_path,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash="a" * 64),
    )
    write_override_status(
        tmp_path,
        DerivativeType.SILHOUETTE_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash="b" * 64),
    )

    delete_override_status(tmp_path, DerivativeType.CUT_SVG)

    assert read_override_status(tmp_path, DerivativeType.CUT_SVG) is None
    assert read_override_status(tmp_path, DerivativeType.SILHOUETTE_SVG) is not None


def test_delete_override_status_removes_the_whole_file_when_it_was_the_only_entry(
    tmp_path: Path,
) -> None:
    write_override_status(
        tmp_path,
        DerivativeType.CUT_SVG,
        StatusRecord(status=Status.APPROVED, note=None, output_hash="a" * 64),
    )

    delete_override_status(tmp_path, DerivativeType.CUT_SVG)

    assert not override_state_path(tmp_path).exists()


def test_delete_override_findings_removes_the_override_report(tmp_path: Path) -> None:
    derived_dir = tmp_path / DERIVED_DIRNAME
    report_path = findings_path(derived_dir, FILENAME, is_override=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{}", encoding="utf-8")

    delete_override_findings(derived_dir, FILENAME)

    assert not report_path.is_file()


def test_discard_override_file_removes_the_file(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    override_file = _write_override(asset_dir, FILENAME)

    discard_override_file(asset_dir, FILENAME)

    assert not override_file.is_file()


def test_discard_override_file_is_a_noop_with_no_file(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    discard_override_file(asset_dir, FILENAME)  # does not raise
