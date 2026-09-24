"""``vpress generate`` end to end against a temporary copy of the fixture
catalog (§6.1, §6.2, §8, §20, §35, §36, issue #23, issue #24).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under each asset's ``derived/``, and the fixture
catalog must never contain one (``tests/fixtures/catalog/README.md``).
"""

import re
import shutil
from pathlib import Path

import pytest
from PIL import Image
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.image import PNGImageSnapshotExtension
from typer.testing import CliRunner

from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance, sha256_bytes
from vectorpress.cli.app import app
from vectorpress.domain import recipe as recipe_module
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import Recipe

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# (asset ID, expected customer-facing filename): §20's slugified display name
# plus transparent_png's ``-color.png`` suffix.
FIXTURE_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-color.png"),
    ("purple_sea_urchin", "purple-sea-urchin-color.png"),
    ("giant_green_anemone", "giant-green-anemone-color.png"),
]

# (asset ID, expected customer-facing filename): §20's slugified display name
# plus silhouette_svg's ``-silhouette.svg`` suffix (issue #24). ochre_sea_star
# is the blob (one subpath), purple_sea_urchin the ring (a hole), and
# giant_green_anemone the blob with a detached island (two disjoint
# subpaths) -- see ``tests/fixtures/catalog/generate_source_pngs.py``.
FIXTURE_SILHOUETTE_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-silhouette.svg"),
    ("purple_sea_urchin", "purple-sea-urchin-silhouette.svg"),
    ("giant_green_anemone", "giant-green-anemone-silhouette.svg"),
]

# (asset ID, expected customer-facing filename): §20's slugified display name
# plus flatcolor_svg's ``-color.svg`` suffix (issue #25). Only ochre_sea_star
# has a flatcolor source; the other two fixture assets have none, so
# flatcolor_svg stays impossible for them (see FIXTURE_IMPOSSIBLE_FLATCOLOR).
FIXTURE_FLATCOLOR_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-color.svg"),
]

# Asset IDs with no flatcolor source (issue #25): flatcolor_svg is impossible
# for both.
FIXTURE_IMPOSSIBLE_FLATCOLOR = ["purple_sea_urchin", "giant_green_anemone"]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


