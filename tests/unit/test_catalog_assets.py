"""catalog.assets: load every asset.toml under a catalog's assets directory."""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.asset import AccuracyStatus, RightsStatus

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _asset_toml(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / "asset.toml"


def test_fixture_catalog_loads_three_valid_assets() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    assert [asset.id for asset in inventory.assets] == [
        "giant_green_anemone",
        "ochre_sea_star",
        "purple_sea_urchin",
    ]
    assert inventory.problems == []


def test_assets_are_sorted_by_id() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    ids = [asset.id for asset in inventory.assets]
    assert ids == sorted(ids)


def test_loaded_asset_carries_rights_and_accuracy_status() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    ochre = next(a for a in inventory.assets if a.id == "ochre_sea_star")
    assert ochre.display_name == "Ochre Sea Star"
    assert ochre.rights_status is RightsStatus.ORIGINAL_ARTWORK
    assert ochre.accuracy_status is AccuracyStatus.APPROVED


def test_sources_list_passes_through_untouched() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    anemone = next(a for a in inventory.assets if a.id == "giant_green_anemone")
    assert anemone.sources == [{"role": "silhouette", "file": "sources/silhouette.png"}]


def test_missing_required_field_is_a_problem_and_other_assets_still_load(
    catalog_copy: Path,
) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    text = path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', "")
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    loaded_ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" in loaded_ids
    assert "giant_green_anemone" in loaded_ids
    assert "ochre_sea_star" not in loaded_ids
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "ochre_sea_star" in str(problem.path)
    assert problem.field == "subject_category"


def test_unknown_key_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    path.write_text(path.read_text(encoding="utf-8") + "\nnot_a_field = true\n", encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert "ochre_sea_star" in ids
    assert "giant_green_anemone" in ids
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "purple_sea_urchin" in str(problem.path)
    assert problem.field == "not_a_field"


def test_rights_status_outside_the_list_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    text = path.read_text(encoding="utf-8").replace(
        'rights_status = "rights_verified"', 'rights_status = "not_a_real_status"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "rights_status"


def test_accuracy_status_outside_the_list_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "giant_green_anemone")
    text = path.read_text(encoding="utf-8").replace(
        'accuracy_status = "not_reviewed"', 'accuracy_status = "not_a_real_status"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "giant_green_anemone" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "accuracy_status"


def test_id_differing_from_folder_name_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    path.write_text(
        'id = "not_the_folder_name"\n' + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "ochre_sea_star" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "id"
    assert "ochre_sea_star" in str(inventory.problems[0].path)


def test_id_matching_folder_name_is_accepted(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    path.write_text('id = "ochre_sea_star"\n' + path.read_text(encoding="utf-8"), encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    assert inventory.problems == []
    assert "ochre_sea_star" in {asset.id for asset in inventory.assets}


def test_toml_syntax_error_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    path.write_text('common_name = "unterminated\n', encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert "purple_sea_urchin" in str(inventory.problems[0].path)


def test_committed_fixture_catalog_is_unmodified_by_mutating_tests() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    assert len(inventory.assets) == 3
    assert inventory.problems == []
