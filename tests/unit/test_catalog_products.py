"""catalog.products: load every product under a catalog's products
directory (§7, §18, ADR 0008, issue #7).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.load import load_catalog_config
from vectorpress.catalog.products import find_product, load_products
from vectorpress.domain.membership import MembershipForm

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _product_toml(root: Path, slug: str) -> Path:
    return root / "products" / f"{slug}.toml"


def test_fixture_catalog_loads_two_valid_products() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    assert [p.slug for p in inventory.products] == [
        "kelp_forest_mini_pack",
        "pacific_coast_tide_pool_standard_pack",
    ]
    assert inventory.problems == []


def test_products_are_sorted_by_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    slugs = [p.slug for p in inventory.products]
    assert slugs == sorted(slugs)


def test_product_over_a_collection_slug_has_its_reference_and_full_listing() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    over_collection = find_product(inventory, "pacific_coast_tide_pool_standard_pack")
    assert over_collection is not None
    assert over_collection.collection_slug == "pacific_coast_tide_pool"
    assert over_collection.membership is None
    assert over_collection.listing is not None
    assert over_collection.listing.title == "Pacific Coast Tide Pool Cut File Collection"


def test_product_with_inline_membership_has_no_listing() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    inline = find_product(inventory, "kelp_forest_mini_pack")
    assert inline is not None
    assert inline.collection_slug is None
    assert inline.membership is not None
    assert inline.membership.form is MembershipForm.RULE
    assert inline.listing is None


def test_missing_products_dir_is_empty_not_an_error(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "catalog.toml").write_text('name = "Empty"\n', encoding="utf-8")
    config = load_catalog_config(root)

    inventory = load_products(root, config)

    assert inventory.products == []
    assert inventory.problems == []


def test_both_collection_slug_and_inline_membership_is_a_problem(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "pacific_coast_tide_pool_standard_pack")
    text = path.read_text(encoding="utf-8")
    text += '\n[membership]\nasset_ids = ["ochre_sea_star"]\n'
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "pacific_coast_tide_pool_standard_pack" not in slugs
    assert len(inventory.problems) == 1
    assert "pacific_coast_tide_pool_standard_pack" in str(inventory.problems[0].path)


def test_neither_collection_slug_nor_inline_membership_is_a_problem(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "pacific_coast_tide_pool_standard_pack")
    text = path.read_text(encoding="utf-8").replace(
        'collection_slug = "pacific_coast_tide_pool"\n', ""
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "pacific_coast_tide_pool_standard_pack" not in slugs
    assert len(inventory.problems) == 1


def test_unknown_derivative_type_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    text = path.read_text(encoding="utf-8").replace(
        'derivative_types = ["cut_svg"]', 'derivative_types = ["not_a_real_type"]'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "kelp_forest_mini_pack" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "kelp_forest_mini_pack" in str(problem.path)
    assert problem.field == "derivative_types.0"


def test_format_outside_section_7_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    text = path.read_text(encoding="utf-8").replace('formats = ["svg"]', 'formats = ["webp"]')
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "kelp_forest_mini_pack" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "kelp_forest_mini_pack" in str(problem.path)
    assert problem.field == "formats.0"


def test_pdf_without_explicit_enablement_is_a_problem_naming_file_and_field(
    catalog_copy: Path,
) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    text = path.read_text(encoding="utf-8").replace('formats = ["svg"]', 'formats = ["svg", "pdf"]')
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "kelp_forest_mini_pack" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "kelp_forest_mini_pack" in str(problem.path)
    assert problem.field == "formats"


def test_eps_without_explicit_enablement_is_a_problem(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    text = path.read_text(encoding="utf-8").replace('formats = ["svg"]', 'formats = ["svg", "eps"]')
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    assert "kelp_forest_mini_pack" not in {p.slug for p in inventory.products}
    assert len(inventory.problems) == 1


def test_pdf_with_explicit_enablement_is_accepted(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    text = path.read_text(encoding="utf-8").replace(
        'formats = ["svg"]', 'formats = ["svg", "pdf"]\nenable_pdf_eps = true'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    assert "kelp_forest_mini_pack" in {p.slug for p in inventory.products}
    assert inventory.problems == []


def test_unknown_listing_key_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "pacific_coast_tide_pool_standard_pack")
    text = path.read_text(encoding="utf-8").replace(
        'title = "Pacific Coast Tide Pool Cut File Collection"\n',
        'title = "Pacific Coast Tide Pool Cut File Collection"\nnot_a_field = true\n',
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "pacific_coast_tide_pool_standard_pack" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "pacific_coast_tide_pool_standard_pack" in str(problem.path)
    assert problem.field == "listing.not_a_field"


def test_mismatched_slug_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    path.write_text(
        'slug = "not_the_file_name"\n' + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    slugs = {p.slug for p in inventory.products}
    assert "kelp_forest_mini_pack" not in slugs
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "kelp_forest_mini_pack" in str(problem.path)
    assert problem.field == "slug"
    assert "not_the_file_name" in problem.message


def test_slug_matching_file_name_is_accepted(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    path.write_text(
        'slug = "kelp_forest_mini_pack"\n' + path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    assert inventory.problems == []
    assert "kelp_forest_mini_pack" in {p.slug for p in inventory.products}


def test_toml_syntax_error_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    path = _product_toml(catalog_copy, "kelp_forest_mini_pack")
    path.write_text('derivative_types = ["unterminated\n', encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_products(catalog_copy, config)

    assert len(inventory.products) == 1
    assert len(inventory.problems) == 1
    assert "kelp_forest_mini_pack" in str(inventory.problems[0].path)


def test_find_product_returns_the_matching_loaded_product() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    found = find_product(inventory, "kelp_forest_mini_pack")

    assert found is not None
    assert found.slug == "kelp_forest_mini_pack"


def test_find_product_returns_none_for_an_unknown_slug() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_products(FIXTURE_CATALOG_ROOT, config)

    assert find_product(inventory, "not_a_real_product") is None


# --- duplicate slugs (issue #5's pattern, reused per issue #7) ---------------------


def test_load_products_reports_a_duplicate_slug_problem_from_the_directory_scan(
    tmp_path: Path,
) -> None:
    """End-to-end through ``load_products``, guarded by a check that both
    files actually landed on disk, same rationale as the collections test
    this mirrors: a case-sensitive filesystem is needed for two files whose
    stems are case-variants of each other to coexist for real.
    """
    root = tmp_path / "catalog"
    (root / "products").mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Dup Test"\n', encoding="utf-8")
    product_toml = (
        'collection_slug = "x"\nderivative_types = ["cut_svg"]\nformats = ["svg"]\n'
        'tier = "individual"\nprice = 1.0\n'
    )
    (root / "products" / "Foo.toml").write_text(product_toml, encoding="utf-8")
    (root / "products" / "foo.toml").write_text(product_toml, encoding="utf-8")
    stems_on_disk = {p.stem for p in (root / "products").iterdir()}
    if len(stems_on_disk) < 2:
        pytest.skip(
            "this filesystem coalesced Foo.toml and foo.toml into one file; "
            "the normalising comparison is covered directly in "
            "test_catalog_collections.py"
        )
    config = load_catalog_config(root)

    inventory = load_products(root, config)

    assert len(inventory.problems) == 2
    assert all(p.field == "slug" for p in inventory.problems)
    assert inventory.products == []


def test_load_products_excludes_duplicate_slug_files_from_products(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the same exclusion as the test above without depending on a real
    filesystem allowing two case-variant filenames to coexist (mirrors
    ``test_load_collections_excludes_duplicate_slug_files_from_collections``).
    """
    root = tmp_path / "catalog"
    products_dir = root / "products"
    sub_a = products_dir / "a"
    sub_b = products_dir / "b"
    sub_a.mkdir(parents=True)
    sub_b.mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Dup Test"\n', encoding="utf-8")
    product_toml = (
        'collection_slug = "x"\nderivative_types = ["cut_svg"]\nformats = ["svg"]\n'
        'tier = "individual"\nprice = 1.0\n'
    )
    foo_upper = sub_a / "Foo.toml"
    foo_lower = sub_b / "foo.toml"
    foo_upper.write_text(product_toml, encoding="utf-8")
    foo_lower.write_text(product_toml, encoding="utf-8")

    real_iterdir = Path.iterdir

    def fake_iterdir(self: Path):
        if self == products_dir:
            return iter([foo_upper, foo_lower])
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    config = load_catalog_config(root)

    inventory = load_products(root, config)

    assert inventory.products == []
    assert len(inventory.problems) == 2
    assert all(p.field == "slug" for p in inventory.problems)
