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
    DerivativeType.FLATCOLOR_SVG: Recipe(
        derivative_type=DerivativeType.FLATCOLOR_SVG,
        accepted_roles=("flatcolor",),
        generator="flatcolor_svg",
        parameters={
            "alpha_threshold": 127,
            "curve_tolerance": 0.2,
            "speckle_size": 2,
            "max_colors": 16,
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
