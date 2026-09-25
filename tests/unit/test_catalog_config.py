"""Domain-layer tests for CatalogConfig: pure validation, no I/O."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.catalog_config import (
    BUILTIN_SOURCE_ROLES,
    CatalogConfig,
)


def test_only_name_required_takes_documented_defaults() -> None:
    config = CatalogConfig.model_validate({"name": "Tide Pool Studio"})

    assert config.name == "Tide Pool Studio"
    assert config.assets_dir == "assets"
    assert config.collections_dir == "collections"
    assert config.products_dir == "products"
    assert config.reference_size_in == 3.0
    assert config.extra_roles == []


def test_directory_names_and_reference_size_can_be_overridden() -> None:
    config = CatalogConfig.model_validate(
        {
            "name": "Tide Pool Studio",
            "assets_dir": "subjects",
            "collections_dir": "sets",
            "products_dir": "packs",
            "reference_size_in": 4.5,
        }
    )

    assert config.assets_dir == "subjects"
    assert config.collections_dir == "sets"
    assert config.products_dir == "packs"
    assert config.reference_size_in == 4.5


def test_extra_roles_extend_the_builtin_roles() -> None:
    config = CatalogConfig.model_validate(
        {"name": "Tide Pool Studio", "extra_roles": ["watercolor"]}
    )

    assert config.source_roles == (*BUILTIN_SOURCE_ROLES, "watercolor")


def test_missing_name_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("name",) for error in errors)


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "not_a_field": True})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("not_a_field",) for error in errors)


def test_wrongly_typed_reference_size_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "reference_size_in": "big"})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("reference_size_in",) for error in errors)


def test_wrongly_typed_assets_dir_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "assets_dir": 123})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("assets_dir",) for error in errors)


# --- editor: unset by default, a program plus optional arguments --------------------


def test_editor_defaults_to_unset() -> None:
    config = CatalogConfig.model_validate({"name": "Tide Pool Studio"})

    assert config.editor is None


def test_editor_can_be_a_program_plus_arguments() -> None:
    config = CatalogConfig.model_validate(
        {"name": "Tide Pool Studio", "editor": ["myeditor", "--flag"]}
    )

    assert config.editor == ["myeditor", "--flag"]


def test_editor_as_a_bare_string_instead_of_a_list_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "editor": "myeditor"})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("editor",) for error in errors)


def test_editor_as_an_empty_list_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "editor": []})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("editor",) for error in errors)


def test_editor_with_a_blank_entry_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CatalogConfig.model_validate({"name": "Tide Pool Studio", "editor": ["myeditor", ""]})

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("editor",) for error in errors)
