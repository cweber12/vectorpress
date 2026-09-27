"""``vpress build`` end to end against a temporary copy of the fixture
catalog (§14, §15, §20, §35, §36, ADR 0004, ADR 0005, ADR 0008, ADR 0013).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under ``builds/``, and the fixture catalog must
never contain one (``tests/fixtures/catalog/README.md``).

Uses ``pacific_coast_tide_pool_png_only`` (``derivative_types =
["transparent_png"]``, ``formats = ["png"]``, no ``[listing]``), the same
PNG-only fixture product PRD 5's own acceptance test already exercises
(``test_prd05_acceptance.py``): its package/ZIP name falls back to its slug,
Title-Case-Hyphen, since it has no listing yet.
"""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
PNG_ONLY_TOP_LEVEL = "Pacific-Coast-Tide-Pool-Png-Only"
PNG_ONLY_MEMBERS = ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin")

# (asset ID, its transparent_png customer filename): §20's slugified display
# name plus transparent_png's "-color.png" suffix.
PNG_ONLY_FILES = {
    "ochre_sea_star": "ochre-sea-star-color.png",
    "giant_green_anemone": "giant-green-anemone-color.png",
    "purple_sea_urchin": "purple-sea-urchin-color.png",
}


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _generate_and_approve_transparent_png(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Get every ``pacific_coast_tide_pool_png_only`` member to eligible:
    generate everything (``acorn_barnacle`` still fails, §35 -- irrelevant
    here, since it belongs to no fixture collection), then approve every
    asset's ``transparent_png`` alone, exactly the way
    ``test_prd05_acceptance.py`` already does for this same product."""
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


@pytest.mark.integration
def test_build_writes_a_png_only_package_and_zip(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    package_dir = build_dir / PNG_ONLY_TOP_LEVEL
    zip_path = build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip"
    manifest_path = build_dir / "manifest.json"
    assert package_dir.is_dir()
    assert zip_path.is_file()
    assert manifest_path.is_file()

    expected_files = sorted(f"PNG/{filename}" for filename in PNG_ONLY_FILES.values())

    # the package directory holds only those PNG/ files -- no SVG/, no
    # state, provenance, findings or source files (§14).
    package_files = sorted(
        p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()
    )
    assert package_files == expected_files

    # the ZIP has a single top-level folder holding the identical files.
    with zipfile.ZipFile(zip_path) as zip_file:
        names = sorted(zip_file.namelist())
    assert names == [f"{PNG_ONLY_TOP_LEVEL}/{f}" for f in expected_files]


@pytest.mark.integration
def test_build_ships_an_override_and_records_it_as_the_manifest_source(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    # a distinct, real generated PNG stands in for a hand-edited override
    # (ADR 0007's override is any file under overrides/ named like the
    # generated one; this test does not need it to have come from an editor).
    other_generated = (
        temp_catalog_root
        / "assets"
        / "giant_green_anemone"
        / "derived"
        / "giant-green-anemone-color.png"
    ).read_bytes()
    ochre_dir = temp_catalog_root / "assets" / "ochre_sea_star"
    generated_bytes = (ochre_dir / "derived" / "ochre-sea-star-color.png").read_bytes()
    assert other_generated != generated_bytes

    override_path = ochre_dir / "overrides" / "ochre-sea-star-color.png"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_bytes(other_generated)

    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    shipped = (build_dir / PNG_ONLY_TOP_LEVEL / "PNG" / "ochre-sea-star-color.png").read_bytes()
    assert shipped == other_generated
    assert shipped != generated_bytes

    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    member = next(
        m
        for m in manifest["members"]
        if m["asset_id"] == "ochre_sea_star" and m["derivative_type"] == "transparent_png"
    )
    assert member["source"] == "override"
    assert member["content_hash"] == hashlib.sha256(other_generated).hexdigest()


@pytest.mark.integration
def test_build_refuses_when_any_member_is_ineligible_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    for asset_id in PNG_ONLY_MEMBERS:
        assert f"{asset_id}\t" in result.output
        assert "transparent_png: missing" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_build_refuses_on_a_customer_filename_collision_and_leaves_the_previous_build_untouched(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    first = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert first.exit_code == 0, first.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    zip_before = (build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip").read_bytes()
    manifest_before = (build_dir / "manifest.json").read_bytes()
    package_files_before = sorted(
        p.relative_to(build_dir / PNG_ONLY_TOP_LEVEL).as_posix()
        for p in (build_dir / PNG_ONLY_TOP_LEVEL).rglob("*")
        if p.is_file()
    )

    # a second asset with the identical display name collides with
    # purple_sea_urchin's own customer file name (§20) once both belong to
    # the same product.
    twin_dir = temp_catalog_root / "assets" / "purple_sea_urchin_twin"
    shutil.copytree(temp_catalog_root / "assets" / "purple_sea_urchin", twin_dir)
    collection_path = temp_catalog_root / "collections" / "pacific_coast_tide_pool.toml"
    before_asset_ids = 'asset_ids = ["ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"]'
    text = collection_path.read_text(encoding="utf-8")
    assert before_asset_ids in text
    collection_path.write_text(
        text.replace(
            before_asset_ids,
            'asset_ids = ["ochre_sea_star", "giant_green_anemone", "purple_sea_urchin", '
            '"purple_sea_urchin_twin"]',
        ),
        encoding="utf-8",
    )

    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    second = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert second.exit_code == 1
    assert "purple_sea_urchin" in second.output
    assert "purple_sea_urchin_twin" in second.output

    assert (build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip").read_bytes() == zip_before
    assert (build_dir / "manifest.json").read_bytes() == manifest_before
    package_files_after = sorted(
        p.relative_to(build_dir / PNG_ONLY_TOP_LEVEL).as_posix()
        for p in (build_dir / PNG_ONLY_TOP_LEVEL).rglob("*")
        if p.is_file()
    )
    assert package_files_after == package_files_before


@pytest.mark.integration
def test_rebuilding_with_no_changes_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    first = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert first.exit_code == 0, first.output
    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    zip_bytes_1 = (build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip").read_bytes()
    manifest_bytes_1 = (build_dir / "manifest.json").read_bytes()

    second = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert second.exit_code == 0, second.output
    zip_bytes_2 = (build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip").read_bytes()
    manifest_bytes_2 = (build_dir / "manifest.json").read_bytes()

    assert zip_bytes_2 == zip_bytes_1
    assert manifest_bytes_2 == manifest_bytes_1


@pytest.mark.integration
def test_manifest_and_zip_listing_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == snapshot(name="manifest")

    with zipfile.ZipFile(build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip") as zip_file:
        names = sorted(zip_file.namelist())
    assert names == snapshot(name="zip_listing")


@pytest.mark.integration
def test_build_on_a_format_type_mismatch_product_fails_to_load_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A format/type mismatch is a product metadata problem at load time
    (ADR 0013, issue #90), not a build failure: ``vpress build`` reaches the
    exact same "product failed to load" exit ``vpress product`` already
    gives, and writes nothing."""
    monkeypatch.chdir(temp_catalog_root)
    product_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    before_formats = 'formats = ["png"]'
    text = product_path.read_text(encoding="utf-8")
    assert before_formats in text
    product_path.write_text(text.replace(before_formats, 'formats = ["svg"]'), encoding="utf-8")

    load_result = runner.invoke(app, ["product", PNG_ONLY_SLUG])
    build_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert load_result.exit_code == 1
    assert build_result.exit_code == 1
    assert build_result.output == load_result.output
    assert not (temp_catalog_root / "builds").exists()
