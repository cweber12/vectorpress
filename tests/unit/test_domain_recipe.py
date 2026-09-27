"""domain.recipe: the fixed recipe declarations (ADR 0003, issue #22)."""

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES, recipe_for


def test_transparent_png_accepts_detailed_flatcolor_silhouette_lineart_in_order() -> None:
    recipe = RECIPES[DerivativeType.TRANSPARENT_PNG]

    assert recipe.accepted_roles == ("detailed", "flatcolor", "silhouette", "lineart")


def test_silhouette_svg_accepts_only_silhouette() -> None:
    recipe = RECIPES[DerivativeType.SILHOUETTE_SVG]

    assert recipe.accepted_roles == ("silhouette",)


def test_flatcolor_svg_accepts_only_flatcolor() -> None:
    recipe = RECIPES[DerivativeType.FLATCOLOR_SVG]

    assert recipe.accepted_roles == ("flatcolor",)


def test_cut_svg_accepts_only_silhouette() -> None:
    """Issue #36: built from the silhouette role, not detailed art (ADR
    0003)."""
    recipe = RECIPES[DerivativeType.CUT_SVG]

    assert recipe.accepted_roles == ("silhouette",)


def test_only_the_four_landed_derivative_types_have_a_recipe() -> None:
    """The other three derivative types (outline_svg, detailed_mono_svg,
    layered_svg) are PRD 3's remaining slices / PRD 10 work and have no
    recipe yet (issue #22's "What to build", issue #36)."""
    assert set(RECIPES) == {
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.CUT_SVG,
        DerivativeType.FLATCOLOR_SVG,
    }


def test_recipe_for_returns_the_recipe_for_a_known_type() -> None:
    recipe = recipe_for("silhouette_svg")

    assert recipe is not None
    assert recipe.derivative_type is DerivativeType.SILHOUETTE_SVG


def test_recipe_for_returns_none_for_a_real_type_with_no_recipe_yet() -> None:
    assert recipe_for("outline_svg") is None


def test_recipe_for_returns_none_for_a_name_that_is_not_a_derivative_type() -> None:
    assert recipe_for("not_a_real_derivative_type") is None


# --- generator identity (issue #23) -------------------------------------------------


def test_transparent_png_has_a_landed_generator() -> None:
    recipe = RECIPES[DerivativeType.TRANSPARENT_PNG]

    assert recipe.generator == "transparent_png"
    assert recipe.parameters == {}


def test_silhouette_svg_has_a_landed_generator_with_its_tracing_parameters() -> None:
    """Issue #24: the solid silhouette SVG generator, with its three
    tracing parameters as recipe parameters so they are part of the recipe
    identity (ADR 0004)."""
    recipe = RECIPES[DerivativeType.SILHOUETTE_SVG]

    assert recipe.generator == "silhouette_svg"
    assert recipe.parameters == {
        "alpha_threshold": 127,
        "curve_tolerance": 0.2,
        "speckle_size": 2,
    }


def test_flatcolor_svg_has_a_landed_generator_with_its_parameters() -> None:
    """Issue #25: the flat-color SVG generator, with its quantization
    parameters (``max_colors``, ``min_color_share`` -- review fix round 1;
    ``shade_merge_tolerance``, ``max_fragments_per_color`` -- issue #83)
    alongside the same three tracing parameters ``silhouette_svg`` uses, all
    part of the recipe identity (ADR 0004)."""
    recipe = RECIPES[DerivativeType.FLATCOLOR_SVG]

    assert recipe.generator == "flatcolor_svg"
    assert recipe.parameters == {
        "alpha_threshold": 127,
        "curve_tolerance": 0.2,
        "speckle_size": 2,
        "max_colors": 16,
        "min_color_share": 0.01,
        "shade_merge_tolerance": 16.0,
        "max_fragments_per_color": 1000,
    }


def test_cut_svg_has_a_landed_generator_with_its_physical_cleanup_parameters() -> None:
    """Issue #36: the cut-file SVG generator, with its physical (not pixel)
    cleanup thresholds -- island area, hole area, opening width -- plus its
    own alpha threshold and a coarser curve tolerance than
    ``silhouette_svg``'s, all part of the recipe identity (ADR 0004, §9.1).
    ``reference_size_in`` is deliberately absent here: it is a catalog-level
    setting merged in at generation time as an effective parameter
    (:func:`vectorpress.pipeline.generate._effective_parameters`), not part
    of this static declaration."""
    recipe = RECIPES[DerivativeType.CUT_SVG]

    assert recipe.generator == "cut_svg"
    assert recipe.parameters == {
        "alpha_threshold": 127,
        "island_min_area_in2": 0.01,
        "hole_min_area_in2": 0.01,
        "opening_width_in": 0.06,
        "curve_tolerance": 0.5,
    }
    assert "reference_size_in" not in recipe.parameters
