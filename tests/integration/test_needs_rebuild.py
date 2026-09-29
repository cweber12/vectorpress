"""Needs rebuild end to end, against a temporary copy of the fixture catalog
(§23, §34, ADR 0004, ADR 0014, ADR 0017, CONTEXT.md "Needs rebuild").

Runs against a temporary copy, never the committed fixture directly: these
tests build real products under ``builds/`` (``tests/fixtures/catalog/README.md``).

Builds all three fixture products -- ``pacific_coast_tide_pool_png_only``,
``pacific_coast_tide_pool_standard_pack`` (both over the ``pacific_coast_tide_pool``
collection: ``ochre_sea_star``, ``giant_green_anemone``, ``purple_sea_urchin``) and
``kelp_forest_mini_pack`` (a rule collection whose only fixture match is
``purple_sea_urchin``, §10's ``exclude`` product) -- so a source change to
``ochre_sea_star`` names exactly the two products that include it, and
``kelp_forest_mini_pack`` -- containing neither -- stays current.

The **previews out of date** and **listing changed** sections below render
real previews through Chromium (every ``_build_every_fixture_product`` call
does), so they run slower than the member-difference tests above.
"""

import io
import json
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.build.previews import CANVASES, PREVIEW_TYPES, render_preview_html
from vectorpress.build.product_resolution import resolve_product
from vectorpress.catalog.assets import asset_dir, load_assets
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.catalog.overrides import effective_derivative
from vectorpress.catalog.products import load_products, lookup_product
from vectorpress.cli.app import app
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.format_folder import copied_folder

runner = CliRunner()

#: The dry-rendered "main" preview's own type/canvas (§16) -- picked once
#: here, the same objects :func:`render_preview_html` itself iterates in
#: :mod:`vectorpress.build.previews`, since one canvas is enough to prove a
#: brand edit reaches the rendered markup.
_MAIN_PREVIEW_TYPE = next(t for t in PREVIEW_TYPES if t.name == "main")
_SQUARE_CANVAS = next(c for c in CANVASES if c.name == "square")

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
STANDARD_PACK_SLUG = "pacific_coast_tide_pool_standard_pack"
MINI_PACK_SLUG = "kelp_forest_mini_pack"

#: Same normalisation CLAUDE.md prescribes for CLI output assertions (see
#: tests/integration/test_validate.py's own ``_normalized_output``): CI
#: runners detect color support and split words across ANSI escape codes.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_DRAWING_RE = re.compile(r"[─-╿]")


def _normalized_output(output: str) -> str:
    return " ".join(_BOX_DRAWING_RE.sub(" ", _ANSI_RE.sub("", output)).split("\n"))


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


#: A fixed LICENSE.txt build year (§27), so a build's manifest -- and any
#: snapshot of it -- never depends on which real calendar year the suite
#: happens to run in.
FIXED_LICENSE_YEAR = 2026


def _fix_license_year(monkeypatch: pytest.MonkeyPatch, year: int = FIXED_LICENSE_YEAR) -> None:
    monkeypatch.setattr("vectorpress.build.product_build._current_year", lambda: year)


