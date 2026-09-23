"""The standardized derivative types the tool can produce (CONTEXT.md
"Derivative type").

A product's ``derivative_types`` field (issue #7) selects which of these it
includes; PRD 2 gives each type its own recipe (which source roles it
accepts, the generator, and its parameters). No I/O here (ADR 0006): this
only names the fixed set.
"""

from enum import StrEnum


class DerivativeType(StrEnum):
    """One of the standardized derivative outputs, each with its own recipe
    (§6, CONTEXT.md "Derivative type").
    """

    TRANSPARENT_PNG = "transparent_png"
    SILHOUETTE_SVG = "silhouette_svg"
    CUT_SVG = "cut_svg"
    FLATCOLOR_SVG = "flatcolor_svg"
    OUTLINE_SVG = "outline_svg"
    DETAILED_MONO_SVG = "detailed_mono_svg"
    LAYERED_SVG = "layered_svg"
