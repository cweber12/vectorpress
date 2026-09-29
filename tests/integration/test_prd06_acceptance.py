"""PRD 6 acceptance walk-through: product build and packaging (§7, §10,
§14, §15, §20, §23, §26, §35, §36, ADR 0004, ADR 0005, ADR 0007, ADR 0012,
ADR 0013).

PRD 6's own Acceptance paragraph: "User can build the fixture product,
unzip it, and find only customer files with consistent names; rebuilding
with no changes produces the same logical contents; changing one source
makes exactly the containing products report needs-rebuild; a rejected cut
file is excluded from a cut-file product while the same asset ships in a
PNG product. Also: a build without a valid brand.toml refuses; a 'refuse'
product with an ineligible member fails while an 'exclude' one ships the
rest; an 'ai_generated' asset with empty licensing notes is blocked; a
product whose reference size exceeds a member's cleanup size warns; a
format/type mismatch is reported at load."

This performs that walk-through end to end, in the same order, on a
temporary copy of the fixture catalog, through the ``CliRunner`` every other
acceptance test in this package already uses. Every mutation reuses a
pattern already proven in ``test_build.py`` or ``test_needs_rebuild.py``
(generate/approve helpers, temp-only products, the owl_limpet
licensing-notes blanking, the standard pack's own DXF/SVG/PNG membership) --
this module drives them in one connected story instead of inventing new
fixtures.
"""

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

STANDARD_PACK_SLUG = "pacific_coast_tide_pool_standard_pack"
STANDARD_PACK_TOP_LEVEL = "Tide-Pool-Collection"
PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
# PNG_ONLY_SLUG's own drafted listing short_title is the referenced
# collection's name, "Pacific Coast Tide Pool" (ADR 0016).
PNG_ONLY_TOP_LEVEL = "Pacific-Coast-Tide-Pool"
MINI_PACK_SLUG = "kelp_forest_mini_pack"

PACIFIC_COAST_MEMBERS = ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin")

# Standard pack's own customer files (§20's slugified display name plus type
# suffix): SVG/ from both included *_svg types, PNG/ from transparent_png,
# DXF/ converted from cut_svg (ADR 0013) -- every format folder the PRD
# names, plus README.txt and LICENSE.txt, and nothing else.
STANDARD_PACK_EXPECTED_FILES = sorted(
    [
        "SVG/ochre-sea-star-cut.svg",
        "SVG/ochre-sea-star-silhouette.svg",
        "SVG/giant-green-anemone-cut.svg",
        "SVG/giant-green-anemone-silhouette.svg",
        "SVG/purple-sea-urchin-cut.svg",
        "SVG/purple-sea-urchin-silhouette.svg",
        "PNG/ochre-sea-star-color.png",
        "PNG/giant-green-anemone-color.png",
        "PNG/purple-sea-urchin-color.png",
        "DXF/ochre-sea-star-cut.dxf",
        "DXF/giant-green-anemone-cut.dxf",
        "DXF/purple-sea-urchin-cut.dxf",
        "README.txt",
        "LICENSE.txt",
    ]
)


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


#: A minimal, valid [listing] table (§18), the same one test_build.py's own
#: temp-only products use: build_product's own listing gate (ADR 0016)
#: refuses any product with none, and these temp-only products exist to
#: exercise one specific build behavior, never listing content.
#: short_title = "" keeps package_name falling back to the product's own
#: slug.
_TEST_PRODUCT_LISTING_TOML = (
    "\n[listing]\n"
    'title = "Test product"\n'
    'short_title = ""\n'
    'description = "Test fixture."\n'
    'category = ""\n'
    'license_type = "Test License"\n'
)


#: A fixed LICENSE.txt build year (§27), the same fixed year test_build.py
#: and test_needs_rebuild.py use, so nothing here depends on which real
#: calendar year the suite happens to run in.
FIXED_LICENSE_YEAR = 2026


def _fix_license_year(monkeypatch: pytest.MonkeyPatch, year: int = FIXED_LICENSE_YEAR) -> None:
    monkeypatch.setattr("vectorpress.build.product_build._current_year", lambda: year)


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


