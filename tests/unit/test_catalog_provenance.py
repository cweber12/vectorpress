"""catalog.provenance: tool-owned provenance records (ADR 0004, issue #23,
issue #26).

Also the only module that reads a source's bytes or decides whether a
derivative is current, stale (with a reason), or missing (ADR 0006's
"catalog... the only layer touching catalog files"; issue #23 review fix
round 2) -- ``read_source_bytes`` and ``derivative_currency`` are tested here
alongside the provenance read/write pair they sit next to.
"""

import json
from dataclasses import replace
from pathlib import Path

from vectorpress.catalog.provenance import (
    DERIVED_DIRNAME,
    OUTPUT_CHANGED_ON_DISK,
    RECIPE_CHANGED,
    SOURCE_CHANGED,
    Provenance,
    derivative_currency,
    provenance_path,
    read_provenance,
    read_source_bytes,
    recipe_identity_hash,
    sha256_bytes,
    write_derivative,
)
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES, Recipe

SOURCES_DIRNAME = "sources"


def _provenance(**overrides: object) -> Provenance:
    defaults: dict[str, object] = {
        "source_file": "silhouette.png",
        "source_hash": "a" * 64,
        "derivative_type": "transparent_png",
        "generator": "transparent_png",
        "parameters": {},
        "recipe_hash": "b" * 64,
        "generator_versions": {"vectorpress": "0.1.0", "Pillow": "12.3.0"},
        "output_file": "ochre-sea-star-color.png",
        "output_hash": "c" * 64,
    }
    defaults.update(overrides)
    return Provenance(**defaults)  # type: ignore[arg-type]


# --- hashing -------------------------------------------------------------------


def test_sha256_bytes_is_a_sha256_hex_digest() -> None:
    digest = sha256_bytes(b"hello")

    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert len(digest) == 64


def test_recipe_identity_hash_changes_when_a_parameter_changes() -> None:
    """ADR 0004: "recipe identity including parameters, hashed so a
    parameter change changes the identity" -- the crux of a §23 acceptance
    criterion."""
    base = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="transparent_png",
        parameters={"margin": 0},
    )
    changed = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="transparent_png",
        parameters={"margin": 4},
    )

    assert recipe_identity_hash(base) != recipe_identity_hash(changed)


def test_recipe_identity_hash_changes_when_the_generator_changes() -> None:
    base = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="transparent_png",
        parameters={},
    )
    other = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="a_different_generator",
        parameters={},
    )

    assert recipe_identity_hash(base) != recipe_identity_hash(other)


def test_recipe_identity_hash_changes_when_a_tracing_parameter_changes() -> None:
    """Issue #24 acceptance criterion: changing one of
    ``silhouette_svg``'s real tracing parameters (curve tolerance here)
    changes the recipe identity, so every derivative built under the old
    value becomes stale (ADR 0004)."""
    base = RECIPES[DerivativeType.SILHOUETTE_SVG]
    changed = replace(base, parameters={**base.parameters, "curve_tolerance": 0.8})

    assert recipe_identity_hash(base) != recipe_identity_hash(changed)


def test_recipe_identity_hash_is_stable_regardless_of_parameter_key_order() -> None:
    a = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="transparent_png",
        parameters={"a": 1, "b": 2},
    )
    b = Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("silhouette",),
        generator="transparent_png",
        parameters={"b": 2, "a": 1},
    )

    assert recipe_identity_hash(a) == recipe_identity_hash(b)


# --- read/write round trip ------------------------------------------------------


def test_write_then_read_round_trips_the_provenance_record(tmp_path: Path) -> None:
    provenance = _provenance()

    write_derivative(tmp_path, provenance.output_file, b"fake png bytes", provenance)
    reread = read_provenance(tmp_path, provenance.output_file)

    assert reread == provenance


def test_read_provenance_returns_none_when_no_record_exists(tmp_path: Path) -> None:
    assert read_provenance(tmp_path, "does-not-exist.png") is None


def test_provenance_lives_beside_the_derivative_never_inside_it(tmp_path: Path) -> None:
    provenance = _provenance()

    write_derivative(tmp_path, provenance.output_file, b"fake png bytes", provenance)

    output_path = tmp_path / provenance.output_file
    assert output_path.read_bytes() == b"fake png bytes"  # the output file holds only image bytes
    record_path = provenance_path(tmp_path, provenance.output_file)
    assert record_path != output_path
    assert record_path.is_file()
    assert (
        json.loads(record_path.read_text(encoding="utf-8"))["output_hash"] == provenance.output_hash
    )


