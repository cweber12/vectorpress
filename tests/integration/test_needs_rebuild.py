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
    assert "Build: needs rebuild" in with_override_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in with_override_output

    # Rebuild so the override becomes the last manifest's own recorded
    # content hash -- discarding it then must flag needs rebuild again,
    # relative to *this* build, not the pre-override one.
    build_result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert build_result.exit_code == 0, build_result.output
    assert "Build: current" in _product_output(temp_catalog_root, PNG_ONLY_SLUG)

    discard_result = runner.invoke(
        app, ["override", "discard", "ochre_sea_star", "transparent_png", "--yes"]
    )
    assert discard_result.exit_code == 0, discard_result.output

    after_discard_output = _product_output(temp_catalog_root, PNG_ONLY_SLUG)
    assert "Build: needs rebuild" in after_discard_output
    assert "ochre_sea_star\ttransparent_png\tchanged" in after_discard_output


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