@pytest.mark.integration
def test_generate_all_writes_every_transparent_png_with_provenance(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``generate --all`` on a temp copy of the
    fixture writes each asset's ``<slug>-color.png`` under its ``derived/``,
    each with a provenance record beside it, one report line per
    derivative."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    for asset_id, filename in FIXTURE_OUTPUTS:
        assert f"{asset_id}\ttransparent_png\tgenerated\t{filename}" in result.stdout

        derived_dir = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME
        output_path = derived_dir / filename
        assert output_path.is_file()

        provenance = read_provenance(derived_dir, filename)
        assert provenance is not None
        assert provenance.output_file == filename
        assert provenance.output_hash == sha256_bytes(output_path.read_bytes())

    # flatcolor_svg is impossible for the two fixture assets with no flatcolor
    # source (issue #25: ochre_sea_star now has one, so it is generated instead
    # -- see test_generate_all_writes_the_flatcolor_svg_with_provenance).
    for asset_id in FIXTURE_IMPOSSIBLE_FLATCOLOR:
        assert f"{asset_id}\tflatcolor_svg\timpossible\t" in result.stdout


@pytest.mark.integration
def test_generate_all_writes_every_silhouette_svg_with_provenance(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``generate --all`` on a temp copy of the
    fixture writes each asset's ``<slug>-silhouette.svg`` under its
    ``derived/``, each with a provenance record beside it; ``vpress asset``
    then shows it ``current`` (issue #24). ``generate`` no longer reports
    ``no generator`` for ``silhouette_svg``."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    assert "no generator" not in result.stdout
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout

        derived_dir = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME
        output_path = derived_dir / filename
        assert output_path.is_file()

        provenance = read_provenance(derived_dir, filename)
        assert provenance is not None
        assert provenance.output_file == filename
        assert provenance.generator == "silhouette_svg"
        assert provenance.output_hash == sha256_bytes(output_path.read_bytes())

        asset_result = runner.invoke(app, ["asset", asset_id])
        assert asset_result.exit_code == 0, asset_result.output
        assert f"silhouette_svg\tcurrent\t{filename}" in asset_result.stdout


@pytest.mark.integration
def test_generate_all_writes_the_flatcolor_svg_with_provenance(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1 (issue #25): ``generate --all`` on a temp copy
    of the fixture writes ochre_sea_star's ``ochre-sea-star-color.svg``
    under its ``derived/`` with a provenance record beside it, and reports
    the other two fixture assets' ``flatcolor_svg`` as ``impossible``
    (neither has a flatcolor source). ``generate`` no longer reports ``no
    generator`` for any type."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    assert "no generator" not in result.stdout
    for asset_id, filename in FIXTURE_FLATCOLOR_OUTPUTS:
        assert f"{asset_id}\tflatcolor_svg\tgenerated\t{filename}" in result.stdout

        derived_dir = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME
        output_path = derived_dir / filename
        assert output_path.is_file()

        provenance = read_provenance(derived_dir, filename)
        assert provenance is not None
        assert provenance.output_file == filename
        assert provenance.generator == "flatcolor_svg"
        assert provenance.output_hash == sha256_bytes(output_path.read_bytes())

        asset_result = runner.invoke(app, ["asset", asset_id])
        assert asset_result.exit_code == 0, asset_result.output
        assert f"flatcolor_svg\tcurrent\t{filename}" in asset_result.stdout

    for asset_id in FIXTURE_IMPOSSIBLE_FLATCOLOR:
        assert f"{asset_id}\tflatcolor_svg\timpossible\t" in result.stdout


@pytest.mark.integration
def test_flatcolor_svg_has_one_fill_per_distinct_opaque_source_color_each_a_source_color(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 2: the fixture's flatcolor source has four
    distinct opaque colors (ochre outer ring, cream middle ring, purple
    inner disk, green island -- see
    ``tests/fixtures/catalog/generate_source_pngs.py``); the SVG has
    exactly that many ``fill`` colors, each equal to one of those source
    colors, no more and no fewer."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert result.exit_code == 0, result.output

    output_path = (
        temp_catalog_root
        / "assets"
        / "ochre_sea_star"
        / DERIVED_DIRNAME
        / "ochre-sea-star-color.svg"
    )
    text = output_path.read_text(encoding="utf-8")
    fills = re.findall(r'fill="(#[0-9a-f]{6})"', text)
    assert set(fills) == {"#c45d26", "#e6d2aa", "#5b2e82", "#3a8c5c"}
    assert len(fills) == 4  # one <path> per color, not merged or duplicated


@pytest.mark.integration
def test_flatcolor_svg_has_no_image_stroke_and_a_tight_view_box(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 2: true vector (no ``<image>``), no stroke, and
    a viewBox tight to the traced geometry (smaller than the 16x16 source
    canvas) -- the same §8 guarantees ``silhouette_svg`` already proves,
    now through several fills."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert result.exit_code == 0, result.output

    output_path = (
        temp_catalog_root
        / "assets"
        / "ochre_sea_star"
        / DERIVED_DIRNAME
        / "ochre-sea-star-color.svg"
    )
    text = output_path.read_text(encoding="utf-8")
    assert "<image" not in text
    assert "data:image" not in text
    assert 'stroke="none"' in text
    assert 'stroke="#' not in text
    view_box_match = re.search(r'viewBox="[\d.-]+ [\d.-]+ ([\d.]+) ([\d.]+)"', text)
    assert view_box_match is not None
    width, height = float(view_box_match.group(1)), float(view_box_match.group(2))
    assert width < 16
    assert height < 16


@pytest.mark.integration
def test_flatcolor_svg_draws_the_enclosed_inner_disk_above_the_ring_enclosing_it(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 2: the purple inner disk is fully enclosed by
    the cream ring around it (see
    ``tests/fixtures/catalog/generate_source_pngs.py``'s
    ``_flatcolor_rings_with_island``); its ``<path>`` must be present, and
    appear later in the document (so it paints on top) than the ring's."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert result.exit_code == 0, result.output

    output_path = (
        temp_catalog_root
        / "assets"
        / "ochre_sea_star"
        / DERIVED_DIRNAME
        / "ochre-sea-star-color.svg"
    )
    text = output_path.read_text(encoding="utf-8")
    assert 'fill="#5b2e82"' in text  # the enclosed inner disk is present
    assert text.index('fill="#e6d2aa"') < text.index('fill="#5b2e82"')


@pytest.mark.integration
def test_second_flatcolor_svg_generate_reports_current_and_a_parameter_change_regenerates(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: a second ``generate`` reports ``current`` and
    changes nothing; changing a quantization/tracing parameter changes the
    recipe identity and so the output is regenerated (ADR 0004)."""
    monkeypatch.chdir(temp_catalog_root)
    first = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert first.exit_code == 0, first.output
    output_path = (
        temp_catalog_root
        / "assets"
        / "ochre_sea_star"
        / DERIVED_DIRNAME
        / "ochre-sea-star-color.svg"
    )
    first_mtime = output_path.stat().st_mtime_ns

    second = runner.invoke(app, ["generate", "ochre_sea_star"])

    assert second.exit_code == 0, second.output
    assert "ochre_sea_star\tflatcolor_svg\tcurrent\tochre-sea-star-color.svg" in second.stdout
    assert output_path.stat().st_mtime_ns == first_mtime

    original = recipe_module.RECIPES[DerivativeType.FLATCOLOR_SVG]
    changed = Recipe(
        derivative_type=original.derivative_type,
        accepted_roles=original.accepted_roles,
        generator=original.generator,
        parameters={**original.parameters, "max_colors": 2},
    )
    monkeypatch.setitem(recipe_module.RECIPES, DerivativeType.FLATCOLOR_SVG, changed)

    third = runner.invoke(app, ["generate", "ochre_sea_star"])

    assert third.exit_code == 0, third.output
    assert "ochre_sea_star\tflatcolor_svg\tgenerated\tochre-sea-star-color.svg" in third.stdout


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_OUTPUTS)
def test_transparent_png_bytes_are_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    """Acceptance criterion 2: each PNG is 8-bit RGBA, cropped to its
    content, transparent outside the shape -- locked byte-for-byte so the
    generator (or a Pillow upgrade) cannot silently change output without a
    reviewed snapshot diff. Identical on ubuntu and windows (§36): the
    generator resamples nothing and writes no ancillary chunks."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", asset_id])
    assert result.exit_code == 0, result.output

    output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
    assert output_path.read_bytes() == snapshot(extension_class=PNGImageSnapshotExtension)


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_SILHOUETTE_OUTPUTS)
def test_silhouette_svg_text_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    """Acceptance criterion 3: the blob (one subpath), the ring (an outer
    subpath and a hole), and the blob with a detached island (two disjoint
    subpaths) are each locked byte-for-byte as text, so the tracer (or a
    library upgrade) cannot silently change output without a reviewed
    snapshot diff. Identical on ubuntu and windows (§36): potracer is pure
    Python and ``svg_document``'s fixed-precision number formatting absorbs
    any last-bit libm difference between platforms before it reaches text."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", asset_id])
    assert result.exit_code == 0, result.output

    output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
    assert output_path.read_text(encoding="utf-8") == snapshot


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_FLATCOLOR_OUTPUTS)
def test_flatcolor_svg_text_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    """Acceptance criterion 3: the four-color fixture (outer ring, middle
    ring, inner disk fully enclosed by it, and a detached island -- see
    ``tests/fixtures/catalog/generate_source_pngs.py``) is locked
    byte-for-byte as text, so the quantizer or tracer (or a library upgrade)
    cannot silently change output without a reviewed snapshot diff.
    Identical on ubuntu and windows (§36): potracer is pure Python, the
    quantizer is plain numpy arithmetic on 8-bit integers, and
    ``svg_document``'s fixed-precision number formatting absorbs any
    last-bit libm difference between platforms before it reaches text."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", asset_id])
    assert result.exit_code == 0, result.output

    output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
    assert output_path.read_text(encoding="utf-8") == snapshot


@pytest.mark.integration
def test_second_generate_all_reports_current_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 3 (issue #23) and acceptance criterion 4 (issue
    #24, issue #25): a second ``generate --all`` reports every
    ``transparent_png``, every ``silhouette_svg``, and ochre_sea_star's
    ``flatcolor_svg`` as ``current``, and no file under any ``derived/``
    changes bytes or mtime (§36) -- the flat-color SVG is idempotent too."""
    monkeypatch.chdir(temp_catalog_root)
    first = runner.invoke(app, ["generate", "--all"])
    assert first.exit_code == 0, first.output

    before: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.iterdir()):
            before[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert before, "generate --all should have written files to compare"

    second = runner.invoke(app, ["generate", "--all"])

    assert second.exit_code == 0, second.output
    for asset_id, filename in FIXTURE_OUTPUTS:
        assert f"{asset_id}\ttransparent_png\tcurrent\t{filename}" in second.stdout
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        assert f"{asset_id}\tsilhouette_svg\tcurrent\t{filename}" in second.stdout
    for asset_id, filename in FIXTURE_FLATCOLOR_OUTPUTS:
        assert f"{asset_id}\tflatcolor_svg\tcurrent\t{filename}" in second.stdout
    for asset_id in FIXTURE_IMPOSSIBLE_FLATCOLOR:
        assert f"{asset_id}\tflatcolor_svg\timpossible\t" in second.stdout

    after: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.iterdir()):
            after[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert after == before


@pytest.mark.integration
def test_vpress_asset_shows_current_after_generation(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 6, first half: ``vpress asset <id>`` shows the
    generated derivative as ``current`` with its filename."""
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "ochre_sea_star"])
    assert generate_result.exit_code == 0, generate_result.output

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert "transparent_png\tcurrent\tochre-sea-star-color.png" in result.stdout


@pytest.mark.integration
def test_generate_all_skips_and_names_an_asset_that_failed_to_load(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The issue's "assets that failed to load are skipped and named": one
    asset's ``asset.toml`` is broken (a missing required field), so it never
    loads at all; ``generate --all`` still generates for the other two,
    names the broken one as skipped, and exits 0 -- a broken asset is a
    ``vpress status`` metadata problem, not a ``generate`` failure (§35: a
    failure involving one asset does not stop the rest)."""
    broken_toml = temp_catalog_root / "assets" / "ochre_sea_star" / "asset.toml"
    broken_toml.write_text(
        broken_toml.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tskipped: failed to load" in result.stdout
    # the broken asset generated nothing
    assert not (temp_catalog_root / "assets" / "ochre_sea_star" / "derived").exists()

    # the other two assets still generated
    for asset_id, filename in FIXTURE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\ttransparent_png\tgenerated\t{filename}" in result.stdout
        output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
        assert output_path.is_file()
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout
        output_path = temp_catalog_root / "assets" / asset_id / DERIVED_DIRNAME / filename
        assert output_path.is_file()


@pytest.mark.integration
def test_vpress_status_missing_count_drops_after_generation(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 6, second half: the ``vpress status`` missing
    count drops once a derivative becomes current."""
    monkeypatch.chdir(temp_catalog_root)
    before = runner.invoke(app, ["status"])
    assert before.exit_code == 0, before.output
    # purple_sea_urchin and giant_green_anemone each contribute 2 missing
    # (transparent_png, silhouette_svg) and 1 impossible (flatcolor_svg);
    # ochre_sea_star has a flatcolor source (issue #25) so all 3 of its
    # recipe-bearing types are missing instead: 2*2 + 3 = 7.
    assert "Missing derivatives: 7" in before.stdout
    assert "Impossible derivatives: 2" in before.stdout

    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 0, generate_result.output

    after = runner.invoke(app, ["status"])

    assert after.exit_code == 0, after.output
    # Every recipe-bearing type for every asset with an acceptable source
    # (issue #24, issue #25) moves from missing to current; flatcolor_svg
    # stays impossible for the two assets with no flatcolor source (counted
    # separately, not as missing).
    assert "Missing derivatives: 0" in after.stdout
    assert "Impossible derivatives: 2" in after.stdout


@pytest.mark.integration
def test_generate_all_reports_failed_for_a_fully_transparent_silhouette_and_continues(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #24 review fix round 1, controller ruling: a silhouette source
    with no ink at all leaves ``silhouette_svg`` with nothing to trace, so
    its generator raises. ``generate --all`` catches that per derivative,
    reports it ``failed`` with a reason, writes nothing for it, still
    generates every other derivative for every asset (including
    ``transparent_png`` and ``flatcolor_svg`` for the same asset -- neither
    selects the broken silhouette source, since the recipe prefers flatcolor
    over silhouette (issue #25) -- and everything for the other two), and
    exits non-zero overall."""
    silhouette_path = temp_catalog_root / "assets" / "ochre_sea_star" / "sources" / "silhouette.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(silhouette_path, format="PNG")
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output
    assert "ochre_sea_star\tsilhouette_svg\tfailed\t" in result.stdout
    failed_line = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("ochre_sea_star\t") and "\tfailed\t" in line
    )
    assert failed_line.split("\t", 3)[3]  # a non-empty reason

    derived_dir = temp_catalog_root / "assets" / "ochre_sea_star" / DERIVED_DIRNAME
    assert not derived_dir.exists() or not any(derived_dir.glob("*silhouette*"))

    # the same asset's other derivatives still generated (from the intact
    # flatcolor source, not the broken silhouette one).
    assert "ochre_sea_star\ttransparent_png\tgenerated\tochre-sea-star-color.png" in result.stdout
    output_path = derived_dir / "ochre-sea-star-color.png"
    assert output_path.is_file()
    assert "ochre_sea_star\tflatcolor_svg\tgenerated\tochre-sea-star-color.svg" in result.stdout
    assert (derived_dir / "ochre-sea-star-color.svg").is_file()

    # the other two assets, untouched by the broken source, generated everything.
    for asset_id, filename in FIXTURE_SILHOUETTE_OUTPUTS:
        if asset_id == "ochre_sea_star":
            continue
        assert f"{asset_id}\tsilhouette_svg\tgenerated\t{filename}" in result.stdout
