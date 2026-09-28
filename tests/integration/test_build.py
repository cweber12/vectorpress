"""``vpress build`` end to end against a temporary copy of the fixture
catalog (§14, §15, §20, §27, §35, §36, ADR 0004, ADR 0005, ADR 0008,
ADR 0013).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under ``builds/``, and the fixture catalog must
never contain one (``tests/fixtures/catalog/README.md``).

Uses ``pacific_coast_tide_pool_png_only`` (``derivative_types =
["transparent_png"]``, ``formats = ["png"]``, no ``[listing]``), the same
PNG-only fixture product PRD 5's own acceptance test already exercises
(``test_prd05_acceptance.py``): its package/ZIP name falls back to its slug,
Title-Case-Hyphen, since it has no listing yet.

DXF conversion (ADR 0013) is exercised against
``pacific_coast_tide_pool_standard_pack``, whose ``derivative_types`` already
list both ``cut_svg`` and ``silhouette_svg`` alongside ``formats = [...,
"dxf"]`` -- so ``DXF/`` is converted from ``cut_svg`` there. A silhouette-only
fallback product is written into the temp catalog copy directly, the same
way other tests here mutate a hand-authored file mid-test, rather than
adding a second checked-in fixture product for one case.
"""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import ezdxf
import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.build._dxf_conversion import (
    svg_to_dxf_bytes,  # pyright: ignore[reportPrivateUsage]
)
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

STANDARD_PACK_SLUG = "pacific_coast_tide_pool_standard_pack"
STANDARD_PACK_TOP_LEVEL = "Tide-Pool-Collection"

# (asset ID, its cut_svg customer filename): §20's slugified display name
# plus cut_svg's own "-cut.svg" suffix -- the DXF converted from it is the
# same name with ".dxf" in place of ".svg" (ADR 0013).
STANDARD_PACK_CUT_SVG_FILES = {
    "ochre_sea_star": "ochre-sea-star-cut.svg",
    "giant_green_anemone": "giant-green-anemone-cut.svg",
    "purple_sea_urchin": "purple-sea-urchin-cut.svg",
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


def _generate_and_approve_standard_pack_types(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Get every ``pacific_coast_tide_pool_standard_pack`` member to
    eligible: generate everything, then approve every asset's ``cut_svg``,
    ``silhouette_svg`` and ``transparent_png`` -- the three types this
    product's own ``derivative_types`` lists."""
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    for derivative_type in ("cut_svg", "silhouette_svg", "transparent_png"):
        approve_result = runner.invoke(app, ["approve", "--all", "--type", derivative_type])
        assert approve_result.exit_code == 0, approve_result.output


#: Short on purpose (Windows' MAX_PATH, ~260 characters, is otherwise a real
#: risk once a build's own ``.tmp-<slug>-<32 hex chars>/<Title-Case-Name>/``
#: prefix is added on top of pytest's own long ``tmp_path`` for a slow test
#: name -- this fixture product's slug stays deliberately short rather than
#: descriptive.
SILHOUETTE_ONLY_SLUG = "tide_pool_silhouette_dxf"
SILHOUETTE_ONLY_TOP_LEVEL = "Tide-Pool-Silhouette-Dxf"


def _write_silhouette_only_dxf_product(root: Path, slug: str) -> None:
    """A product referencing the same ``pacific_coast_tide_pool`` collection
    as the standard pack, but with only ``silhouette_svg`` included: the
    fixture for ADR 0013's fallback rule (§7's "DXF/ converted from cut_svg,
    else silhouette_svg"), written straight into a temp catalog copy rather
    than as a second checked-in fixture product (this module's own
    docstring)."""
    (root / "products" / f"{slug}.toml").write_text(
        'collection_slug = "pacific_coast_tide_pool"\n'
        'derivative_types = ["silhouette_svg"]\n'
        'formats = ["svg", "dxf"]\n'
        'tier = "individual"\n'
        "price = 4.00\n",
        encoding="utf-8",
    )


def _dxf_filename(svg_filename: str) -> str:
    return f"{svg_filename.removesuffix('.svg')}.dxf"


def _entity_count(dxf_bytes: bytes) -> int:
    """The DXF's own ``POLYLINE`` entity count, read back with ``ezdxf``
    directly as this test's own oracle -- entirely independent of
    ``build._dxf_conversion``'s own writer, so it does not just check the
    conversion against itself."""
    import io

    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("ascii")))  # pyright: ignore[reportPrivateImportUsage]
    polylines = doc.modelspace().query("POLYLINE")  # pyright: ignore[reportUnknownArgumentType]
    return len(list(polylines))  # pyright: ignore[reportUnknownArgumentType]


