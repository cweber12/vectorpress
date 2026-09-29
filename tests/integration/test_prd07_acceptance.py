"""PRD 7 acceptance walk-through: previews, listing metadata and marketplace
export (§16, §17, §18, §19, §26, §27, §36, ADR 0014, ADR 0015, ADR 0016,
ADR 0017, ADR 0018).

PRD 7's own Acceptance paragraph, in order: ``vpress listing draft`` on a
fixture product without a listing appends exactly the drafted table, every
pre-existing byte unchanged; running it again, or on a partial listing,
refuses and changes nothing. ``vpress build`` on a product without a
listing refuses naming the draft command and writes nothing. Building the
fixture product produces ``previews/`` with ``01``-``05`` at both canvases
at the right pixel sizes; a one-type, <=12-member product produces no
``04`` or ``05``; no preview or export file is inside the ZIP. A catalog
``templates/previews/brand.css`` override changes the rendered HTML and is
named in the build report; a template reading an undefined variable fails
the build naming it; a template referencing a remote URL fails the build.
Changing ``card_style`` in ``brand.toml`` makes every built product report
needs-rebuild with "previews out of date", with no product file changed;
rebuilding changes the previews. Editing listing text reports "listing
changed"; rebuilding carries the edit into every export, and the listing is
never rewritten. The Etsy bundle for a product with a 141-character title
and 14 tags flags the title, lists the 14th tag under "does not fit", and
the build still succeeds with the warnings in the manifest. A product with
one ``ai_generated`` member of three gets "1 of 3" disclosure in every
bundle and ``listing.json``, and no licensing notes anywhere in
``builds/``. A brand naming a font the tool does not ship, with no font
file, is a brand metadata problem and the build refuses. (The real-catalog
item is covered separately, with a human in the loop.)

This performs that walk-through end to end, in the same order, on a
temporary copy of the fixture catalog, through the ``CliRunner`` every other
acceptance test in this package already uses. Every mutation reuses a
pattern already proven in ``test_listing_draft.py``, ``test_build.py``,
``test_previews.py`` or ``test_needs_rebuild.py`` -- this module drives them
in one connected story instead of inventing new fixtures. Three fixture
products (``pacific_coast_tide_pool_standard_pack``,
``pacific_coast_tide_pool_png_only``, ``kelp_forest_mini_pack``) are built
once and reused across steps; two temp-only products cover what no
committed fixture reaches on its own -- 13 synthetic members at two
derivative types for the ``variants``/``contents`` preview types (§16's own
"2+ types" and ">12 members" floors), and a three-member product naming
``owl_limpet`` for the AI-disclosure "1 of 3" scenario (§26).
"""

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from vectorpress.build.export import EXPORT_DIRNAME, LISTING_EXPORT_FILENAME
from vectorpress.catalog.listing_draft import COMMAND_NAME
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

STANDARD_PACK_SLUG = "pacific_coast_tide_pool_standard_pack"
PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
MINI_PACK_SLUG = "kelp_forest_mini_pack"

#: The header comment `vpress listing draft` opens a drafted table with
#: (ADR 0016) -- stripped back off a fixture product's own already-drafted
#: listing to reach the "no [listing] yet" state item 1 below needs, the
#: same reversal ``test_listing_draft.py`` uses.
_DRAFTED_HEADER_MARKER = "\n# Drafted by `vpress listing draft`"


def _without_drafted_listing(text: str) -> str:
    return text[: text.index(_DRAFTED_HEADER_MARKER)]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


#: A fixed LICENSE.txt build year (§27), so nothing here depends on which
#: real calendar year the suite happens to run in.
FIXED_LICENSE_YEAR = 2026


def _fix_license_year(monkeypatch: pytest.MonkeyPatch, year: int = FIXED_LICENSE_YEAR) -> None:
    monkeypatch.setattr("vectorpress.build.product_build._current_year", lambda: year)


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


