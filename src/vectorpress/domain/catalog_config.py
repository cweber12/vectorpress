"""The catalog root configuration model.

No I/O here (ADR 0006): this module only defines and validates the shape of
``catalog.toml``. Locating the file and reading it off disk is the ``catalog``
layer's job.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Roles a source image can have without being listed in ``catalog.toml``
#: (ADR 0003). A catalog may declare additional roles via ``extra_roles``.
BUILTIN_SOURCE_ROLES = ("silhouette", "lineart", "flatcolor", "detailed")

DEFAULT_ASSETS_DIR = "assets"
DEFAULT_COLLECTIONS_DIR = "collections"
DEFAULT_PRODUCTS_DIR = "products"
DEFAULT_REFERENCE_SIZE_IN = 3.0


class CatalogConfig(BaseModel):
    """Brand-independent configuration hand-authored at the catalog root.

    Read-only to the tool (ADR 0005): loading validates this shape, nothing
    in this codebase writes it back.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: str
    assets_dir: str = DEFAULT_ASSETS_DIR
    collections_dir: str = DEFAULT_COLLECTIONS_DIR
    products_dir: str = DEFAULT_PRODUCTS_DIR
    reference_size_in: float = DEFAULT_REFERENCE_SIZE_IN
    extra_roles: list[str] = Field(default_factory=list)
    #: The external editor 'vpress open' launches: a program plus optional
    #: arguments, e.g. ["code", "--wait"]. Unset (the default) falls back to
    #: the OS default opener (§6.8, §24).
    editor: list[str] | None = None

    @field_validator("editor")
    @classmethod
    def _editor_is_a_program_plus_arguments(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(value) == 0 or any(not part for part in value)):
            raise ValueError(
                "editor must be a non-empty list of non-empty strings "
                "(a program name, plus optional arguments)"
            )
        return value

    @property
    def source_roles(self) -> tuple[str, ...]:
        """Every role this catalog accepts: the built-in ones plus its own."""
        return (*BUILTIN_SOURCE_ROLES, *self.extra_roles)
