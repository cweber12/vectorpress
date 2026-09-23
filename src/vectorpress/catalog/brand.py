"""Load and validate a catalog root's ``brand.toml`` (§27).

Hand-authored and read-only to the tool (ADR 0005): this module only ever
reads it, through the standard-library ``tomllib``. Unlike ``catalog.toml``,
whose presence is guaranteed by how the root was located, a catalog can
exist before its brand is written: a missing ``brand.toml`` is a
``MetadataProblem``, not a raised error (issue #3).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.brand import Brand

BRAND_CONFIG_FILENAME = "brand.toml"


@dataclass(frozen=True)
class BrandResult:
    """The catalog's brand, plus every problem found loading it.

    ``brand`` is ``None`` when ``brand.toml`` is missing, malformed, fails
    schema validation, or names a mark file that does not exist under the
    catalog root; in every such case ``problems`` names the file and, where
    the problem traces to one, the field.
    """

    brand: Brand | None
    problems: list[MetadataProblem]


def load_brand(root: Path) -> BrandResult:
    """Load and validate the ``brand.toml`` at a catalog root.

    A missing file is reported as an absence problem rather than raised
    (issue #3's "a catalog can exist before its brand is written").
    """
    path = root / BRAND_CONFIG_FILENAME
    rel_path = path.relative_to(root)

    if not path.is_file():
        return BrandResult(
            brand=None,
            problems=[MetadataProblem(rel_path, None, "brand.toml not found")],
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return BrandResult(brand=None, problems=[MetadataProblem(rel_path, None, str(exc))])

    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        return BrandResult(
            brand=None,
            problems=[MetadataProblem(rel_path, None, f"TOML syntax error: {exc}")],
        )

    try:
        brand = Brand.model_validate(data)
    except ValidationError as exc:
        return BrandResult(brand=None, problems=_problems_from_validation_error(rel_path, exc))

    if not (root / brand.mark_file).is_file():
        return BrandResult(
            brand=None,
            problems=[
                MetadataProblem(
                    rel_path,
                    "mark_file",
                    f"mark file not found: {brand.mark_file}",
                )
            ],
        )

    return BrandResult(brand=brand, problems=[])


def _problems_from_validation_error(path: Path, exc: ValidationError) -> list[MetadataProblem]:
    problems: list[MetadataProblem] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or None
        problems.append(MetadataProblem(path, field, error["msg"]))
    return problems
