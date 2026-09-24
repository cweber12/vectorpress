"""``vpress generate`` end to end against a temporary copy of the fixture
catalog (§6.1, §6.2, §8, §20, §35, §36, issue #23, issue #24).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under each asset's ``derived/``, and the fixture
catalog must never contain one (``tests/fixtures/catalog/README.md``).
"""

import shutil
from pathlib import Path

import pytest
from PIL import Image
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.image import PNGImageSnapshotExtension
from typer.testing import CliRunner

from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance, sha256_bytes
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# (asset ID, expected customer-facing filename): §20's slugified display name
# plus transparent_png's ``-color.png`` suffix.
FIXTURE_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-color.png"),
    ("purple_sea_urchin", "purple-sea-urchin-color.png"),
    ("giant_green_anemone", "giant-green-anemone-color.png"),
]

# (asset ID, expected customer-facing filename): §20's slugified display name
# plus silhouette_svg's ``-silhouette.svg`` suffix (issue #24). ochre_sea_star
# is the blob (one subpath), purple_sea_urchin the ring (a hole), and
# giant_green_anemone the blob with a detached island (two disjoint
# subpaths) -- see ``tests/fixtures/catalog/generate_source_pngs.py``.
FIXTURE_SILHOUETTE_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-silhouette.svg"),
    ("purple_sea_urchin", "purple-sea-urchin-silhouette.svg"),
    ("giant_green_anemone", "giant-green-anemone-silhouette.svg"),
]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


@pytest.mark.integration
def test_generate_all_writes_every_transparent_png_with_provenance(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``generate --all`` on a temp copy of the
    fixture writes each asset's ``<slug>-color.png`` under its ``derived/``,
    each with a provenance record beside it, one report line per
    derivative."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    for asset_id, filename in FIXTURE_OUTPUTS:
        assert f"{asset_id}\ttransparent_png\tgenerated\t{filename}" in result.stdout

        derived_dir = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME
        output_path = derived_dir / filename
        assert output_path.is_file()

        provenance = read_provenance(derived_dir, filename)
        assert provenance is not None
        assert provenance.output_file == filename
        assert provenance.output_hash == sha256_bytes(output_path.read_bytes())

    # flatcolor_svg is impossible for every fixture asset (none has a flatcolor source).
    assert "ochre_sea_star\tflatcolor_svg\timpossible\t" in result.stdout


@pytest.mark.integration
def test_generate_all_writes_every_silhouette_svg_with_provenance(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``generate --all`` on a temp copy of the
    fixture writes each asset's ``<slug>-silhouette.svg`` under its
    ``derived/``, each with a provenance record beside it; ``vpress asset``
    then shows it ``current`` (issue #24). ``generate`` no longer reports
    ``no generator`` for ``silhouette_svg``."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    assert "no generator" not in result.stdout
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout

        derived_dir = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME
        output_path = derived_dir / filename
        assert output_path.is_file()

        provenance = read_provenance(derived_dir, filename)
        assert provenance is not None
        assert provenance.output_file == filename
        assert provenance.generator == "silhouette_svg"
        assert provenance.output_hash == sha256_bytes(output_path.read_bytes())

        asset_result = runner.invoke(app, ["asset", asset_id])
        assert asset_result.exit_code == 0, asset_result.output
        assert f"silhouette_svg\tcurrent\t{filename}" in asset_result.stdout


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_OUTPUTS)
def test_transparent_png_bytes_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    """Acceptance criterion 2: each PNG is 8-bit RGBA, cropped to its
    content, transparent outside the shape -- locked byte-for-byte so the
    generator (or a Pillow upgrade) cannot silently change output without a
    reviewed snapshot diff. Identical on ubuntu and windows (§36): the
    generator resamples nothing and writes no ancillary chunks."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", asset_id])
    assert result.exit_code == 0, result.output

    output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
    assert output_path.read_bytes() == snapshot(extension_class=PNGImageSnapshotExtension)


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_SILHOUETTE_OUTPUTS)
def test_silhouette_svg_text_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    """Acceptance criterion 3: the blob (one subpath), the ring (an outer
    subpath and a hole), and the blob with a detached island (two disjoint
    subpaths) are each locked byte-for-byte as text, so the tracer (or a
    library upgrade) cannot silently change output without a reviewed
    snapshot diff. Identical on ubuntu and windows (§36): potracer is pure
    Python and ``svg_document``'s fixed-precision number formatting absorbs
    any last-bit libm difference between platforms before it reaches text."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", asset_id])
    assert result.exit_code == 0, result.output

    output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
    assert output_path.read_text(encoding="utf-8") == snapshot


