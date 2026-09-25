"""catalog.collection_resolution: wiring the domain's pure membership
resolution (explicit list, rule, and collection union) to a loaded
catalog's assets and collections, and turning an unknown explicit asset ID,
an unknown collection slug, or a cycle into a reference problem (§11, §12,
§13, §34).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.collection_resolution import (
    MEMBERSHIP_ASSET_IDS_FIELD,
    MEMBERSHIP_COLLECTION_SLUGS_FIELD,
    collection_toml_path,
    lookup_and_resolve_collection,
    resolve_collection,
    resolve_collections,
)
from vectorpress.catalog.collections import find_collection, load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.collection_resolution import WayIn, WayInKind

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PACIFIC_COAST_MEMBERS = {"ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"}


def _asset(**overrides: object) -> Asset:
    """A minimal, fully-populated asset for tests that fabricate
    "known assets" rather than loading the real fixture."""
    fields: dict[str, object] = {
        "id": "test_asset",
        "common_name": "Test asset",
        "display_name": "Test Asset",
        "description": "A test asset.",
        "subject_category": "Echinoderm",
        "taxonomic_group": "Echinoderm",
        "rights_status": RightsStatus.ORIGINAL_ARTWORK,
        "accuracy_status": AccuracyStatus.APPROVED,
        "sources": [Source(role="silhouette", file="silhouette.png")],
    }
    fields.update(overrides)
    return Asset(**fields)  # type: ignore[arg-type]


def _known_assets(*asset_ids: str) -> list[Asset]:
    """A list of bare-bones known assets, one per ID -- used where a test
    only needs the explicit-list ID set, not real classification data."""
    return [_asset(id=asset_id) for asset_id in asset_ids]


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _collection_toml(root: Path, slug: str) -> Path:
    return root / "collections" / f"{slug}.toml"


# --- resolve_collection: the explicit form, against the real fixture ----------------


def test_resolving_the_explicit_fixture_collection_lists_exactly_its_three_members() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "pacific_coast_tide_pool")
    assert collection is not None

    resolved = resolve_collection(
        collection, config, known_assets=_known_assets(*PACIFIC_COAST_MEMBERS)
    )

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert all(member.ways_in[0].kind is WayInKind.EXPLICIT for member in resolved.members)
    assert resolved.reference_problems == []


def test_resolving_the_rule_fixture_collection_lists_the_kelp_forest_asset() -> None:
    """``kelp_forest_ecosystem``'s rule (``ecosystems`` includes "Kelp
    forest") matches ``purple_sea_urchin`` and no other fixture asset --
    the same acceptance walkthrough ``vpress collection
    kelp_forest_ecosystem`` runs (§11)."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "kelp_forest_ecosystem")
    assert collection is not None
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets

    resolved = resolve_collection(collection, config, known_assets=known_assets)

    assert [member.asset_id for member in resolved.members] == ["purple_sea_urchin"]
    assert resolved.members[0].ways_in == (WayIn(WayInKind.RULE),)
    assert resolved.reference_problems == []


def test_a_rule_matching_no_asset_resolves_to_no_members_and_no_problem() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "kelp_forest_ecosystem")
    assert collection is not None

    resolved = resolve_collection(
        collection, config, known_assets=_known_assets("some_other_asset")
    )

    assert resolved.members == []
    assert resolved.reference_problems == []


# --- an unknown asset ID is a reference problem, not a stop ------------------------


def test_an_unknown_asset_id_is_a_reference_problem_and_the_rest_still_resolve(
    catalog_copy: Path,
) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        '"purple_sea_urchin"]', '"purple_sea_urchin", "not_a_real_asset"]'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "pacific_coast_tide_pool")
    assert collection is not None

    resolved = resolve_collection(
        collection, config, known_assets=_known_assets(*PACIFIC_COAST_MEMBERS)
    )

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert len(resolved.reference_problems) == 1
    problem = resolved.reference_problems[0]
    assert problem.path == Path("collections") / "pacific_coast_tide_pool.toml"
    assert problem.field == MEMBERSHIP_ASSET_IDS_FIELD
    assert "not_a_real_asset" in problem.message


