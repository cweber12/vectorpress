"""The catalog's brand configuration model.

No I/O here (ADR 0006): this module only defines and validates the shape of
``brand.toml``. Reading the file, and checking the mark file exists on disk,
is the ``catalog`` layer's job.
"""

from pydantic import BaseModel, ConfigDict

#: Font family names this tool ships its own font files for (ADR 0014):
#: allowed as ``heading_font`` / ``body_font`` without a matching
#: ``*_font_file``.
SHIPPED_FONT_FAMILIES = frozenset({"Inter", "Space Grotesk"})

#: The only extensions ADR 0014 allows a brand's own ``heading_font_file`` /
#: ``body_font_file`` to name.
FONT_FILE_EXTENSIONS = frozenset({".ttf", ".otf", ".woff2"})


class BrandTypography(BaseModel):
    """Preview typography settings (§27, ADR 0014).

    ``heading_font`` and ``body_font`` name a font family; without a
    matching ``*_font_file``, the name must be one of
    :data:`SHIPPED_FONT_FAMILIES`, else it is a brand metadata problem
    naming the field. ``heading_font_file`` and ``body_font_file`` each name
    a font file relative to the catalog root -- one file serving both
    weights. Checking a font file's existence and extension, and a
    fileless family name against :data:`SHIPPED_FONT_FAMILIES`, needs the
    catalog root, so the ``catalog`` layer does it, not this pure model
    (ADR 0006).
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    heading_font: str
    body_font: str
    heading_font_file: str | None = None
    body_font_file: str | None = None


class BrandCardStyle(BaseModel):
    """Product-card styling values (§27).

    PRD 7 maps these to CSS custom properties for the HTML preview templates
    (ADR 0008); nothing is rendered here.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    background_color: str
    accent_color: str
    text_color: str


class Brand(BaseModel):
    """The catalog's brand configuration (``brand.toml``), hand-authored and
    read-only to the tool (ADR 0005).

    Defines the product-level presentation requirements a catalog can carry
    once instead of recreating per product (§27): the brand name, its mark
    (logo) file, preview typography, product-card styling, standard wording,
    license naming and template, copyright wording, and standard README
    text. Field shapes are chosen so PRD 7 can map them to preview template
    variables without change (ADR 0008); this module renders nothing.

    ``mark_file`` and ``license_file`` each name a file relative to the
    catalog root; checking that it exists is the ``catalog`` layer's job
    (this module has no filesystem awareness, per ADR 0006). ``license_file``
    is a hand-written license template a build copies to ``LICENSE.txt``,
    substituting ``{brand}``, ``{product}``, ``{copyright}`` and ``{year}``
    (§27) -- the same template regardless of an included asset's rights
    status.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    name: str
    mark_file: str
    typography: BrandTypography
    card_style: BrandCardStyle
    standard_wording: str
    license_name: str
    license_file: str
    copyright_wording: str
    readme_text: str
