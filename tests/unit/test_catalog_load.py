"""catalog.load: read and validate catalog.toml at a catalog root, and the
single load entry point (``load_catalog``) that aggregates metadata
problems from every hand-authored file (issue #6).
"""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.errors import CatalogConfigError
from vectorpress.catalog.load import load_catalog, load_catalog_config

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def _write_catalog_toml(root: Path, text: str) -> Path:
    root.mkdir(exist_ok=True)
    path = root / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def test_load_valid_config(tmp_path: Path) -> None:
    _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\n')

    config = load_catalog_config(tmp_path)

    assert config.name == "Tide Pool Studio"
    assert config.assets_dir == "assets"
    assert config.reference_size_in == 3.0


def test_toml_syntax_error_names_file(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "unterminated\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    assert str(path) in str(exc_info.value)


def test_unknown_key_names_file_and_field(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\nnot_a_field = true\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "not_a_field" in message


def test_wrongly_typed_value_names_file_and_field(tmp_path: Path) -> None:
    path = _write_catalog_toml(tmp_path, 'name = "Tide Pool Studio"\nreference_size_in = "big"\n')

    with pytest.raises(CatalogConfigError) as exc_info:
        load_catalog_config(tmp_path)

    message = str(exc_info.value)
    assert str(path) in message
    assert "reference_size_in" in message


# --- load_catalog: the single load entry point (issue #6) -------------------------


def test_load_catalog_on_the_clean_fixture_has_no_problems() -> None:
    catalog = load_catalog(FIXTURE_CATALOG_ROOT)

    assert catalog.config is not None
    assert catalog.config.name == "Tide Pool Studio"
    assert [asset.id for asset in catalog.assets] == [
        "acorn_barnacle",
        "giant_green_anemone",
        "ochre_sea_star",
        "owl_limpet",
        "purple_sea_urchin",
    ]
    assert [c.slug for c in catalog.collections] == [
        "kelp_forest_ecosystem",
        "pacific_coast_tide_pool",
    ]
    assert [p.slug for p in catalog.products] == [
        "kelp_forest_mini_pack",
        "pacific_coast_tide_pool_standard_pack",
    ]
    assert catalog.brand is not None
    assert catalog.brand.name == "Tide Pool Studio"
    assert catalog.problems == []


def test_load_catalog_without_brand_toml_reports_its_absence(catalog_copy: Path) -> None:
    (catalog_copy / "brand.toml").unlink()

    catalog = load_catalog(catalog_copy)

    assert catalog.config is not None
    assert [asset.id for asset in catalog.assets] == [
        "acorn_barnacle",
        "giant_green_anemone",
        "ochre_sea_star",
        "owl_limpet",
        "purple_sea_urchin",
    ]
    assert catalog.brand is None
    assert len(catalog.problems) == 1
    assert catalog.problems[0].path == Path("brand.toml")


def test_load_catalog_aggregates_brand_problems_alongside_asset_problems(
    catalog_copy: Path,
) -> None:
    asset_path = catalog_copy / "assets" / "ochre_sea_star" / "asset.toml"
    asset_path.write_text(
        asset_path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    brand_path = catalog_copy / "brand.toml"
    brand_path.write_text(
        brand_path.read_text(encoding="utf-8").replace(
            'mark_file = "mark.png"', 'mark_file = "does_not_exist.png"'
        ),
        encoding="utf-8",
    )

    catalog = load_catalog(catalog_copy)

    assert catalog.brand is None
    assert len(catalog.problems) == 2
    paths = {problem.path for problem in catalog.problems}
    assert Path("assets") / "ochre_sea_star" / "asset.toml" in paths
    assert Path("brand.toml") in paths


def test_load_catalog_with_a_broken_catalog_toml_is_a_problem_not_a_raise(
    tmp_path: Path,
) -> None:
    root = tmp_path / "catalog"
    _write_catalog_toml(root, 'name = "Broken"\nreference_size_in = "big"\n')

    catalog = load_catalog(root)

    assert catalog.config is None
    assert catalog.assets == []
    assert catalog.collections == []
    assert len(catalog.problems) == 1
    problem = catalog.problems[0]
    assert problem.path == Path("catalog.toml")
    assert "reference_size_in" in problem.message


def test_load_catalog_aggregates_asset_problems_and_keeps_the_valid_assets(
    catalog_copy: Path,
) -> None:
    path = catalog_copy / "assets" / "ochre_sea_star" / "asset.toml"
    text = path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', "")
    path.write_text(text, encoding="utf-8")

    catalog = load_catalog(catalog_copy)

    loaded_ids = {asset.id for asset in catalog.assets}
    assert loaded_ids == {
        "acorn_barnacle",
        "giant_green_anemone",
        "owl_limpet",
        "purple_sea_urchin",
    }
    assert len(catalog.problems) == 1
    assert "ochre_sea_star" in str(catalog.problems[0].path)
    assert catalog.problems[0].field == "subject_category"


def test_load_catalog_aggregates_collection_problems_alongside_asset_problems(
    catalog_copy: Path,
) -> None:
    asset_path = catalog_copy / "assets" / "ochre_sea_star" / "asset.toml"
    asset_path.write_text(
        asset_path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    collection_path = catalog_copy / "collections" / "pacific_coast_tide_pool.toml"
    collection_path.write_text(
        collection_path.read_text(encoding="utf-8").replace(
            'marketplace_category = "Nature & Wildlife"\n', ""
        ),
        encoding="utf-8",
    )

    catalog = load_catalog(catalog_copy)

    assert len(catalog.problems) == 2
    paths = {problem.path for problem in catalog.problems}
    assert Path("assets") / "ochre_sea_star" / "asset.toml" in paths
    assert Path("collections") / "pacific_coast_tide_pool.toml" in paths
    loaded_slugs = {c.slug for c in catalog.collections}
    assert loaded_slugs == {"kelp_forest_ecosystem"}


def test_load_catalog_root_is_the_catalog_root_passed_in() -> None:
    catalog = load_catalog(FIXTURE_CATALOG_ROOT)

    assert catalog.root == FIXTURE_CATALOG_ROOT


def test_load_catalog_problem_messages_never_carry_pydantics_value_error_prefix(
    catalog_copy: Path,
) -> None:
    """Issue #16: a cross-field ``model_validator`` check has nothing pydantic
    can call "the field", and whatever the field, pydantic prefixes a raised
    exception's message with "Value error, " (or, for an ``assert``,
    "Assertion failed, "). Neither should ever reach a rendered
    ``MetadataProblem``, across every hand-authored-file loader that shares
    ``problems_from_validation_error``: this breaks an asset, the brand, a
    collection and a product, each in a way that actually raises a pydantic
    ``ValidationError`` out of that loader's ``model_validate`` call (not a
    catalog-layer check like ``brand``'s mark-file-exists, which never goes
    through ``problems_from_validation_error`` and so proves nothing here),
    and confirms all four problems are present before checking every
    message.
    """
    asset_path = catalog_copy / "assets" / "ochre_sea_star" / "asset.toml"
    asset_path.write_text(
        asset_path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    # Brand: drop a required field so Brand.model_validate itself fails
    # (as opposed to load_brand's separate, hand-built mark-file-exists
    # check, which was never pydantic-wrapped and so never exercises
    # problems_from_validation_error).
    brand_path = catalog_copy / "brand.toml"
    brand_path.write_text(
        brand_path.read_text(encoding="utf-8").replace('name = "Tide Pool Studio"\n', ""),
        encoding="utf-8",
    )
    # Collection: an emptied-out [membership] table (model-level check).
    collection_path = catalog_copy / "collections" / "kelp_forest_ecosystem.toml"
    collection_path.write_text(
        collection_path.read_text(encoding="utf-8").replace(
            '[membership.rule]\nfield = "ecosystems"\nvalues = ["Kelp forest"]\n',
            "[membership]\n",
        ),
        encoding="utf-8",
    )
    # Product: both a collection slug and an inline membership (model-level
    # check with no single field pydantic can name).
    product_path = catalog_copy / "products" / "pacific_coast_tide_pool_standard_pack.toml"
    product_path.write_text(
        product_path.read_text(encoding="utf-8")
        + '\n[membership]\nasset_ids = ["ochre_sea_star"]\n',
        encoding="utf-8",
    )

    catalog = load_catalog(catalog_copy)

    # Pin exactly which file each problem came from, so a loader whose
    # break silently failed to produce a problem (as brand's did before
    # this test was fixed) cannot pass this test vacuously.
    problems_by_path = {problem.path: problem for problem in catalog.problems}
    assert len(catalog.problems) == 4
    assert Path("assets") / "ochre_sea_star" / "asset.toml" in problems_by_path
    assert Path("brand.toml") in problems_by_path
    assert Path("collections") / "kelp_forest_ecosystem.toml" in problems_by_path
    assert Path("products") / "pacific_coast_tide_pool_standard_pack.toml" in problems_by_path
    assert catalog.brand is None
    for problem in catalog.problems:
        assert not problem.message.startswith("Value error,"), problem
        assert not problem.message.startswith("Assertion failed,"), problem


def test_load_catalog_aggregates_product_problems_alongside_collection_problems(
    catalog_copy: Path,
) -> None:
    collection_path = catalog_copy / "collections" / "pacific_coast_tide_pool.toml"
    collection_path.write_text(
        collection_path.read_text(encoding="utf-8").replace(
            'marketplace_category = "Nature & Wildlife"\n', ""
        ),
        encoding="utf-8",
    )
    product_path = catalog_copy / "products" / "kelp_forest_mini_pack.toml"
    product_path.write_text(
        product_path.read_text(encoding="utf-8").replace(
            'derivative_types = ["cut_svg"]', 'derivative_types = ["not_a_real_type"]'
        ),
        encoding="utf-8",
    )

    catalog = load_catalog(catalog_copy)

    assert len(catalog.problems) == 2
    paths = {problem.path for problem in catalog.problems}
    assert Path("collections") / "pacific_coast_tide_pool.toml" in paths
    assert Path("products") / "kelp_forest_mini_pack.toml" in paths
    loaded_slugs = {p.slug for p in catalog.products}
    assert loaded_slugs == {"pacific_coast_tide_pool_standard_pack"}
