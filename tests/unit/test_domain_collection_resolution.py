"""domain.collection_resolution: resolving an explicit asset ID list and a
metadata rule into current members (§11, §12).
"""

from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.collection_resolution import (
    ResolvedMember,
    WayIn,
    WayInKind,
    resolve_explicit,
    resolve_membership,
    resolve_rule,
)
from vectorpress.domain.membership import ClassificationField, Membership, MembershipRule


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


# --- resolve_rule: a metadata rule over asset classifications (§11) ----------------


def _asset(**overrides: object) -> Asset:
    """A fully-populated asset so a rule test only overrides the
    classification field(s) it exercises."""
    fields: dict[str, object] = {
        "id": "test_asset",
        "common_name": "Test asset",
        "display_name": "Test Asset",
        "description": "A test asset.",
        "subject_category": "Echinoderm",
        "tags": ["sea star"],
        "regions": ["California"],
        "ecosystems": ["Tide pool"],
        "taxonomic_group": "Echinoderm",
        "rights_status": RightsStatus.ORIGINAL_ARTWORK,
        "accuracy_status": AccuracyStatus.APPROVED,
        "sources": [Source(role="silhouette", file="silhouette.png")],
    }
    fields.update(overrides)
    return Asset(**fields)  # type: ignore[arg-type]


def test_rule_matches_on_tags() -> None:
    rule = MembershipRule(field=ClassificationField.TAGS, values=["sea star"])
    asset = _asset(id="ochre_sea_star", tags=["sea star", "tide pool"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("ochre_sea_star", (WayIn(WayInKind.RULE),))]


def test_rule_matches_on_regions() -> None:
    rule = MembershipRule(field=ClassificationField.REGIONS, values=["Oregon"])
    asset = _asset(id="bat_star", regions=["California", "Oregon"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("bat_star", (WayIn(WayInKind.RULE),))]


def test_rule_matches_on_ecosystems() -> None:
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"])
    asset = _asset(id="purple_sea_urchin", ecosystems=["Tide pool", "Kelp forest"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.RULE),))]


def test_rule_matches_on_group_against_taxonomic_group() -> None:
    """``group`` stands for ``Asset.taxonomic_group`` (§11)."""
    rule = MembershipRule(field=ClassificationField.GROUP, values=["Echinoderm"])
    asset = _asset(id="ochre_sea_star", taxonomic_group="Echinoderm")
    non_match = _asset(id="turban_snail", taxonomic_group="Mollusk")

    result = resolve_rule(rule, [asset, non_match])

    assert result == [ResolvedMember("ochre_sea_star", (WayIn(WayInKind.RULE),))]


def test_rule_matches_on_category_against_subject_category() -> None:
    """``category`` stands for ``Asset.subject_category`` (§11)."""
    rule = MembershipRule(field=ClassificationField.CATEGORY, values=["Mollusk"])
    asset = _asset(id="turban_snail", subject_category="Mollusk")
    non_match = _asset(id="ochre_sea_star", subject_category="Echinoderm")

    result = resolve_rule(rule, [asset, non_match])

    assert result == [ResolvedMember("turban_snail", (WayIn(WayInKind.RULE),))]


def test_rule_matches_any_of_several_rule_values() -> None:
    rule = MembershipRule(field=ClassificationField.TAGS, values=["limpet", "sea star"])
    limpet = _asset(id="owl_limpet", tags=["limpet"])
    star = _asset(id="ochre_sea_star", tags=["sea star"])
    neither = _asset(id="turban_snail", tags=["snail"])

    result = resolve_rule(rule, [limpet, star, neither])

    assert {member.asset_id for member in result} == {"owl_limpet", "ochre_sea_star"}


def test_rule_matches_any_of_several_asset_values_for_a_multi_valued_field() -> None:
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"])
    asset = _asset(id="purple_sea_urchin", ecosystems=["Tide pool", "Kelp forest", "Subtidal"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.RULE),))]


def test_rule_match_ignores_case() -> None:
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"])
    asset = _asset(id="purple_sea_urchin", ecosystems=["kelp forest"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.RULE),))]


def test_rule_match_ignores_surrounding_whitespace() -> None:
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["  Kelp forest  "])
    asset = _asset(id="purple_sea_urchin", ecosystems=["Kelp forest"])

    result = resolve_rule(rule, [asset])

    assert result == [ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.RULE),))]


def test_rule_match_is_exact_not_substring() -> None:
    """ "tide pool" does not match "tide pool rock" (§11)."""
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["tide pool"])
    asset = _asset(id="ochre_sea_star", ecosystems=["tide pool rock"])

    result = resolve_rule(rule, [asset])

    assert result == []


def test_rule_matching_nothing_resolves_to_an_empty_list() -> None:
    rule = MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Deep sea vent"])
    asset = _asset(id="ochre_sea_star", ecosystems=["Tide pool"])

    result = resolve_rule(rule, [asset])

    assert result == []


# --- resolve_membership: explicit and rule together (§11, §12) --------------------


def test_resolve_membership_with_only_a_rule_produces_rule_members() -> None:
    membership = Membership(
        rule=MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"])
    )
    asset = _asset(id="purple_sea_urchin", ecosystems=["Kelp forest"])

    result = resolve_membership(membership, [asset])

    assert result.members == [ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.RULE),))]
    assert result.unknown_asset_ids == []


def test_resolve_membership_with_only_explicit_ids_matches_resolve_explicit() -> None:
    membership = Membership(asset_ids=["ochre_sea_star"])
    asset = _asset(id="ochre_sea_star")

    result = resolve_membership(membership, [asset])

    assert result.members == [ResolvedMember("ochre_sea_star", (WayIn(WayInKind.EXPLICIT),))]


def test_resolve_membership_mixed_lists_the_deduplicated_union() -> None:
    """A collection with both an explicit list and a rule has the
    de-duplicated union of both as members (§11)."""
    membership = Membership(
        asset_ids=["owl_limpet"],
        rule=MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"]),
    )
    explicit_only = _asset(id="owl_limpet", ecosystems=["Rocky intertidal"])
    rule_only = _asset(id="purple_sea_urchin", ecosystems=["Kelp forest"])

    result = resolve_membership(membership, [explicit_only, rule_only])

    assert {member.asset_id for member in result.members} == {"owl_limpet", "purple_sea_urchin"}


def test_resolve_membership_mixed_member_matched_both_ways_lists_both_once() -> None:
    """A member that got in both explicitly and by rule appears once, with
    both ways in (§11)."""
    membership = Membership(
        asset_ids=["purple_sea_urchin"],
        rule=MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Kelp forest"]),
    )
    asset = _asset(id="purple_sea_urchin", ecosystems=["Kelp forest"])

    result = resolve_membership(membership, [asset])

    assert result.members == [
        ResolvedMember("purple_sea_urchin", (WayIn(WayInKind.EXPLICIT), WayIn(WayInKind.RULE)))
    ]
