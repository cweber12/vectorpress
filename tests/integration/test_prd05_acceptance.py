"""PRD 5 acceptance walk-through: collections and products (§7, §10.1, §11,
§12, §13, §28, §33, §34, ADR 0008, ADR 0011).

PRD 5's own Acceptance paragraph: "User can define a rule-based collection
and an explicit one, define several products over the same collection with
different derivative types, resolve each, and see the correct
eligible/excluded/missing breakdown. Adding a matching asset to the catalog
appears in the rule-based collection without editing it." This performs
that walk-through end to end on a temporary copy of the fixture catalog,
through the ``CliRunner`` every other acceptance test in this package
already uses.

The fixture already carries the rule-based collection
(``kelp_forest_ecosystem``) and the explicit one (``pacific_coast_tide_pool``),
plus two products (``pacific_coast_tide_pool_standard_pack``,
``pacific_coast_tide_pool_png_only``) over the identical explicit collection
with different ``derivative_types`` (``tests/fixtures/catalog/README.md``).
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PACIFIC_COAST_MEMBERS = ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin")


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _add_kelp_forest_asset(root: Path, asset_id: str) -> None:
    """A new asset, added to the catalog only by copying ``bat_star`` (whose
    own ``asset.toml`` notes it deliberately matches no rule-based fixture
    collection) and giving it kelp-forest ecosystems -- never by editing a
    collection or product file."""
    source_dir = root / "assets" / "bat_star"
    new_dir = root / "assets" / asset_id
    shutil.copytree(source_dir, new_dir)
    toml_path = new_dir / "asset.toml"
    text = toml_path.read_text(encoding="utf-8")
    assert 'ecosystems = ["Subtidal", "Rocky reef"]' in text
    toml_path.write_text(
        text.replace('ecosystems = ["Subtidal", "Rocky reef"]', 'ecosystems = ["Kelp forest"]'),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_prd_05_acceptance_walkthrough(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    # 1. an explicit collection and a rule-based one, each resolving as
    # their own membership form declares.
    explicit_result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])
    assert explicit_result.exit_code == 0, explicit_result.output
    assert "Membership form: explicit" in explicit_result.stdout
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"{asset_id}\texplicit" in explicit_result.stdout

    rule_result = runner.invoke(app, ["collection", "kelp_forest_ecosystem"])
    assert rule_result.exit_code == 0, rule_result.output
    assert "Membership form: rule" in rule_result.stdout
    assert "purple_sea_urchin\trule" in rule_result.stdout

    # 2. two products sit over the identical explicit collection with
    # different derivative_types (tests/fixtures/catalog/products/*.toml).
    standard_pack_path = (
        temp_catalog_root / "products" / "pacific_coast_tide_pool_standard_pack.toml"
    )
    png_only_path = temp_catalog_root / "products" / "pacific_coast_tide_pool_png_only.toml"
    standard_pack_before = standard_pack_path.read_text(encoding="utf-8")
    png_only_before = png_only_path.read_text(encoding="utf-8")

    # 3. before anything is generated: both fully excluded, missing every
    # included type for every member.
    before_standard = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])
    assert before_standard.exit_code == 0, before_standard.output
    assert "Members: 3" in before_standard.stdout
    assert "Eligible: 0" in before_standard.stdout
    assert "Excluded: 3" in before_standard.stdout
    assert "Missing required derivatives: 9" in before_standard.stdout  # 3 types x 3 members

    before_png_only = runner.invoke(app, ["product", "pacific_coast_tide_pool_png_only"])
    assert before_png_only.exit_code == 0, before_png_only.output
    assert "Members: 3" in before_png_only.stdout
    assert "Eligible: 0" in before_png_only.stdout
    assert "Excluded: 3" in before_png_only.stdout
    assert "Missing required derivatives: 3" in before_png_only.stdout  # 1 type x 3 members

    # generate everything, then approve only transparent_png: the PNG-only
    # product becomes fully eligible while the standard pack (which also
    # needs cut_svg and silhouette_svg approved) stays excluded (§10).
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)
    approve_png_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_png_result.exit_code == 0, approve_png_result.output

    after_png_only = runner.invoke(app, ["product", "pacific_coast_tide_pool_png_only"])
    assert after_png_only.exit_code == 0, after_png_only.output
    assert "Eligible: 3" in after_png_only.stdout
    assert "Excluded: 0" in after_png_only.stdout
    assert "Missing required derivatives: 0" in after_png_only.stdout

    after_standard_partial = runner.invoke(
        app, ["product", "pacific_coast_tide_pool_standard_pack"]
    )
    assert after_standard_partial.exit_code == 0, after_standard_partial.output
    assert "Eligible: 0" in after_standard_partial.stdout
    assert "Excluded: 3" in after_standard_partial.stdout
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"{asset_id}\texplicit\texcluded" in after_standard_partial.stdout

    # approving the rest makes the standard pack fully eligible too.
    approve_rest_result = runner.invoke(app, ["approve", "--all"])
    assert approve_rest_result.exit_code == 0, approve_rest_result.output
    after_standard_full = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])
    assert after_standard_full.exit_code == 0, after_standard_full.output
    assert "Eligible: 3" in after_standard_full.stdout
    assert "Excluded: 0" in after_standard_full.stdout

    # neither product's hand-authored file was ever touched.
    assert standard_pack_path.read_text(encoding="utf-8") == standard_pack_before
    assert png_only_path.read_text(encoding="utf-8") == png_only_before

    # 4. a newly added matching asset appears in the rule-based collection,
    # and in every product over it, without editing any collection or
    # product file.
    collection_path = temp_catalog_root / "collections" / "kelp_forest_ecosystem.toml"
    product_path = temp_catalog_root / "products" / "kelp_forest_mini_pack.toml"
    collection_before = collection_path.read_text(encoding="utf-8")
    product_before = product_path.read_text(encoding="utf-8")

    _add_kelp_forest_asset(temp_catalog_root, "sunflower_star")

    new_asset_collection = runner.invoke(app, ["collection", "kelp_forest_ecosystem"])
    assert new_asset_collection.exit_code == 0, new_asset_collection.output
    assert "sunflower_star\trule" in new_asset_collection.stdout
    assert "Members: 2" in new_asset_collection.stdout

    new_asset_product = runner.invoke(app, ["product", "kelp_forest_mini_pack"])
    assert new_asset_product.exit_code == 0, new_asset_product.output
    assert "sunflower_star\trule" in new_asset_product.stdout
    assert "Members: 2" in new_asset_product.stdout

    assert collection_path.read_text(encoding="utf-8") == collection_before
    assert product_path.read_text(encoding="utf-8") == product_before

    # the new member is visible from its own side too (§33, §34) -- the
    # same resolution 'vpress collection'/'vpress product' just showed,
    # never a second path.
    sunflower_asset_result = runner.invoke(app, ["asset", "sunflower_star"])
    assert sunflower_asset_result.exit_code == 0, sunflower_asset_result.output
    assert "kelp_forest_ecosystem\tKelp Forest Ecosystem\trule" in sunflower_asset_result.stdout
    assert "kelp_forest_mini_pack" in sunflower_asset_result.stdout
