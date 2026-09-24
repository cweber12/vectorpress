"""catalog.provenance: tool-owned provenance records (ADR 0004, issue #23)."""

import json
from pathlib import Path

from vectorpress.catalog.provenance import (
    Provenance,
    provenance_path,
    read_provenance,
    recipe_identity_hash,
    sha256_bytes,
    write_derivative,
)
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import Recipe


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
