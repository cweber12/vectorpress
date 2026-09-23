import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress import __version__
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_status_from_the_catalog_root_prints_name_and_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Tide Pool Studio" in result.stdout
    assert str(FIXTURE_CATALOG_ROOT.resolve()) in result.stdout


def test_status_from_a_subdirectory_walks_up_to_the_catalog_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Locating the root by walking up works even though this catalog has no
    ``brand.toml`` (that absence is its own problem, asserted elsewhere);
    the outcome checked here is that the walk-up finds the right root, not
    that the catalog is otherwise clean.
    """
    root = tmp_path / "catalog"
    subdir = root / "assets" / "ochre_sea_star"
    subdir.mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Tide Pool Studio"\n', encoding="utf-8")
    monkeypatch.chdir(subdir)

    result = runner.invoke(app, ["status"])

    assert "No catalog.toml found" not in result.output
    assert "Tide Pool Studio" in result.stdout


def test_status_with_catalog_flag_works_from_any_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(FIXTURE_CATALOG_ROOT), "status"])

    assert result.exit_code == 0
    assert "Tide Pool Studio" in result.stdout


def test_status_outside_any_catalog_names_directories_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code != 0
    assert str(tmp_path.resolve()) in result.output


def test_status_with_malformed_catalog_names_file_and_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "catalog.toml").write_text(
        'name = "Broken"\nreference_size_in = "big"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code != 0
    assert "catalog.toml" in result.output
    assert "reference_size_in" in result.output


def test_status_reports_the_asset_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Assets: 3" in result.stdout


def test_status_reports_the_asset_count_on_a_partially_broken_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Deferred from issue #6: the ``Assets: N`` line counts only the assets
    that loaded, even when one asset's ``asset.toml`` is broken, at the CLI
    layer end to end (locate, load, render).
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    ochre = root / "assets" / "ochre_sea_star" / "asset.toml"
    ochre.write_text(
        ochre.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "status"])

    assert result.exit_code != 0
    assert "Assets: 2" in result.stdout


def test_status_reports_the_collection_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Collections: 2" in result.stdout


def test_status_reports_the_product_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Products: 2" in result.stdout


def test_status_prints_the_brand_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Brand: Tide Pool Studio" in result.stdout


def test_status_without_brand_toml_reports_its_absence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    (root / "brand.toml").unlink()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "status"])

    assert result.exit_code != 0
    assert "Brand: none" in result.stdout
    assert "brand.toml" in result.stdout
    assert "not found" in result.stdout


def test_status_with_a_bad_brand_names_file_and_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    brand_path = root / "brand.toml"
    brand_path.write_text(
        brand_path.read_text(encoding="utf-8").replace(
            'mark_file = "mark.png"', 'mark_file = "does_not_exist.png"'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "status"])

    assert result.exit_code != 0
    assert "brand.toml" in result.stdout
    assert "mark_file" in result.stdout
    assert "does_not_exist.png" in result.stdout


def test_status_on_the_clean_fixture_states_there_are_no_problems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Metadata problems: none" in result.stdout


def test_status_lists_a_missing_field_an_unknown_role_and_a_duplicate_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 2 (issue #6): three problems from three files,
    grouped by file, with field and message, non-zero exit.

    Folder-named assets mean a duplicate asset ID can only arise as an
    ``id`` field disagreeing with its own folder (#4's check); this asset
    is excluded and the mismatch is reported as the "duplicate ID" case.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)

    ochre = root / "assets" / "ochre_sea_star" / "asset.toml"
    ochre.write_text(
        ochre.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )

    urchin = root / "assets" / "purple_sea_urchin" / "asset.toml"
    urchin.write_text(
        urchin.read_text(encoding="utf-8").replace(
            'role = "silhouette"', 'role = "not_a_real_role"'
        ),
        encoding="utf-8",
    )

    anemone = root / "assets" / "giant_green_anemone" / "asset.toml"
    anemone.write_text(
        'id = "purple_sea_urchin"\n' + anemone.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "status"])

    assert result.exit_code != 0
    assert "Metadata problems: 3" in result.stdout
    assert str(Path("assets") / "ochre_sea_star" / "asset.toml") in result.stdout
    assert "subject_category" in result.stdout
    assert str(Path("assets") / "purple_sea_urchin" / "asset.toml") in result.stdout
    assert "not_a_real_role" in result.stdout
    assert str(Path("assets") / "giant_green_anemone" / "asset.toml") in result.stdout
    assert "purple_sea_urchin" in result.stdout
    assert "does not match folder name" in result.stdout


def test_assets_lists_the_fixture_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["assets"])

    assert result.exit_code == 0
    for asset_id, display_name, rights, accuracy in [
        ("ochre_sea_star", "Ochre Sea Star", "original_artwork", "approved"),
        ("purple_sea_urchin", "Purple Sea Urchin", "rights_verified", "reviewed"),
        ("giant_green_anemone", "Giant Green Anemone", "public_domain_source", "not_reviewed"),
    ]:
        assert asset_id in result.stdout
        assert display_name in result.stdout
        assert rights in result.stdout
        assert accuracy in result.stdout


def test_assets_lists_the_valid_ones_when_one_asset_is_broken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 3 (issue #6): one broken asset does not stop
    ``vpress assets`` from listing the others, at the CLI layer.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    ochre = root / "assets" / "ochre_sea_star" / "asset.toml"
    ochre.write_text(
        ochre.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "assets"])

    assert result.exit_code == 0
    assert "ochre_sea_star" not in result.stdout
    assert "purple_sea_urchin" in result.stdout
    assert "giant_green_anemone" in result.stdout


def test_assets_are_sorted_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["assets"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    ids = [line.split()[0] for line in lines]
    assert ids == sorted(ids)


def test_assets_reports_a_source_count_per_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["assets"])

    assert result.exit_code == 0
    lines = {line.split("\t")[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert lines["ochre_sea_star"].split("\t")[-1] == "2"
    assert lines["purple_sea_urchin"].split("\t")[-1] == "1"
    assert lines["giant_green_anemone"].split("\t")[-1] == "1"


def test_asset_shows_id_display_name_statuses_and_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0
    assert "ochre_sea_star" in result.stdout
    assert "Ochre Sea Star" in result.stdout
    assert "original_artwork" in result.stdout
    assert "approved" in result.stdout
    assert "silhouette.png" in result.stdout
    assert "silhouette" in result.stdout
    assert "lineart.png" in result.stdout
    assert "lineart" in result.stdout


def test_asset_with_unknown_id_exits_non_zero_and_names_the_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "not_a_real_asset"])

    assert result.exit_code != 0
    assert "not_a_real_asset" in result.output
    assert "Unknown asset" in result.output
    assert ".toml" not in result.output  # does not claim a file exists


def test_asset_with_toml_syntax_error_names_the_file_and_the_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 1 (issue #15): a malformed ``asset.toml`` (syntax
    error) is reported by ``vpress asset <id>`` naming the file and the
    problem, not ``Unknown asset``.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    urchin = root / "assets" / "purple_sea_urchin" / "asset.toml"
    urchin.write_text('common_name = "unterminated\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "asset", "purple_sea_urchin"])

    assert result.exit_code != 0
    assert "Unknown asset" not in result.output
    assert str(Path("assets") / "purple_sea_urchin" / "asset.toml") in result.output
    assert "TOML syntax error" in result.output


def test_asset_with_missing_required_field_lists_the_problem_with_file_and_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 2 (issue #15), schema-problem half: a missing
    required field is reported with file and field, same rendering as
    ``vpress status``.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    ochre = root / "assets" / "ochre_sea_star" / "asset.toml"
    ochre.write_text(
        ochre.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "asset", "ochre_sea_star"])

    assert result.exit_code != 0
    assert "Unknown asset" not in result.output
    assert str(Path("assets") / "ochre_sea_star" / "asset.toml") in result.output
    assert "subject_category" in result.output


def test_asset_with_missing_source_file_lists_the_problem_with_file_and_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 2 (issue #15), source-problem half: a declared
    source file that is missing is reported with file and field.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    asset_dir = root / "assets" / "purple_sea_urchin"
    (asset_dir / "sources" / "silhouette.png").unlink()  # leave nothing undeclared behind
    urchin = asset_dir / "asset.toml"
    urchin.write_text(
        urchin.read_text(encoding="utf-8").replace(
            'file = "silhouette.png"', 'file = "missing.png"'
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "asset", "purple_sea_urchin"])

    assert result.exit_code != 0
    assert "Unknown asset" not in result.output
    assert str(Path("assets") / "purple_sea_urchin" / "asset.toml") in result.output
    assert "sources[0].file" in result.output
    assert "missing.png" in result.output


def test_collections_lists_both_fixture_collections_with_slug_name_and_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collections"])

    assert result.exit_code == 0
    for slug, name, form in [
        ("pacific_coast_tide_pool", "Pacific Coast Tide Pool", "explicit"),
        ("kelp_forest_ecosystem", "Kelp Forest Ecosystem", "rule"),
    ]:
        assert slug in result.stdout
        assert name in result.stdout
        assert form in result.stdout


def test_collections_are_sorted_by_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collections"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    slugs = [line.split("\t")[0] for line in lines]
    assert slugs == sorted(slugs)


def test_products_lists_both_fixture_products_with_slug_title_tier_and_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splits each line on the tab separator and asserts the exact 4-tuple
    per product, rather than substring checks: ``"standard_pack"``,
    ``"mini_pack"`` and ``"pacific_coast_tide_pool"`` are all substrings of
    the product slugs themselves, so a dropped or garbled tier/collection
    column would not have failed a substring-only assertion.
    """
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["products"])

    assert result.exit_code == 0
    lines = {
        line.split("\t")[0]: tuple(line.split("\t"))
        for line in result.stdout.splitlines()
        if line.strip()
    }
    assert lines["pacific_coast_tide_pool_standard_pack"] == (
        "pacific_coast_tide_pool_standard_pack",
        "Pacific Coast Tide Pool Cut File Collection",
        "standard_pack",
        "pacific_coast_tide_pool",
    )
    assert lines["kelp_forest_mini_pack"] == (
        "kelp_forest_mini_pack",
        "kelp_forest_mini_pack",
        "mini_pack",
        "inline (rule)",
    )


def test_products_falls_back_to_slug_when_there_is_no_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["products"])

    assert result.exit_code == 0
    lines = {line.split("\t")[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert lines["kelp_forest_mini_pack"].split("\t")[1] == "kelp_forest_mini_pack"


def test_products_are_sorted_by_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["products"])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    slugs = [line.split("\t")[0] for line in lines]
    assert slugs == sorted(slugs)
