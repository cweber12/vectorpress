"""The catalog's brand configuration model.

No I/O here (ADR 0006): this module only defines and validates the shape of
``brand.toml``. Reading the file, and checking the mark file exists on disk,
is the ``catalog`` layer's job.
"""

from pydantic import BaseModel, ConfigDict


class BrandTypography(BaseModel):
    """Preview typography settings (§27).

    PRD 7 maps these to CSS custom properties for the HTML preview templates
    (ADR 0008); nothing is rendered here.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    heading_font: str
    body_font: str


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