# --- atomic, idempotent writes ---------------------------------------------------


def test_write_derivative_does_not_rewrite_output_bytes_when_they_already_match(
    tmp_path: Path,
) -> None:
    """§36: "When generation produces bytes equal to the recorded output
    hash, no file is rewritten" -- checked here at the write layer directly,
    independent of the higher-level current-check that normally skips the
    call altogether."""
    output_bytes = b"fake png bytes"
    provenance = _provenance(output_hash=sha256_bytes(output_bytes))
    write_derivative(tmp_path, provenance.output_file, output_bytes, provenance)
    output_path = tmp_path / provenance.output_file
    mtime_before = output_path.stat().st_mtime_ns

    write_derivative(tmp_path, provenance.output_file, output_bytes, provenance)

    assert output_path.stat().st_mtime_ns == mtime_before
    assert output_path.read_bytes() == output_bytes


def test_write_derivative_does_not_rewrite_provenance_when_the_payload_already_matches(
    tmp_path: Path,
) -> None:
    """Issue #26 review fix round 1: the same idempotence applies to the
    provenance record itself, not just the output bytes -- this is what
    keeps ``generate --force`` on an unchanged derivative a true no-op on
    disk (AC5's "no file is rewritten (bytes and mtime unchanged)"),
    matching the write of the output bytes right above."""
    output_bytes = b"fake png bytes"
    provenance = _provenance(output_hash=sha256_bytes(output_bytes))
    write_derivative(tmp_path, provenance.output_file, output_bytes, provenance)
    record_path = provenance_path(tmp_path, provenance.output_file)
    mtime_before = record_path.stat().st_mtime_ns
    bytes_before = record_path.read_bytes()

    # A fresh call with an identical provenance record (as a real second,
    # unchanged generation, or a ``--force`` regeneration, would produce).
    write_derivative(tmp_path, provenance.output_file, output_bytes, provenance)

    assert record_path.stat().st_mtime_ns == mtime_before
    assert record_path.read_bytes() == bytes_before


def test_write_derivative_rewrites_provenance_when_the_payload_differs(tmp_path: Path) -> None:
    """A provenance record that differs -- even only in
    ``generator_versions``, e.g. a library upgrade -- is still written: the
    idempotence check compares the whole serialized payload, not just the
    hashes it is built from.

    Asserted through content, not mtime: on some filesystems two writes this
    close together can land in the same mtime tick, so an unchanged mtime
    would not reliably distinguish "rewritten with new content" from "write
    skipped" -- the content itself does that unambiguously.
    """
    output_bytes = b"fake png bytes"
    provenance = _provenance(output_hash=sha256_bytes(output_bytes))
    write_derivative(tmp_path, provenance.output_file, output_bytes, provenance)
    record_path = provenance_path(tmp_path, provenance.output_file)

    upgraded = replace(
        provenance, generator_versions={**provenance.generator_versions, "Pillow": "99.0.0"}
    )
    write_derivative(tmp_path, provenance.output_file, output_bytes, upgraded)

    assert json.loads(record_path.read_text(encoding="utf-8"))["generator_versions"]["Pillow"] == (
        "99.0.0"
    )


def test_write_derivative_creates_the_derived_directory(tmp_path: Path) -> None:
    provenance = _provenance()
    derived_dir = tmp_path / "derived"

    write_derivative(derived_dir, provenance.output_file, b"fake png bytes", provenance)

    assert (derived_dir / provenance.output_file).is_file()
    assert provenance_path(derived_dir, provenance.output_file).is_file()


def test_write_derivative_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    provenance = _provenance()

    write_derivative(tmp_path, provenance.output_file, b"fake png bytes", provenance)

    leftover = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftover == []


# --- read_source_bytes ------------------------------------------------------------


def test_read_source_bytes_reads_the_file_under_sources(tmp_path: Path) -> None:
    (tmp_path / SOURCES_DIRNAME).mkdir()
    (tmp_path / SOURCES_DIRNAME / "silhouette.png").write_bytes(b"fake source bytes")

    assert read_source_bytes(tmp_path, "silhouette.png") == b"fake source bytes"


# --- derivative_currency (ADR 0004, §36, issue #26) ---------------------------------


def _asset_dir_with_source(tmp_path: Path, source_bytes: bytes = b"source v1") -> Path:
    asset_dir = tmp_path / "ochre_sea_star"
    (asset_dir / SOURCES_DIRNAME).mkdir(parents=True)
    (asset_dir / SOURCES_DIRNAME / "silhouette.png").write_bytes(source_bytes)
    return asset_dir


