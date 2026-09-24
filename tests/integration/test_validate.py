"""``vpress validate`` end to end against a temporary copy of the fixture
catalog (§9, §9.1, §9.2, §35, §36, ADR 0004, ADR 0007, issue #37).

Runs against a temporary copy, never the committed fixture directly -- same
reason as ``tests/integration/test_generate.py``: this command writes real
findings JSON files under each asset's ``derived/``, and the fixture catalog
must never contain one.

The fixture's cut-file subjects (``tests/fixtures/catalog/generate_source_pngs.py``,
issue #36): ``ochre_sea_star`` (a single blob, one piece), ``purple_sea_urchin``
(a ring -- one piece with a hole, not two pieces), ``giant_green_anemone``
(a blob plus a detached island -- two pieces), and ``owl_limpet`` (a larger
canvas with cleanup noise plus a detached piece that survives cleanup -- two
pieces). ``acorn_barnacle``'s only source is truncated (issue #27), so its
``cut_svg`` never generates at all -- it stays ``missing``, never validated.
"""

import json
import shutil
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.catalog.findings import findings_path, read_findings_report
from vectorpress.catalog.provenance import DERIVED_DIRNAME, sha256_bytes
from vectorpress.cli.app import app
from vectorpress.domain import recipe as recipe_module
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import Recipe
from vectorpress.validate.cut_file import validate_cut_file

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# (asset ID, cut-file filename) -- every fixture asset with a decodable
# silhouette source, the same set ``test_generate.py``'s own
# ``FIXTURE_CUT_SVG_OUTPUTS`` validates a cut file exists for (issue #36).
FIXTURE_CUT_FILES = [
    ("ochre_sea_star", "ochre-sea-star-cut.svg"),
    ("purple_sea_urchin", "purple-sea-urchin-cut.svg"),
    ("giant_green_anemone", "giant-green-anemone-cut.svg"),
    ("owl_limpet", "owl-limpet-cut.svg"),
]

# Subjects whose cut file is a single physical piece -- pass, no findings.
FIXTURE_PASS_ASSETS = ["ochre_sea_star", "purple_sea_urchin"]