def test_an_asset_id_whose_own_file_failed_to_load_is_also_a_reference_problem() -> None:
    """ "No loaded asset has it" covers a failed-to-load asset too: its ID is
    simply absent from ``known_assets``, the same as a genuinely
    nonexistent one."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "pacific_coast_tide_pool")
    assert collection is not None

    # purple_sea_urchin omitted from known_assets, as if its own asset.toml
    # had failed to load.
    resolved = resolve_collection(
        collection, config, known_assets=_known_assets("ochre_sea_star", "giant_green_anemone")
    )

    assert {member.asset_id for member in resolved.members} == {
        "ochre_sea_star",
        "giant_green_anemone",
    }
    assert len(resolved.reference_problems) == 1
    assert "purple_sea_urchin" in resolved.reference_problems[0].message


def test_resolve_collections_gathers_every_collections_own_problems(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        '"purple_sea_urchin"]', '"purple_sea_urchin", "not_a_real_asset"]'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)

    resolved_all = resolve_collections(
        inventory.collections,
        config,
        known_assets=_known_assets(*PACIFIC_COAST_MEMBERS, "turban_snail"),
    )

    total_problems = [p for r in resolved_all for p in r.reference_problems]
    assert len(total_problems) == 1
    assert "not_a_real_asset" in total_problems[0].message


# --- a mixed explicit + rule collection: de-duplicated union, both ways in --------


def test_mixed_membership_lists_the_deduplicated_union_with_both_ways_in(
    catalog_copy: Path,
) -> None:
    """A collection with both an explicit list and a rule lists the
    de-duplicated union of both as members; a doubly-matched member lists
    both ways in (§11)."""
    path = _collection_toml(catalog_copy, "kelp_forest_ecosystem")
    text = path.read_text(encoding="utf-8")
    # owl_limpet does not match the rule; adding it explicitly, alongside
    # purple_sea_urchin (already a rule match), exercises both the union
    # and the doubly-matched member in one collection. asset_ids must land
    # in [membership] itself, before the [membership.rule] subtable.
    text = text.replace(
        "[membership.rule]",
        '[membership]\nasset_ids = ["owl_limpet", "purple_sea_urchin"]\n\n[membership.rule]',
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "kelp_forest_ecosystem")
    assert collection is not None

    known_assets = load_assets(catalog_copy, config).assets

    resolved = resolve_collection(collection, config, known_assets=known_assets)

    members_by_id = {member.asset_id: member.ways_in for member in resolved.members}
    assert members_by_id == {
        "owl_limpet": (WayIn(WayInKind.EXPLICIT),),
        "purple_sea_urchin": (WayIn(WayInKind.EXPLICIT), WayIn(WayInKind.RULE)),
    }


# --- union and mixed collections: membership.collection_slugs (§11, §13) ----------


def _write_collection_toml(root: Path, slug: str, membership_toml: str) -> None:
    """A minimal, valid collection file naming only the parts a union test
    needs to vary."""
    path = _collection_toml(root, slug)
    path.write_text(
        f'name = "{slug}"\n'
        f'description = "test collection"\n'
        f'marketplace_category = "Nature & Wildlife"\n\n'
        f"{membership_toml}\n",
        encoding="utf-8",
    )


def test_resolving_the_union_fixture_collection_lists_the_deduplicated_members(
    catalog_copy: Path,
) -> None:
    """``pacific_coast_marine`` unions ``pacific_coast_tide_pool`` and
    ``kelp_forest_ecosystem`` plus ``turban_snail`` explicitly:
    ``purple_sea_urchin`` -- a member of both unioned collections -- appears
    once, with both "via" ways in (§13), the acceptance walkthrough ``vpress
    collection pacific_coast_marine`` runs."""
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "pacific_coast_marine")
    assert collection is not None
    known_assets = load_assets(catalog_copy, config).assets

    resolved = resolve_collection(collection, config, known_assets, inventory.collections)

    members_by_id = {member.asset_id: member.ways_in for member in resolved.members}
    assert members_by_id == {
        "turban_snail": (WayIn(WayInKind.EXPLICIT),),
        "ochre_sea_star": (WayIn(WayInKind.VIA, "pacific_coast_tide_pool"),),
        "giant_green_anemone": (WayIn(WayInKind.VIA, "pacific_coast_tide_pool"),),
        "purple_sea_urchin": (
            WayIn(WayInKind.VIA, "kelp_forest_ecosystem"),
            WayIn(WayInKind.VIA, "pacific_coast_tide_pool"),
        ),
    }
    assert resolved.reference_problems == []


def test_a_newly_added_matching_asset_appears_in_the_union_without_editing_either_file(
    catalog_copy: Path,
) -> None:
    """Adding a new kelp-forest asset to the catalog makes it appear in
    ``pacific_coast_marine`` too -- through ``kelp_forest_ecosystem``'s own
    live rule resolution -- without touching either collection's file
    (§11, §12, §13)."""
    kelp_before = _collection_toml(catalog_copy, "kelp_forest_ecosystem").read_text(
        encoding="utf-8"
    )
    marine_before = _collection_toml(catalog_copy, "pacific_coast_marine").read_text(
        encoding="utf-8"
    )
    source_dir = catalog_copy / "assets" / "bat_star"
    new_dir = catalog_copy / "assets" / "sunflower_star"
    shutil.copytree(source_dir, new_dir)
    asset_toml = new_dir / "asset.toml"
    original = asset_toml.read_text(encoding="utf-8")
    target = 'ecosystems = ["Subtidal", "Rocky reef"]'
    assert target in original  # guards against a silent no-op if bat_star's fixture changes
    asset_toml.write_text(
        original.replace(target, 'ecosystems = ["kelp forest"]'), encoding="utf-8"
    )
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "pacific_coast_marine")
    assert collection is not None
    known_assets = load_assets(catalog_copy, config).assets

    resolved = resolve_collection(collection, config, known_assets, inventory.collections)

    assert "sunflower_star" in {member.asset_id for member in resolved.members}
    assert (
        _collection_toml(catalog_copy, "kelp_forest_ecosystem").read_text(encoding="utf-8")
        == kelp_before
    )
    assert (
        _collection_toml(catalog_copy, "pacific_coast_marine").read_text(encoding="utf-8")
        == marine_before
    )


def test_an_unknown_collection_slug_is_a_reference_problem_and_the_rest_still_resolve(
    catalog_copy: Path,
) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_marine")
    target = 'collection_slugs = ["pacific_coast_tide_pool", "kelp_forest_ecosystem"]'
    text = path.read_text(encoding="utf-8")
    assert target in text
    path.write_text(
        text.replace(
            target,
            'collection_slugs = ["pacific_coast_tide_pool", "kelp_forest_ecosystem",'
            ' "not_a_real_collection"]',
        ),
        encoding="utf-8",
    )
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "pacific_coast_marine")
    assert collection is not None
    known_assets = load_assets(catalog_copy, config).assets

    resolved = resolve_collection(collection, config, known_assets, inventory.collections)

    assert {member.asset_id for member in resolved.members} >= PACIFIC_COAST_MEMBERS
    assert len(resolved.reference_problems) == 1
    problem = resolved.reference_problems[0]
    assert problem.path == Path("collections") / "pacific_coast_marine.toml"
    assert problem.field == MEMBERSHIP_COLLECTION_SLUGS_FIELD
    assert "not_a_real_collection" in problem.message


def test_a_self_cycle_terminates_and_is_a_reference_problem(catalog_copy: Path) -> None:
    _write_collection_toml(catalog_copy, "loop", '[membership]\ncollection_slugs = ["loop"]')
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection = find_collection(inventory, "loop")
    assert collection is not None

    resolved = resolve_collection(
        collection, config, known_assets=[], known_collections=inventory.collections
    )

    assert resolved.members == []
    assert len(resolved.reference_problems) == 1
    problem = resolved.reference_problems[0]
    assert problem.field == MEMBERSHIP_COLLECTION_SLUGS_FIELD
    assert "loop -> loop" in problem.message


def test_a_two_collection_cycle_terminates_and_is_a_reference_problem(catalog_copy: Path) -> None:
    _write_collection_toml(catalog_copy, "cycle_a", '[membership]\ncollection_slugs = ["cycle_b"]')
    _write_collection_toml(catalog_copy, "cycle_b", '[membership]\ncollection_slugs = ["cycle_a"]')
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)
    collection_a = find_collection(inventory, "cycle_a")
    assert collection_a is not None

    resolved = resolve_collection(
        collection_a, config, known_assets=[], known_collections=inventory.collections
    )

    assert resolved.members == []
    assert len(resolved.reference_problems) == 1
    assert "cycle_a -> cycle_b -> cycle_a" in resolved.reference_problems[0].message


def test_resolve_collections_resolves_the_union_within_the_same_catalog_pass() -> None:
    """``resolve_collections`` (plural) supplies every collection it loaded
    as the ``known_collections`` each one's union resolves against, so
    ``vpress status``/``vpress attention`` see a fully resolved union with
    no extra wiring."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets

    resolved_all = resolve_collections(inventory.collections, config, known_assets)

    marine = next(r for r in resolved_all if r.collection.slug == "pacific_coast_marine")
    assert {member.asset_id for member in marine.members} == {
        "turban_snail",
        "ochre_sea_star",
        "giant_green_anemone",
        "purple_sea_urchin",
    }
    assert marine.reference_problems == []