#: A minimal, valid [listing] table (§18), the same shape test_build.py's
#: own temp-only products use (ADR 0016's build-time gate needs one).
_TEST_PRODUCT_LISTING_TOML = (
    "\n[listing]\n"
    'title = "Test product"\n'
    'short_title = ""\n'
    'description = "Test fixture."\n'
    'category = ""\n'
    'license_type = "Test License"\n'
)

# --- item 3: a product reaching both the "variants" and "contents" floors ---

VARIANTS_CONTENTS_SLUG = "variants_contents_walkthrough_product"
#: Just over §16's ">12 members" floor for `contents`, kept small so this
#: walkthrough's own tracing cost stays reasonable (test_previews.py's own
#: 49-member fixture proves the multi-page split; one page is enough here).
VARIANTS_CONTENTS_COUNT = 13

#: The source silhouette every synthetic member's own asset folder shares
#: (``purple_sea_urchin``'s): real artwork to crop, not a blank canvas --
#: the same source test_previews.py's own many-members fixture copies.
_VARIANTS_CONTENTS_SOURCE_ASSET = "purple_sea_urchin"

_VARIANTS_CONTENTS_ASSET_TOML = """\
common_name = "Walkthrough Test {index:03d}"
display_name = "Walkthrough Test {index:03d}"
description = "A synthetic test asset for the PRD 7 acceptance walkthrough."
subject_category = "Test"
taxonomic_group = "Test"

rights_status = "original_artwork"
accuracy_status = "approved"

[[sources]]
role = "silhouette"
file = "silhouette.png"
"""


def _write_variants_contents_product(root: Path, count: int) -> None:
    """``count`` synthetic assets, each its own folder, plus a product
    naming them inline with two derivative types (§16's own "variants" and
    "contents" floors: 2+ types, more than 12 members)."""
    source_sources_dir = root / "assets" / _VARIANTS_CONTENTS_SOURCE_ASSET / "sources"
    asset_ids: list[str] = []
    for index in range(1, count + 1):
        asset_id = f"variants_contents_test_{index:03d}"
        asset_ids.append(asset_id)
        asset_dir = root / "assets" / asset_id
        shutil.copytree(source_sources_dir, asset_dir / "sources")
        (asset_dir / "asset.toml").write_text(
            _VARIANTS_CONTENTS_ASSET_TOML.format(index=index), encoding="utf-8"
        )

    product_text = (
        'derivative_types = ["transparent_png", "cut_svg"]\n'
        'formats = ["png", "svg"]\n'
        'tier = "individual"\n'
        "price = 9.00\n\n"
        "[membership]\n"
        f"asset_ids = {asset_ids!r}\n" + _TEST_PRODUCT_LISTING_TOML
    ).replace("'", '"')
    (root / "products" / f"{VARIANTS_CONTENTS_SLUG}.toml").write_text(
        product_text, encoding="utf-8"
    )


# --- item 7: one ai_generated member of three -------------------------------

AI_DISCLOSURE_SLUG = "ai_disclosure_walkthrough_product"
_AI_DISCLOSURE_TEXT = (
    "1 of 3 designs in this pack were created with generative AI image "
    "tools and converted to vector files."
)
#: owl_limpet's own committed licensing notes (asset.toml): never written
#: anywhere under builds/ (ADR 0018).
_FORBIDDEN_LICENSING_TEXT = "Midjourney"


def _write_ai_disclosure_product(root: Path) -> None:
    """A temp-only product with three members, only ``owl_limpet`` -- the
    fixture's own ``ai_generated`` asset, with its committed licensing notes
    left untouched -- carrying that rights status (§26, ADR 0018)."""
    product_text = (
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership]\n"
        'asset_ids = ["owl_limpet", "ochre_sea_star", "giant_green_anemone"]\n'
        "\n[listing]\n"
        'title = "Walkthrough AI Disclosure Product"\n'
        'short_title = ""\n'
        'description = "Test fixture with one ai_generated member of three."\n'
        'category = "Nature & Wildlife"\n'
        'license_type = "Test License"\n'
    )
    (root / "products" / f"{AI_DISCLOSURE_SLUG}.toml").write_text(product_text, encoding="utf-8")


