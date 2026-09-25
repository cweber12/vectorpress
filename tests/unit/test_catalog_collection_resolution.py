"""catalog.collection_resolution: wiring the domain's pure membership
resolution (explicit list and rule) to a loaded catalog's assets and
collections, and turning unknown explicit asset IDs into reference problems
(§11, §12, §34).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.collection_resolution import (
    MEMBERSHIP_ASSET_IDS_FIELD,
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
        inventory.collections, config, known_assets=_known_assets(*PACIFIC_COAST_MEMBERS)
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
