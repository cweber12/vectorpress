"""``vpress generate`` end to end against a temporary copy of the fixture
catalog (§6.1, §20, §35, §36, issue #23).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under each asset's ``derived/``, and the fixture
catalog must never contain one (``tests/fixtures/catalog/README.md``).
"""

import shutil
from pathlib import Path

import pytest
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

    # silhouette_svg has a recipe but no generator yet this slice (issue #22, #23).
    assert "ochre_sea_star\tsilhouette_svg\tno generator\t" in result.stdout
    # flatcolor_svg is impossible for every fixture asset (none has a flatcolor source).
    assert "ochre_sea_star\tflatcolor_svg\timpossible\t" in result.stdout


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
def test_second_generate_all_reports_current_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 3: a second ``generate --all`` reports every
    ``transparent_png`` as ``current``, and no file under any ``derived/``
    changes bytes or mtime (§36)."""
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
    # Each of the three fixture assets' transparent_png moves from missing to
    # current; silhouette_svg (no generator yet) and flatcolor_svg
    # (impossible) are unaffected.
    assert "Missing derivatives: 3" in after.stdout