# --- collection_toml_path -----------------------------------------------------------


def test_collection_toml_path_joins_the_configured_dir_and_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    assert collection_toml_path(config, "pacific_coast_tide_pool") == Path(
        "collections/pacific_coast_tide_pool.toml"
    )


# --- lookup_and_resolve_collection: unknown slug vs. failed-to-load ----------------


def test_lookup_and_resolve_returns_the_resolved_collection_for_a_known_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    result = lookup_and_resolve_collection(
        inventory, config, _known_assets(*PACIFIC_COAST_MEMBERS), "pacific_coast_tide_pool"
    )

    assert result.resolved is not None
    assert result.resolved.collection.slug == "pacific_coast_tide_pool"
    assert result.problems == []


def test_lookup_and_resolve_is_empty_for_a_genuinely_unknown_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    result = lookup_and_resolve_collection(inventory, config, [], "not_a_real_collection")

    assert result.resolved is None
    assert result.problems == []


def test_lookup_and_resolve_reports_problems_for_a_slug_that_failed_to_load(
    catalog_copy: Path,
) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        'marketplace_category = "Nature & Wildlife"\n', ""
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)
    inventory = load_collections(catalog_copy, config)

    result = lookup_and_resolve_collection(inventory, config, [], "pacific_coast_tide_pool")

    assert result.resolved is None
    assert len(result.problems) == 1
    assert result.problems[0].field == "marketplace_category"