def _generate_into(asset_dir: Path, source_bytes: bytes, recipe_hash: str) -> Provenance:
    """Simulate one generation: write an output derived from ``source_bytes``
    plus its provenance, the way ``pipeline.generate._generate_one`` does."""
    output_bytes = b"generated:" + source_bytes
    provenance = _provenance(
        source_hash=sha256_bytes(source_bytes),
        recipe_hash=recipe_hash,
        output_hash=sha256_bytes(output_bytes),
    )
    write_derivative(asset_dir / DERIVED_DIRNAME, provenance.output_file, output_bytes, provenance)
    return provenance


def test_derivative_currency_is_missing_when_no_provenance_exists(tmp_path: Path) -> None:
    asset_dir = _asset_dir_with_source(tmp_path)

    currency = derivative_currency(
        asset_dir, "ochre-sea-star-color.png", "silhouette.png", "r" * 64
    )

    assert currency.state is DerivativeState.MISSING
    assert currency.reason is None


def test_derivative_currency_is_current_right_after_generation(tmp_path: Path) -> None:
    asset_dir = _asset_dir_with_source(tmp_path)
    provenance = _generate_into(asset_dir, b"source v1", recipe_hash="r" * 64)

    currency = derivative_currency(asset_dir, provenance.output_file, "silhouette.png", "r" * 64)

    assert currency.state is DerivativeState.CURRENT
    assert currency.reason is None


def test_derivative_currency_is_stale_source_changed_when_the_source_file_changed(
    tmp_path: Path,
) -> None:
    """Issue #26 acceptance criterion 1: overwriting the source with
    different valid content marks the derivative built from it
    ``stale (source changed)``."""
    asset_dir = _asset_dir_with_source(tmp_path)
    provenance = _generate_into(asset_dir, b"source v1", recipe_hash="r" * 64)

    (asset_dir / SOURCES_DIRNAME / "silhouette.png").write_bytes(b"source v2")

    currency = derivative_currency(asset_dir, provenance.output_file, "silhouette.png", "r" * 64)

    assert currency.state is DerivativeState.STALE
    assert currency.reason == SOURCE_CHANGED


def test_derivative_currency_is_stale_recipe_changed_when_the_recipe_hash_changed(
    tmp_path: Path,
) -> None:
    """Issue #26 acceptance criterion 3: a recipe parameter change marks
    every derivative of that type ``stale (recipe changed)``."""
    asset_dir = _asset_dir_with_source(tmp_path)
    provenance = _generate_into(asset_dir, b"source v1", recipe_hash="r" * 64)

    currency = derivative_currency(asset_dir, provenance.output_file, "silhouette.png", "d" * 64)

    assert currency.state is DerivativeState.STALE
    assert currency.reason == RECIPE_CHANGED


def test_derivative_currency_is_missing_when_the_output_file_was_deleted(tmp_path: Path) -> None:
    """Issue #26 acceptance criterion 4, second half: a deleted derivative
    is ``missing``, not stale, even though its provenance record is still
    sitting beside it."""
    asset_dir = _asset_dir_with_source(tmp_path)
    provenance = _generate_into(asset_dir, b"source v1", recipe_hash="r" * 64)
    (asset_dir / DERIVED_DIRNAME / provenance.output_file).unlink()

    currency = derivative_currency(asset_dir, provenance.output_file, "silhouette.png", "r" * 64)

    assert currency.state is DerivativeState.MISSING
    assert currency.reason is None


def test_derivative_currency_is_stale_output_changed_on_disk_when_hand_edited(
    tmp_path: Path,
) -> None:
    """Issue #26 acceptance criterion 4, first half: a hand-edited output no
    longer matches its recorded hash, so it is
    ``stale (output changed on disk)`` -- it still exists, unlike a deleted
    one (it would need to be regenerated, or the edit tracked as an
    override in a later PRD)."""
    asset_dir = _asset_dir_with_source(tmp_path)
    provenance = _generate_into(asset_dir, b"source v1", recipe_hash="r" * 64)
    (asset_dir / DERIVED_DIRNAME / provenance.output_file).write_bytes(b"hand-edited bytes")

    currency = derivative_currency(asset_dir, provenance.output_file, "silhouette.png", "r" * 64)

    assert currency.state is DerivativeState.STALE
    assert currency.reason == OUTPUT_CHANGED_ON_DISK
