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
    assert result.brand.license_file == "license_template.txt"


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


def test_missing_license_file_field_names_file_and_field(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace('license_file = "license_template.txt"\n', "")
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "license_file"


def test_license_path_that_does_not_exist_names_file_and_field(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'license_file = "license_template.txt"',
        'license_file = "does_not_exist.txt"',
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "license_file"
    assert "does_not_exist.txt" in problem.message


# --- typography (§27, ADR 0014): "a font never silently falls back" -------


def test_heading_font_the_tool_does_not_ship_with_no_font_file_is_a_problem(
    catalog_copy: Path,
) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'heading_font = "Space Grotesk"', 'heading_font = "Comic Sans MS"'
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "typography.heading_font"
    assert "Comic Sans MS" in problem.message


def test_body_font_the_tool_does_not_ship_with_no_font_file_is_a_problem(
    catalog_copy: Path,
) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace('body_font = "Inter"', 'body_font = "Papyrus"')
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "typography.body_font"
    assert "Papyrus" in problem.message


def test_font_file_that_does_not_exist_is_a_problem(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    text = path.read_text(encoding="utf-8").replace(
        'heading_font = "Space Grotesk"',
        'heading_font = "Custom Display"\nheading_font_file = "fonts/does_not_exist.woff2"',
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "typography.heading_font_file"
    assert "does_not_exist.woff2" in problem.message


def test_font_file_with_the_wrong_extension_is_a_problem(catalog_copy: Path) -> None:
    path = catalog_copy / "brand.toml"
    bad_font_path = catalog_copy / "fonts" / "custom.txt"
    bad_font_path.parent.mkdir(parents=True, exist_ok=True)
    bad_font_path.write_text("not a font", encoding="utf-8")
    text = path.read_text(encoding="utf-8").replace(
        'body_font = "Inter"',
        'body_font = "Custom Body"\nbody_font_file = "fonts/custom.txt"',
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.brand is None
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.path == Path("brand.toml")
    assert problem.field == "typography.body_font_file"
    assert "custom.txt" in problem.message


@pytest.mark.parametrize("extension", ["ttf", "otf", "woff2"])
def test_a_valid_catalog_font_file_loads_with_any_family_name(
    catalog_copy: Path, extension: str
) -> None:
    """Naming a font file lifts the shipped-family restriction entirely
    (ADR 0014): any family name is fine once a real file backs it."""
    path = catalog_copy / "brand.toml"
    font_path = catalog_copy / "fonts" / f"custom.{extension}"
    font_path.parent.mkdir(parents=True, exist_ok=True)
    font_path.write_bytes(b"FAKEFONTBYTES")
    text = path.read_text(encoding="utf-8").replace(
        'heading_font = "Space Grotesk"',
        f'heading_font = "Custom Display"\nheading_font_file = "fonts/custom.{extension}"',
    )
    path.write_text(text, encoding="utf-8")

    result = load_brand(catalog_copy)

    assert result.problems == []
    assert result.brand is not None
    assert result.brand.typography.heading_font_file == f"fonts/custom.{extension}"