@pytest.mark.integration
def test_second_generate_all_reports_current_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 3 (issue #23) and acceptance criterion 4 (issue
    #24): a second ``generate --all`` reports every ``transparent_png`` and
    every ``silhouette_svg`` as ``current``, and no file under any
    ``derived/`` changes bytes or mtime (§36) -- the silhouette SVG is
    idempotent too."""
    monkeypatch.chdir(temp_catalog_root)
    first = runner.invoke(app, ["generate", "--all"])
    assert first.exit_code == 0, first.output

    before: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.iterdir()):
            before[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert before, "generate --all should have written files to compare"

    second = runner.invoke(app, ["generate", "--all"])

    assert second.exit_code == 0, second.output
    for asset_id, filename in FIXTURE_OUTPUTS:
        assert f"{asset_id}\ttransparent_png\tcurrent\t{filename}" in second.stdout
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        assert f"{asset_id}\tsilhouette_svg\tcurrent\t{filename}" in second.stdout

    after: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.iterdir()):
            after[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert after == before


@pytest.mark.integration
def test_vpress_asset_shows_current_after_generation(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 6, first half: ``vpress asset <id>`` shows the
    generated derivative as ``current`` with its filename."""
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert generate_result.exit_code == 0, generate_result.output

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert "transparent_png\tcurrent\tochre-sea-star-color.png" in result.stdout


@pytest.mark.integration
def test_generate_all_skips_and_names_an_asset_that_failed_to_load(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The issue's "assets that failed to load are skipped and named": one
    asset's ``asset.toml`` is broken (a missing required field), so it never
    loads at all; ``generate --all`` still generates for the other two,
    names the broken one as skipped, and exits 0 -- a broken asset is a
    ``vpress status`` metadata problem, not a ``generate`` failure (§35: a
    failure involving one asset does not stop the rest)."""
    broken_toml = temp_catalog_root / "assets" / "ochre_sea_star" / "asset.toml"
    broken_toml.write_text(
        broken_toml.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tskipped: failed to load" in result.stdout
    # the broken asset generated nothing
    assert not (temp_catalog_root / "assets" / "ochre_sea_star" / "derived").exists()

    # the other two assets still generated
    for asset_id, filename in FIXTURE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\ttransparent_png\tgenerated\t{filename}" in result.stdout
        output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
        assert output_path.is_file()
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout
        output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
        assert output_path.is_file()


@pytest.mark.integration
def test_vpress_status_missing_count_drops_after_generation(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 6, second half: the ``vpress status`` missing
    count drops once a derivative becomes current."""
    monkeypatch.chdir(temp_catalog_root)
    before = runner.invoke(app, ["status"])
    assert before.exit_code == 0, before.output
    assert "Missing derivatives: 6" in before.stdout

    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 0, generate_result.output

    after = runner.invoke(app, ["status"])

    assert after.exit_code == 0, after.output
    # Each of the three fixture assets' transparent_png and silhouette_svg
    # move from missing to current (issue #24); flatcolor_svg stays
    # impossible for all three (counted separately, not as missing).
    assert "Missing derivatives: 0" in after.stdout


@pytest.mark.integration
def test_generate_all_reports_failed_for_a_fully_transparent_silhouette_and_continues(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #24 review fix round 1, controller ruling: a silhouette source
    with no ink at all leaves ``silhouette_svg`` with nothing to trace, so
    its generator raises. ``generate --all`` catches that per derivative,
    reports it ``failed`` with a reason, writes nothing for it, still
    generates every other derivative for every asset (including
    ``transparent_png`` for the same asset, and everything for the other
    two), and exits non-zero overall."""
    silhouette_path = temp_catalog_root / "assets" / "ochre_sea_star" / "sources" / "silhouette.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(silhouette_path, format="PNG")
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output
    assert "ochre_sea_star\tsilhouette_svg\tfailed\t" in result.stdout
    failed_line = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("ochre_sea_star\t") and "\tfailed\t" in line
    )
    assert failed_line.split("\t", 3)[3]  # a non-empty reason

    derived_dir = temp_catalog_root / "assets" / "ochre_sea_star" / DERIVED_DIRNAME
    assert not derived_dir.exists() or not any(derived_dir.glob("*silhouette*"))

    # the same asset's other derivative still generated.
    assert "ochre_sea_star\ttransparent_png\tgenerated\tochre-sea-star-color.png" in result.stdout
    output_path = derived_dir / "ochre-sea-star-color.png"
    assert output_path.is_file()

    # the other two assets, untouched by the broken source, generated everything.
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout
