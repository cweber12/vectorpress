"""domain.collection_resolution: resolving an explicit asset ID list into
current members (§11).
"""

from vectorpress.domain.collection_resolution import (
    ResolvedMember,
    WayIn,
    WayInKind,
    resolve_explicit,
)


def test_every_known_id_becomes_an_explicit_member() -> None:
    result = resolve_explicit(
        ["ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"],
        known_asset_ids={"ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"},
    )

    assert result.unknown_asset_ids == []
    assert result.members == [
        ResolvedMember("giant_green_anemone", (WayIn(WayInKind.EXPLICIT),)),
        ResolvedMember("ochre_sea_star", (WayIn(WayInKind.EXPLICIT),)),
        ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.EXPLICIT),)),
    ]


def test_members_are_sorted_by_asset_id_regardless_of_declared_order() -> None:
    result = resolve_explicit(
        ["purple_sea_urchin", "giant_green_anemone", "ochre_sea_star"],
        known_asset_ids={"ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"},
    )

    assert [member.asset_id for member in result.members] == [
        "giant_green_anemone",
        "ochre_sea_star",
        "purple_sea_urchin",
    ]


def test_a_repeated_id_produces_one_member_not_several() -> None:
    result = resolve_explicit(
        ["ochre_sea_star", "ochre_sea_star", "ochre_sea_star"],
        known_asset_ids={"ochre_sea_star"},
    )

    assert result.members == [ResolvedMember("ochre_sea_star", (WayIn(WayInKind.EXPLICIT),))]


def test_an_id_with_no_loaded_asset_is_unknown_not_a_member() -> None:
    result = resolve_explicit(
        ["ochre_sea_star", "not_a_real_asset"], known_asset_ids={"ochre_sea_star"}
    )

    assert [member.asset_id for member in result.members] == ["ochre_sea_star"]
    assert result.unknown_asset_ids == ["not_a_real_asset"]


def test_unknown_ids_are_sorted_and_de_duplicated() -> None:
    result = resolve_explicit(
        ["zebra_asset", "aardvark_asset", "zebra_asset"], known_asset_ids=set()
    )

    assert result.members == []
    assert result.unknown_asset_ids == ["aardvark_asset", "zebra_asset"]


def test_empty_asset_ids_resolve_to_no_members_and_no_unknown_ids() -> None:
    result = resolve_explicit([], known_asset_ids={"ochre_sea_star"})

    assert result.members == []
    assert result.unknown_asset_ids == []


def test_way_in_explicit_renders_as_its_kind() -> None:
    assert str(WayIn(WayInKind.EXPLICIT)) == "explicit"


def test_way_in_via_renders_with_the_contributing_slug() -> None:
    assert (
        str(WayIn(WayInKind.VIA, via_slug="kelp_forest_ecosystem")) == "via kelp_forest_ecosystem"
    )
