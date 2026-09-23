"""catalog.assets: load every asset.toml under a catalog's assets directory."""

import shutil
from pathlib import Path

import pytest

from vectorpress.catalog.assets import (
    duplicate_slug_problems,  # pure helper, tested directly below
    find_asset,
    load_assets,
)
from vectorpress.catalog.load import load_catalog_config
from vectorpress.domain.asset import AccuracyStatus, RightsStatus, Source

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def catalog_copy(tmp_path: Path) -> Path:
    """A mutable copy of the fixture catalog, so tests can break it safely."""
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _asset_toml(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / "asset.toml"


def test_fixture_catalog_loads_three_valid_assets() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    assert [asset.id for asset in inventory.assets] == [
        "giant_green_anemone",
        "ochre_sea_star",
        "purple_sea_urchin",
    ]
    assert inventory.problems == []


def test_assets_are_sorted_by_id() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    ids = [asset.id for asset in inventory.assets]
    assert ids == sorted(ids)


def test_loaded_asset_carries_rights_and_accuracy_status() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    ochre = next(a for a in inventory.assets if a.id == "ochre_sea_star")
    assert ochre.display_name == "Ochre Sea Star"
    assert ochre.rights_status is RightsStatus.ORIGINAL_ARTWORK
    assert ochre.accuracy_status is AccuracyStatus.APPROVED


def test_sources_parse_with_role_and_file() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    anemone = next(a for a in inventory.assets if a.id == "giant_green_anemone")
    assert anemone.sources == [Source(role="silhouette", file="silhouette.png")]


def test_asset_with_two_roles_loads_both_sources() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    ochre = next(a for a in inventory.assets if a.id == "ochre_sea_star")
    assert {source.role for source in ochre.sources} == {"silhouette", "lineart"}


def test_missing_required_field_is_a_problem_and_other_assets_still_load(
    catalog_copy: Path,
) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    text = path.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', "")
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    loaded_ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" in loaded_ids
    assert "giant_green_anemone" in loaded_ids
    assert "ochre_sea_star" not in loaded_ids
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "ochre_sea_star" in str(problem.path)
    assert problem.field == "subject_category"


def test_unknown_key_is_a_problem_naming_file_and_field(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    # Inserted before any [[sources]] table: a bare key after one would be
    # parsed as belonging to that table, not to the asset itself.
    text = path.read_text(encoding="utf-8").replace(
        'accuracy_status = "reviewed"',
        'accuracy_status = "reviewed"\nnot_a_field = true',
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert "ochre_sea_star" in ids
    assert "giant_green_anemone" in ids
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "purple_sea_urchin" in str(problem.path)
    assert problem.field == "not_a_field"


def test_rights_status_outside_the_list_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    text = path.read_text(encoding="utf-8").replace(
        'rights_status = "rights_verified"', 'rights_status = "not_a_real_status"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "rights_status"


def test_accuracy_status_outside_the_list_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "giant_green_anemone")
    text = path.read_text(encoding="utf-8").replace(
        'accuracy_status = "not_reviewed"', 'accuracy_status = "not_a_real_status"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "giant_green_anemone" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "accuracy_status"


def test_id_differing_from_folder_name_is_a_problem(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    path.write_text(
        'id = "not_the_folder_name"\n' + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "ochre_sea_star" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert inventory.problems[0].field == "id"
    assert "ochre_sea_star" in str(inventory.problems[0].path)


def test_id_matching_folder_name_is_accepted(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "ochre_sea_star")
    path.write_text('id = "ochre_sea_star"\n' + path.read_text(encoding="utf-8"), encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    assert inventory.problems == []
    assert "ochre_sea_star" in {asset.id for asset in inventory.assets}


def test_toml_syntax_error_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    path.write_text('common_name = "unterminated\n', encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    assert "purple_sea_urchin" in str(inventory.problems[0].path)


def test_committed_fixture_catalog_is_unmodified_by_mutating_tests() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)

    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    assert len(inventory.assets) == 3
    assert inventory.problems == []


# --- source validation (issue #4) -------------------------------------------------


def test_unknown_role_is_a_problem_naming_the_source(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    text = path.read_text(encoding="utf-8").replace(
        'role = "silhouette"', 'role = "not_a_real_role"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert problem.field == "sources[0].role"
    assert "not_a_real_role" in problem.message
    assert "silhouette.png" in problem.message


def test_declared_missing_file_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    asset_dir = catalog_copy / "assets" / "purple_sea_urchin"
    (asset_dir / "sources" / "silhouette.png").unlink()  # leave nothing undeclared behind
    path = asset_dir / "asset.toml"
    text = path.read_text(encoding="utf-8").replace(
        'file = "silhouette.png"', 'file = "missing.png"'
    )
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert problem.field == "sources[0].file"
    assert "missing.png" in problem.message


def test_undeclared_file_in_sources_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    sources_dir = catalog_copy / "assets" / "purple_sea_urchin" / "sources"
    (sources_dir / "detailed.png").write_bytes(b"not a real png, contents unchecked")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "detailed.png" in str(problem.path)


def test_duplicate_source_declaration_is_a_problem_naming_the_file(catalog_copy: Path) -> None:
    path = _asset_toml(catalog_copy, "purple_sea_urchin")
    text = path.read_text(encoding="utf-8")
    text += '\n[[sources]]\nrole = "silhouette"\nfile = "silhouette.png"\n'
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert "silhouette.png" in problem.message


def test_asset_with_no_sources_is_a_problem(catalog_copy: Path) -> None:
    asset_dir = catalog_copy / "assets" / "purple_sea_urchin"
    (asset_dir / "sources" / "silhouette.png").unlink()  # leave nothing undeclared behind
    path = asset_dir / "asset.toml"
    text = path.read_text(encoding="utf-8")
    text = text[: text.index("# Source images:")]
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    ids = {asset.id for asset in inventory.assets}
    assert "purple_sea_urchin" not in ids
    assert len(inventory.assets) == 2
    assert len(inventory.problems) == 1
    problem = inventory.problems[0]
    assert problem.field == "sources"
    assert "no source images" in problem.message


def test_catalog_declared_extra_role_is_accepted(catalog_copy: Path) -> None:
    catalog_toml = catalog_copy / "catalog.toml"
    catalog_toml.write_text(
        catalog_toml.read_text(encoding="utf-8") + '\nextra_roles = ["reference_photo"]\n',
        encoding="utf-8",
    )
    asset_dir = catalog_copy / "assets" / "purple_sea_urchin"
    (asset_dir / "sources" / "reference.png").write_bytes(b"stand-in bytes, unchecked")
    path = asset_dir / "asset.toml"
    text = path.read_text(encoding="utf-8")
    text += '\n[[sources]]\nrole = "reference_photo"\nfile = "reference.png"\n'
    path.write_text(text, encoding="utf-8")
    config = load_catalog_config(catalog_copy)

    inventory = load_assets(catalog_copy, config)

    assert inventory.problems == []
    urchin = next(a for a in inventory.assets if a.id == "purple_sea_urchin")
    assert "reference_photo" in {source.role for source in urchin.sources}


def test_find_asset_returns_the_matching_loaded_asset() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    found = find_asset(inventory, "ochre_sea_star")

    assert found is not None
    assert found.id == "ochre_sea_star"


def test_find_asset_returns_none_for_an_unknown_id() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    inventory = load_assets(FIXTURE_CATALOG_ROOT, config)

    assert find_asset(inventory, "not_a_real_asset") is None


# --- duplicate asset ID across case-variant folders (issue #17) -------------------


# A real filesystem is not exercised here: on Linux/macOS, two asset folders
# named e.g. "Sea_Otter" and "sea_otter" both exist, but on Windows they
# coalesce into one, so a test that creates such folders for real would see
# two candidate folders on Linux and one on Windows, diverging exactly like
# the issue warns against. The normalising comparison itself is therefore
# tested directly, against fabricated paths, independent of what a given
# OS's filesystem allows.


def test_duplicate_slug_problems_flags_case_variant_asset_ids() -> None:
    problems = duplicate_slug_problems(
        [
            (Path("assets/Sea_Otter/asset.toml"), "Sea_Otter"),
            (Path("assets/sea_otter/asset.toml"), "sea_otter"),
        ],
        field="id",
    )

    assert len(problems) == 2
    paths = {p.path for p in problems}
    assert paths == {
        Path("assets/Sea_Otter/asset.toml"),
        Path("assets/sea_otter/asset.toml"),
    }
    assert all(p.field == "id" for p in problems)
    assert all("duplicate id" in p.message for p in problems)


def test_duplicate_slug_problems_is_empty_for_distinct_asset_ids() -> None:
    problems = duplicate_slug_problems(
        [
            (Path("assets/ochre_sea_star/asset.toml"), "ochre_sea_star"),
            (Path("assets/purple_sea_urchin/asset.toml"), "purple_sea_urchin"),
        ],
        field="id",
    )

    assert problems == []


def test_load_assets_excludes_duplicate_id_folders_from_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the same exclusion as collections'
    ``test_load_collections_excludes_duplicate_slug_files_from_collections``,
    but for asset folders: two real folders live in separate real parent
    directories (so both always exist, on every OS), and the assets
    directory's listing is faked to present them as if they were siblings
    named ``Sea_Otter``/``sea_otter``.

    This is the one duplicate-ID test that is not skipped on Windows, so the
    exclusion behaviour itself is always pinned somewhere in CI.
    """
    root = tmp_path / "catalog"
    assets_dir = root / "assets"
    parent_a = assets_dir / "a"
    parent_b = assets_dir / "b"
    otter_upper = parent_a / "Sea_Otter"
    otter_lower = parent_b / "sea_otter"
    otter_upper.mkdir(parents=True)
    otter_lower.mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Dup Test"\n', encoding="utf-8")
    (otter_upper / "asset.toml").write_text('common_name = "Sea Otter"\n', encoding="utf-8")
    (otter_lower / "asset.toml").write_text('common_name = "Sea Otter"\n', encoding="utf-8")

    real_iterdir = Path.iterdir

    def fake_iterdir(self: Path):
        if self == assets_dir:
            return iter([otter_upper, otter_lower])
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    config = load_catalog_config(root)

    inventory = load_assets(root, config)

    assert inventory.assets == []
    assert len(inventory.problems) == 2
    assert all(p.field == "id" for p in inventory.problems)
    paths = {p.path for p in inventory.problems}
    assert paths == {
        Path("assets/a/Sea_Otter/asset.toml"),
        Path("assets/b/sea_otter/asset.toml"),
    }
