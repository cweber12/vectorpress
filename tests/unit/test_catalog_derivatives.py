"""catalog.derivatives: recipe-based source selection and derivative state
(ADR 0003, issue #22).

Pure functions over fabricated ``Asset`` objects, not the fixture catalog on
disk: selection has no filesystem awareness, so these tests don't need one
either (CLAUDE.md's layering guardrail -- only ``catalog.assets`` reads
asset folders).
"""

from vectorpress.catalog.derivatives import (
    count_derivative_states,
    select_derivatives,
    select_source,
)
from vectorpress.domain.asset import AccuracyStatus, Asset, DerivativePin, RightsStatus, Source
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES


def _asset(sources: list[Source], derivatives: dict[str, DerivativePin] | None = None) -> Asset:
    return Asset(
        id="test_asset",
        common_name="Test Asset",
        display_name="Test Asset",
        description="A fabricated asset for pure selection tests.",
        subject_category="Test",
        taxonomic_group="Test",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=sources,
        derivatives=derivatives or {},
    )


# --- preference order and tie-break -----------------------------------------------


def test_preference_order_selects_the_first_accepted_role_present() -> None:
    """transparent_png accepts detailed, flatcolor, silhouette, lineart in
    that order (issue #22): an asset with both detailed and silhouette
    sources selects detailed."""
    asset = _asset(
        [
            Source(role="silhouette", file="silhouette.png"),
            Source(role="detailed", file="detailed.png"),
        ]
    )
    recipe = RECIPES[DerivativeType.TRANSPARENT_PNG]

    selection = select_source(asset, recipe)

    assert selection.state is DerivativeState.MISSING
    assert selection.source == Source(role="detailed", file="detailed.png")


def test_first_declared_source_wins_a_tie_within_one_role() -> None:
    asset = _asset(
        [
            Source(role="silhouette", file="first.png"),
            Source(role="silhouette", file="second.png"),
        ]
    )
    recipe = RECIPES[DerivativeType.SILHOUETTE_SVG]

    selection = select_source(asset, recipe)

    assert selection.state is DerivativeState.MISSING
    assert selection.source == Source(role="silhouette", file="first.png")


# --- impossible ---------------------------------------------------------------


def test_no_source_with_an_accepted_role_is_impossible_and_names_the_roles() -> None:
    asset = _asset([Source(role="lineart", file="lineart.png")])
    recipe = RECIPES[DerivativeType.FLATCOLOR_SVG]

    selection = select_source(asset, recipe)

    assert selection.state is DerivativeState.IMPOSSIBLE
    assert selection.source is None
    assert selection.reason is not None
    assert "flatcolor" in selection.reason


# --- pinning --------------------------------------------------------------------


def test_pin_is_selected_over_the_preference_order_default() -> None:
    asset = _asset(
        [
            Source(role="silhouette", file="silhouette.png"),
            Source(role="lineart", file="lineart.png"),
        ],
        derivatives={"transparent_png": DerivativePin(source="lineart.png")},
    )
    recipe = RECIPES[DerivativeType.TRANSPARENT_PNG]

    selection = select_source(asset, recipe)

    assert selection.state is DerivativeState.MISSING
    assert selection.source == Source(role="lineart", file="lineart.png")


# --- select_derivatives: only recipe-bearing types, in declaration order ----------


def test_select_derivatives_reports_only_the_three_recipe_bearing_types() -> None:
    asset = _asset([Source(role="silhouette", file="silhouette.png")])

    selections = select_derivatives(asset)

    assert [s.derivative_type for s in selections] == [
        DerivativeType.TRANSPARENT_PNG,
        DerivativeType.SILHOUETTE_SVG,
        DerivativeType.FLATCOLOR_SVG,
    ]


def test_select_derivatives_matches_the_fixture_asset_shape() -> None:
    """Mirrors the shape ``vpress asset ochre_sea_star`` and its siblings
    show (issue #22 acceptance criterion 1): transparent_png and
    silhouette_svg select the silhouette source as missing, flatcolor_svg is
    impossible."""
    asset = _asset([Source(role="silhouette", file="silhouette.png")])

    by_type = {s.derivative_type: s for s in select_derivatives(asset)}

    assert by_type[DerivativeType.TRANSPARENT_PNG].state is DerivativeState.MISSING
    assert by_type[DerivativeType.TRANSPARENT_PNG].source == Source(
        role="silhouette", file="silhouette.png"
    )
    assert by_type[DerivativeType.SILHOUETTE_SVG].state is DerivativeState.MISSING
    assert by_type[DerivativeType.SILHOUETTE_SVG].source == Source(
        role="silhouette", file="silhouette.png"
    )
    assert by_type[DerivativeType.FLATCOLOR_SVG].state is DerivativeState.IMPOSSIBLE


# --- count_derivative_states ------------------------------------------------------


def test_count_derivative_states_tallies_across_assets() -> None:
    one_source_asset = _asset([Source(role="silhouette", file="silhouette.png")])
    two_source_asset = _asset(
        [
            Source(role="silhouette", file="silhouette.png"),
            Source(role="lineart", file="lineart.png"),
        ]
    )

    counts = count_derivative_states([one_source_asset, two_source_asset])

    # Each asset: transparent_png missing, silhouette_svg missing,
    # flatcolor_svg impossible (neither asset has a flatcolor source).
    assert counts.missing == 4
    assert counts.impossible == 2


def test_count_derivative_states_is_zero_for_no_assets() -> None:
    counts = count_derivative_states([])

    assert counts.missing == 0
    assert counts.impossible == 0