# Subjects whose cut file has a genuinely separate second piece -- needs
# review, one disconnected_fragments finding each.
FIXTURE_NEEDS_REVIEW_ASSETS = ["giant_green_anemone", "owl_limpet"]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _derived_dir(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


# --- acceptance criterion 1: pass / needs review, with a located finding ------------------


@pytest.mark.integration
def test_validate_all_reports_pass_or_needs_review_for_every_cut_file(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle still fails

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    for asset_id in FIXTURE_PASS_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tpass" in result.stdout
    for asset_id in FIXTURE_NEEDS_REVIEW_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tneeds review" in result.stdout
        assert "disconnected_fragments" in result.stdout


@pytest.mark.integration
def test_giant_green_anemone_fragment_is_located_at_the_detached_islands_bbox(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: the fixture's detached island traces to a
    tight circle at document coordinates (12,2)-(14,4) (locked already by
    ``test_generate.py``'s own cut-SVG snapshot) -- the finding's location is
    exactly that bounding box, in the SVG's own user units."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "giant_green_anemone"])

    assert result.exit_code == 0, result.output
    assert (
        "giant_green_anemone\tcut_svg\tgiant-green-anemone-cut.svg\tneeds review" in result.stdout
    )
    finding_line = next(
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("disconnected_fragments")
    )
    assert "(12.0,2.0)-(14.0,4.0)" in finding_line


@pytest.mark.integration
def test_owl_limpets_detached_piece_is_flagged_at_its_own_real_bbox(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``owl_limpet``'s detached piece (issue #36's
    cleanup fixture) survives cleanup and is flagged the same way
    ``giant_green_anemone``'s is -- the CLI's reported location matches what
    calling the (separately unit-tested) pure ``validate_cut_file`` function
    directly on the same generated bytes produces."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, "owl_limpet") / "owl-limpet-cut.svg"
    expected = validate_cut_file(svg_path.read_bytes(), 3.0)
    assert len(expected.findings) == 1  # sanity: the fixture really has one extra piece
    expected_bbox = expected.findings[0].location

    result = runner.invoke(app, ["validate", "owl_limpet"])

    assert result.exit_code == 0, result.output
    finding_line = next(
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("disconnected_fragments")
    )
    assert (
        f"({expected_bbox.min_x},{expected_bbox.min_y})-({expected_bbox.max_x},{expected_bbox.max_y})"
        in (finding_line)
    )


@pytest.mark.integration
def test_vpress_asset_shows_the_findings_result(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])

    ochre = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert ochre.exit_code == 0, ochre.output
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tpass" in ochre.stdout

    anemone = runner.invoke(app, ["asset", "giant_green_anemone"])
    assert anemone.exit_code == 0, anemone.output
    assert "cut_svg\tcurrent\tgiant-green-anemone-cut.svg\tneeds review" in anemone.stdout


# --- acceptance criterion 2: findings JSON, nothing written inside the SVG or TOML --------


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_findings_json_records_hash_reference_size_and_thresholds(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, asset_id: str, filename: str
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, asset_id) / filename

    result = runner.invoke(app, ["validate", asset_id])
    assert result.exit_code == 0, result.output

    report = read_findings_report(_derived_dir(temp_catalog_root, asset_id), filename)
    assert report is not None
    assert report.validated_file == filename
    assert report.content_hash == sha256_bytes(svg_path.read_bytes())
    assert report.reference_size_in == 3.0  # the catalog default (§9.1)
    assert isinstance(report.thresholds, dict)


@pytest.mark.integration
def test_nothing_is_written_inside_the_svg_or_any_toml_file(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = (
        _derived_dir(temp_catalog_root, "giant_green_anemone") / "giant-green-anemone-cut.svg"
    )
    svg_before = svg_path.read_bytes()
    toml_paths = sorted(temp_catalog_root.rglob("*.toml"))
    toml_before = {path: path.read_bytes() for path in toml_paths}

    result = runner.invoke(app, ["validate", "--all"])
    assert result.exit_code == 0, result.output

    assert svg_path.read_bytes() == svg_before
    for path in toml_paths:
        assert path.read_bytes() == toml_before[path]
    # ADR 0007: findings are JSON state beside the derivative, never inside it.
    assert findings_path(
        _derived_dir(temp_catalog_root, "giant_green_anemone"), "giant-green-anemone-cut.svg"
    ).is_file()


# --- snapshot: findings JSON locked, byte-identical across platforms (acceptance criterion 3) --


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_findings_json_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", asset_id])
    assert result.exit_code == 0, result.output

    path = findings_path(_derived_dir(temp_catalog_root, asset_id), filename)
    # content_hash is a function of the (already snapshot-locked) SVG bytes,
    # so it is itself already implicitly locked -- but pretty-printed here
    # for a readable diff if the SVG generator, or this issue's own findings
    # shape, ever changes it.
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot


# --- acceptance criterion 4: idempotent, and staleness ------------------------------------


@pytest.mark.integration
def test_second_validate_all_rewrites_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    first = runner.invoke(app, ["validate", "--all"])
    assert first.exit_code == 0, first.output

    before: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.glob("*.findings.json")):
            before[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert before, "validate --all should have written at least one findings report"

    second = runner.invoke(app, ["validate", "--all"])
    assert second.exit_code == 0, second.output

    after: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.glob("*.findings.json")):
            after[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert after == before


@pytest.mark.integration
def test_hand_editing_the_cut_file_makes_its_findings_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: ``vpress asset`` shows ``findings stale``
    after the validated SVG's bytes change on disk, until ``validate`` runs
    again."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    validated = runner.invoke(app, ["validate", "ochre_sea_star"])
    assert validated.exit_code == 0, validated.output
    before = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tpass" in before.stdout

    svg_path = _derived_dir(temp_catalog_root, "ochre_sea_star") / "ochre-sea-star-cut.svg"
    svg_path.write_text(
        svg_path.read_text(encoding="utf-8").replace("<svg ", '<svg data-hand-edited="1" '),
        encoding="utf-8",
    )

    after = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert after.exit_code == 0, after.output
    assert "cut_svg\tstale (output changed on disk)\tochre-sea-star-cut.svg\tfindings stale" in (
        after.stdout
    )

    revalidated = runner.invoke(app, ["validate", "ochre_sea_star"])
    assert revalidated.exit_code == 0, revalidated.output
    settled = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "findings stale" not in settled.stdout


@pytest.mark.integration
def test_regenerating_with_a_changed_recipe_makes_findings_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: forcing regeneration under a changed recipe
    parameter (the same monkeypatch style ``test_generate.py`` uses) changes
    the cut file's bytes, so its earlier findings report no longer matches."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "giant_green_anemone"])
    before = runner.invoke(app, ["asset", "giant_green_anemone"])
    assert "needs review" in before.stdout

    original = recipe_module.RECIPES[DerivativeType.CUT_SVG]
    changed = Recipe(
        derivative_type=original.derivative_type,
        accepted_roles=original.accepted_roles,
        generator=original.generator,
        parameters={**original.parameters, "curve_tolerance": 0.05},
    )
    monkeypatch.setitem(recipe_module.RECIPES, DerivativeType.CUT_SVG, changed)
    forced = runner.invoke(app, ["generate", "--force", "giant_green_anemone"])
    assert forced.exit_code == 0, forced.output

    after = runner.invoke(app, ["asset", "giant_green_anemone"])

    assert after.exit_code == 0, after.output
    assert "findings stale" in after.stdout


@pytest.mark.integration
def test_reference_size_change_makes_every_findings_report_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: §9.1's reference size is part of what
    ``findings_currency`` compares -- changing the catalog default is
    detected the same way a changed SVG hash is, even when the cut file
    itself did not change."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "ochre_sea_star"])

    catalog_toml = temp_catalog_root / "catalog.toml"
    catalog_toml.write_text(
        catalog_toml.read_text(encoding="utf-8") + "\nreference_size_in = 6.0\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert "findings stale" in result.stdout


# --- acceptance criterion 6/7: missing/impossible cut files, and usage errors -------------


@pytest.mark.integration
def test_an_asset_with_no_cut_file_yet_is_reported_missing_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Before generation, every asset's ``cut_svg`` is ``missing`` -- issue
    #37's "An asset whose cut file is missing or impossible is reported as
    such and not validated"."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tcut_svg\tmissing" in result.stdout


@pytest.mark.integration
def test_acorn_barnacles_never_generated_cut_file_is_reported_missing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``acorn_barnacle``'s only source is truncated (issue #27), so
    ``cut_svg`` never generates; ``validate --all`` still reports it, rather
    than crashing on a missing file, and the run overall still exits 0 (a
    missing cut file is not a validation failure)."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "acorn_barnacle\tcut_svg\tmissing" in result.stdout


@pytest.mark.integration
def test_validate_requires_exactly_one_of_asset_id_or_all(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    neither = runner.invoke(app, ["validate"])
    assert neither.exit_code != 0

    both = runner.invoke(app, ["validate", "ochre_sea_star", "--all"])
    assert both.exit_code != 0


@pytest.mark.integration
def test_validate_all_skips_and_names_an_asset_that_failed_to_load(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    broken_toml = temp_catalog_root / "assets" / "ochre_sea_star" / "asset.toml"
    broken_toml.write_text(
        broken_toml.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tskipped: failed to load" in result.stdout


@pytest.mark.integration
def test_validate_unknown_asset_id_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["validate", "no_such_asset"])

    assert result.exit_code == 1
    assert "Unknown asset" in result.stdout + result.output


# --- a validation failure is reported on stderr and the run still exits 1 ------------------


@pytest.mark.integration
def test_an_unparseable_cut_file_is_reported_on_stderr_and_the_run_exits_1(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§35: a hand-edited override that no longer parses is a validation
    failure, named with asset, file and cause -- and, unlike a needs-review
    result, makes the whole run exit non-zero, after every other asset was
    still attempted."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, "ochre_sea_star") / "ochre-sea-star-cut.svg"
    svg_path.write_bytes(b"not valid xml at all <<<")

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 1, result.output
    assert "ochre_sea_star" in result.output
    assert "ochre-sea-star-cut.svg" in result.output
    # every other asset was still attempted despite the one failure.
    assert (
        "giant_green_anemone\tcut_svg\tgiant-green-anemone-cut.svg\tneeds review" in result.stdout
    )


@pytest.mark.integration
def test_generate_still_never_validates(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #37: ``vpress generate`` is unchanged and does not validate --
    no findings report exists until ``validate`` itself runs."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output  # acorn_barnacle still fails to generate
    for asset_id, filename in FIXTURE_CUT_FILES:
        assert not findings_path(_derived_dir(temp_catalog_root, asset_id), filename).exists()
    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tnot validated" in asset_result.stdout