@pytest.mark.integration
def test_prd_07_acceptance_walkthrough(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _fix_license_year(monkeypatch)
    monkeypatch.chdir(temp_catalog_root)

    # === 1. `vpress listing draft` appends exactly the drafted table,
    # every pre-existing byte unchanged; running it again, or on a partial
    # listing, refuses and changes nothing. ===
    # write_bytes, never write_text, for these two: write_text applies this
    # platform's own newline translation (LF -> CRLF on Windows), which
    # would make the file's own detected newline (ADR 0016's
    # _detect_newline) drift from the fixture's committed LF convention
    # and break the byte-prefix comparisons below.
    mini_pack_path = temp_catalog_root / "products" / f"{MINI_PACK_SLUG}.toml"
    stripped_mini_pack = _without_drafted_listing(mini_pack_path.read_text(encoding="utf-8"))
    stripped_mini_pack_bytes = stripped_mini_pack.encode("utf-8")
    mini_pack_path.write_bytes(stripped_mini_pack_bytes)

    png_only_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    stripped_png_only = _without_drafted_listing(png_only_path.read_text(encoding="utf-8"))
    stripped_png_only_bytes = stripped_png_only.encode("utf-8")
    png_only_path.write_bytes(stripped_png_only_bytes)

    # 1a. Drafting a product with no [listing] appends exactly the drafted
    # table: the file's own pre-existing bytes are an unchanged prefix.
    draft_result = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])
    assert draft_result.exit_code == 0, draft_result.output
    after_draft = mini_pack_path.read_bytes()
    assert after_draft.startswith(stripped_mini_pack_bytes)
    appended = after_draft[len(stripped_mini_pack_bytes) :].decode("utf-8")
    assert appended.startswith(_DRAFTED_HEADER_MARKER)
    assert "[listing]" in appended
    assert 'short_title = "Kelp Forest Mini Pack"' in appended

    # 1b. Running it again refuses and changes nothing.
    rerun_result = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])
    assert rerun_result.exit_code == 1
    assert mini_pack_path.read_bytes() == after_draft

    # 1c. Drafting on a product with a partial listing refuses and changes
    # nothing.
    with png_only_path.open("a", encoding="utf-8") as handle:
        handle.write('\n[listing]\ntitle = "Only a title"\n')
    partial_bytes = png_only_path.read_bytes()
    partial_draft_result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])
    assert partial_draft_result.exit_code == 1
    assert png_only_path.read_bytes() == partial_bytes

    # Restore the no-listing state and draft PNG_ONLY_SLUG for real: its
    # own drafted values are needed, byte-for-byte, by steps 5b and 6 below.
    png_only_path.write_bytes(stripped_png_only_bytes)
    real_draft_result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])
    assert real_draft_result.exit_code == 0, real_draft_result.output

    # === 2. `vpress build` on a product without a listing refuses, naming
    # the draft command, and writes nothing. ===
    standard_pack_path = temp_catalog_root / "products" / f"{STANDARD_PACK_SLUG}.toml"
    standard_pack_original = standard_pack_path.read_bytes()
    standard_pack_text = standard_pack_original.decode("utf-8")
    standard_pack_path.write_text(
        standard_pack_text[: standard_pack_text.index("\n[listing]")] + "\n", encoding="utf-8"
    )

    no_listing_build = runner.invoke(app, ["build", STANDARD_PACK_SLUG])
    assert no_listing_build.exit_code == 1
    assert f"{COMMAND_NAME} {STANDARD_PACK_SLUG}" in no_listing_build.output
    assert not (temp_catalog_root / "builds").exists()

    standard_pack_path.write_bytes(standard_pack_original)

    # === Get every member eligible, add the two temp-only products this
    # walkthrough needs, and build every product once. ===
    _write_variants_contents_product(temp_catalog_root, VARIANTS_CONTENTS_COUNT)
    _write_ai_disclosure_product(temp_catalog_root)

    runner.invoke(app, ["generate", "--all"])
    for derivative_type in ("cut_svg", "silhouette_svg", "transparent_png"):
        approve_result = runner.invoke(app, ["approve", "--all", "--type", derivative_type])
        assert approve_result.exit_code == 0, approve_result.output

    built_slugs = (
        STANDARD_PACK_SLUG,
        PNG_ONLY_SLUG,
        MINI_PACK_SLUG,
        VARIANTS_CONTENTS_SLUG,
        AI_DISCLOSURE_SLUG,
    )
    for slug in built_slugs:
        build_result = runner.invoke(app, ["build", slug])
        assert build_result.exit_code == 0, build_result.output

    # === 3. Previews `01`-`05` at both canvases at the right pixel sizes;
    # a one-type, <=12-member product produces no `04` or `05`; no preview
    # or export file is inside the ZIP. ===
    canvas_sizes = {"square": (2000, 2000), "landscape": (2400, 1600)}

    variants_build_dir = _build_dir(temp_catalog_root, VARIANTS_CONTENTS_SLUG)
    variants_previews_dir = variants_build_dir / "previews"
    variants_preview_names = {p.name for p in variants_previews_dir.iterdir() if p.is_file()}
    expected_variants_previews = {
        f"{nn}-{name}-{canvas}.png"
        for nn, name in (("01", "main"), ("02", "included"), ("03", "formats"), ("04", "variants"))
        for canvas in canvas_sizes
    } | {f"05-contents-1-{canvas}.png" for canvas in canvas_sizes}
    assert variants_preview_names == expected_variants_previews
    for name in variants_preview_names:
        canvas = "square" if "square" in name else "landscape"
        with Image.open(variants_previews_dir / name) as image:
            assert image.size == canvas_sizes[canvas]

    zip_paths = list(variants_build_dir.glob("*.zip"))
    assert len(zip_paths) == 1
    with zipfile.ZipFile(zip_paths[0]) as zip_file:
        zip_names = zip_file.namelist()
    assert not any("preview" in name.lower() for name in zip_names)
    assert not any(EXPORT_DIRNAME in name for name in zip_names)

    for slug in (PNG_ONLY_SLUG, MINI_PACK_SLUG):
        previews_dir = _build_dir(temp_catalog_root, slug) / "previews"
        preview_names = {p.name for p in previews_dir.iterdir() if p.is_file()}
        expected = {
            f"{nn}-{name}-{canvas}.png"
            for nn, name in (("01", "main"), ("02", "included"), ("03", "formats"))
            for canvas in canvas_sizes
        }
        assert preview_names == expected

    # === 4. A catalog `templates/previews/brand.css` override changes the
    # rendered HTML and is named in the build report; a template reading an
    # undefined variable fails the build naming it; a template referencing
    # a remote URL fails the build. ===
    previews_override_dir = temp_catalog_root / "templates" / "previews"
    previews_override_dir.mkdir(parents=True)
    (previews_override_dir / "brand.css").write_text(
        "body { background: hotpink; }\n", encoding="utf-8"
    )

    css_override_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert css_override_result.exit_code == 0, css_override_result.output
    assert "Catalog template overrides: 1" in css_override_result.output
    assert "  templates/previews/brand.css" in css_override_result.output
    css_html = (temp_catalog_root / "templates" / "previews" / "brand.css").read_text(
        encoding="utf-8"
    )
    assert "hotpink" in css_html  # sanity: the override itself is what the build read
    (previews_override_dir / "brand.css").unlink()

    override_template_path = previews_override_dir / "main.html.j2"
    override_template_path.write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        "{% block content %}{{ not_a_real_context_variable }}{% endblock %}\n",
        encoding="utf-8",
    )
    undefined_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert undefined_result.exit_code == 1
    assert "main.html.j2" in undefined_result.output
    assert "not_a_real_context_variable" in undefined_result.output
    override_template_path.unlink()

    override_template_path.write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        '{% block content %}<img src="https://example.invalid/remote-logo.png">{% endblock %}\n',
        encoding="utf-8",
    )
    remote_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert remote_result.exit_code == 1
    assert "main.html.j2" in remote_result.output
    assert "https://example.invalid/remote-logo.png" in remote_result.output
    override_template_path.unlink()

    # Rebuild cleanly, override gone, so PNG_ONLY_SLUG is a valid "current"
    # baseline again for step 5.
    clean_rebuild = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert clean_rebuild.exit_code == 0, clean_rebuild.output

    # === 5a. Changing `card_style` in `brand.toml` makes every built
    # product report needs-rebuild with "previews out of date", with no
    # product file changed; rebuilding changes the previews. ===
    product_bytes_before = {
        slug: (temp_catalog_root / "products" / f"{slug}.toml").read_bytes() for slug in built_slugs
    }
    brand_path = temp_catalog_root / "brand.toml"
    brand_text = brand_path.read_text(encoding="utf-8")
    before_accent = 'accent_color = "#C45D26"'
    assert before_accent in brand_text
    brand_path.write_text(
        brand_text.replace(before_accent, 'accent_color = "#2244ff"'), encoding="utf-8"
    )

    for slug in built_slugs:
        product_result = runner.invoke(app, ["product", slug])
        assert product_result.exit_code == 0, product_result.output
        assert "Build: needs rebuild" in product_result.stdout
        assert "previews out of date" in product_result.stdout
        assert "listing changed" not in product_result.stdout

    for slug, original_bytes in product_bytes_before.items():
        assert (temp_catalog_root / "products" / f"{slug}.toml").read_bytes() == original_bytes

    for slug in built_slugs:
        rebuild_result = runner.invoke(app, ["build", slug])
        assert rebuild_result.exit_code == 0, rebuild_result.output
        current_result = runner.invoke(app, ["product", slug])
        assert "Build: current" in current_result.stdout

    # === 5b. Editing listing text reports "listing changed"; rebuilding
    # carries the edit into every export, and the listing is never
    # rewritten. ===
    product_text = png_only_path.read_text(encoding="utf-8")
    before_description = (
        'description = "The tide pool subjects in this catalog, hand-picked rather than '
        'grouped by a\\nrule.\\n\\nHand-illustrated, scientifically accurate cut files."'
    )
    assert before_description in product_text
    sentinel = "EDITED PITCH SENTINEL"
    edited_product_text = product_text.replace(before_description, f'description = "{sentinel}"')
    png_only_path.write_text(edited_product_text, encoding="utf-8")

    listing_changed_result = runner.invoke(app, ["product", PNG_ONLY_SLUG])
    assert listing_changed_result.exit_code == 0, listing_changed_result.output
    assert "Build: needs rebuild" in listing_changed_result.stdout
    assert "listing changed" in listing_changed_result.stdout
    assert "previews out of date" not in listing_changed_result.stdout

    listing_rebuild_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert listing_rebuild_result.exit_code == 0, listing_rebuild_result.output
    assert png_only_path.read_text(encoding="utf-8") == edited_product_text

    png_only_build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    for filename in ("etsy.txt", "creative-fabrica.txt", "design-bundles.txt", "direct-store.txt"):
        bundle_text = (png_only_build_dir / EXPORT_DIRNAME / filename).read_text(encoding="utf-8")
        assert sentinel in bundle_text
    listing_export = json.loads(
        (png_only_build_dir / EXPORT_DIRNAME / LISTING_EXPORT_FILENAME).read_text(encoding="utf-8")
    )
    assert listing_export["listing"]["description"] == sentinel

    # === 6. The Etsy bundle for a product with a 141-character title and
    # 14 tags flags the title, lists the 14th tag under "does not fit", and
    # the build still succeeds with the warnings in the manifest. ===
    text = png_only_path.read_text(encoding="utf-8")
    # chr(0x2013), not a literal en dash, so this source file carries no
    # ambiguous-character token (ruff RUF001) -- the drafted title's own
    # separator, matched exactly regardless.
    before_title = f'title = "Pacific Coast Tide Pool {chr(0x2013)} PNG Cut Files"'
    assert before_title in text
    over_limit_title = "T" * 141
    text = text.replace(before_title, f'title = "{over_limit_title}"')

    before_tags = 'tags = ["tide pool", "pacific coast", "color png", "png"]'
    assert before_tags in text
    fourteen_tags = [f"tag{i}" for i in range(1, 15)]
    tags_literal = ", ".join(f'"{tag}"' for tag in fourteen_tags)
    text = text.replace(before_tags, f"tags = [{tags_literal}]")
    png_only_path.write_text(text, encoding="utf-8")

    limits_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert limits_result.exit_code == 0, limits_result.output
    assert "Export limit warnings: 1" in limits_result.output
    assert "etsy\ttitle\t141 characters (limit 140)" in limits_result.output
    assert "Does not fit: 1" in limits_result.output
    assert "etsy\ttags\ttag14" in limits_result.output

    limits_manifest = json.loads((png_only_build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert limits_manifest["export_limit_warnings"] == [
        {"marketplace": "etsy", "field": "title", "measure": "141 characters (limit 140)"}
    ]
    assert limits_manifest["export_does_not_fit"] == [
        {"marketplace": "etsy", "field": "tags", "item": "tag14"}
    ]

    # === 7. A product with one ai_generated member of three gets "1 of 3"
    # disclosure in every bundle and listing.json; licensing notes appear
    # nowhere under builds/. ===
    ai_build_dir = _build_dir(temp_catalog_root, AI_DISCLOSURE_SLUG)
    ai_export = json.loads(
        (ai_build_dir / EXPORT_DIRNAME / LISTING_EXPORT_FILENAME).read_text(encoding="utf-8")
    )
    assert ai_export["ai_disclosure"] == {
        "count": 1,
        "total": 3,
        "text": _AI_DISCLOSURE_TEXT,
    }
    for filename in ("etsy.txt", "creative-fabrica.txt", "design-bundles.txt", "direct-store.txt"):
        bundle_text = (ai_build_dir / EXPORT_DIRNAME / filename).read_text(encoding="utf-8")
        assert _AI_DISCLOSURE_TEXT in bundle_text

    builds_root = temp_catalog_root / "builds"
    for path in builds_root.rglob("*"):
        if path.is_file() and path.suffix != ".zip":
            assert _FORBIDDEN_LICENSING_TEXT not in path.read_text(
                encoding="utf-8", errors="ignore"
            ), path
    for zip_path in builds_root.rglob("*.zip"):
        with zipfile.ZipFile(zip_path) as zip_file:
            for name in zip_file.namelist():
                assert _FORBIDDEN_LICENSING_TEXT.encode("utf-8") not in zip_file.read(name), name

    # === 8. A brand naming a font the tool does not ship, with no font
    # file, is a brand metadata problem and the build refuses. ===
    final_brand_text = brand_path.read_text(encoding="utf-8")
    before_heading_font = 'heading_font = "Space Grotesk"'
    assert before_heading_font in final_brand_text
    brand_path.write_text(
        final_brand_text.replace(before_heading_font, 'heading_font = "Comic Sans MS"'),
        encoding="utf-8",
    )

    font_result = runner.invoke(app, ["build", MINI_PACK_SLUG])
    assert font_result.exit_code == 1
    assert "brand.toml" in font_result.output
    assert "typography.heading_font" in font_result.output
    assert "Comic Sans MS" in font_result.output