def _build_every_fixture_product(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Generate, approve and build all three fixture products (§10's
    ``kelp_forest_mini_pack`` resolves to its one matching member,
    ``purple_sea_urchin``): the state every "current" assertion in this
    module starts from."""
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    for derivative_type in ("transparent_png", "silhouette_svg", "cut_svg"):
        approve_result = runner.invoke(app, ["approve", "--all", "--type", derivative_type])
        assert approve_result.exit_code == 0, approve_result.output

    for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG, MINI_PACK_SLUG):
        build_result = runner.invoke(app, ["build", slug])
        assert build_result.exit_code == 0, build_result.output


def _product_output(root: Path, slug: str) -> str:
    """'vpress product <slug>''s output, addressed by ``--catalog`` rather
    than a chdir -- callers use this after ``monkeypatch.chdir`` has already
    put the working directory elsewhere for a different reason."""
    result = runner.invoke(app, ["--catalog", str(root), "product", slug])
    assert result.exit_code == 0, result.output
    return result.stdout


def _render_main_html(root: Path, slug: str) -> str:
    """``slug``'s real "main" preview HTML, rendered purely via Jinja
    (:func:`~vectorpress.build.previews.render_preview_html`, no Chromium)
    against the catalog's own *current* brand/product/membership on disk --
    gathered the same way :func:`~vectorpress.build.product_build.build_product`
    itself would, so a brand edit's effect on the actual rendered markup can
    be asserted directly, never inferred from a PNG's bytes (previews are
    not held to byte-identical output, ADR 0014, so PNG bytes alone can
    differ -- or fail to -- for reasons having nothing to do with what
    changed)."""
    config = load_catalog_config(root)
    product = lookup_product(load_products(root, config), config, slug).product
    assert product is not None
    brand = load_brand(root).brand
    assert brand is not None
    known_assets = load_assets(root, config).assets
    known_collections = load_collections(root, config).collections
    resolved = resolve_product(product, root, config, known_assets, known_collections)
    assets_by_id = {asset.id: asset for asset in known_assets}

    content_by_member: dict[str, dict[DerivativeType, bytes]] = {}
    files_by_folder: dict[str, list[str]] = {}
    for member in resolved.eligible_members:
        asset = assets_by_id[member.asset_id]
        asset_dir_path = asset_dir(root, config, asset.id)
        for derivative_type in product.derivative_types:
            filename = derivative_filename(asset.display_name, derivative_type)
            effective = effective_derivative(asset_dir_path, filename)
            assert effective is not None
            content_by_member.setdefault(asset.id, {})[derivative_type] = effective.bytes
            folder = copied_folder(derivative_type)
            assert folder is not None
            files_by_folder.setdefault(folder.value.upper(), []).append(filename)

    return render_preview_html(
        root,
        _MAIN_PREVIEW_TYPE,
        _SQUARE_CANVAS,
        product,
        brand,
        resolved.eligible_members,
        assets_by_id,
        content_by_member,
        files_by_folder,
    )


# --- acceptance: every fixture product is current once built ----------------


@pytest.mark.integration
def test_every_fixture_product_is_current_after_building_all(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG, MINI_PACK_SLUG):
        assert "Build: current" in _product_output(temp_catalog_root, slug)

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 0" in status_result.stdout


# --- acceptance: a never-built product is distinct from needs rebuild -------


@pytest.mark.integration
def test_a_never_built_product_shows_never_built(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["product", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    assert "Build: never built" in result.stdout
    assert "Build: current" not in result.stdout
    assert "Build: needs rebuild" not in result.stdout


# --- acceptance: a source change flags exactly the products containing it ---


@pytest.mark.integration
def test_changing_one_source_flags_only_the_products_containing_that_asset(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Changing ``ochre_sea_star``'s ``flatcolor`` source (the role
    ``transparent_png`` selects for it -- ``silhouette_svg``/``cut_svg``
    select ``silhouette`` instead, so this touches only ``transparent_png``),
    regenerating and re-approving, must flag exactly the two products that
    include ``ochre_sea_star``'s ``transparent_png``
    (``pacific_coast_tide_pool_png_only`` and
    ``pacific_coast_tide_pool_standard_pack``) -- naming the changed (asset,
    type) -- while ``kelp_forest_mini_pack``, whose one member is
    ``purple_sea_urchin``, stays current."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    # ochre_sea_star is the fixture's only asset with a flatcolor source at
    # all, so there is no other asset's own flatcolor.png to substitute
    # (test_build.py's override tests swap a generated file between two
    # assets for exactly this reason): a real edit -- a filled rectangle --
    # stands in for a hand edit instead, still a real, valid PNG, just
    # different bytes.
    ochre_flatcolor_path = (
        temp_catalog_root / "assets" / "ochre_sea_star" / "sources" / "flatcolor.png"
    )
    original_bytes = ochre_flatcolor_path.read_bytes()
    with Image.open(ochre_flatcolor_path) as image:
        edited = image.convert("RGBA")
        ImageDraw.Draw(edited).rectangle((0, 0, 9, 9), fill=(255, 0, 255, 255))
        buffer = io.BytesIO()
        edited.save(buffer, format="PNG")
    assert buffer.getvalue() != original_bytes
    ochre_flatcolor_path.write_bytes(buffer.getvalue())

    monkeypatch.chdir(temp_catalog_root)
    # acorn_barnacle always fails to generate in this fixture (it belongs to
    # no fixture collection, §35 -- irrelevant here, the same non-zero exit
    # test_build.py's own generate-and-approve helpers already ignore).
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    png_only_output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    standard_pack_output = _product_output(temp_catalog_root, STANDARD_PACK_SLUG)
    mini_pack_output = _product_output(temp_catalog_root, MINI_PACK_SLUG)

    assert "Build: needs rebuild" in png_only_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in png_only_output
    assert "Build: needs rebuild" in standard_pack_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in standard_pack_output
    assert "Build: current" in mini_pack_output

    status_result = runner.invoke(app, ["--catalog", str(temp_catalog_root), "status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 2" in status_result.stdout


# --- acceptance: an override, then discarding it, each flag the containing products ---


@pytest.mark.integration
def test_adding_then_discarding_an_override_each_flag_the_containing_product(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    # A distinct, real generated PNG stands in for a hand-edited override
    # (ADR 0007's override is any file under overrides/ named like the
    # generated one).
    other_generated = (
        temp_catalog_root
        / "assets"
        / "giant_green_anemone"
        / "derived"
        / "giant-green-anemone-color.png"
    ).read_bytes()
    ochre_dir = temp_catalog_root / "assets" / "ochre_sea_star"
    override_path = ochre_dir / "overrides" / "ochre-sea-star-color.png"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_bytes(other_generated)

    monkeypatch.chdir(temp_catalog_root)
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    with_override_output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    standard_pack_with_override_output = _product_output(temp_catalog_root, STANDARD_PACK_SLUG)
    assert "Build: needs rebuild" in with_override_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in with_override_output
    # ochre_sea_star's transparent_png is also included in the standard
    # pack, so the identical override flags it too, while
    # kelp_forest_mini_pack -- whose one member is purple_sea_urchin --
    # stays current throughout.
    assert "Build: needs rebuild" in standard_pack_with_override_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in standard_pack_with_override_output
    assert "Build: current" in _product_output(temp_catalog_root, MINI_PACK_SLUG)

    # Rebuild both so the override becomes the last manifest's own recorded
    # content hash -- discarding it then must flag needs rebuild again,
    # relative to *this* build, not the pre-override one.
    for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG):
        build_result = runner.invoke(app, ["build", slug])
        assert build_result.exit_code == 0, build_result.output
        assert "Build: current" in _product_output(temp_catalog_root, slug)

    discard_result = runner.invoke(
        app, ["override", "discard", "ochre_sea_star", "transparent_png", "--yes"]
    )
    assert discard_result.exit_code == 0, discard_result.output

    after_discard_png_only = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    after_discard_standard_pack = _product_output(temp_catalog_root, STANDARD_PACK_SLUG)
    assert "Build: needs rebuild" in after_discard_png_only
    assert "ochre_sea_star\ttransparent_png\tchanged" in after_discard_png_only
    assert "Build: needs rebuild" in after_discard_standard_pack
    assert "ochre_sea_star\ttransparent_png\tchanged" in after_discard_standard_pack
    assert "Build: current" in _product_output(temp_catalog_root, MINI_PACK_SLUG)


# --- acceptance: vpress status's count is locked by snapshot -----------------


@pytest.mark.integration
def test_status_products_needing_rebuild_count_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    _fix_license_year(monkeypatch)
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    # The catalog root itself (status's own second line) is a fresh tmp_path
    # every run -- redacted before comparison, the same way its own
    # unpredictable text would break any other full-output snapshot.
    normalized = _normalized_output(result.stdout).replace(str(temp_catalog_root), "<catalog-root>")
    assert normalized == snapshot


@pytest.mark.integration
def test_status_products_needing_rebuild_count_is_locked_by_snapshot_when_nonzero(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    """The same snapshot lock, once one product actually needs rebuilding
    (an edited license template, the simplest deterministic trigger) --
    the zero-count snapshot above only ever proves the count field exists,
    never that it counts correctly."""
    _fix_license_year(monkeypatch)
    _build_every_fixture_product(monkeypatch, temp_catalog_root)
    license_path = temp_catalog_root / "license_template.txt"
    license_path.write_text(
        license_path.read_text(encoding="utf-8") + "\nAn extra line.\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    normalized = _normalized_output(result.stdout).replace(str(temp_catalog_root), "<catalog-root>")
    assert normalized == snapshot


# --- fix round 1: a manifest predating the current format never crashes -----


@pytest.mark.integration
def test_a_manifest_predating_the_current_format_reads_as_needs_rebuild_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A real catalog's own build history can predate a field a newer tool
    version added to the manifest -- reading it back must never crash
    ``vpress product`` or ``vpress status`` (the controller's ruling):
    report needs rebuild with an explicit reason instead."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    manifest_path = temp_catalog_root / "builds" / PNG_ONLY_SLUG / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    del data["license_template_hash"]
    del data["readme_wording_hash"]
    del data["allow_unapproved"]
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    product_result = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in product_result
    assert "manifest predates the current format" in product_result

    status_result = runner.invoke(app, ["--catalog", str(temp_catalog_root), "status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 1" in status_result.stdout


# --- fix round 1: added / removed, driven directly -----------------------------


@pytest.mark.integration
def test_a_newly_included_derivative_type_shows_added(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Widening a product's own ``derivative_types`` after it was built adds
    (asset, type) entries no last manifest has -- ``silhouette_svg`` is
    already approved for every ``pacific_coast_tide_pool`` member
    (``_build_every_fixture_product`` approves it catalog-wide for the
    standard pack), so each becomes eligible again immediately, with one new
    entry apiece."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    product_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    text = product_path.read_text(encoding="utf-8")
    before = 'derivative_types = ["transparent_png"]\nformats = ["png"]'
    assert before in text
    product_path.write_text(
        text.replace(
            before,
            'derivative_types = ["transparent_png", "silhouette_svg"]\nformats = ["png", "svg"]',
        ),
        encoding="utf-8",
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)

    assert "Build: needs rebuild" in output
    for asset_id in ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"):
        assert f"{asset_id}\tsilhouette_svg\tadded" in output


@pytest.mark.integration
def test_a_member_leaving_the_collection_shows_removed(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Dropping a member from an explicit collection membership after the
    product was built removes every (asset, type) entry the last manifest
    had for it -- ``kelp_forest_mini_pack``'s own rule membership is
    unaffected (it never referenced ``pacific_coast_tide_pool``'s own
    explicit list), so it stays current."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    collection_path = temp_catalog_root / "collections" / "pacific_coast_tide_pool.toml"
    text = collection_path.read_text(encoding="utf-8")
    before = 'asset_ids = ["ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"]'
    assert before in text
    collection_path.write_text(
        text.replace(before, 'asset_ids = ["ochre_sea_star", "giant_green_anemone"]'),
        encoding="utf-8",
    )

    png_only_output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    standard_pack_output = _product_output(temp_catalog_root, STANDARD_PACK_SLUG)
    mini_pack_output = _product_output(temp_catalog_root, MINI_PACK_SLUG)

    assert "Build: needs rebuild" in png_only_output
    assert "purple_sea_urchin\ttransparent_png\tremoved" in png_only_output
    assert "Build: needs rebuild" in standard_pack_output
    for derivative_type in ("cut_svg", "silhouette_svg", "transparent_png"):
        assert f"purple_sea_urchin\t{derivative_type}\tremoved" in standard_pack_output
    # purple_sea_urchin is kelp_forest_mini_pack's rule membership's only
    # match, entirely independent of pacific_coast_tide_pool's own explicit
    # list -- dropping it there leaves the mini pack untouched.
    assert "Build: current" in mini_pack_output


# --- fix round 1: brand wording changes, driven directly ------------------------


@pytest.mark.integration
def test_license_template_change_flags_needs_rebuild_naming_the_reason(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    license_path = temp_catalog_root / "license_template.txt"
    license_path.write_text(
        license_path.read_text(encoding="utf-8") + "\nAn extra line.\n", encoding="utf-8"
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "license template: changed" in output
    assert "README wording: changed" not in output


@pytest.mark.integration
def test_readme_wording_change_flags_needs_rebuild_naming_the_reason(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    brand_path = temp_catalog_root / "brand.toml"
    before = 'standard_wording = "Hand-illustrated, scientifically accurate cut files."'
    text = brand_path.read_text(encoding="utf-8")
    assert before in text
    brand_path.write_text(
        text.replace(before, 'standard_wording = "Hand-illustrated, small-batch cut files."'),
        encoding="utf-8",
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "README wording: changed" in output
    assert "license template: changed" not in output


# --- fix round 1: reference size changes, driven directly -----------------------


@pytest.mark.integration
def test_reference_size_change_flags_needs_rebuild_naming_the_change(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    product_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    text = product_path.read_text(encoding="utf-8")
    assert "reference_size_in" not in text
    # Inserted before the product's own [listing] table, not appended at
    # the file's end: a bare key appended after a table header parses as
    # that table's own key instead (TOML), and this fixture product now
    # carries a drafted [listing] (ADR 0016).
    table_start = text.index("\n[listing]")
    new_text = text[: table_start + 1] + "reference_size_in = 6.0\n" + text[table_start + 1 :]
    product_path.write_text(new_text, encoding="utf-8")

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "reference size: changed (3in → 6in)" in output


# --- fix round 1: a build made with --allow-unapproved reads as current -----------


@pytest.mark.integration
def test_a_build_made_with_allow_unapproved_reads_as_current_with_no_further_change(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The controller's ruling: needs-rebuild re-resolves eligibility under
    the *same* ``--allow-unapproved`` the last build recorded, so a build
    made with it shows current -- never ``removed`` for its own admitted
    members -- when nothing has actually changed since."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    build_result = runner.invoke(app, ["build", PNG_ONLY_SLUG, "--allow-unapproved"])
    assert build_result.exit_code == 0, build_result.output
    assert "Admitted unapproved: 3" in build_result.output

    assert "Build: current" in _product_output(temp_catalog_root, PNG_ONLY_SLUG)


# --- acceptance: a brand edit reaches every built product, no product.toml changes ---


@pytest.mark.integration
def test_card_style_change_flags_previews_out_of_date_for_every_built_product(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0014's own worked example: ``card_style`` is one of the
    presentation hash's brand fields, so editing it reaches every already
    built product as "previews out of date" -- naming no product.toml
    change -- and rebuilding clears the reason. Previews are not held to
    byte-identical output (ADR 0014), so this asserts the actual effect --
    the dry-rendered HTML text before and after (:func:`_render_main_html`,
    via ``render_preview_html``) and the manifest's own recorded
    ``presentation_hash`` before and after the rebuild -- never PNG bytes,
    which Chromium/OS nondeterminism could differ (or fail to differ) on
    for reasons having nothing to do with ``card_style`` actually reaching
    the template."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    product_bytes_before = {
        slug: (temp_catalog_root / "products" / f"{slug}.toml").read_bytes()
        for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG, MINI_PACK_SLUG)
    }
    manifest_path = temp_catalog_root / "builds" / PNG_ONLY_SLUG / "manifest.json"
    presentation_hash_before = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "presentation_hash"
    ]
    html_before = _render_main_html(temp_catalog_root, PNG_ONLY_SLUG)

    brand_path = temp_catalog_root / "brand.toml"
    text = brand_path.read_text(encoding="utf-8")
    before = 'accent_color = "#C45D26"'
    assert before in text
    new_accent_color = "#2244ff"
    brand_path.write_text(
        text.replace(before, f'accent_color = "{new_accent_color}"'), encoding="utf-8"
    )

    html_after = _render_main_html(temp_catalog_root, PNG_ONLY_SLUG)
    assert html_after != html_before
    assert new_accent_color not in html_before.lower()
    assert new_accent_color in html_after.lower()

    for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG, MINI_PACK_SLUG):
        output = _product_output(temp_catalog_root, slug)
        assert "Build: needs rebuild" in output
        assert "previews out of date" in output
        assert "listing changed" not in output

    for slug, original_bytes in product_bytes_before.items():
        assert (temp_catalog_root / "products" / f"{slug}.toml").read_bytes() == original_bytes

    monkeypatch.chdir(temp_catalog_root)
    for slug in (PNG_ONLY_SLUG, STANDARD_PACK_SLUG, MINI_PACK_SLUG):
        build_result = runner.invoke(app, ["build", slug])
        assert build_result.exit_code == 0, build_result.output
        assert "Build: current" in _product_output(temp_catalog_root, slug)

    presentation_hash_after = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "presentation_hash"
    ]
    assert presentation_hash_after != presentation_hash_before


# --- acceptance: a catalog template override reports previews out of date ---


@pytest.mark.integration
def test_adding_a_catalog_template_override_reports_previews_out_of_date(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0014's "every template file the build used, shipped or
    override" -- adding a catalog ``templates/previews/`` override, even
    one that changes nothing about what a template shows
    (``{% extends %}`` with no block overridden), still flags previews out
    of date: the override file itself is now part of what a build loads."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    override_path = temp_catalog_root / "templates" / "previews" / "main.html.j2"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text('{% extends "shipped/main.html.j2" %}\n', encoding="utf-8")

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "previews out of date" in output


# --- acceptance: replacing the mark or a font file reports previews out of date ---


@pytest.mark.integration
def test_replacing_the_mark_file_reports_previews_out_of_date(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0014's "the mark and font file bytes" are hashed directly --
    replacing ``brand.toml``'s own ``mark_file`` on disk, with
    ``brand.toml`` itself untouched, still flags previews out of date."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    mark_path = temp_catalog_root / "mark.png"
    with Image.open(mark_path) as image:
        edited = image.convert("RGBA")
        ImageDraw.Draw(edited).rectangle((0, 0, 9, 9), fill=(0, 255, 0, 255))
        buffer = io.BytesIO()
        edited.save(buffer, format="PNG")
    assert buffer.getvalue() != mark_path.read_bytes()
    mark_path.write_bytes(buffer.getvalue())

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "previews out of date" in output


@pytest.mark.integration
def test_replacing_a_catalog_font_file_reports_previews_out_of_date(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The font-file half of the same ADR 0014 input: a brand naming a
    catalog font file (rather than one of the two shipped families) whose
    file bytes change on disk -- ``brand.toml`` itself untouched -- must
    still flag previews out of date."""
    font_path = temp_catalog_root / "custom-heading.woff2"
    font_path.write_bytes(b"FONT-BYTES-V1")
    brand_path = temp_catalog_root / "brand.toml"
    text = brand_path.read_text(encoding="utf-8")
    before = 'heading_font = "Space Grotesk"\n'
    assert before in text
    brand_path.write_text(
        text.replace(before, before + 'heading_font_file = "custom-heading.woff2"\n'),
        encoding="utf-8",
    )

    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    font_path.write_bytes(b"FONT-BYTES-V2-DIFFERENT-LENGTH")

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "previews out of date" in output


