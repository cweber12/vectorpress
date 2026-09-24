import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress import __version__
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

#: Rich (via typer's usage-error rendering) wraps a long message across
#: several lines inside a bordered panel, box-drawing characters and all.
#: Stripping those characters and collapsing whitespace before asserting on
#: the message text makes the check robust to exactly where the wrap falls
#: (issue #26 review fix round 1).
_BOX_DRAWING_RE = re.compile(r"[─-╿]")


def _normalized_output(output: str) -> str:
    return " ".join(_BOX_DRAWING_RE.sub(" ", output).split())


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


def test_status_reports_missing_and_impossible_derivative_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance criterion 2 (issue #22), updated by issue #25's flatcolor
    fixture source: purple_sea_urchin and giant_green_anemone each
    contribute transparent_png and silhouette_svg as missing plus
    flatcolor_svg as impossible (2 missing + 1 impossible each = 4 missing,
    2 impossible); ochre_sea_star now has a flatcolor source, so all three
    of its recipe-bearing types are missing instead (3 missing, 0
    impossible) -- 7 missing, 2 impossible overall. Still exits 0 -- these
    are inventory counts, not metadata problems."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Missing derivatives: 7" in result.stdout
    assert "Impossible derivatives: 2" in result.stdout


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
    # ochre_sea_star also has a flatcolor source now (issue #25).
    assert lines["ochre_sea_star"].split("\t")[-1] == "3"
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
    assert "flatcolor.png" in result.stdout
    assert "flatcolor" in result.stdout


def test_asset_lists_derivatives_missing_and_impossible_for_an_asset_without_flatcolor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance criterion 1 (issue #22): transparent_png and
    silhouette_svg select the silhouette source as missing, flatcolor_svg is
    impossible naming the accepted role, for the two fixture assets with no
    flatcolor source (purple_sea_urchin, giant_green_anemone; ochre_sea_star
    has one since issue #25 and is covered separately below)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    for asset_id in ["purple_sea_urchin", "giant_green_anemone"]:
        result = runner.invoke(app, ["asset", asset_id])

        assert result.exit_code == 0
        assert "Derivatives:" in result.stdout
        assert "transparent_png\tmissing\tsilhouette.png (silhouette)" in result.stdout
        assert "silhouette_svg\tmissing\tsilhouette.png (silhouette)" in result.stdout
        assert "flatcolor_svg\timpossible\t" in result.stdout
        assert "flatcolor" in result.stdout


def test_asset_lists_derivatives_for_the_asset_with_a_flatcolor_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ochre_sea_star's flatcolor source (issue #25) makes flatcolor_svg
    missing rather than impossible, and -- since the transparent_png recipe
    prefers flatcolor over silhouette (issue #22's accepted-roles order) --
    transparent_png now selects it too, not the silhouette source."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0
    assert "Derivatives:" in result.stdout
    assert "transparent_png\tmissing\tflatcolor.png (flatcolor)" in result.stdout
    assert "silhouette_svg\tmissing\tsilhouette.png (silhouette)" in result.stdout
    assert "flatcolor_svg\tmissing\tflatcolor.png (flatcolor)" in result.stdout


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


# --- generate (issue #23) ---------------------------------------------------------
#
# End-to-end behaviour of ``generate --all``/``generate <id>`` writing real
# files (outcome reporting, idempotence, provenance, snapshot-locked bytes)
# lives in tests/integration/test_generate.py, against a temporary copy of
# the fixture (the committed fixture must never contain ``derived/``). These
# tests cover the paths that write nothing: usage errors and unknown assets,
# which can run directly against the read-only fixture.


def test_generate_with_neither_an_id_nor_all_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A usage error is typer's own ``Usage: ...`` / ``Error: ...``
    rendering (raised as ``typer.BadParameter``, exit code 2) -- not just
    any non-zero exit, which an unknown asset ID (exit 1) or a crash would
    also produce (issue #26 review fix round 1)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "Provide exactly one of: an asset ID, --all, --stale." in _normalized_output(
        result.output
    )


def test_generate_with_both_an_id_and_all_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "ochre_sea_star", "--all"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "Provide exactly one of: an asset ID, --all, --stale." in _normalized_output(
        result.output
    )


def test_generate_with_unknown_id_exits_non_zero_and_names_the_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "not_a_real_asset"])

    assert result.exit_code == 1
    assert "not_a_real_asset" in result.output
    assert "Unknown asset" in result.output


# --- generate --stale / --force usage errors (issue #26) --------------------------


def test_generate_with_an_id_and_stale_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "ochre_sea_star", "--stale"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "Provide exactly one of: an asset ID, --all, --stale." in _normalized_output(
        result.output
    )


def test_generate_with_all_and_stale_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "--all", "--stale"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "Provide exactly one of: an asset ID, --all, --stale." in _normalized_output(
        result.output
    )


def test_generate_with_force_and_stale_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "--stale", "--force"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "--force combines with an asset ID or --all, not --stale." in _normalized_output(
        result.output
    )


def test_generate_with_force_alone_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--force`` combines with an asset ID or ``--all``, not on its own
    (it selects nothing to force): this is caught by the same "exactly one
    selector" check as no selector at all."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["generate", "--force"])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert "Provide exactly one of: an asset ID, --all, --stale." in _normalized_output(
        result.output
    )
