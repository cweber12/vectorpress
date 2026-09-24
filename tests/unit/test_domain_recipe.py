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


def test_only_the_three_initial_derivative_types_have_a_recipe() -> None:
    """The other four derivative types (cut_svg, outline_svg,
    detailed_mono_svg, layered_svg) are PRD 3 / PRD 10 work and have no
    recipe yet (issue #22's "What to build")."""
    assert set(RECIPES) == {
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.FLATCOLOR_SVG,
    }


def test_recipe_for_returns_the_recipe_for_a_known_type() -> None:
    recipe = recipe_for("silhouette_svg")

    assert recipe is not None
    assert recipe.derivative_type is DerivativeType.SILHOUETTE_SVG


def test_recipe_for_returns_none_for_a_real_type_with_no_recipe_yet() -> None:
    assert recipe_for("cut_svg") is None


def test_recipe_for_returns_none_for_a_name_that_is_not_a_derivative_type() -> None:
    assert recipe_for("not_a_real_derivative_type") is None


# --- generator identity (issue #23) -------------------------------------------------


def test_transparent_png_has_a_landed_generator() -> None:
    recipe = RECIPES[DerivativeType.TRANSPARENT_PNG]

    assert recipe.generator == "transparent_png"
    assert recipe.parameters == {}


def test_silhouette_svg_and_flatcolor_svg_have_no_generator_yet() -> None:
    """PRD 3 lands their generators; until then ``vpress generate`` reports
    them ``no generator`` rather than attempting to run one (issue #23)."""
    assert RECIPES[DerivativeType.SILHOUETTE_SVG].generator is None
    assert RECIPES[DerivativeType.FLATCOLOR_SVG].generator is None
