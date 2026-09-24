"""A broken source fails visibly and touches nothing else (§35, issue #27).

``acorn_barnacle`` is one of the fixture's assets (``tests/fixtures/catalog/README.md``):
valid metadata, but its only source is a deliberately truncated PNG -- valid
signature and header, cut off before the pixel data finishes decoding. Source
validation only checks that a declared file exists, never that it decodes, so
the asset loads cleanly and its three recipe-bearing derivative types
(``transparent_png``, ``silhouette_svg``, ``cut_svg`` -- issue #36) each fail
at *generation* time instead. ``flatcolor_svg`` stays ``impossible`` -- it has
no flatcolor source at all, the same as ``purple_sea_urchin``,
``giant_green_anemone`` and ``owl_limpet``.

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under each asset's ``derived/``, and the fixture
catalog must never contain one (``tests/fixtures/catalog/README.md``).
"""

import shutil
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# (asset ID, expected customer-facing filename): the healthy fixture assets'
# transparent_png output -- generation for them must succeed alongside
# acorn_barnacle's failure, not be dragged down by it.
HEALTHY_TRANSPARENT_PNG_OUTPUTS = [
    ("ochre_sea_star", "ochre-sea-star-color.png"),
    ("purple_sea_urchin", "purple-sea-urchin-color.png"),
    ("giant_green_anemone", "giant-green-anemone-color.png"),
    ("owl_limpet", "owl-limpet-color.png"),
]

BROKEN_ASSET_ID = "acorn_barnacle"
BROKEN_SOURCE_FILENAME = "silhouette.png"
# The three recipe-bearing derivative types acorn_barnacle's only (broken)
# source is selected for (issue #36 adds cut_svg); flatcolor_svg has no
# source at all and stays impossible, not failed.
BROKEN_DERIVATIVE_TYPES = ["transparent_png", "silhouette_svg", "cut_svg"]


def _temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _broken_derived_dir(root: Path) -> Path:
    return root / "assets" / BROKEN_ASSET_ID / DERIVED_DIRNAME


def _broken_source_path(root: Path) -> Path:
    return root / "assets" / BROKEN_ASSET_ID / "sources" / BROKEN_SOURCE_FILENAME


# --- acceptance criterion 1: visible, named failures, non-zero exit, summary ------


@pytest.mark.integration
def test_generate_all_generates_every_healthy_derivative_and_reports_acorn_barnacle_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output
    for asset_id, filename in HEALTHY_TRANSPARENT_PNG_OUTPUTS:
        assert f"{asset_id}\ttransparent_png\tgenerated\t{filename}" in result.stdout
        output_path = root / "assets" / asset_id / DERIVED_DIRNAME / filename
        assert output_path.is_file()

    for derivative_type in BROKEN_DERIVATIVE_TYPES:
        assert f"{BROKEN_ASSET_ID}\t{derivative_type}\tfailed\t" in result.stdout
    assert f"{BROKEN_ASSET_ID}\tflatcolor_svg\timpossible\t" in result.stdout


@pytest.mark.integration
def test_generate_all_prints_one_stderr_line_per_failed_derivative_naming_asset_type_source_and_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 1: one stderr line per failed acorn_barnacle
    derivative, naming the asset, the type, ``silhouette.png``, and the
    cause -- not the generic stdout report line's four tab-separated
    fields, a dedicated diagnostic (§35: failures must be visible and
    understandable)."""
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output
    for derivative_type in BROKEN_DERIVATIVE_TYPES:
        matching_lines = [
            line
            for line in result.stderr.splitlines()
            if BROKEN_ASSET_ID in line and derivative_type in line
        ]
        assert matching_lines, (
            f"expected a stderr line for {BROKEN_ASSET_ID}/{derivative_type}, got:\n{result.stderr}"
        )
        assert len(matching_lines) == 1, (
            f"expected exactly one stderr line for {BROKEN_ASSET_ID}/{derivative_type}, "
            f"got:\n{matching_lines}"
        )
        line = matching_lines[0]
        assert BROKEN_SOURCE_FILENAME in line
        # a cause follows the source file name -- non-empty, not just the
        # asset/type/source-file naming with nothing explaining why.
        assert line.rstrip().endswith(":") is False


@pytest.mark.integration
def test_generate_all_ends_with_a_stderr_summary_naming_the_failure_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Acceptance criterion 1: a run with failures ends with a summary
    naming how many -- exactly acorn_barnacle's three (transparent_png,
    silhouette_svg, cut_svg -- issue #36); flatcolor_svg is impossible, not
    failed, and does not count. Asserted as the exact, final stderr line
    (not just "some line contains a 3 and the word failed" -- the three
    per-derivative diagnostic lines above it already contain "failed", so a
    looser check would not catch a missing or miscounted summary)."""
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert stderr_lines, "expected stderr output"
    assert stderr_lines[-1] == "generate: 3 derivative(s) failed"


