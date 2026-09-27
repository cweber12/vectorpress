"""Recipe declarations: which source roles each derivative type accepts, in
preference order, and how it is generated (ADR 0003, ADR 0004, CONTEXT.md
"Recipe").

No I/O here (ADR 0006): a recipe is fixed, catalog-independent data, not
something read off disk. Not every :class:`~vectorpress.domain.derivative_type.DerivativeType`
has a recipe yet -- PRD 3 and PRD 10 add generation for the rest -- so a type
without one is simply absent from :data:`RECIPES` rather than mapped to an
empty recipe; per the PRD, a type with no recipe is reported nowhere (neither
missing nor impossible).
"""

from collections.abc import Mapping
from dataclasses import dataclass

from vectorpress.domain.derivative_type import DerivativeType


@dataclass(frozen=True)
class Recipe:
    """How one derivative type selects its source and is generated (ADR
    0003, issue #23).

    ``accepted_roles`` lists roles in preference order. Selecting a source
    for one asset against this recipe -- and telling "missing" from
    "impossible" -- is :func:`vectorpress.catalog.derivatives.select_source`,
    since it reasons about a loaded asset, not just this static declaration.

    ``generator`` names the :mod:`vectorpress.pipeline` generator that
    produces this type's output, looked up through
    :func:`vectorpress.pipeline.registry.get_generator`; ``None`` for a
    recipe-bearing type whose generator has not landed yet. ``parameters``
    are passed to the generator verbatim and are part of the recipe identity
    (ADR 0004): changing them changes every derivative's provenance and marks
    it stale, even when ``generator`` itself is unchanged.
    """

    derivative_type: DerivativeType
    accepted_roles: tuple[str, ...]
    generator: str | None
    parameters: Mapping[str, object]


#: The recipe for every derivative type this PRD slice covers (issue #22,
#: issue #23). Keyed by type so a lookup by known type is direct; use
#: :func:`recipe_for` to look one up by a name that may not even be a real
#: derivative type.
RECIPES: dict[DerivativeType, Recipe] = {
    DerivativeType.TRANSPARENT_PNG: Recipe(
        derivative_type=DerivativeType.TRANSPARENT_PNG,
        accepted_roles=("detailed", "flatcolor", "silhouette", "lineart"),
        generator="transparent_png",
        parameters={},
    ),
    DerivativeType.SILHOUETTE_SVG: Recipe(
        derivative_type=DerivativeType.SILHOUETTE_SVG,
        accepted_roles=("silhouette",),
        generator="silhouette_svg",
        parameters={"alpha_threshold": 127, "curve_tolerance": 0.2, "speckle_size": 2},
    ),
    DerivativeType.CUT_SVG: Recipe(
        derivative_type=DerivativeType.CUT_SVG,
        accepted_roles=("silhouette",),
        generator="cut_svg",
        parameters={
            "alpha_threshold": 127,
            # Every cleanup threshold below is a physical measurement, not a
            # pixel count (ADR 0007, §9.1): "island", "hole" and "opening
            # width" are only meaningful at a known output size, and that
            # size -- the catalog's default reference size, never a
            # product's (ADR 0009) -- is not part of this static
            # declaration: ``pipeline.generate`` merges it in at generation
            # time as an *effective* parameter, so changing it alone still
            # changes this recipe's identity without editing this dict.
            "island_min_area_in2": 0.01,
            "hole_min_area_in2": 0.01,
            "opening_width_in": 0.06,
            # Coarser than silhouette_svg's 0.2 (issue #36's "typically a
            # coarser curve tolerance"): a cut file trades fine detail for
            # manufacturability on purpose (§6.3).
            "curve_tolerance": 0.5,
        },
    ),
    DerivativeType.FLATCOLOR_SVG: Recipe(
        derivative_type=DerivativeType.FLATCOLOR_SVG,
        accepted_roles=("flatcolor",),
        generator="flatcolor_svg",
        parameters={
            "alpha_threshold": 127,
            "curve_tolerance": 0.2,
            "speckle_size": 2,
            "max_colors": 16,
            # A palette candidate must be at least this share of every ink
            # pixel to count as a genuinely flat color (review fix round 1,
            # issue #25): keeps a real anti-aliased edge blend -- a thin
            # seam, however many distinct shades it breaks into -- from
            # winning its own palette slot and so its own sliver <path>.
            "min_color_share": 0.01,
            # Shades within this Euclidean RGB distance of a more frequent
            # shade count as that shade when the palette is chosen (issue
            # #83): per-pixel noise inside a flat region, unlike an edge
            # blend, is spread across the whole region, so several of its
            # shades clear min_color_share on their own. Measured on real
            # noisy sources, 8 is the smallest distance that settles on the
            # visible palette; 16 leaves margin while keeping two colors a
            # viewer can tell apart from merging.
            "shade_merge_tolerance": 16.0,
            # A color whose pixels form more separate fragments than this
            # fails generation instead of being traced (issue #83, §35):
            # the source is not flat-color. Real flat-color regions number
            # in the tens per color; the noisy sources that hung the tracer
            # had 5,000-20,000.
            "max_fragments_per_color": 1000,
        },
    ),
}


def recipe_for(derivative_type_name: str) -> Recipe | None:
    """The recipe for one derivative type name, or ``None``.

    ``None`` covers two cases alike, matching how ADR 0003's "missing vs
    impossible" and this PRD's pin-validation rule both talk about "a type
    that has no recipe" without distinguishing them: ``derivative_type_name``
    is not one of :class:`DerivativeType`'s values at all, or it is but PRD 3
    / PRD 10 have not given it a recipe yet.
    """
    try:
        derivative_type = DerivativeType(derivative_type_name)
    except ValueError:
        return None
    return RECIPES.get(derivative_type)
