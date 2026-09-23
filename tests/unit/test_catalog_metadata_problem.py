"""catalog.metadata_problem: turn a pydantic ``ValidationError`` into
``MetadataProblem``s (issue #2, issue #16).
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from vectorpress.catalog.metadata_problem import problems_from_validation_error
from vectorpress.domain.metadata_field_error import MetadataFieldError

PATH = Path("products/example.toml")


class _FieldLevel(BaseModel):
    """A model with a per-field check, so pydantic's own ``loc`` already
    names the field — the case that already worked before issue #16.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str

    @field_validator("name")
    @classmethod
    def _not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("name must not be blank")
        return name


class _CrossFieldPlain(BaseModel):
    """A model-level check that raises a plain ``ValueError`` — no field
    attribution beyond what pydantic gives it (an empty ``loc``).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    a: str | None = None
    b: str | None = None

    @model_validator(mode="after")
    def _one_of_a_or_b(self) -> "_CrossFieldPlain":
        if (self.a is None) == (self.b is None):
            raise ValueError("exactly one of a or b is required")
        return self


class _CrossFieldAttributed(BaseModel):
    """A model-level check that raises ``MetadataFieldError`` to attribute
    the problem to the fields it concerns.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    a: str | None = None
    b: str | None = None

    @model_validator(mode="after")
    def _one_of_a_or_b(self) -> "_CrossFieldAttributed":
        if (self.a is None) == (self.b is None):
            raise MetadataFieldError("a/b", "exactly one of a or b is required")
        return self


def _validation_error(model: type[BaseModel], data: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(data)
    return exc_info.value


def test_field_level_error_keeps_its_field_and_loses_the_value_error_prefix() -> None:
    exc = _validation_error(_FieldLevel, {"name": "  "})

    problems = problems_from_validation_error(PATH, exc)

    assert len(problems) == 1
    assert problems[0].field == "name"
    assert problems[0].message == "name must not be blank"


def test_cross_field_plain_value_error_loses_the_value_error_prefix_but_has_no_field() -> None:
    """Without ``MetadataFieldError``, pydantic's empty ``loc`` still leaves
    the problem field-less, but the "Value error, " prefix is always
    stripped regardless of how the error was raised.
    """
    exc = _validation_error(_CrossFieldPlain, {})

    problems = problems_from_validation_error(PATH, exc)

    assert len(problems) == 1
    assert problems[0].field is None
    assert problems[0].message == "exactly one of a or b is required"


def test_cross_field_metadata_field_error_is_attributed_to_its_named_field() -> None:
    exc = _validation_error(_CrossFieldAttributed, {})

    problems = problems_from_validation_error(PATH, exc)

    assert len(problems) == 1
    assert problems[0].field == "a/b"
    assert problems[0].message == "exactly one of a or b is required"


def test_cross_field_metadata_field_error_also_fires_when_both_are_set() -> None:
    exc = _validation_error(_CrossFieldAttributed, {"a": "x", "b": "y"})

    problems = problems_from_validation_error(PATH, exc)

    assert len(problems) == 1
    assert problems[0].field == "a/b"


def test_no_message_from_any_case_above_starts_with_pydantics_value_error_prefix() -> None:
    for model, data in (
        (_FieldLevel, {"name": "  "}),
        (_CrossFieldPlain, {}),
        (_CrossFieldAttributed, {}),
    ):
        exc = _validation_error(model, data)
        for problem in problems_from_validation_error(PATH, exc):
            assert not problem.message.startswith("Value error,")
