"""catalog.load: read and validate catalog.toml at a catalog root, and the
single load entry point (``load_catalog``) that aggregates metadata
problems from every hand-authored file (issue #6).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.errors import CatalogConfigError
from vectorpress.catalog.load import load_catalog, load_catalog_config

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def _write_catalog_toml(root: Path, text: str) -> Path:
    root.mkdir(exist_ok=True)
    path = root / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def test_load_valid_config(tmp_path: Path) -> None:
    _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\n')

    config = load_catalog_config(tmp_path)

    assert config.name == "Tide Pool Studio"
    assert config.assets_dir == "assets"
    assert config.reference_size_in == 3.0


def test_toml_syntax_error_names_file(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "unterminated\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    assert str(path) in str(exc_info.value)


def test_unknown_key_names_file_and_field(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\nnot_a_field = true\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "not_a_field" in message


def test_wrongly_typed_value_names_file_and_field(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\nreference_size_in = "big"\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "reference_size_in" in message


# --- load_catalog: the single load entry point (issue #6) -------------------------


def test_load_catalog_on_the_clean_fixture_has_no_problems() -> None:
    catalog = load_catalog(FIXTURE_CATALOG_ROOT)

    assert catalog.config is not None
    assert catalog.config.name == "Tide Pool Studio"
    assert [asset.id for asset in catalog.assets] == [
        "giant_green_anemone",
        "ochre_sea_star",
        "purple_sea_urchin",
    ]
    assert catalog.problems == []


def test_load_catalog_with_a_broken_catalog_toml_is_a_problem_not_a_raise(
    tmp_path: Path,
) -> None:
    root = tmp_path / "catalog"
    _write_catalog_toml(root, 'name = "Broken"\nreference_size_in = "big"\n')

    catalog = load_catalog(root)

    assert catalog.config is None
    assert catalog.assets == []
    assert len(catalog.problems) == 1
    problem = catalog.problems[0]
    assert problem.path == Path("catalog.toml")
    assert "reference_size_in" in problem.message


def test_load_catalog_aggregates_asset_problems_and_keeps_the_valid_assets(
    catalog_copy: Path,
) -> None:
    path = catalog_copy / "assets" / "ochre_sea_star" / "asset.toml"
    text = path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', "")
    path.write_text(text, encoding="utf-8")

    catalog = load_catalog(catalog_copy)

    loaded_ids = {asset.id for asset in catalog.assets}
    assert loaded_ids == {"giant_green_anemone", "purple_sea_urchin"}
    assert len(catalog.problems) == 1
    assert "ochre_sea_star" in str(catalog.problems[0].path)
    assert catalog.problems[0].field == "subject_category"


def test_load_catalog_root_is_the_catalog_root_passed_in() -> None:
    catalog = load_catalog(FIXTURE_CATALOG_ROOT)

    assert catalog.root == FIXTURE_CATALOG_ROOT