def _count_close_commands(svg_bytes: bytes) -> int:
    """The number of explicit ``Z``/``z`` close commands across every
    ``<path>``'s own ``d`` in ``svg_bytes`` -- a second, independent way to
    count closed subpaths, via plain XML parsing and a regex over the raw
    ``d`` text, never through ``build._dxf_conversion.closed_rings`` itself.
    A fixture cut file is potrace-generated: every subpath it has is closed
    with an explicit ``Z`` (:mod:`vectorpress.pipeline.svg_document`), so
    this count is exact for it, and comparing the DXF's own entity count
    against it -- rather than against ``closed_rings``'s own count -- would
    still catch ``closed_rings`` silently dropping a subpath, which
    comparing it against itself never could.
    """
    import re
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg_bytes)
    return sum(
        len(re.findall(r"[Zz]", element.attrib.get("d", "")))
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "path"
    )


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


#: A fixed LICENSE.txt build year (§27), so a test asserting on rendered
#: text -- or locking it in a snapshot -- never depends on which real
#: calendar year the test suite happens to run in.
FIXED_LICENSE_YEAR = 2026


def _fix_license_year(monkeypatch: pytest.MonkeyPatch, year: int = FIXED_LICENSE_YEAR) -> None:
    monkeypatch.setattr("vectorpress.build.product_build._current_year", lambda: year)


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

    expected_files = sorted(
        [f"PNG/{filename}" for filename in PNG_ONLY_FILES.values()] + ["README.txt", "LICENSE.txt"]
    )

    # the package directory holds only those PNG/ files plus README.txt and
    # LICENSE.txt at its top level -- no SVG/, no state, provenance,
    # findings or source files (§14, §27).
    package_files = sorted(
        p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()
    )
    assert package_files == expected_files

    # the ZIP has a single top-level folder holding the identical files.
    with zipfile.ZipFile(zip_path) as zip_file:
        names = sorted(zip_file.namelist())
    assert names == [f"{PNG_ONLY_TOP_LEVEL}/{f}" for f in expected_files]


@pytest.mark.integration
def test_build_writes_readme_and_license_with_every_placeholder_substituted(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _fix_license_year(monkeypatch)
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    package_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG) / PNG_ONLY_TOP_LEVEL
    license_text = (package_dir / "LICENSE.txt").read_text(encoding="utf-8")
    readme_text = (package_dir / "README.txt").read_text(encoding="utf-8")

    # every {brand}/{product}/{copyright}/{year} placeholder is gone --
    # PNG_ONLY_SLUG has no [listing] yet, so {product} falls back to its
    # slug (§27).
    assert "{" not in license_text
    assert "Tide Pool Studio" in license_text
    assert PNG_ONLY_SLUG in license_text
    assert "© Tide Pool Studio. All rights reserved." in license_text
    assert str(FIXED_LICENSE_YEAR) in license_text

    for filename in PNG_ONLY_FILES.values():
        assert filename in readme_text
    assert "Included formats: PNG" in readme_text
    assert "Files checked at reference size: 3in" in readme_text
    assert "© Tide Pool Studio. All rights reserved." in readme_text


