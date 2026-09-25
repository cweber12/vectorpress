"""catalog.collection_resolution: wiring the domain's pure explicit
resolution to a loaded catalog's assets and collections, and turning
unknown asset IDs into reference problems (§11, §34).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.collection_resolution import (
    MEMBERSHIP_ASSET_IDS_FIELD,
    collection_toml_path,
    lookup_and_resolve_collection,
    resolve_collection,
    resolve_collections,
)
from vectorpress.catalog.collections import find_collection, load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.collection_resolution import WayInKind

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PACIFIC_COAST_MEMBERS = {"ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"}


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

    resolved = resolve_collection(collection, config, known_asset_ids=PACIFIC_COAST_MEMBERS)

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert all(member.ways_in[0].kind is WayInKind.EXPLICIT for member in resolved.members)
    assert resolved.reference_problems == []


def test_resolving_the_rule_fixture_collection_has_no_explicit_members_or_problems() -> None:
    """This slice resolves only ``membership.asset_ids`` -- a rule
    collection declares none, so it has no members yet and no reference
    problems (a rule value is never a reference problem)."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "kelp_forest_ecosystem")
    assert collection is not None

    resolved = resolve_collection(collection, config, known_asset_ids=PACIFIC_COAST_MEMBERS)

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

    resolved = resolve_collection(collection, config, known_asset_ids=PACIFIC_COAST_MEMBERS)

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert len(resolved.reference_problems) == 1
    problem = resolved.reference_problems[0]
    assert problem.path == Path("collections") / "pacific_coast_tide_pool.toml"
    assert problem.field == MEMBERSHIP_ASSET_IDS_FIELD
    assert "not_a_real_asset" in problem.message


def test_an_asset_id_whose_own_file_failed_to_load_is_also_a_reference_problem() -> None:
    """ "No loaded asset has it" covers a failed-to-load asset too: its ID is
    simply absent from ``known_asset_ids``, the same as a genuinely
    nonexistent one."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)
    collection = find_collection(inventory, "pacific_coast_tide_pool")
    assert collection is not None

    # purple_sea_urchin omitted from known_asset_ids, as if its own
    # asset.toml had failed to load.
    resolved = resolve_collection(
        collection, config, known_asset_ids={"ochre_sea_star", "giant_green_anemone"}
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
        inventory.collections, config, known_asset_ids=PACIFIC_COAST_MEMBERS
    )

    total_problems = [p for r in resolved_all for p in r.reference_problems]
    assert len(total_problems) == 1
    assert "not_a_real_asset" in total_problems[0].message


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
        inventory, config, PACIFIC_COAST_MEMBERS, "pacific_coast_tide_pool"
    )

    assert result.resolved is not None
    assert result.resolved.collection.slug == "pacific_coast_tide_pool"
    assert result.problems == []


def test_lookup_and_resolve_is_empty_for_a_genuinely_unknown_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    result = lookup_and_resolve_collection(inventory, config, set(), "not_a_real_collection")

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

    result = lookup_and_resolve_collection(inventory, config, set(), "pacific_coast_tide_pool")

    assert result.resolved is None
    assert len(result.problems) == 1
    assert result.problems[0].field == "marketplace_category"
