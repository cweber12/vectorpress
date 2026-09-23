"""catalog.locate: find the catalog root from cwd or an explicit --catalog path."""

from pathlib import Path

import pytest

from vectorpress.catalog.errors import CatalogNotFoundError
from vectorpress.catalog.locate import locate_catalog_root


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "catalog.toml").write_text('name = "Fixture"\n', encoding="utf-8")
    return root


def test_locate_from_cwd_at_the_root_itself(catalog_root: Path) -> None:
    assert locate_catalog_root(catalog_root) == catalog_root


def test_locate_from_cwd_walks_up_from_a_subdirectory(catalog_root: Path) -> None:
    nested = catalog_root / "assets" / "ochre_sea_star"
    nested.mkdir(parents=True)

    assert locate_catalog_root(nested) == catalog_root


def test_locate_from_explicit_flag_ignores_cwd(catalog_root: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert locate_catalog_root(elsewhere, explicit=catalog_root) == catalog_root


def test_locate_not_found_names_directories_searched(tmp_path: Path) -> None:
    empty = tmp_path / "not_a_catalog"
    empty.mkdir()

    with pytest.raises(CatalogNotFoundError) as exc_info:
        locate_catalog_root(empty)

    assert empty.resolve() in exc_info.value.searched
    assert str(empty.resolve()) in str(exc_info.value)


def test_locate_not_found_with_explicit_flag_names_that_directory(tmp_path: Path) -> None:
    empty = tmp_path / "not_a_catalog"
    empty.mkdir()

    with pytest.raises(CatalogNotFoundError) as exc_info:
        locate_catalog_root(tmp_path, explicit=empty)

    assert exc_info.value.searched == [empty.resolve()]