@pytest.mark.integration
def test_build_refuses_without_brand_toml_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    (temp_catalog_root / "brand.toml").unlink()

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "brand.toml" in result.output
    assert "not found" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_build_refuses_when_license_file_is_removed_from_brand_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    brand_path = temp_catalog_root / "brand.toml"
    before = 'license_file = "license_template.txt"\n'
    text = brand_path.read_text(encoding="utf-8")
    assert before in text
    brand_path.write_text(text.replace(before, ""), encoding="utf-8")

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "brand.toml" in result.output
    assert "license_file" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_build_refuses_when_license_file_names_a_path_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    brand_path = temp_catalog_root / "brand.toml"
    before = 'license_file = "license_template.txt"'
    text = brand_path.read_text(encoding="utf-8")
    assert before in text
    brand_path.write_text(
        text.replace(before, 'license_file = "does_not_exist.txt"'), encoding="utf-8"
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "license_file" in result.output
    assert "does_not_exist.txt" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_build_refuses_on_an_unknown_license_placeholder_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    license_path = temp_catalog_root / "license_template.txt"
    license_path.write_text(
        license_path.read_text(encoding="utf-8") + "\n{not_a_real_placeholder}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "not_a_real_placeholder" in result.output
    assert not (temp_catalog_root / "builds").exists()


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


def _add_ai_generated_test_product(root: Path) -> None:
    """A temp-only product (not part of the committed fixture) whose sole
    member is ``owl_limpet``, with its ``licensing_notes`` blanked in this
    same temp copy: the §26 block, "refuse" mode's own fixture, alongside
    ``PNG_ONLY_SLUG``'s ordinary missing-derivative one above."""
    path = root / "assets" / "owl_limpet" / "asset.toml"
    text = path.read_text(encoding="utf-8")
    assert 'rights_status = "ai_generated"\n' in text
    before = (
        'licensing_notes = "Generated with Midjourney (v6) under its commercial-use terms '
        'for paid subscribers; the ai_generated rights-status fixture (§26)."\n'
    )
    assert before in text
    path.write_text(text.replace(before, 'licensing_notes = ""\n'), encoding="utf-8")

    product_text = (
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership]\n"
        'asset_ids = ["owl_limpet"]\n'
    )
    (root / "products" / "owl_limpet_test_product.toml").write_text(product_text, encoding="utf-8")


@pytest.mark.integration
def test_build_refuses_naming_an_ai_generated_member_with_empty_licensing_notes(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§26's licensing-notes block reaches ``vpress build`` the same way a
    rights or accuracy block already does: "refuse" (the default) fails the
    build, naming the member and the reason, even with its one derivative
    fully approved."""
    _add_ai_generated_test_product(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "owl_limpet"])
    approve_result = runner.invoke(app, ["approve", "owl_limpet", "--all-types"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["build", "owl_limpet_test_product"])

    assert result.exit_code == 1
    assert "owl_limpet" in result.output
    assert (
        "licensing notes: must name the AI tool and its terms (rights status: ai generated)"
        in result.output
    )
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_build_refuses_when_membership_does_not_resolve_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """An unknown collection_slug is a reference problem, not a load
    failure (§11): resolve_product still returns, with no members and this
    problem instead. vpress build refuses on it the same way it refuses on
    an ineligible member -- exit 1, the reference problems listed, nothing
    written."""
    monkeypatch.chdir(temp_catalog_root)
    product_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    before_collection_slug = 'collection_slug = "pacific_coast_tide_pool"'
    text = product_path.read_text(encoding="utf-8")
    assert before_collection_slug in text
    product_path.write_text(
        text.replace(before_collection_slug, 'collection_slug = "no_such_collection"'),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "Reference problems" in result.output
    assert "no_such_collection" in result.output
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
    _fix_license_year(monkeypatch)
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
def test_manifest_records_every_included_assets_rights_status(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§26: recorded for every included asset, not only ``ai_generated``
    ones -- ``PNG_ONLY_SLUG``'s three members cover three different rights
    statuses, none of them ``ai_generated`` (owl_limpet, the fixture's own
    ``ai_generated`` asset, belongs to no fixture product)."""
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asset_rights_statuses"] == [
        {"asset_id": "giant_green_anemone", "rights_status": "public_domain_source"},
        {"asset_id": "ochre_sea_star", "rights_status": "original_artwork"},
        {"asset_id": "purple_sea_urchin", "rights_status": "rights_verified"},
    ]


@pytest.mark.integration
def test_readme_and_license_text_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    """README.txt and LICENSE.txt's exact rendered text (§27), pinned so a
    wording or ordering change is a deliberate, reviewed snapshot update --
    the year is fixed (:func:`_fix_license_year`) so this never depends on
    which real calendar year the suite happens to run in."""
    _fix_license_year(monkeypatch)
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    package_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG) / PNG_ONLY_TOP_LEVEL
    readme_text = (package_dir / "README.txt").read_text(encoding="utf-8")
    license_text = (package_dir / "LICENSE.txt").read_text(encoding="utf-8")

    assert readme_text == snapshot(name="readme")
    assert license_text == snapshot(name="license")


