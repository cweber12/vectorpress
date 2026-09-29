"""``vpress build``'s preview rendering end to end, against a temporary copy
of the fixture catalog (§16, ADR 0014, ADR 0015).

Runs against a temporary copy, never the committed fixture directly, the
same reason ``test_build.py`` does (``tests/fixtures/catalog/README.md``).
Chromium actually renders here (unlike ``tests/unit/test_build_previews.py``,
which only exercises the Jinja side): these are the tests CI's own
``playwright install chromium`` step exists for.
"""

import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from vectorpress.catalog.manifests import read_manifest
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
PNG_ONLY_TOP_LEVEL = "Pacific-Coast-Tide-Pool"

EXPECTED_PREVIEWS = [
    "previews/01-main-landscape.png",
    "previews/01-main-square.png",
    "previews/02-included-landscape.png",
    "previews/02-included-square.png",
    "previews/03-formats-landscape.png",
    "previews/03-formats-square.png",
]
EXPECTED_SIZES = {
    "previews/01-main-square.png": (2000, 2000),
    "previews/01-main-landscape.png": (2400, 1600),
    "previews/02-included-square.png": (2000, 2000),
    "previews/02-included-landscape.png": (2400, 1600),
    "previews/03-formats-square.png": (2000, 2000),
    "previews/03-formats-landscape.png": (2400, 1600),
}


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _generate_and_approve_transparent_png(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output


def _generate_and_approve_cut_svg(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "cut_svg"])
    assert approve_result.exit_code == 0, approve_result.output


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


def _preview_files(build_dir: Path) -> dict[str, bytes]:
    previews_dir = build_dir / "previews"
    return {
        f"previews/{path.name}": path.read_bytes()
        for path in previews_dir.iterdir()
        if path.is_file()
    }