# --- acceptance criterion 2: nothing half-written, the asset reports missing ------


@pytest.mark.integration
def test_after_a_failed_run_acorn_barnacle_derived_has_no_output_temp_file_or_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["generate", "--all"])
    assert result.exit_code == 1, result.output

    derived_dir = _broken_derived_dir(root)
    if derived_dir.exists():
        entries = list(derived_dir.iterdir())
        assert entries == [], f"expected an empty or absent derived/, found: {entries}"


@pytest.mark.integration
def test_after_a_failed_run_vpress_asset_shows_the_broken_derivatives_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output

    result = runner.invoke(app, ["asset", BROKEN_ASSET_ID])

    assert result.exit_code == 0, result.output
    for derivative_type in BROKEN_DERIVATIVE_TYPES:
        assert f"{derivative_type}\tmissing\t{BROKEN_SOURCE_FILENAME} (silhouette)" in result.stdout
    assert "current" not in result.stdout
    assert "stale" not in result.stdout


@pytest.mark.integration
def test_read_provenance_is_none_for_both_broken_derivatives_after_a_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same "missing" story, checked directly against provenance rather
    than through ``vpress asset``'s rendering: no provenance record exists
    for any failed type."""
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["generate", "--all"])
    assert result.exit_code == 1, result.output

    derived_dir = _broken_derived_dir(root)
    assert read_provenance(derived_dir, "acorn-barnacle-color.png") is None
    assert read_provenance(derived_dir, "acorn-barnacle-silhouette.svg") is None
    assert read_provenance(derived_dir, "acorn-barnacle-cut.svg") is None


# --- acceptance criterion 5: retry after fixing the source -----------------------


@pytest.mark.integration
def test_replacing_the_broken_source_and_regenerating_succeeds_with_no_residue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§35's "allow the user to retry after resolving the issue": once the
    truncated source is replaced with a valid PNG, ``generate`` produces
    every previously-failed derivative with provenance, and reports none of
    them as ``failed`` -- no residue from the earlier failed run."""
    root = _temp_catalog_root(tmp_path)
    monkeypatch.chdir(root)
    first = runner.invoke(app, ["generate", "--all"])
    assert first.exit_code == 1, first.output

    Image.new("RGBA", (16, 16), (150, 100, 50, 255)).save(_broken_source_path(root), format="PNG")

    second = runner.invoke(app, ["generate", BROKEN_ASSET_ID])

    assert second.exit_code == 0, second.output
    assert "failed" not in second.stdout
    for derivative_type in BROKEN_DERIVATIVE_TYPES:
        assert f"{BROKEN_ASSET_ID}\t{derivative_type}\tgenerated\t" in second.stdout

    derived_dir = _broken_derived_dir(root)
    assert (derived_dir / "acorn-barnacle-color.png").is_file()
    assert (derived_dir / "acorn-barnacle-silhouette.svg").is_file()
    assert (derived_dir / "acorn-barnacle-cut.svg").is_file()
    assert read_provenance(derived_dir, "acorn-barnacle-color.png") is not None
    assert read_provenance(derived_dir, "acorn-barnacle-silhouette.svg") is not None
    assert read_provenance(derived_dir, "acorn-barnacle-cut.svg") is not None

    asset_result = runner.invoke(app, ["asset", BROKEN_ASSET_ID])
    assert asset_result.exit_code == 0, asset_result.output
    for derivative_type in BROKEN_DERIVATIVE_TYPES:
        assert f"{derivative_type}\tcurrent\t" in asset_result.stdout
