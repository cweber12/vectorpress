"""``vpress asset``'s publication eligibility section end to end, against a
temporary copy of the fixture catalog (§10, §10.1, ADR 0008).

Runs against a temporary copy, never the committed fixture directly: these
tests generate and approve derivatives, writing real files under each
asset's ``derived/``, and the fixture catalog must never contain one
(``tests/fixtures/catalog/README.md``).
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _eligibility_line(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("Eligibility"))


def _eligibility_section(output: str) -> str:
    """Everything from the ``Eligibility`` line to the end of the output --
    the derivative state/status lines above it (which legitimately say
    ``missing``/``needs review`` for other types) must not leak into an
    assertion about the eligibility section alone."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Eligibility"))
    return "\n".join(lines[start:])


# --- acceptance criterion 2: blocked with one reason per unapproved type, -----------
# --- then eligible once every existing derivative is approved -----------------------


@pytest.mark.integration
def test_ochre_sea_star_is_blocked_with_one_reason_per_unapproved_type_after_generate(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert _eligibility_line(result.stdout).endswith("blocked")
    # ochre_sea_star has a flatcolor source, so all four recipe-bearing
    # types are current and needs_review right after generate --all.
    for derivative_type in ("transparent_png", "silhouette_svg", "cut_svg", "flatcolor_svg"):
        assert f"  {derivative_type}: needs review" in result.stdout


@pytest.mark.integration
def test_ochre_sea_star_is_eligible_after_approving_every_derivative(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])

    approve_result = runner.invoke(app, ["approve", "ochre_sea_star", "--all-types"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert _eligibility_line(result.stdout) == (
        "Eligibility (transparent_png, silhouette_svg, cut_svg, flatcolor_svg): eligible"
    )
    # ochre_sea_star's accuracy is already approved and every optional
    # metadata field is filled in (tests/fixtures/catalog/README.md): no
    # warnings either.
    assert "Warnings: none" in result.stdout


# --- acceptance criterion 3: --types narrows to one type, ignoring the rest ---------


@pytest.mark.integration
def test_types_transparent_png_is_eligible_once_only_the_png_is_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§10: "the same sea star can ship in a PNG-only product while its cut
    file is still being fixed" -- transparent_png alone is approved,
    cut_svg is left needs_review, and --types transparent_png reports
    eligible regardless."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "ochre_sea_star"])

    approve_result = runner.invoke(app, ["approve", "ochre_sea_star", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["asset", "ochre_sea_star", "--types", "transparent_png"])

    assert result.exit_code == 0, result.output
    assert _eligibility_line(result.stdout) == "Eligibility (transparent_png): eligible"

    # The default (every non-impossible type) is still blocked: cut_svg is
    # still needs_review.
    default_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert _eligibility_line(default_result.stdout).endswith("blocked")
    assert "  cut_svg: needs review" in default_result.stdout


# --- acceptance criterion 4: a rights-blocked asset stays blocked even fully approved --


@pytest.mark.integration
def test_gumboot_chiton_stays_blocked_by_rights_status_even_fully_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "gumboot_chiton"])

    approve_result = runner.invoke(app, ["approve", "gumboot_chiton", "--all-types"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["asset", "gumboot_chiton"])

    assert result.exit_code == 0, result.output
    assert _eligibility_line(result.stdout).endswith("blocked")
    assert "  rights status: do not publish" in result.stdout
    # No unapproved-derivative reason: every existing derivative is approved.
    section = _eligibility_section(result.stdout)
    assert "needs review" not in section
    assert "missing" not in section