@pytest.mark.integration
def test_build_on_a_format_type_mismatch_product_fails_to_load_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A listed format no included type fills, or an included type no
    listed format carries, is a product metadata problem at load time
    (ADR 0013), not a build failure: ``vpress build`` reaches the exact
    same "product failed to load" exit ``vpress product`` already gives,
    and writes nothing."""
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


# --- ineligible_members: refuse (default) vs. exclude (§10) -----------------


def _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    """Get ``pacific_coast_tide_pool_standard_pack`` to fully eligible, then
    reject ``ochre_sea_star``'s own ``cut_svg`` alone: the fixture for §10's
    two ``ineligible_members`` modes. Its other approved derivatives
    (``silhouette_svg``, ``transparent_png``) stay untouched, so
    ``ochre_sea_star`` is ineligible only for a product that includes
    ``cut_svg``."""
    _generate_and_approve_standard_pack_types(monkeypatch, root)
    reject_result = runner.invoke(app, ["reject", "ochre_sea_star", "cut_svg"])
    assert reject_result.exit_code == 0, reject_result.output


def _set_ineligible_members_exclude(product_path: Path) -> None:
    """Add ``ineligible_members = "exclude"`` to a product file's top-level
    keys -- before its first ``[listing]`` table when it has one, since a
    bare key appended after a table header would parse as that table's own
    key instead (TOML)."""
    text = product_path.read_text(encoding="utf-8")
    assert "ineligible_members" not in text
    insertion = 'ineligible_members = "exclude"\n'
    table_start = text.find("\n[")
    new_text = (
        text + insertion
        if table_start == -1
        else text[: table_start + 1] + insertion + text[table_start + 1 :]
    )
    product_path.write_text(new_text, encoding="utf-8")


@pytest.mark.integration
def test_refuse_mode_fails_naming_the_ineligible_member_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``ineligible_members`` defaults to ``refuse`` (§10): one rejected
    ``cut_svg`` fails the whole cut-file product, naming the ineligible
    member and its reason, and writes nothing."""
    _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])

    assert result.exit_code == 1
    assert "1 ineligible member(s)" in result.output
    assert "ochre_sea_star\t" in result.output
    assert "cut_svg: rejected" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_exclude_mode_ships_the_eligible_members_and_records_the_excluded_one(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Set to ``exclude``, the same product ships its two eligible members
    and reports and records ``ochre_sea_star`` as excluded, with its
    ``cut_svg: rejected`` reason, in both the build output and the
    manifest (§10)."""
    _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(monkeypatch, temp_catalog_root)
    product_path = temp_catalog_root / "products" / f"{STANDARD_PACK_SLUG}.toml"
    _set_ineligible_members_exclude(product_path)

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])

    assert result.exit_code == 0, result.output
    assert "Excluded: 1" in result.output
    assert "ochre_sea_star\tcut_svg: rejected" in result.output

    build_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG)
    package_dir = build_dir / STANDARD_PACK_TOP_LEVEL
    package_files = sorted(
        p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()
    )
    assert not any("ochre-sea-star" in f for f in package_files)
    assert any("giant-green-anemone" in f for f in package_files)
    assert any("purple-sea-urchin" in f for f in package_files)

    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert all(m["asset_id"] != "ochre_sea_star" for m in manifest["members"])
    assert manifest["excluded_members"] == [
        {
            "asset_id": "ochre_sea_star",
            "blocking_reasons": [
                {"kind": "derivative_status", "derivative_type": "cut_svg", "value": "rejected"}
            ],
        }
    ]


@pytest.mark.integration
def test_a_product_that_does_not_include_the_rejected_type_still_ships_the_asset(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Eligibility considers only a product's own included derivative
    types (§10): the PNG-only product still ships ``ochre_sea_star``'s PNG
    even though its ``cut_svg`` is rejected, since ``transparent_png`` is
    untouched -- the same rejection ``test_refuse_mode_fails_...`` and
    ``test_exclude_mode_ships_...`` make the cut-file product refuse or
    exclude it over."""
    _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    package_dir = build_dir / PNG_ONLY_TOP_LEVEL
    assert (package_dir / "PNG" / PNG_ONLY_FILES["ochre_sea_star"]).is_file()
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any(m["asset_id"] == "ochre_sea_star" for m in manifest["members"])
    assert manifest["excluded_members"] == []


@pytest.mark.integration
def test_exclude_product_with_no_eligible_member_refuses_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``kelp_forest_mini_pack`` is the fixture's one committed ``exclude``
    product. Even in ``exclude`` mode, a build with nothing eligible still
    refuses the same way ``refuse`` does (§10) -- its single rule-matched
    member is never generated here at all, so it excludes down to zero. The
    refusal line says so in wording distinct from ``refuse`` mode's "N
    ineligible member(s)" (carried in from #95's review): "nothing was
    eligible" reads differently from "N named members block the build"."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["build", "kelp_forest_mini_pack"])

    assert result.exit_code == 1
    assert (
        "build: kelp_forest_mini_pack refused: no eligible member (ineligible_members = exclude)"
        in result.output
    )
    assert "purple_sea_urchin\t" in result.output
    assert "cut_svg: missing" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_exclude_mode_manifest_excluded_members_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    _fix_license_year(monkeypatch)
    _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(monkeypatch, temp_catalog_root)
    product_path = temp_catalog_root / "products" / f"{STANDARD_PACK_SLUG}.toml"
    _set_ineligible_members_exclude(product_path)

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG)
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["excluded_members"] == snapshot(name="excluded_members")


