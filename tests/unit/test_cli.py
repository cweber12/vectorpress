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
#: several lines inside a bordered panel, box-drawing characters and all,
#: and -- on a runner that detects color support, e.g. CI (issue #26 review
#: fix round 2: local runs here are uncolored, so this only showed up on
#: CI) -- wraps individual words in ANSI SGR escape sequences too. Stripping
#: both, then collapsing whitespace, before asserting on the message text
#: makes the check robust to exactly where the wrap falls and to whether
#: the runner colors its output (issue #26 review fix round 1, round 2).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_DRAWING_RE = re.compile(r"[─-╿]")


def _normalized_output(output: str) -> str:
    return " ".join(_BOX_DRAWING_RE.sub(" ", _ANSI_RE.sub("", output)).split())


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
    assert "Assets: 11" in result.stdout


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
    assert "Assets: 10" in result.stdout


def test_status_reports_the_collection_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Collections: 3" in result.stdout


def test_status_reports_the_product_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Products: 3" in result.stdout


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
    fixture source, issue #27's acorn_barnacle, issue #36's cut_svg recipe,
    issue #39's four area-finding fixtures and issue #40's two shape-finding
    fixtures: purple_sea_urchin, giant_green_anemone, owl_limpet,
    gumboot_chiton, bat_star, keyhole_limpet, turban_snail, nudibranch and
    coralline_algae each have only a silhouette source, so transparent_png,
    silhouette_svg and cut_svg are missing and flatcolor_svg is impossible
    (3 missing + 1 impossible each = 27 missing, 9 impossible across the
    nine); ochre_sea_star has a flatcolor source too, so all four of its
    recipe-bearing types are missing instead (4 missing, 0 impossible);
    acorn_barnacle has only a silhouette source, so transparent_png,
    silhouette_svg and cut_svg are missing (its truncated source is a
    generation-time failure, not something ``status`` decodes) and
    flatcolor_svg is impossible (3 missing, 1 impossible) -- 34 missing, 10
    impossible overall. Still exits 0 -- these are inventory counts, not
    metadata problems."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Missing derivatives: 34" in result.stdout
    assert "Impossible derivatives: 10" in result.stdout


