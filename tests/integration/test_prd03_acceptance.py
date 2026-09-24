"""PRD 3 acceptance walk-through: cut-file derivative and quality
validation (§6.3, §8, §9, §9.1, §9.2, ADR 0007, issue #41).

PRD 3's own Acceptance paragraph: "User can generate cut files, see a
findings report with locations for each, and see pass / needs-review per
file. Fixture catalog includes subjects that deliberately trip each
finding type. Snapshot tests lock findings output." This performs that
walk-through end to end, on a temporary copy of the fixture catalog, using
real ``uv run vpress`` subprocess invocations (issue #41's own "with uv run
vpress commands only") rather than the in-process ``CliRunner`` every other
integration test in this package uses -- the one test that proves the
actual installed console script (``pyproject.toml``'s own
``[project.scripts]`` entry) works end to end, not just the Typer app
object in-process.

This is issue #41's own closing test: between the fixture catalog's own
subjects (six §9 kinds a *generated* cut file can trip -- disconnected
fragments, accidental dot, tiny isolated shape, small hole, narrow
feature, excessive complexity) and ``tests/fixtures/findings/``'s own trip
SVGs (the five kinds only a hand-edited SVG can trip -- open path, raster
content, stray object, duplicate geometry, unintended overlap), every one
of §9's eleven kinds is proven to fire at least once.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"
FINDINGS_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "findings"

#: Every §9 kind, by its own JSON/CLI token -- kept as a plain literal set
#: here (not imported from :class:`~vectorpress.domain.finding.FindingKind`)
#: so this walk-through reads the CLI's own text output exactly the way a
#: user would, never the domain model directly.
ALL_ELEVEN_KINDS = {
    "open_path",
    "tiny_isolated_shape",
    "accidental_dot",
    "small_hole",
    "narrow_feature",
    "excessive_complexity",
    "stray_object",
    "duplicate_geometry",
    "overlap",
    "disconnected_fragments",
    "raster_content",
}

TRIP_SVGS = ["open_path", "raster_content", "stray_object", "duplicate_geometry", "overlap"]


def _run_vpress(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real, installed ``vpress`` console script (never the
    in-process Typer app object) against ``cwd`` -- ``uv run --project``
    lets this run with a working directory outside the repo (the temp
    catalog copy, or the fixture directory a trip SVG's own path is read
    relative to) while still resolving this project's own venv."""
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "vpress", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _finding_lines(output: str) -> list[str]:
    """Every finding line ``vpress validate`` prints -- two-space indented,
    tab-separated kind / location / message (``vectorpress.cli.app``'s own
    ``_echo_finding``)."""
    return [line for line in output.splitlines() if line.startswith("  ")]


_LOCATION_RE = re.compile(r"^\(-?[\d.]+,-?[\d.]+\)-\(-?[\d.]+,-?[\d.]+\)$")


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


@pytest.fixture
def temp_findings_dir(tmp_path: Path) -> Path:
    """A throwaway copy of ``tests/fixtures/findings/`` (issue #41 review
    fix round 1, mirroring ``tests/integration/test_validate.py``'s own
    fixture of the same name): every ``--file`` call below validates a
    copy, never the committed fixture directly, so a regression that wrote
    a findings report beside the validated file (exactly what catalog
    validation does) could never land in the real repo checkout."""
    dest = tmp_path / "findings"
    shutil.copytree(FINDINGS_FIXTURES_DIR, dest)
    return dest


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_prd_03_acceptance_walkthrough(temp_catalog_root: Path, temp_findings_dir: Path) -> None:
    # 1. generate --all
    generate_result = _run_vpress(["generate", "--all"], cwd=temp_catalog_root)
    assert generate_result.returncode == 1, generate_result.stdout + generate_result.stderr
    # acorn_barnacle's truncated source still fails generation on its own
    # (issue #27); every other fixture asset's cut file is produced.

    # 2. validate --all
    validate_all_result = _run_vpress(["validate", "--all"], cwd=temp_catalog_root)
    assert validate_all_result.returncode == 0, (
        validate_all_result.stdout + validate_all_result.stderr
    )

    # 3. validate --file on each trip SVG (a throwaway copy, never the
    # committed fixture -- temp_findings_dir's own docstring)
    file_outputs: list[str] = []
    for name in TRIP_SVGS:
        svg_path = temp_findings_dir / f"{name}.svg"
        file_result = _run_vpress(
            ["validate", "--file", str(svg_path), "--reference-size", "3"],
            cwd=temp_catalog_root,
        )
        assert file_result.returncode == 0, file_result.stdout + file_result.stderr
        file_outputs.append(file_result.stdout)

    clean_result = _run_vpress(
        ["validate", "--file", str(temp_findings_dir / "clean.svg"), "--reference-size", "3"],
        cwd=temp_catalog_root,
    )
    assert clean_result.returncode == 0, clean_result.stdout + clean_result.stderr

    combined_output = validate_all_result.stdout + "".join(file_outputs) + clean_result.stdout

    # Every one of the eleven §9 kinds appears at least once, across the
    # catalog subjects and the trip SVGs together.
    finding_lines = _finding_lines(combined_output)
    kinds_seen = {line.strip().split("\t")[0] for line in finding_lines}
    assert kinds_seen == ALL_ELEVEN_KINDS, ALL_ELEVEN_KINDS - kinds_seen

    # Every finding has a location: this walk-through's own findings all
    # carry real geometry (none of the no-geometry stray-object sub-cases
    # -- an empty group, a stray <text> element -- are exercised by a trip
    # SVG here; those are unit-tested directly, see ``tests/fixtures/
    # findings/README.md``), so every line's own location column is a real
    # bbox, never the "(no bbox)" marker a no-geometry finding would print.
    for line in finding_lines:
        columns = line.strip().split("\t")
        assert len(columns) >= 2, line
        assert _LOCATION_RE.match(columns[1]), line

    # Both pass and needs review occur (validate --all alone already has
    # both -- ochre_sea_star/purple_sea_urchin/turban_snail pass,
    # gumboot_chiton/bat_star/keyhole_limpet/nudibranch/coralline_algae/
    # giant_green_anemone/owl_limpet need review).
    assert "\tpass" in validate_all_result.stdout
    assert "\tneeds review" in validate_all_result.stdout