# --- --allow-unapproved: per-build override (§10, §10.1) ----------------------------


@pytest.mark.integration
def test_build_refuses_when_members_are_only_needs_review(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``generate --all`` with no approval leaves every member's
    ``transparent_png`` at ``needs_review`` (§22.1: a freshly generated
    derivative is recorded straight as ``needs_review``) -- without
    ``--allow-unapproved``, ``vpress build`` refuses exactly like any other
    unapproved member (§10.1)."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    for asset_id in PNG_ONLY_MEMBERS:
        assert f"{asset_id}\t" in result.output
        assert "transparent_png: needs review" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_allow_unapproved_ships_needs_review_members_and_lists_them_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The same ``needs_review``-only catalog, built with
    ``--allow-unapproved``: it ships, the build output lists every admitted
    (asset, derivative type) with its status, and the manifest records the
    identical list."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG, "--allow-unapproved"])

    assert result.exit_code == 0, result.output
    assert "Admitted unapproved: 3" in result.output
    for asset_id in PNG_ONLY_MEMBERS:
        assert f"{asset_id}\ttransparent_png\tneeds_review" in result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    package_dir = build_dir / PNG_ONLY_TOP_LEVEL
    for filename in PNG_ONLY_FILES.values():
        assert (package_dir / "PNG" / filename).is_file()

    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["admitted_unapproved_members"] == [
        {"asset_id": asset_id, "derivative_type": "transparent_png", "status": "needs_review"}
        for asset_id in sorted(PNG_ONLY_MEMBERS)
    ]


@pytest.mark.integration
def test_allow_unapproved_still_excludes_a_rejected_derivative(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A rejected derivative still makes its member ineligible under
    ``--allow-unapproved`` (§10.1's override "covers approval only"):
    ``ochre_sea_star``'s rejected ``cut_svg`` still refuses the whole
    (``refuse`` mode) build, flag or no flag."""
    _reject_ochre_sea_stars_cut_svg_after_standard_pack_approval(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG, "--allow-unapproved"])

    assert result.exit_code == 1
    assert "ochre_sea_star\t" in result.output
    assert "cut_svg: rejected" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_allow_unapproved_admitted_unapproved_members_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    _fix_license_year(monkeypatch)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG, "--allow-unapproved"])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["admitted_unapproved_members"] == snapshot(name="admitted_unapproved_members")


# --- DXF conversion (ADR 0013, §7) -------------------------------------------


@pytest.mark.integration
def test_build_produces_dxf_converted_from_the_effective_cut_svg(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A product with ``cut_svg`` included and ``dxf`` listed produces
    ``DXF/<name>-cut.dxf`` per member, converted from the effective
    ``cut_svg`` -- the override when one is present, not the generated file
    underneath it."""
    _generate_and_approve_standard_pack_types(monkeypatch, temp_catalog_root)

    # ochre_sea_star's cut_svg is overridden with a distinct, real generated
    # cut_svg (ADR 0007's override is any file under overrides/ named like
    # the generated one; this does not need to have come from an editor).
    other_cut_svg = (
        temp_catalog_root
        / "assets"
        / "giant_green_anemone"
        / "derived"
        / "giant-green-anemone-cut.svg"
    ).read_bytes()
    ochre_dir = temp_catalog_root / "assets" / "ochre_sea_star"
    generated_cut_svg = (ochre_dir / "derived" / "ochre-sea-star-cut.svg").read_bytes()
    assert other_cut_svg != generated_cut_svg
    override_path = ochre_dir / "overrides" / "ochre-sea-star-cut.svg"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_bytes(other_cut_svg)
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "cut_svg"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG)
    package_dir = build_dir / STANDARD_PACK_TOP_LEVEL
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    dxf_members = {m["asset_id"]: m for m in manifest["dxf_members"]}

    for asset_id, cut_svg_filename in STANDARD_PACK_CUT_SVG_FILES.items():
        dxf_path = package_dir / "DXF" / _dxf_filename(cut_svg_filename)
        assert dxf_path.is_file()
        assert dxf_members[asset_id]["source_derivative_type"] == "cut_svg"

    # ochre_sea_star's DXF came from its override, not the generated cut_svg
    # underneath it.
    ochre_dxf_bytes = (package_dir / "DXF" / "ochre-sea-star-cut.dxf").read_bytes()
    assert ochre_dxf_bytes == svg_to_dxf_bytes(other_cut_svg)
    assert ochre_dxf_bytes != svg_to_dxf_bytes(generated_cut_svg)
    assert (
        dxf_members["ochre_sea_star"]["source_content_hash"]
        == hashlib.sha256(other_cut_svg).hexdigest()
    )
    assert (
        dxf_members["ochre_sea_star"]["content_hash"] == hashlib.sha256(ochre_dxf_bytes).hexdigest()
    )


@pytest.mark.integration
def test_build_produces_dxf_converted_from_silhouette_svg_when_cut_svg_not_included(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A product with ``silhouette_svg`` and no ``cut_svg`` produces DXFs
    converted from ``silhouette_svg`` (ADR 0013's fallback)."""
    _write_silhouette_only_dxf_product(temp_catalog_root, SILHOUETTE_ONLY_SLUG)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "silhouette_svg"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["build", SILHOUETTE_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, SILHOUETTE_ONLY_SLUG)
    package_dir = build_dir / SILHOUETTE_ONLY_TOP_LEVEL
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))

    for asset_id in ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"):
        silhouette_svg = temp_catalog_root / "assets" / asset_id / "derived"
        svg_filename = next(
            p.name for p in silhouette_svg.iterdir() if p.name.endswith("-silhouette.svg")
        )
        dxf_bytes = (package_dir / "DXF" / _dxf_filename(svg_filename)).read_bytes()
        assert dxf_bytes == svg_to_dxf_bytes((silhouette_svg / svg_filename).read_bytes())

    dxf_members = {m["asset_id"]: m for m in manifest["dxf_members"]}
    for asset_id in ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"):
        assert dxf_members[asset_id]["source_derivative_type"] == "silhouette_svg"


@pytest.mark.integration
def test_rebuilding_the_standard_pack_with_no_changes_produces_byte_identical_dxfs(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_standard_pack_types(monkeypatch, temp_catalog_root)

    first = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert first.exit_code == 0, first.output
    build_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG)
    package_dir = build_dir / STANDARD_PACK_TOP_LEVEL
    dxf_bytes_1 = {
        asset_id: (package_dir / "DXF" / _dxf_filename(cut_svg_filename)).read_bytes()
        for asset_id, cut_svg_filename in STANDARD_PACK_CUT_SVG_FILES.items()
    }
    manifest_bytes_1 = (build_dir / "manifest.json").read_bytes()

    second = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert second.exit_code == 0, second.output
    dxf_bytes_2 = {
        asset_id: (package_dir / "DXF" / _dxf_filename(cut_svg_filename)).read_bytes()
        for asset_id, cut_svg_filename in STANDARD_PACK_CUT_SVG_FILES.items()
    }
    manifest_bytes_2 = (build_dir / "manifest.json").read_bytes()

    assert dxf_bytes_2 == dxf_bytes_1
    assert manifest_bytes_2 == manifest_bytes_1


@pytest.mark.integration
def test_dxf_conversion_failure_refuses_the_build_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A conversion failure (here: hand-corrupting the effective cut_svg's
    path data past what ``svgelements`` can parse) fails the whole build,
    naming the asset, and writes nothing (§35)."""
    _generate_and_approve_standard_pack_types(monkeypatch, temp_catalog_root)

    ochre_dir = temp_catalog_root / "assets" / "ochre_sea_star"
    cut_svg_path = ochre_dir / "derived" / "ochre-sea-star-cut.svg"
    corrupted = cut_svg_path.read_text(encoding="utf-8").replace('d="M', 'd="M0,0 L abc M', 1)
    override_path = ochre_dir / "overrides" / "ochre-sea-star-cut.svg"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(corrupted, encoding="utf-8")
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "cut_svg"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])

    assert result.exit_code == 1
    assert "ochre_sea_star" in result.output
    assert "DXF" in result.output
    assert not (temp_catalog_root / "builds").exists()


@pytest.mark.integration
def test_dxf_is_locked_by_snapshot_and_its_entity_count_matches_the_svgs_closed_paths(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    _generate_and_approve_standard_pack_types(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert result.exit_code == 0, result.output

    package_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG) / STANDARD_PACK_TOP_LEVEL
    dxf_bytes = (package_dir / "DXF" / "ochre-sea-star-cut.dxf").read_bytes()
    svg_bytes = (package_dir / "SVG" / "ochre-sea-star-cut.svg").read_bytes()

    assert dxf_bytes.decode("ascii") == snapshot(name="ochre_sea_star_cut_dxf")
    # an independent oracle (§_count_close_commands's own docstring), not
    # closed_rings itself: this asset's cut file is potrace-generated, so
    # its own explicit Z count already equals its closed-subpath count.
    assert _entity_count(dxf_bytes) == _count_close_commands(svg_bytes)
