"""catalog.collections: load every collection under a catalog's collections
directory (§11, ADR 0008, issue #5).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.collections import (
    duplicate_slug_problems,  # pure helper, tested directly below
    find_collection,
    load_collections,
)
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.membership import MembershipForm

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _collection_toml(root: Path, slug: str) -> Path:
    return root / "collections" / f"{slug}.toml"


def test_fixture_catalog_loads_two_valid_collections() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    assert [c.slug for c in inventory.collections] == [
        "kelp_forest_ecosystem",
        "pacific_coast_tide_pool",
    ]
    assert inventory.problems == []


def test_collections_are_sorted_by_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    slugs = [c.slug for c in inventory.collections]
    assert slugs == sorted(slugs)


def test_explicit_collection_has_explicit_form_and_its_asset_ids() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    explicit = find_collection(inventory, "pacific_coast_tide_pool")
    assert explicit is not None
    assert explicit.membership.form is MembershipForm.EXPLICIT
    assert explicit.membership.asset_ids == [
        "ochre_sea_star",
        "giant_green_anemone",
        "purple_sea_urchin",
    ]


def test_rule_collection_has_rule_form_and_its_clause() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    rule_based = find_collection(inventory, "kelp_forest_ecosystem")
    assert rule_based is not None
    assert rule_based.membership.form is MembershipForm.RULE
    assert rule_based.membership.rule is not None
    assert rule_based.membership.rule.field.value == "ecosystems"
    assert rule_based.membership.rule.values == ["Kelp forest"]


def test_missing_collections_dir_is_empty_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "catalog.toml").write_text('name = "Empty"\n', encoding="utf-8")
    config = load_catalog_config(root)

    inventory = load_collections(root, config)

    assert inventory.collections == []
    assert inventory.problems == []


def test_missing_required_field_is_a_problem_and_other_collections_still_load(
    catalog_copy: Path,
) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        'marketplace_category = "Nature & Wildlife"\n', ""
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    slugs = {c.slug for c in inventory.collections}
    assert "kelp_forest_ecosystem" in slugs
    assert "pacific_coast_tide_pool" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "pacific_coast_tide_pool" in str(problem.path)
    assert problem.field == "marketplace_category"


def test_unknown_key_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        'marketplace_category = "Nature & Wildlife"',
        'marketplace_category = "Nature & Wildlife"\nnot_a_field = true',
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    slugs = {c.slug for c in inventory.collections}
    assert "pacific_coast_tide_pool" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "pacific_coast_tide_pool" in str(problem.path)
    assert problem.field == "not_a_field"


def test_rule_over_an_unknown_classification_field_is_a_problem(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "kelp_forest_ecosystem")
    text = path.read_text(encoding="utf-8").replace(
        'field = "ecosystems"', 'field = "not_a_real_field"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    slugs = {c.slug for c in inventory.collections}
    assert "kelp_forest_ecosystem" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "kelp_forest_ecosystem" in str(problem.path)
    assert problem.field == "membership.rule.field"


def test_mismatched_slug_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    path.write_text(
        'slug = "not_the_file_name"\n' + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    slugs = {c.slug for c in inventory.collections}
    assert "pacific_coast_tide_pool" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "pacific_coast_tide_pool" in str(problem.path)
    assert problem.field == "slug"
    assert "not_the_file_name" in problem.message


def test_slug_matching_file_name_is_accepted(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    path.write_text(
        'slug = "pacific_coast_tide_pool"\n' + path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    assert inventory.problems == []
    assert "pacific_coast_tide_pool" in {c.slug for c in inventory.collections}


def test_toml_syntax_error_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "kelp_forest_ecosystem")
    path.write_text('name = "unterminated\n', encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    assert len(inventory.collections) == 1
    assert len(inventory.problems) == 1
    assert "kelp_forest_ecosystem" in str(inventory.problems[0].path)


def test_empty_membership_is_a_problem(catalog_copy: Path) -> None:
    path = _collection_toml(catalog_copy, "pacific_coast_tide_pool")
    text = path.read_text(encoding="utf-8").replace(
        'asset_ids = ["ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"]\n', ""
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_collections(catalog_copy, config)

    slugs = {c.slug for c in inventory.collections}
    assert "pacific_coast_tide_pool" not in slugs
    assert len(inventory.problems) == 1


def test_find_collection_returns_the_matching_loaded_collection() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    found = find_collection(inventory, "pacific_coast_tide_pool")

    assert found is not None
    assert found.slug == "pacific_coast_tide_pool"


def test_find_collection_returns_none_for_an_unknown_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    assert find_collection(inventory, "not_a_real_collection") is None


def test_committed_fixture_catalog_is_unmodified_by_mutating_tests() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_collections(FIXTURE_CATALOG_ROOT, config)

    assert len(inventory.collections) == 2
    assert inventory.problems == []


# --- duplicate slugs (issue #5) ------------------------------------------------------
#
# Two on-disk files whose stems are case-variants of each other (``Foo.toml``
# and ``foo.toml``) can coexist on a case-sensitive filesystem (Linux CI) but
# not on Windows, where the second write silently overwrites the first —
# so a test that creates such files for real would see two collections on
# Linux and one on Windows, diverging exactly like the issue warns against.
# The normalising comparison itself is therefore tested directly, against
# fabricated paths, independent of what a given OS's filesystem allows.


def test_duplicate_slug_problems_flags_case_variant_stems() -> None:
    problems = duplicate_slug_problems(
        [
            (Path("collections/Foo.toml"), "Foo"),
            (Path("collections/foo.toml"), "foo"),
        ]
    )

    assert len(problems) == 2
    paths = {p.path for p in problems}
    assert paths == {Path("collections/Foo.toml"), Path("collections/foo.toml")}
    assert all(p.field == "slug" for p in problems)
    assert all("duplicate slug" in p.message for p in problems)


def test_duplicate_slug_problems_is_empty_for_distinct_stems() -> None:
    problems = duplicate_slug_problems(
        [
            (Path("collections/kelp_forest_ecosystem.toml"), "kelp_forest_ecosystem"),
            (Path("collections/pacific_coast_tide_pool.toml"), "pacific_coast_tide_pool"),
        ]
    )

    assert problems == []


def test_load_collections_reports_a_duplicate_slug_problem_from_the_directory_scan(
    tmp_path: Path,
) -> None:
    """End-to-end through ``load_collections``, guarded by a check that both
    files actually landed on disk (see the module note above) so the test
    fails loudly rather than silently passing with only one file on a
    filesystem that coalesced the two writes.
    """
    root = tmp_path / "catalog"
    (root / "collections").mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Dup Test"\n', encoding="utf-8")
    collection_toml = (
        'name = "X"\ndescription = "d"\nmarketplace_category = "c"\n'
        '\n[membership]\nasset_ids = ["a"]\n'
    )
    (root / "collections" / "Foo.toml").write_text(collection_toml, encoding="utf-8")
    (root / "collections" / "foo.toml").write_text(collection_toml, encoding="utf-8")
    stems_on_disk = {p.stem for p in (root / "collections").iterdir()}
    if len(stems_on_disk) < 2:
        pytest.skip(
            "this filesystem coalesced Foo.toml and foo.toml into one file; "
            "the normalising comparison is covered directly above"
        )
    config = load_catalog_config(root)

    inventory = load_collections(root, config)

    assert len(inventory.problems) == 2
    assert all(p.field == "slug" for p in inventory.problems)
