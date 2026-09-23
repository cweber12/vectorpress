"""catalog.load: read and validate catalog.toml at a catalog root."""

from pathlib import Path

import pytest

from vectorpress.catalog.errors import CatalogConfigError
from vectorpress.catalog.load import load_catalog_config


def _write_catalog_toml(root: Path, text: str) -> Path:
    root.mkdir(exist_ok=True)
    path = root / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


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