def _generate_and_approve_every_fixture_type(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Get every ``pacific_coast_tide_pool`` (and ``kelp_forest_mini_pack``)
    member to eligible: generate everything -- ``acorn_barnacle`` always
    fails (§35), irrelevant here, the same non-zero exit
    ``test_build.py``'s own helpers already ignore -- then approve every
    asset's ``cut_svg``, ``silhouette_svg`` and ``transparent_png``."""
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    for derivative_type in ("cut_svg", "silhouette_svg", "transparent_png"):
        approve_result = runner.invoke(app, ["approve", "--all", "--type", derivative_type])
        assert approve_result.exit_code == 0, approve_result.output


def _build_every_fixture_product(root: Path) -> None:
    for slug in (STANDARD_PACK_SLUG, PNG_ONLY_SLUG, MINI_PACK_SLUG):
        result = runner.invoke(app, ["build", slug])
        assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_prd_06_acceptance_walkthrough(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _fix_license_year(monkeypatch)
    monkeypatch.chdir(temp_catalog_root)
    _generate_and_approve_every_fixture_type(monkeypatch, temp_catalog_root)
    _build_every_fixture_product(temp_catalog_root)

    # === 1. Build the fixture product, unzip it, and find only customer
    # files with consistent names (SVG/, PNG/, DXF/, README.txt,
    # LICENSE.txt). ===
    build_dir = _build_dir(temp_catalog_root, STANDARD_PACK_SLUG)
    zip_path = build_dir / f"{STANDARD_PACK_TOP_LEVEL}.zip"
    package_dir = build_dir / STANDARD_PACK_TOP_LEVEL

    with zipfile.ZipFile(zip_path) as zip_file:
        zip_names = sorted(zip_file.namelist())
    assert zip_names == [f"{STANDARD_PACK_TOP_LEVEL}/{f}" for f in STANDARD_PACK_EXPECTED_FILES]

    package_files = sorted(
        p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()
    )
    assert package_files == STANDARD_PACK_EXPECTED_FILES

    # === 2. A rebuild with no changes gives the same logical contents. ===
    zip_bytes_before = zip_path.read_bytes()
    manifest_path = build_dir / "manifest.json"
    manifest_bytes_before = manifest_path.read_bytes()

    rebuild_result = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert rebuild_result.exit_code == 0, rebuild_result.output

    assert zip_path.read_bytes() == zip_bytes_before
    assert manifest_path.read_bytes() == manifest_bytes_before

    # === 3. Changing one source makes exactly the containing products
    # report needs rebuild. ===
    # ochre_sea_star's flatcolor source is the role transparent_png selects
    # for it (silhouette_svg/cut_svg select silhouette instead), so this
    # touches only transparent_png, and only the two products that include
    # it -- kelp_forest_mini_pack, whose one member is purple_sea_urchin,
    # must stay current.
    ochre_flatcolor_path = (
        temp_catalog_root / "assets" / "ochre_sea_star" / "sources" / "flatcolor.png"
    )
    original_flatcolor_bytes = ochre_flatcolor_path.read_bytes()
    with Image.open(ochre_flatcolor_path) as image:
        edited = image.convert("RGBA")
        ImageDraw.Draw(edited).rectangle((0, 0, 9, 9), fill=(255, 0, 255, 255))
        buffer = io.BytesIO()
        edited.save(buffer, format="PNG")
    assert buffer.getvalue() != original_flatcolor_bytes
    ochre_flatcolor_path.write_bytes(buffer.getvalue())

    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    standard_pack_after_change = runner.invoke(app, ["product", STANDARD_PACK_SLUG])
    png_only_after_change = runner.invoke(app, ["product", PNG_ONLY_SLUG])
    mini_pack_after_change = runner.invoke(app, ["product", MINI_PACK_SLUG])
    assert standard_pack_after_change.exit_code == 0, standard_pack_after_change.output
    assert png_only_after_change.exit_code == 0, png_only_after_change.output
    assert mini_pack_after_change.exit_code == 0, mini_pack_after_change.output

    assert "Build: needs rebuild" in standard_pack_after_change.stdout
    assert "ochre_sea_star\ttransparent_png\tchanged" in standard_pack_after_change.stdout
    assert "Build: needs rebuild" in png_only_after_change.stdout
    assert "ochre_sea_star\ttransparent_png\tchanged" in png_only_after_change.stdout
    assert "Build: current" in mini_pack_after_change.stdout

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 2" in status_result.stdout

    # === 8 (out of story order; ochre_sea_star's cut_svg must still be
    # approved, before item 4/6 below rejects it). A product whose
    # reference size exceeds a member's cleanup size warns. ===
    # ochre_sea_star's own cleanup size is 6in (tests/fixtures/catalog's own
    # asset.toml comment, ADR 0012), smaller than this temp-only product's
    # 8in reference size.
    oversized_slug = "ochre_oversized_cut_svg"
    (temp_catalog_root / "products" / f"{oversized_slug}.toml").write_text(
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n"
        "reference_size_in = 8.0\n\n"
        "[membership]\n"
        'asset_ids = ["ochre_sea_star"]\n' + _TEST_PRODUCT_LISTING_TOML,
        encoding="utf-8",
    )

    oversized_build = runner.invoke(app, ["build", oversized_slug])

    assert oversized_build.exit_code == 0, oversized_build.output
    assert "Cleanup size warnings: 1" in oversized_build.output
    assert "ochre_sea_star\tcleanup size 6in < product reference size 8in" in oversized_build.output
    oversized_manifest = json.loads(
        (_build_dir(temp_catalog_root, oversized_slug) / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert oversized_manifest["cleanup_size_warnings"] == [
        {"asset_id": "ochre_sea_star", "cleanup_size_in": 6.0}
    ]

    # === 4 & 6. A rejected cut file is excluded from a cut-file product
    # while the same asset ships in the PNG product. A 'refuse' product with
    # an ineligible member fails while an 'exclude' one ships the rest. ===
    reject_result = runner.invoke(app, ["reject", "ochre_sea_star", "cut_svg"])
    assert reject_result.exit_code == 0, reject_result.output

    # 6a. 'refuse' (the standard pack's own default): the whole build fails,
    # naming the ineligible member and its reason, and writes nothing new.
    standard_pack_zip_before_refusal = zip_path.read_bytes()
    refuse_build = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert refuse_build.exit_code == 1
    assert "1 ineligible member(s)" in refuse_build.output
    assert "ochre_sea_star\t" in refuse_build.output
    assert "cut_svg: rejected" in refuse_build.output
    assert zip_path.read_bytes() == standard_pack_zip_before_refusal

    # 6b. Switched to 'exclude': ships the two eligible members, reports and
    # records the excluded one.
    standard_pack_path = temp_catalog_root / "products" / f"{STANDARD_PACK_SLUG}.toml"
    text = standard_pack_path.read_text(encoding="utf-8")
    assert "ineligible_members" not in text
    table_start = text.find("\n[")
    standard_pack_path.write_text(
        text[: table_start + 1] + 'ineligible_members = "exclude"\n' + text[table_start + 1 :],
        encoding="utf-8",
    )

    exclude_build = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert exclude_build.exit_code == 0, exclude_build.output
    assert "Excluded: 1" in exclude_build.output
    assert "ochre_sea_star\tcut_svg: rejected" in exclude_build.output

    exclude_package_files = sorted(
        p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*") if p.is_file()
    )
    assert not any("ochre-sea-star" in f for f in exclude_package_files)
    assert any("giant-green-anemone" in f for f in exclude_package_files)
    assert any("purple-sea-urchin" in f for f in exclude_package_files)

    exclude_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert all(m["asset_id"] != "ochre_sea_star" for m in exclude_manifest["members"])
    assert exclude_manifest["excluded_members"] == [
        {
            "asset_id": "ochre_sea_star",
            "blocking_reasons": [
                {"kind": "derivative_status", "derivative_type": "cut_svg", "value": "rejected"}
            ],
        }
    ]

    # 4b. The same asset still ships in the PNG product: ochre_sea_star's
    # rejected cut_svg never touches transparent_png, which this product
    # doesn't even include.
    png_only_rebuild = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert png_only_rebuild.exit_code == 0, png_only_rebuild.output
    png_only_manifest = json.loads(
        (_build_dir(temp_catalog_root, PNG_ONLY_SLUG) / "manifest.json").read_text(encoding="utf-8")
    )
    assert any(m["asset_id"] == "ochre_sea_star" for m in png_only_manifest["members"])
    assert png_only_manifest["excluded_members"] == []
    png_only_package_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG) / PNG_ONLY_TOP_LEVEL
    assert (png_only_package_dir / "PNG" / "ochre-sea-star-color.png").is_file()

    # === 5. A build without a valid brand.toml refuses. ===
    brand_path = temp_catalog_root / "brand.toml"
    brand_bytes = brand_path.read_bytes()
    brand_path.unlink()

    no_brand_build = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert no_brand_build.exit_code == 1
    assert "brand.toml" in no_brand_build.output
    assert "not found" in no_brand_build.output

    brand_path.write_bytes(brand_bytes)

    # === 7. An ai_generated asset with empty licensing notes is blocked.
    # ===
    # owl_limpet is the fixture's ai_generated asset (§26); its own
    # licensing_notes are blanked here, the same way test_build.py's
    # _add_ai_generated_test_product does, rather than editing the
    # committed fixture (owl_limpet keeps its real notes there).
    owl_limpet_asset_path = temp_catalog_root / "assets" / "owl_limpet" / "asset.toml"
    owl_limpet_text = owl_limpet_asset_path.read_text(encoding="utf-8")
    assert 'rights_status = "ai_generated"\n' in owl_limpet_text
    licensing_notes_line = (
        'licensing_notes = "Generated with Midjourney (v6) under its commercial-use terms '
        'for paid subscribers; the ai_generated rights-status fixture (§26)."\n'
    )
    assert licensing_notes_line in owl_limpet_text
    owl_limpet_asset_path.write_text(
        owl_limpet_text.replace(licensing_notes_line, 'licensing_notes = ""\n'), encoding="utf-8"
    )

    owl_limpet_product_slug = "owl_limpet_ai_generated_test_product"
    (temp_catalog_root / "products" / f"{owl_limpet_product_slug}.toml").write_text(
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership]\n"
        'asset_ids = ["owl_limpet"]\n' + _TEST_PRODUCT_LISTING_TOML,
        encoding="utf-8",
    )
    runner.invoke(app, ["generate", "owl_limpet"])
    approve_owl_limpet = runner.invoke(app, ["approve", "owl_limpet", "--all-types"])
    assert approve_owl_limpet.exit_code == 0, approve_owl_limpet.output

    owl_limpet_build = runner.invoke(app, ["build", owl_limpet_product_slug])
    assert owl_limpet_build.exit_code == 1
    assert "owl_limpet" in owl_limpet_build.output
    assert (
        "licensing notes: must name the AI tool and its terms (rights status: ai generated)"
        in owl_limpet_build.output
    )
    assert not _build_dir(temp_catalog_root, owl_limpet_product_slug).exists()

    # === 9. A format/type mismatch is reported at load. ===
    # png_only lists derivative_types = ["transparent_png"] -- changing its
    # own formats to ["svg"] leaves nothing filling "svg" and leaves
    # transparent_png carried by no listed format: a product metadata
    # problem at load time (ADR 0013), not a build failure, so 'vpress
    # build' fails identically to 'vpress product'.
    png_only_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    png_only_text = png_only_path.read_text(encoding="utf-8")
    before_formats = 'formats = ["png"]'
    assert before_formats in png_only_text
    png_only_path.write_text(
        png_only_text.replace(before_formats, 'formats = ["svg"]'), encoding="utf-8"
    )

    mismatch_product = runner.invoke(app, ["product", PNG_ONLY_SLUG])
    mismatch_build = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert mismatch_product.exit_code == 1
    assert mismatch_build.exit_code == 1
    assert mismatch_build.output == mismatch_product.output
    assert "Metadata problems" in mismatch_build.output
    assert "is not filled by any included derivative type" in mismatch_build.output
    assert "is not carried by any included format" in mismatch_build.output
