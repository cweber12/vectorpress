"""A model-level validation failure attributed to the field(s) it concerns.

A ``model_validator(mode="after")`` check spans more than one field (for
example, whether a product references a collection by slug or declares an
inline membership, but not both or neither), so pydantic records it with an
empty ``loc`` — the resulting ``MetadataProblem`` (``catalog.metadata_problem``)
would otherwise carry no field. Raising ``MetadataFieldError`` instead of a
plain ``ValueError`` lets the field(s) travel with the error so the
``catalog`` layer's converter can attribute the problem correctly.

Lives in ``domain`` rather than ``catalog`` (ADR 0006): the models that raise
it must not import downward from ``catalog``.
"""


class MetadataFieldError(ValueError):
    """Raised in place of ``ValueError`` by a cross-field model validator.

    ``field`` names the field the check concerns, or several joined by
    ``/`` (for example ``"collection_slug/membership"``) when the check
    spans more than one.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
