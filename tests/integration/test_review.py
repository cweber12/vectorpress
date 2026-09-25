"""``vpress approve`` and the status tracer end to end, against a temporary
copy of the fixture catalog (§10, §22.1, ADR 0004).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under each asset's ``derived/``, and the fixture
catalog must never contain one (``tests/fixtures/catalog/README.md``).
"""

import json
import shutil
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.catalog.status import read_status, state_path
from vectorpress.cli.app import app
from vectorpress.domain import recipe as recipe_module
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import Recipe

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _derived_dir(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


# --- acceptance criterion 1: new derivatives enter needs_review ---------------------


@pytest.mark.integration
def test_generate_all_leaves_every_existing_derivative_needs_review(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)

    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert asset_result.exit_code == 0, asset_result.output
    for line in asset_result.stdout.splitlines():
        if line.startswith("  ") and "current" in line:
            assert "needs review" in line, line

    assert state_path(_derived_dir(temp_catalog_root, "ochre_sea_star")).is_file()
    assert state_path(_derived_dir(temp_catalog_root, "purple_sea_urchin")).is_file()
    assert state_path(_derived_dir(temp_catalog_root, "giant_green_anemone")).is_file()


# --- acceptance criterion 2: approve with a note, idempotent ------------------------


@pytest.mark.integration
def test_approve_with_a_note_shows_approved_and_the_note(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])

    approve_result = runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg", "--note", "clean"])
    assert approve_result.exit_code == 0, approve_result.output
    assert "approved" in approve_result.stdout

    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert asset_result.exit_code == 0, asset_result.output
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "approved" in cut_svg_line
    assert "clean" in cut_svg_line


@pytest.mark.integration
def test_a_second_identical_approve_rewrites_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])
    runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg", "--note", "clean"])
    state_file = state_path(_derived_dir(temp_catalog_root, "ochre_sea_star"))
    mtime_before = state_file.stat().st_mtime_ns
    bytes_before = state_file.read_bytes()

    second = runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg", "--note", "clean"])

    assert second.exit_code == 0, second.output
    assert state_file.stat().st_mtime_ns == mtime_before
    assert state_file.read_bytes() == bytes_before


# --- acceptance criterion 3: regeneration rules (§22.1) ------------------------------


@pytest.mark.integration
def test_force_regenerate_with_unchanged_output_keeps_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])
    runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg", "--note", "clean"])

    forced = runner.invoke(app, ["generate", "--force", "ochre_sea_star"])
    assert forced.exit_code == 0, forced.output

    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "approved" in cut_svg_line
    assert "clean" in cut_svg_line


@pytest.mark.integration
def test_a_recipe_change_that_alters_the_output_returns_an_approved_derivative_to_needs_review(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])
    runner.invoke(app, ["approve", "ochre_sea_star", "silhouette_svg"])

    original = recipe_module.RECIPES[DerivativeType.SILHOUETTE_SVG]
    changed = Recipe(
        derivative_type=original.derivative_type,
        accepted_roles=original.accepted_roles,
        generator=original.generator,
        parameters={**original.parameters, "curve_tolerance": 0.8},
    )
    monkeypatch.setitem(recipe_module.RECIPES, DerivativeType.SILHOUETTE_SVG, changed)

    regenerated = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert regenerated.exit_code == 0, regenerated.output

    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    silhouette_line = next(
        line
        for line in asset_result.stdout.splitlines()
        if line.strip().startswith("silhouette_svg")
    )
    assert "needs review" in silhouette_line


# --- acceptance criterion 4: status follows the bytes --------------------------------


@pytest.mark.integration
def test_hand_editing_an_approved_derivative_reports_needs_review(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])
    runner.invoke(app, ["approve", "ochre_sea_star", "transparent_png"])

    output_path = _derived_dir(temp_catalog_root, "ochre_sea_star") / "ochre-sea-star-color.png"
    output_path.write_bytes(b"hand-edited, not a real PNG anymore")

    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert asset_result.exit_code == 0, asset_result.output
    png_line = next(
        line
        for line in asset_result.stdout.splitlines()
        if line.strip().startswith("transparent_png")
    )
    assert "needs review" in png_line
    assert "approved" not in png_line


# --- acceptance criterion 6: approve errors ------------------------------------------


@pytest.mark.integration
def test_approving_a_missing_derivative_is_an_error_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)  # nothing generated yet

    result = runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg"])

    assert result.exit_code == 1, result.output
    assert not _derived_dir(temp_catalog_root, "ochre_sea_star").exists()


@pytest.mark.integration
def test_approving_an_impossible_derivative_is_an_error_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "purple_sea_urchin"])  # no flatcolor source
    derived_dir = _derived_dir(temp_catalog_root, "purple_sea_urchin")
    bytes_before = state_path(derived_dir).read_bytes()

    result = runner.invoke(app, ["approve", "purple_sea_urchin", "flatcolor_svg"])

    assert result.exit_code == 1, result.output
    assert state_path(derived_dir).read_bytes() == bytes_before
    assert read_status(derived_dir, DerivativeType.FLATCOLOR_SVG) is None


@pytest.mark.integration
def test_approving_an_unknown_derivative_type_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])

    result = runner.invoke(app, ["approve", "ochre_sea_star", "not_a_real_type"])

    assert result.exit_code == 1, result.output
    assert "Unknown derivative type" in result.output


@pytest.mark.integration
def test_approving_an_unknown_asset_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["approve", "not_a_real_asset", "cut_svg"])

    assert result.exit_code == 1, result.output


# --- acceptance criterion 7: _state.json shape locked by snapshot -------------------


@pytest.mark.integration
def test_state_json_shape_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])
    approve_result = runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg", "--note", "clean"])
    assert approve_result.exit_code == 0, approve_result.output

    path = state_path(_derived_dir(temp_catalog_root, "ochre_sea_star"))
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot


# --- vpress status: counts by status --------------------------------------------------


@pytest.mark.integration
def test_vpress_status_counts_derivatives_by_status(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])

    before = runner.invoke(app, ["status"])
    assert before.exit_code == 0, before.output
    # every recipe-bearing type generated for ochre_sea_star (transparent_png,
    # silhouette_svg, cut_svg, flatcolor_svg) starts needs_review.
    assert "Needs review: 4" in before.stdout
    assert "Approved: 0" in before.stdout

    runner.invoke(app, ["approve", "ochre_sea_star", "cut_svg"])

    after = runner.invoke(app, ["status"])
    assert after.exit_code == 0, after.output
    assert "Needs review: 3" in after.stdout
    assert "Approved: 1" in after.stdout
