"""A nonexistent asset ID added to a collection's explicit list is a
reference problem visible from ``vpress collection``, ``vpress status`` and
``vpress attention``, and never changes either command's exit code --
resolving the rest of the collection still succeeds (§11, §34).
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PACIFIC_COAST_MEMBERS = ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin")


def _add_nonexistent_member(root: Path) -> None:
    path = root / "collections" / "pacific_coast_tide_pool.toml"
    text = path.read_text(encoding="utf-8").replace(
        '"purple_sea_urchin"]', '"purple_sea_urchin", "not_a_real_asset"]'
    )
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    _add_nonexistent_member(root)
    return root


@pytest.mark.integration
def test_collection_still_lists_the_three_real_members(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])

    assert result.exit_code == 0, result.output
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"{asset_id}\texplicit" in result.stdout
    assert "Members: 3" in result.stdout


@pytest.mark.integration
def test_collection_names_the_file_field_and_unknown_id(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])

    assert result.exit_code == 0, result.output
    assert "Reference problems: 1" in result.stdout
    assert str(Path("collections") / "pacific_coast_tide_pool.toml") in result.stdout
    assert "membership.asset_ids" in result.stdout
    assert "not_a_real_asset" in result.stdout


@pytest.mark.integration
def test_status_shows_the_reference_problem_without_changing_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The reference problem is printed under its own "Reference problems"
    count, separate from "Metadata problems": only the metadata count is
    non-zero-checked for the exit code, and it stays at zero here."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "Metadata problems: none" in result.stdout
    assert "Reference problems: 1" in result.stdout
    assert "membership.asset_ids" in result.stdout
    assert "not_a_real_asset" in result.stdout


@pytest.mark.integration
def test_attention_shows_the_reference_problem_without_changing_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert "membership.asset_ids" in result.stdout
    assert "not_a_real_asset" in result.stdout


@pytest.mark.integration
def test_attention_json_carries_the_reference_problem_in_missing_metadata(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    problems = [p for p in payload["missing_metadata"] if p["field"] == "membership.asset_ids"]
    assert len(problems) == 1
    assert "not_a_real_asset" in problems[0]["message"]
    assert problems[0]["path"] == "collections/pacific_coast_tide_pool.toml"


@pytest.mark.integration
def test_status_exit_code_is_unaffected_by_a_reference_problem_on_the_clean_fixture(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Confirms the reference problem alone -- with no other metadata
    problem present -- still exits 0, not just "exit code happens to stay
    the same as some other failure"."""
    monkeypatch.chdir(temp_catalog_root)

    clean_result = runner.invoke(app, ["--catalog", str(FIXTURE_CATALOG_ROOT), "status"])
    broken_result = runner.invoke(app, ["status"])

    assert clean_result.exit_code == 0
    assert broken_result.exit_code == 0
    assert clean_result.exit_code == broken_result.exit_code
