"""Read and validate a catalog root's ``catalog.toml``.

``catalog.toml`` is hand-authored and read-only to the tool (ADR 0005): this
module only ever reads it, through the standard-library ``tomllib``.
"""

import tomllib
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.errors import CatalogConfigError
from vectorpress.catalog.locate import CATALOG_CONFIG_FILENAME
from vectorpress.domain.catalog_config import CatalogConfig


def load_catalog_config(root: Path) -> CatalogConfig:
    """Load and validate the ``catalog.toml`` at a catalog root.

    Raises ``CatalogConfigError`` naming the file, and where the problem
    traces to one, the offending field, for a TOML syntax error, an unknown
    key, or a wrongly typed value.
    """
    path = root / CATALOG_CONFIG_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogConfigError(path, str(exc)) from exc

    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogConfigError(path, f"TOML syntax error: {exc}") from exc

    try:
        return CatalogConfig.model_validate(data)
    except ValidationError as exc:
        raise CatalogConfigError(path, _format_validation_error(exc)) from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {field}: {error['msg']}")
    return "\n".join(lines)