@pytest.mark.integration
def test_build_writes_every_preview_type_at_both_canvases_never_in_the_zip_and_lists_them_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    previews_dir = build_dir / "previews"
    assert previews_dir.is_dir()

    preview_names = sorted(p.name for p in previews_dir.iterdir() if p.is_file())
    assert preview_names == sorted(Path(rel_path).name for rel_path in EXPECTED_PREVIEWS)

    for rel_path, (expected_width, expected_height) in EXPECTED_SIZES.items():
        with Image.open(previews_dir / Path(rel_path).name) as image:
            assert image.size == (expected_width, expected_height)

    # Never inside the package or the ZIP (§14).
    package_dir = build_dir / PNG_ONLY_TOP_LEVEL
    package_files = {p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*")}
    assert "previews" not in package_files
    with zipfile.ZipFile(build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip") as zip_file:
        assert not any("preview" in name.lower() for name in zip_file.namelist())

    manifest = read_manifest(temp_catalog_root, PNG_ONLY_SLUG)
    assert manifest is not None
    assert manifest.previews == EXPECTED_PREVIEWS


# --- acceptance: the build report names every catalog template override in use (ADR 0015, #121) --


@pytest.mark.integration
def test_a_build_with_no_catalog_templates_reports_no_overrides(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    assert "Catalog template overrides: 0" in result.output
    assert "templates/previews/" not in result.output


@pytest.mark.integration
def test_a_catalog_brand_css_override_is_named_in_the_build_report(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    override_dir = temp_catalog_root / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "brand.css").write_text("body { background: hotpink; }\n", encoding="utf-8")

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    assert "Catalog template overrides: 1" in result.output
    assert "  templates/previews/brand.css" in result.output


@pytest.mark.integration
def test_catalog_override_reading_an_undefined_variable_refuses_the_build_naming_it_and_leaves_the_previous_build_intact(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    first = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert first.exit_code == 0, first.output
    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    previous_previews = _preview_files(build_dir)
    previous_manifest_bytes = (build_dir / "manifest.json").read_bytes()

    override_dir = temp_catalog_root / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        "{% block content %}{{ not_a_real_context_variable }}{% endblock %}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "main.html.j2" in result.output
    assert "not_a_real_context_variable" in result.output
    # The previous build is untouched -- same preview bytes, same manifest.
    assert _preview_files(build_dir) == previous_previews
    assert (build_dir / "manifest.json").read_bytes() == previous_manifest_bytes


@pytest.mark.integration
def test_catalog_override_referencing_a_remote_url_refuses_the_build(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    override_dir = temp_catalog_root / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        '{% block content %}<img src="https://example.invalid/remote-logo.png">{% endblock %}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "main.html.j2" in result.output
    assert "https://example.invalid/remote-logo.png" in result.output
    assert not (temp_catalog_root / "builds" / PNG_ONLY_SLUG).exists()


# --- `[previews] featured` (§16): an unresolved ID refuses the build -------


@pytest.mark.integration
def test_an_unresolved_featured_id_refuses_the_build_naming_it(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A hand-authored ``[previews] featured`` naming an asset ID that is
    not one of the product's own resolved members is a product metadata
    problem, reported the same way ``vpress build`` already reports every
    other reference problem (§16, CONTEXT.md "Featured member")."""
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)
    product_toml = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    with product_toml.open("a", encoding="utf-8") as f:
        f.write('\n[previews]\nfeatured = ["not_a_real_asset"]\n')

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "not_a_real_asset" in result.output
    assert not (temp_catalog_root / "builds" / PNG_ONLY_SLUG).exists()


# --- Conditional previews (§16): `04 variants` and `05 contents` -----------

MINI_PACK_SLUG = "kelp_forest_mini_pack"


@pytest.mark.integration
def test_a_product_with_one_derivative_type_and_few_members_produces_no_variants_or_contents(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``kelp_forest_mini_pack`` has one derivative type (``cut_svg``) and
    one member (``purple_sea_urchin``) -- short of ``variants``' 2-or-more
    derivative types and ``contents``' more-than-12 members, so neither
    renders (§16): ``04`` and ``05`` stay unused numbers, never empty
    placeholder files."""
    _generate_and_approve_cut_svg(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", MINI_PACK_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, MINI_PACK_SLUG)
    preview_names = sorted(p.name for p in (build_dir / "previews").iterdir() if p.is_file())
    assert preview_names == [
        "01-main-landscape.png",
        "01-main-square.png",
        "02-included-landscape.png",
        "02-included-square.png",
        "03-formats-landscape.png",
        "03-formats-square.png",
    ]

    manifest = read_manifest(temp_catalog_root, MINI_PACK_SLUG)
    assert manifest is not None
    assert not any("variants" in name or "contents" in name for name in manifest.previews)


# A product big enough to exercise both conditional types at once: 2
# derivative types (>= "variants"'s own floor) and 49 members (> "contents"'s
# own floor, and enough for a second, partial contents page -- §16's own
# "48 and the remainder"). Built once per module (module-scoped fixture)
# since generating and tracing 49 assets is the expensive part of this file's
# own tests, not something any one assertion needs to pay for on its own.
MANY_MEMBERS_SLUG = "many_derivative_types_many_members_test_product"
MANY_MEMBERS_COUNT = 49
MANY_MEMBERS_LAST_PAGE_COUNT = MANY_MEMBERS_COUNT - 48

#: The source silhouette every synthetic member's own asset folder shares
#: (``purple_sea_urchin``'s): real, already-tuned artwork (real content to
#: crop -- ``tests/fixtures/catalog/README.md``), not a blank canvas.
_MANY_MEMBERS_SOURCE_ASSET = "purple_sea_urchin"

#: A minimal, valid asset (ADR 0005): ``{index}`` becomes a unique display
#: name and folder ID, so every one of the 49 copies loads as its own,
#: distinct member instead of colliding on ID or on display name (which
#: ``preview_members`` sorts and ``derivative_filename`` slugifies).
_MANY_MEMBERS_ASSET_TOML = """\
common_name = "Contents Test {index:03d}"
display_name = "Contents Test {index:03d}"
description = "A synthetic test asset for preview pagination."
subject_category = "Test"
taxonomic_group = "Test"

rights_status = "original_artwork"
accuracy_status = "approved"

[[sources]]
role = "silhouette"
file = "silhouette.png"
"""


#: The same minimal, valid ``[listing]`` table ``test_build.py`` writes for
#: its own temp-only products (ADR 0016's build-time gate needs one).
_TEST_PRODUCT_LISTING_TOML = (
    "\n[listing]\n"
    'title = "Test product"\n'
    'short_title = ""\n'
    'description = "Test fixture."\n'
    'category = ""\n'
    'license_type = "Test License"\n'
)


def _write_many_members_product(root: Path, count: int) -> list[str]:
    """Write ``count`` synthetic assets (each its own folder, copied from
    ``purple_sea_urchin``'s real silhouette source) plus a product whose
    inline membership lists them by ID, with ``derivative_types =
    ["transparent_png", "cut_svg"]`` (2 types, for ``variants``) and
    ``formats = ["png", "svg"]``. Returns the asset IDs, in the same
    zero-padded order ``display_name`` sorts them (§16's own member order)."""
    source_sources_dir = root / "assets" / _MANY_MEMBERS_SOURCE_ASSET / "sources"
    asset_ids: list[str] = []
    for index in range(1, count + 1):
        asset_id = f"contents_test_{index:03d}"
        asset_ids.append(asset_id)
        asset_dir = root / "assets" / asset_id
        shutil.copytree(source_sources_dir, asset_dir / "sources")
        (asset_dir / "asset.toml").write_text(
            _MANY_MEMBERS_ASSET_TOML.format(index=index), encoding="utf-8"
        )

    product_text = (
        'derivative_types = ["transparent_png", "cut_svg"]\n'
        'formats = ["png", "svg"]\n'
        'tier = "individual"\n'
        "price = 9.00\n\n"
        "[membership]\n"
        f"asset_ids = {asset_ids!r}\n" + _TEST_PRODUCT_LISTING_TOML
    ).replace("'", '"')
    (root / "products" / f"{MANY_MEMBERS_SLUG}.toml").write_text(product_text, encoding="utf-8")
    return asset_ids


@pytest.fixture(scope="module")
def many_members_build_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build :data:`MANY_MEMBERS_SLUG` once for every test in this module
    that reads its own output, rather than once per test: generating and
    tracing 49 members is the expensive part (module's own docstring)."""
    root = tmp_path_factory.mktemp("many_members_catalog") / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    _write_many_members_product(root, MANY_MEMBERS_COUNT)

    catalog_args = ["--catalog", str(root)]
    runner.invoke(app, [*catalog_args, "generate", "--all"])
    for derivative_type in ("transparent_png", "cut_svg"):
        approve_result = runner.invoke(
            app, [*catalog_args, "approve", "--all", "--type", derivative_type]
        )
        assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, [*catalog_args, "build", MANY_MEMBERS_SLUG])
    assert result.exit_code == 0, result.output
    return _build_dir(root, MANY_MEMBERS_SLUG)


@pytest.mark.integration
def test_a_product_with_more_than_12_members_and_2_derivative_types_produces_01_through_05(
    many_members_build_dir: Path,
) -> None:
    previews_dir = many_members_build_dir / "previews"
    preview_names = {p.name for p in previews_dir.iterdir() if p.is_file()}

    expected = {
        f"{number}-{name}-{canvas}.png"
        for number, name in (
            ("01", "main"),
            ("02", "included"),
            ("03", "formats"),
            ("04", "variants"),
        )
        for canvas in ("square", "landscape")
    } | {
        f"05-contents-{page}-{canvas}.png" for page in (1, 2) for canvas in ("square", "landscape")
    }
    assert preview_names == expected

    sizes = {
        "square": (2000, 2000),
        "landscape": (2400, 1600),
    }
    for name in preview_names:
        canvas = "square" if "square" in name else "landscape"
        with Image.open(previews_dir / name) as image:
            assert image.size == sizes[canvas]

    # Never inside the package or the ZIP (§14).
    package_dirs = [
        p for p in many_members_build_dir.iterdir() if p.is_dir() and p.name != "previews"
    ]
    assert len(package_dirs) == 1
    package_files = {p.relative_to(package_dirs[0]).as_posix() for p in package_dirs[0].rglob("*")}
    assert "previews" not in package_files
    zip_paths = list(many_members_build_dir.glob("*.zip"))
    assert len(zip_paths) == 1
    with zipfile.ZipFile(zip_paths[0]) as zip_file:
        assert not any("preview" in name.lower() for name in zip_file.namelist())


@pytest.mark.integration
def test_a_product_with_49_members_produces_two_contents_pages_with_48_and_the_remainder(
    many_members_build_dir: Path,
) -> None:
    """49 members, at 48 per page (§16), means exactly two ``contents``
    pages -- the exact 48-then-1 split itself is
    ``test_build_previews.py::test_pages_splits_contents_at_the_page_size_with_the_remainder_on_its_own_page``'s
    own job (pure Jinja, no Chromium); this proves the real, generated
    catalog wires up to that same math end to end: 49 real members, no
    third page, and every member accounted for in the manifest."""
    previews_dir = many_members_build_dir / "previews"
    assert (previews_dir / "05-contents-1-square.png").is_file()
    assert (previews_dir / "05-contents-2-square.png").is_file()
    assert (previews_dir / "05-contents-1-landscape.png").is_file()
    assert (previews_dir / "05-contents-2-landscape.png").is_file()
    assert not list(previews_dir.glob("05-contents-3-*.png"))

    root = many_members_build_dir.parents[1]
    manifest = read_manifest(root, MANY_MEMBERS_SLUG)
    assert manifest is not None
    # One entry per eligible member (unlike manifest.members, one per
    # included derivative type): the product's own true member count.
    assert len(manifest.asset_rights_statuses) == MANY_MEMBERS_COUNT
    assert MANY_MEMBERS_LAST_PAGE_COUNT == MANY_MEMBERS_COUNT - 48


@pytest.mark.integration
def test_many_members_manifest_lists_previews_in_upload_order(many_members_build_dir: Path) -> None:
    root = many_members_build_dir.parents[1]
    manifest = read_manifest(root, MANY_MEMBERS_SLUG)
    assert manifest is not None

    expected = (
        [f"previews/01-main-{c}.png" for c in ("landscape", "square")]
        + [f"previews/02-included-{c}.png" for c in ("landscape", "square")]
        + [f"previews/03-formats-{c}.png" for c in ("landscape", "square")]
        + [f"previews/04-variants-{c}.png" for c in ("landscape", "square")]
        + [f"previews/05-contents-1-{c}.png" for c in ("landscape", "square")]
        + [f"previews/05-contents-2-{c}.png" for c in ("landscape", "square")]
    )
    assert manifest.previews == expected
