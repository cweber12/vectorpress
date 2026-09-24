"""The standardized derivative types the tool can produce (CONTEXT.md
"Derivative type").

A product's ``derivative_types`` field (issue #7) selects which of these it
includes; PRD 2 gives each type its own recipe (which source roles it
accepts, the generator, and its parameters). No I/O here (ADR 0006): this
only names the fixed set.
"""

import re
import unicodedata
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


#: The customer-facing filename suffix for each derivative type with a
#: landed generator (§20, issue #23, issue #24, issue #25): every type gets
#: an explicit suffix, no type uses the bare stem.
_FILENAME_SUFFIXES: dict[DerivativeType, str] = {
    DerivativeType.TRANSPARENT_PNG: "-color.png",
    DerivativeType.SILHOUETTE_SVG: "-silhouette.svg",
    DerivativeType.FLATCOLOR_SVG: "-color.svg",
}

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(display_name: str) -> str:
    """A customer-facing, lower-case, hyphen-separated, ASCII slug of a
    display name (§20): ``"Ochre Sea Star"`` becomes ``"ochre-sea-star"``.

    Non-ASCII characters are folded to their closest ASCII equivalent where
    one exists (e.g. an accent is dropped) and discarded otherwise, since a
    filename must be ASCII-safe across the marketplaces this tool targets.
    """
    ascii_name = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    return _SLUG_STRIP_RE.sub("-", ascii_name.lower()).strip("-")


def derivative_filename(display_name: str, derivative_type: DerivativeType) -> str:
    """The customer-facing filename for one asset's derivative of
    ``derivative_type`` (§20, issue #23): the asset's display name slugified,
    plus that type's suffix. The asset ID is never customer-facing
    (CONTEXT.md "Asset ID"), so this takes the display name, not the ID.

    Raises ``KeyError`` for a derivative type with no filename suffix yet
    (mirrors :func:`~vectorpress.domain.recipe.recipe_for`'s "no recipe yet"
    absence rather than a sentinel): callers only reach here for a type with
    a landed generator, and every such type has a suffix by construction.
    """
    return f"{slugify(display_name)}{_FILENAME_SUFFIXES[derivative_type]}"