def test_status_lists_a_missing_field_an_unknown_role_and_a_duplicate_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 2 (issue #6): three problems from three files,
    grouped by file, with field and message, non-zero exit.

    Folder-named assets mean a duplicate asset ID can only arise as an
    ``id`` field disagreeing with its own folder (#4's check); this asset
    is excluded and the mismatch is reported as the "duplicate ID" case.

    Uses assets none of the fixture's collections reference (bat_star,
    coralline_algae, keyhole_limpet -- their own asset.toml notes say so):
    breaking a collection member here would also surface it as a reference
    problem, which is exercised on its own in
    tests/integration/test_collection_resolution.py, not this count.
    """
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)

    bat_star = root / "assets" / "bat_star" / "asset.toml"
    bat_star.write_text(
        bat_star.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )

    coralline_algae = root / "assets" / "coralline_algae" / "asset.toml"
    coralline_algae.write_text(
        coralline_algae.read_text(encoding="utf-8").replace(
            'role = "silhouette"', 'role = "not_a_real_role"'
        ),
        encoding="utf-8",
    )

    keyhole_limpet = root / "assets" / "keyhole_limpet" / "asset.toml"
    keyhole_limpet.write_text(
        'id = "coralline_algae"\n' + keyhole_limpet.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "status"])

    assert result.exit_code != 0
    assert "Metadata problems: 3" in result.stdout
    assert str(Path("assets") / "bat_star" / "asset.toml") in result.stdout
    assert "subject_category" in result.stdout
    assert str(Path("assets") / "coralline_algae" / "asset.toml") in result.stdout
    assert "not_a_real_role" in result.stdout
    assert str(Path("assets") / "keyhole_limpet" / "asset.toml") in result.stdout
    assert "coralline_algae" in result.stdout
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


def test_asset_shows_its_own_cleanup_size_when_it_differs_from_the_catalog_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visibility (ADR 0012): ``ochre_sea_star``'s committed
    ``[derivatives.cut_svg] reference_size_in = 6.0`` shows on its cut_svg
    line as a cleanup-size note, naming the size that differs from the
    catalog's 3.0in default."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0
    cut_svg_line = next(
        line for line in result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "cleanup size: 6in" in cut_svg_line


def test_asset_shows_no_cleanup_size_note_when_it_matches_the_catalog_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case (ADR 0012): an asset with no cleanup-size override of
    its own shows no note at all."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "purple_sea_urchin"])

    assert result.exit_code == 0
    cut_svg_line = next(
        line for line in result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "cleanup size" not in cut_svg_line


def test_asset_default_eligibility_covers_every_type_the_asset_can_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ochre_sea_star has a flatcolor source, so all four recipe-bearing
    types are non-impossible and shown by default (§10.1)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0
    eligibility_line = next(
        line for line in result.stdout.splitlines() if line.startswith("Eligibility")
    )
    assert eligibility_line.startswith(
        "Eligibility (transparent_png, silhouette_svg, cut_svg, flatcolor_svg):"
    )


def test_asset_lists_every_collection_it_belongs_to_including_rule_and_via(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``purple_sea_urchin`` is explicit in ``pacific_coast_tide_pool``,
    rule-matched into ``kelp_forest_ecosystem``, and pulled into
    ``pacific_coast_marine`` via both of those (§33, §34, its own
    ``pacific_coast_marine.toml`` comment)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "purple_sea_urchin"])

    assert result.exit_code == 0
    assert "Collections: 3" in result.stdout
    assert "pacific_coast_tide_pool\tPacific Coast Tide Pool\texplicit" in result.stdout
    assert "kelp_forest_ecosystem\tKelp Forest Ecosystem\trule" in result.stdout
    marine_line = next(
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("pacific_coast_marine")
    )
    assert "via pacific_coast_tide_pool" in marine_line
    assert "via kelp_forest_ecosystem" in marine_line


def test_asset_lists_every_product_it_belongs_to_with_its_own_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same asset, the product-side section: every product over a
    collection it belongs to, each showing that product's own eligibility
    for that product's derivative types -- excluded everywhere on the
    clean fixture, since nothing is generated yet."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "purple_sea_urchin"])

    assert result.exit_code == 0
    assert "Products: 3" in result.stdout
    assert (
        "pacific_coast_tide_pool_standard_pack\tPacific Coast Tide Pool Cut File Collection\t"
        "explicit\texcluded" in result.stdout
    )
    assert (
        "pacific_coast_tide_pool_png_only\tpacific_coast_tide_pool_png_only\texplicit\texcluded"
        in (result.stdout)
    )
    assert "kelp_forest_mini_pack\tkelp_forest_mini_pack\trule\texcluded" in result.stdout


def test_asset_in_no_collection_says_so_instead_of_an_empty_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bat_star``'s own ``asset.toml`` notes it matches no rule-based
    fixture collection and is on no explicit list either -- "Collections:
    none" / "Products: none", never a header with nothing under it."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "bat_star"])

    assert result.exit_code == 0
    assert "Collections: none" in result.stdout
    assert "Products: none" in result.stdout


def test_asset_with_types_option_narrows_eligibility_to_the_named_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "purple_sea_urchin", "--types", "transparent_png"])

    assert result.exit_code == 0
    assert "Eligibility (transparent_png): blocked" in result.stdout
    assert "transparent_png: missing" in result.stdout


def test_asset_with_an_unknown_type_in_types_exits_non_zero_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star", "--types", "not_a_real_type"])

    assert result.exit_code == 1
    assert "not_a_real_type" in result.output


def test_asset_with_an_empty_types_option_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["asset", "ochre_sea_star", "--types", " , "])

    assert result.exit_code == 2
    assert "Usage:" in result.output


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


def test_collections_lists_every_fixture_collection_with_slug_name_and_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collections"])

    assert result.exit_code == 0
    for slug, name, form in [
        ("pacific_coast_tide_pool", "Pacific Coast Tide Pool", "explicit"),
        ("kelp_forest_ecosystem", "Kelp Forest Ecosystem", "rule"),
        ("pacific_coast_marine", "Pacific Coast Marine", "mixed"),
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


def test_collections_member_count_column_reflects_current_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit fixture collection resolves to 3 members; the rule
    collection resolves to 1 (purple_sea_urchin, the only fixture asset
    whose ecosystems include "Kelp forest"); the union collection resolves
    to 4 -- the de-duplicated union of both plus turban_snail (§13)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collections"])

    assert result.exit_code == 0
    lines = {line.split("\t")[0]: line for line in result.stdout.splitlines() if line.strip()}
    assert lines["pacific_coast_tide_pool"].split("\t")[-1] == "3"
    assert lines["kelp_forest_ecosystem"].split("\t")[-1] == "1"
    assert lines["pacific_coast_marine"].split("\t")[-1] == "4"


# --- vpress collection <slug> (§11, §34) -------------------------------------------


def test_collection_on_the_fixture_lists_exactly_its_three_explicit_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])

    assert result.exit_code == 0, result.output
    assert "Pacific Coast Tide Pool" in result.stdout
    assert "Members: 3" in result.stdout
    for asset_id in ("giant_green_anemone", "ochre_sea_star", "purple_sea_urchin"):
        assert f"{asset_id}\texplicit" in result.stdout
    assert "Reference problems: none" in result.stdout


def test_collection_on_the_fixture_lists_exactly_the_kelp_forest_asset_as_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance criterion 1: ``kelp_forest_ecosystem`` lists exactly the
    assets whose ``ecosystems`` include "Kelp forest" -- currently
    ``purple_sea_urchin`` -- each as ``rule``."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "kelp_forest_ecosystem"])

    assert result.exit_code == 0, result.output
    assert "Members: 1" in result.stdout
    assert "purple_sea_urchin\trule" in result.stdout


def test_collection_on_the_fixture_union_lists_the_deduplicated_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance criterion 1: ``pacific_coast_marine`` -- a union of
    ``pacific_coast_tide_pool`` and ``kelp_forest_ecosystem`` plus
    ``turban_snail`` explicitly -- lists the de-duplicated members of both
    collections; ``purple_sea_urchin``, in both, appears once with both
    "via" ways in (§13)."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "pacific_coast_marine"])

    assert result.exit_code == 0, result.output
    assert "Membership form: mixed" in result.stdout
    assert "Members: 4" in result.stdout
    assert "turban_snail\texplicit" in result.stdout
    assert "ochre_sea_star\tvia pacific_coast_tide_pool" in result.stdout
    assert "giant_green_anemone\tvia pacific_coast_tide_pool" in result.stdout
    urchin_line = next(
        line for line in result.stdout.splitlines() if line.strip().startswith("purple_sea_urchin")
    )
    assert "via kelp_forest_ecosystem" in urchin_line
    assert "via pacific_coast_tide_pool" in urchin_line
    assert "Reference problems: none" in result.stdout


def test_collection_header_shows_the_rule_field_and_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header names the rule itself -- field and values -- for a
    rule-based collection."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "kelp_forest_ecosystem"])

    assert result.exit_code == 0, result.output
    assert "Membership form: rule" in result.stdout
    assert "Rule: ecosystems = Kelp forest" in result.stdout


def test_collection_header_has_no_rule_line_for_an_explicit_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])

    assert result.exit_code == 0, result.output
    assert "Rule:" not in result.stdout


def test_collection_prints_description_tags_and_marketplace_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "pacific_coast_tide_pool"])

    assert result.exit_code == 0, result.output
    assert "Nature & Wildlife" in result.stdout
    assert "tide pool" in result.stdout
    assert "Membership form: explicit" in result.stdout


def test_collection_with_unknown_slug_exits_non_zero_and_names_the_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, ["collection", "not_a_real_collection"])

    assert result.exit_code != 0
    assert "not_a_real_collection" in result.output
    assert "Unknown collection" in result.output
    assert ".toml" not in result.output  # does not claim a file exists


def test_collection_that_failed_to_load_exits_non_zero_with_a_distinct_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 3: an unknown slug and a collection file that
    failed to load are told apart, mirroring ``vpress asset``'s and
    ``vpress product``'s own lookup split."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    path = root / "collections" / "pacific_coast_tide_pool.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'marketplace_category = "Nature & Wildlife"\n', ""
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--catalog", str(root), "collection", "pacific_coast_tide_pool"])

    assert result.exit_code != 0
    assert "Unknown collection" not in result.output
    assert str(Path("collections") / "pacific_coast_tide_pool.toml") in result.output
    assert "marketplace_category" in result.output


def test_products_lists_every_fixture_product_with_slug_title_tier_collection_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Splits each line on the tab separator and asserts the exact 6-tuple
    per product, rather than substring checks: ``"standard_pack"``,
    ``"mini_pack"`` and ``"pacific_coast_tide_pool"`` are all substrings of
    the product slugs themselves, so a dropped or garbled tier/collection/
    count column would not have failed a substring-only assertion. Every
    fixture product reads 0 eligible on the clean fixture (nothing
    generated yet, §34); the member count is each product's own resolved
    membership size.
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
        "3",
        "0",
    )
    assert lines["pacific_coast_tide_pool_png_only"] == (
        "pacific_coast_tide_pool_png_only",
        "pacific_coast_tide_pool_png_only",
        "collection",
        "pacific_coast_tide_pool",
        "3",
        "0",
    )
    assert lines["kelp_forest_mini_pack"] == (
        "kelp_forest_mini_pack",
        "kelp_forest_mini_pack",
        "mini_pack",
        "inline (rule)",
        "1",
        "0",
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


# --- approve/reject/regenerate targeting usage errors (§10, §24) ------------------
#
# ``approve``, ``reject`` and ``regenerate`` share one targeting shape
# (``pipeline.review._validate_review_targeting``); these run against the
# read-only fixture, the same as ``generate``'s usage-error tests above --
# a usage error is caught, and nothing loaded or written, before the
# catalog is ever touched. End-to-end bulk behaviour (what gets approved,
# skipped, and the summary line) lives in
# ``tests/integration/test_review.py``, against a temporary catalog copy.

_TARGETING_ERROR = "Give exactly one of: ASSET_ID DERIVATIVE_TYPE, ASSET_ID --all-types, or --all."


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_no_targeting_at_all_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command])

    assert result.exit_code == 2
    assert "Usage:" in result.output
    assert _TARGETING_ERROR in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_an_asset_id_alone_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An asset ID with neither a derivative type nor --all-types is
    ambiguous, the same as no targeting at all."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "ochre_sea_star"])

    assert result.exit_code == 2
    assert _TARGETING_ERROR in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_an_asset_id_and_all_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "ochre_sea_star", "--all"])

    assert result.exit_code == 2
    assert _TARGETING_ERROR in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_an_asset_id_type_and_all_types_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "ochre_sea_star", "cut_svg", "--all-types"])

    assert result.exit_code == 2
    assert _TARGETING_ERROR in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_all_types_alone_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--all-types needs an asset ID -- on its own it targets nothing."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "--all-types"])

    assert result.exit_code == 2
    assert _TARGETING_ERROR in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_a_type_filter_but_no_all_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--type only means something alongside --all."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "ochre_sea_star", "cut_svg", "--type", "cut_svg"])

    assert result.exit_code == 2
    assert "--type only narrows --all." in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_a_status_filter_but_no_all_is_a_usage_error(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--status only means something alongside --all."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(
        app, [command, "ochre_sea_star", "--all-types", "--status", "needs_review"]
    )

    assert result.exit_code == 2
    assert "--status only narrows --all." in _normalized_output(result.output)


@pytest.mark.parametrize("command", ["approve", "reject", "regenerate"])
def test_review_command_with_an_unknown_asset_id_exits_non_zero_and_names_the_id(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    result = runner.invoke(app, [command, "not_a_real_asset", "cut_svg"])

    assert result.exit_code == 1
    assert "not_a_real_asset" in result.output
    assert "Unknown asset" in result.output
