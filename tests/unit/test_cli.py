from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress import __version__
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_status_from_the_catalog_root_prints_name_and_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Tide Pool Studio" in result.stdout
    assert str(FIXTURE_CATALOG_ROOT.resolve()) in result.stdout


def test_status_from_a_subdirectory_walks_up_to_the_catalog_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "catalog"
    subdir = root / "assets" / "ochre_sea_star"
    subdir.mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Tide Pool Studio"\n', encoding="utf-8")
    monkeypatch.chdir(subdir)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Tide Pool Studio" in result.stdout


def test_status_with_catalog_flag_works_from_any_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(FIXTURE_CATALOG_ROOT), "status"])

    assert result.exit_code == 0
    assert "Tide Pool Studio" in result.stdout


def test_status_outside_any_catalog_names_directories_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code != 0
    assert str(tmp_path.resolve()) in result.output


def test_status_with_malformed_catalog_names_file_and_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "catalog.toml").write_text(
        'name = "Broken"\nreference_size_in = "big"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code != 0
    assert str((tmp_path / "catalog.toml").resolve()) in result.output
    assert "reference_size_in" in result.output


def test_status_reports_the_asset_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "3" in result.stdout


def test_assets_lists_the_fixture_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["assets"])

    assert result.exit_code == 0
    for asset_id, display_name, rights, accuracy in [
        ("ochre_sea_star", "Ochre Sea Star", "original_artwork", "approved"),
        ("purple_sea_urchin", "Purple Sea Urchin", "rights_verified", "reviewed"),
        ("giant_green_anemone", "Giant Green Anemone", "public_domain_source", "not_reviewed"),
    ]:
        assert asset_id in result.stdout
        assert display_name in result.stdout
        assert rights in result.stdout
        assert accuracy in result.stdout


def test_assets_are_sorted_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["assets"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    ids = [line.split()[0] for line in lines]
    assert ids == sorted(ids)
