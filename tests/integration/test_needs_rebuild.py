"""Needs rebuild end to end, against a temporary copy of the fixture catalog
(§23, §34, ADR 0004, CONTEXT.md "Needs rebuild").

Runs against a temporary copy, never the committed fixture directly: these
tests build real products under ``builds/`` (``tests/fixtures/catalog/README.md``).

Builds all three fixture products -- ``pacific_coast_tide_pool_png_only``,
``pacific_coast_tide_pool_standard_pack`` (both over the ``pacific_coast_tide_pool``
collection: ``ochre_sea_star``, ``giant_green_anemone``, ``purple_sea_urchin``) and
``kelp_forest_mini_pack`` (a rule collection whose only fixture match is
``purple_sea_urchin``, §10's ``exclude`` product) -- so a source change to
``ochre_sea_star`` names exactly the two products that include it, and
``kelp_forest_mini_pack`` -- containing neither -- stays current.
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

from vectorpress.cli.app import app

runner = CliRunner()

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
    product_path.write_text(text + "reference_size_in = 6.0\n", encoding="utf-8")

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
