"""catalog.brand: load and validate a catalog root's brand.toml (§27, issue #3)."""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.brand import load_brand

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def test_fixture_catalog_loads_a_valid_brand() -> None:
    result = load_brand(FIXTURE_CATALOG_ROOT)

    assert result.problems == []
    assert result.brand is not None
    assert result.brand.name == "Tide Pool Studio"
    assert result.brand.mark_file == "mark.png"


def test_missing_brand_toml_is_a_problem_not_a_raise(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()

    result = load_brand(root)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field is None
    assert "not found" in problem.message


def test_toml_syntax_error_names_file(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "brand.toml").write_text('name = "unterminated\n', encoding="utf-8")

    result = load_brand(root)

    assert result.brand is None
    assert len(result.problems) == 1
    assert result.problems[0].path == Path("brand.toml")


def test_unknown_key_names_file_and_field(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'mark_file = "mark.png"', 'mark_file = "mark.png"\nnot_a_field = true'
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "not_a_field"


def test_missing_required_field_names_file_and_field(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'license_name = "Tide Pool Studio Personal & Small Business Use License"\n', ""
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "license_name"


def test_mark_path_that_does_not_exist_names_file_and_field(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'mark_file = "mark.png"', 'mark_file = "does_not_exist.png"'
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "mark_file"
    assert "does_not_exist.png" in problem.message
