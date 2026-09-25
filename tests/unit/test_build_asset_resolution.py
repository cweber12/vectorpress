"""build.asset_resolution: reuse made visible from the asset's own side --
every collection and product one asset currently belongs to (§33, §34,
ADR 0008, ADR 0011).

Runs against the real, committed fixture catalog directly: resolution is
read-only, so every asset reads as nothing-generated-yet, the same starting
state ``tests/unit/test_build_product_resolution.py`` runs against.
``purple_sea_urchin`` is the fixture's own reuse example: explicit in
``pacific_coast_tide_pool``, rule-matched into ``kelp_forest_ecosystem``,
and pulled into ``pacific_coast_marine`` via both of those --
``tests/fixtures/catalog/collections/pacific_coast_marine.toml``'s own
comment names this exact case.
"""

from pathlib import Path

from vectorpress.build.asset_resolution import AssetReuse, resolve_asset_reuse
from vectorpress.build.product_resolution import MemberEligibility
from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.catalog.products import load_products
from vectorpress.domain.collection_resolution import WayIn, WayInKind
from vectorpress.domain.derivative_type import DerivativeType

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def _resolve(asset_id: str) -> AssetReuse:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    known_products = load_products(FIXTURE_CATALOG_ROOT, config).products
    return resolve_asset_reuse(
        asset_id, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections, known_products
    )


def test_purple_sea_urchin_lists_every_collection_it_belongs_to_with_how_it_got_in() -> None:
    reuse = _resolve("purple_sea_urchin")

    by_slug = {membership.collection.slug: membership.ways_in for membership in reuse.collections}
    assert set(by_slug) == {
        "pacific_coast_tide_pool",
        "kelp_forest_ecosystem",
        "pacific_coast_marine",
    }
    assert by_slug["pacific_coast_tide_pool"] == (WayIn(WayInKind.EXPLICIT),)
    assert by_slug["kelp_forest_ecosystem"] == (WayIn(WayInKind.RULE),)
    # pulled into the union collection through both contributing collections.
    assert set(by_slug["pacific_coast_marine"]) == {
        WayIn(WayInKind.VIA, "pacific_coast_tide_pool"),
        WayIn(WayInKind.VIA, "kelp_forest_ecosystem"),
    }


def test_purple_sea_urchin_lists_every_product_it_belongs_to_with_its_own_eligibility() -> None:
    reuse = _resolve("purple_sea_urchin")

    by_slug = {membership.product.slug: membership for membership in reuse.products}
    assert set(by_slug) == {
        "pacific_coast_tide_pool_standard_pack",
        "pacific_coast_tide_pool_png_only",
        "kelp_forest_mini_pack",
    }
    # nothing generated yet: excluded everywhere, each for that product's
    # own derivative types.
    for membership in by_slug.values():
        assert membership.eligibility is MemberEligibility.EXCLUDED
    assert [
        reason.derivative_type for reason in by_slug["kelp_forest_mini_pack"].blocking_reasons
    ] == [DerivativeType.CUT_SVG]
    assert {
        reason.derivative_type
        for reason in by_slug["pacific_coast_tide_pool_standard_pack"].blocking_reasons
    } == {DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG, DerivativeType.TRANSPARENT_PNG}


def test_an_asset_in_no_collection_or_product_resolves_to_neither() -> None:
    """``bat_star``'s own ``asset.toml`` notes its ecosystems deliberately
    match no rule-based fixture collection, and it is not on any explicit
    list either -- so both come back empty, never a lookup error."""
    reuse = _resolve("bat_star")

    assert reuse.collections == []
    assert reuse.products == []


def test_an_asset_in_a_collection_but_no_product_lists_only_the_collection() -> None:
    """``turban_snail`` is explicit in ``pacific_coast_marine`` (its
    ``asset_ids``) but is a member of no product in the fixture."""
    reuse = _resolve("turban_snail")

    assert [m.collection.slug for m in reuse.collections] == ["pacific_coast_marine"]
    assert reuse.collections[0].ways_in == (WayIn(WayInKind.EXPLICIT),)
    assert reuse.products == []