# --- acceptance: editing listing text reports listing changed, rebuild clears it ---


@pytest.mark.integration
def test_editing_a_non_preview_listing_field_reports_listing_changed_only(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0017: the listing hash covers the whole ``[listing]`` table, not
    only ``title``/``short_title`` (the two fields previews themselves
    print, ADR 0014's own listing inputs) -- editing ``marketplace_notes``
    alone flags "listing changed" with no "previews out of date". Rebuilding
    clears it, and the product's own TOML file is never rewritten by the
    tool (ADR 0005): its bytes after the rebuild are exactly what this test
    itself wrote."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    product_path = temp_catalog_root / "products" / f"{PNG_ONLY_SLUG}.toml"
    text = product_path.read_text(encoding="utf-8")
    before = 'marketplace_notes = ""'
    assert before in text
    edited_text = text.replace(before, 'marketplace_notes = "Bundle price valid through June."')
    product_path.write_text(edited_text, encoding="utf-8")

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "listing changed" in output
    assert "previews out of date" not in output

    monkeypatch.chdir(temp_catalog_root)
    build_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert build_result.exit_code == 0, build_result.output

    assert "Build: current" in _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert product_path.read_text(encoding="utf-8") == edited_text


# --- acceptance: a rights status change never reports previews out of date ---


@pytest.mark.integration
def test_changing_an_assets_rights_status_does_not_report_previews_out_of_date(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0015: rights status is not in the preview context at all -- a
    rights-status edit alone, no derivative content change, must leave
    every needs-rebuild reason untouched, including the presentation
    hash."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    asset_path = temp_catalog_root / "assets" / "ochre_sea_star" / "asset.toml"
    text = asset_path.read_text(encoding="utf-8")
    before = 'rights_status = "original_artwork"'
    assert before in text
    asset_path.write_text(
        text.replace(before, 'rights_status = "licensed_source"'), encoding="utf-8"
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: current" in output
    assert "previews out of date" not in output


# --- acceptance: a broken catalog override never crashes a read-only command ---


@pytest.mark.integration
def test_a_catalog_override_syntax_error_reports_previews_out_of_date_without_crashing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A broken catalog override must never crash ``vpress product`` or
    ``vpress status`` (§34): needs-rebuild's own dry render (ADR 0014)
    catches the identical :class:`~vectorpress.build.previews.
    PreviewRenderError` an actual rebuild would refuse on, here a Jinja
    syntax error, and reports it as "previews out of date" naming the
    template, instead of letting the exception propagate."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    override_path = temp_catalog_root / "templates" / "previews" / "main.html.j2"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        '{% extends "shipped/main.html.j2" %}\n{% block content %}{% if %}broken{% endblock %}\n',
        encoding="utf-8",
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "previews out of date" in output
    assert "cannot render" in output
    assert "main.html.j2" in output

    status_result = runner.invoke(app, ["--catalog", str(temp_catalog_root), "status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 3" in status_result.stdout


@pytest.mark.integration
def test_a_catalog_override_undefined_variable_reports_previews_out_of_date_without_crashing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The undefined-variable half of the same broken-override guarantee:
    ``vpress product`` and ``vpress status`` both still exit cleanly,
    reporting "previews out of date" rather than an uncaught
    ``UndefinedError``."""
    _build_every_fixture_product(monkeypatch, temp_catalog_root)

    override_path = temp_catalog_root / "templates" / "previews" / "main.html.j2"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        '{% extends "shipped/main.html.j2" %}\n'
        "{% block content %}{{ this_is_not_in_the_context }}{% endblock %}\n",
        encoding="utf-8",
    )

    output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in output
    assert "previews out of date" in output
    assert "cannot render" in output
    assert "main.html.j2" in output
    assert "this_is_not_in_the_context" in output

    status_result = runner.invoke(app, ["--catalog", str(temp_catalog_root), "status"])
    assert status_result.exit_code == 0, status_result.output
    assert "Products needing rebuild: 3" in status_result.stdout
