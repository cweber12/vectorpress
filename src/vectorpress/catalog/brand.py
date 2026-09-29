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

from vectorpress.catalog.metadata_problem import MetadataProblem, problems_from_validation_error
from vectorpress.domain.brand import (
    FONT_FILE_EXTENSIONS,
    SHIPPED_FONT_FAMILIES,
    Brand,
    BrandTypography,
)

BRAND_CONFIG_FILENAME = "brand.toml"


@dataclass(frozen=True)
class BrandResult:
    """The catalog's brand, plus every problem found loading it.

    ``brand`` is ``None`` when ``brand.toml`` is missing, malformed, fails
    schema validation, names a mark file or license file that does not
    exist under the catalog root, or has a typography problem (a font file
    that does not exist or has the wrong extension, or -- with no font file
    -- a family name this tool does not ship, ADR 0014); in every such case
    ``problems`` names the file and, where the problem traces to one, the
    field.
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
        return BrandResult(brand=None, problems=problems_from_validation_error(rel_path, exc))

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

    if not (root / brand.license_file).is_file():
        return BrandResult(
            brand=None,
            problems=[
                MetadataProblem(
                    rel_path,
                    "license_file",
                    f"license file not found: {brand.license_file}",
                )
            ],
        )

    typography_problem = _typography_problem(root, rel_path, brand.typography)
    if typography_problem is not None:
        return BrandResult(brand=None, problems=[typography_problem])

    return BrandResult(brand=brand, problems=[])


def _font_field_problem(
    root: Path, rel_path: Path, role: str, family: str, font_file: str | None
) -> MetadataProblem | None:
    """One typography role's own brand metadata problem, if any (ADR 0014:
    "a font never silently falls back"): a font file with the wrong
    extension or that does not exist under the catalog root, or -- with no
    font file at all -- a family name this tool does not ship."""
    if font_file is not None:
        field = f"typography.{role}_font_file"
        if Path(font_file).suffix.lower() not in FONT_FILE_EXTENSIONS:
            return MetadataProblem(
                rel_path, field, f"font file must be .ttf, .otf or .woff2: {font_file}"
            )
        if not (root / font_file).is_file():
            return MetadataProblem(rel_path, field, f"font file not found: {font_file}")
        return None

    if family not in SHIPPED_FONT_FAMILIES:
        shipped = " or ".join(sorted(SHIPPED_FONT_FAMILIES))
        return MetadataProblem(
            rel_path,
            f"typography.{role}_font",
            f"{family!r} is not a font this tool ships ({shipped}); "
            f"set typography.{role}_font_file to a font file instead",
        )
    return None


def _typography_problem(
    root: Path, rel_path: Path, typography: BrandTypography
) -> MetadataProblem | None:
    return _font_field_problem(
        root, rel_path, "heading", typography.heading_font, typography.heading_font_file
    ) or _font_field_problem(
        root, rel_path, "body", typography.body_font, typography.body_font_file
    )
