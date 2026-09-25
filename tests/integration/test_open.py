"""``vpress open`` end to end, against a temporary copy of the fixture
catalog (§6.8, §24, ADR 0005, ADR 0007).

Runs against a temporary copy, never the committed fixture directly: this
command writes real files under an asset's ``derived/`` (via ``generate``)
and, with ``--override``, ``overrides/`` -- the fixture catalog must never
contain either (``tests/fixtures/catalog/README.md``).

Launching goes through ``cli.app``'s ``_launcher`` seam
(``vectorpress.pipeline.open_editor.Launcher``): every test here injects a
recording fake, so nothing ever spawns a real process or the OS's own
opener.
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.catalog.overrides import override_path, read_override_provenance
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.cli import app as cli_app_module
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

ASSET_ID = "ochre_sea_star"
FILENAME = "ochre-sea-star-cut.svg"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


class _RecordingLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str] | None, Path]] = []

    def __call__(self, argv: list[str] | None, path: Path) -> None:
        self.calls.append((argv, path))


@pytest.fixture
def recording_launcher(monkeypatch: pytest.MonkeyPatch) -> _RecordingLauncher:
    launcher = _RecordingLauncher()
    monkeypatch.setattr(cli_app_module, "_launcher", launcher)
    return launcher


def _derived_dir(root: Path, asset_id: str = ASSET_ID) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


def _append_editor(root: Path, editor_toml_value: str) -> None:
    path = root / "catalog.toml"
    path.write_text(path.read_text(encoding="utf-8") + f"\n{editor_toml_value}\n", encoding="utf-8")


# --- acceptance criterion 1: catalog.toml's editor, or the OS default ---------------


@pytest.mark.integration
def test_open_launches_the_configured_editor_with_the_path_appended(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    _append_editor(temp_catalog_root, 'editor = ["myeditor", "--flag"]')
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg"])

    assert result.exit_code == 0, result.output
    expected_path = _derived_dir(temp_catalog_root) / FILENAME
    assert recording_launcher.calls == [(["myeditor", "--flag", str(expected_path)], expected_path)]


@pytest.mark.integration
def test_open_with_no_editor_configured_falls_back_to_the_os_default(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    # the fixture catalog.toml leaves editor unset (tests/fixtures/catalog/catalog.toml).
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg"])

    assert result.exit_code == 0, result.output
    expected_path = _derived_dir(temp_catalog_root) / FILENAME
    # argv is None: the seam's signal that the OS default opener applies
    # (vectorpress.pipeline.open_editor.default_launcher, exercised for real
    # by tests/unit/test_pipeline_open_editor.py).
    assert recording_launcher.calls == [(None, expected_path)]


# --- acceptance criterion 2: override present targets it; --generated targets the ---
# --- generated file regardless -------------------------------------------------------


@pytest.mark.integration
def test_open_targets_the_override_when_one_exists(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    override = override_path(temp_catalog_root / "assets" / ASSET_ID, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>hand-edited</svg>")

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg"])

    assert result.exit_code == 0, result.output
    assert recording_launcher.calls == [(None, override)]


@pytest.mark.integration
def test_open_generated_targets_the_generated_file_even_with_an_override(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    override = override_path(temp_catalog_root / "assets" / ASSET_ID, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>hand-edited</svg>")
    generated_path = _derived_dir(temp_catalog_root) / FILENAME

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg", "--generated"])

    assert result.exit_code == 0, result.output
    assert recording_launcher.calls == [(None, generated_path)]


# --- acceptance criterion 3: --override starts one, create-only ---------------------


@pytest.mark.integration
def test_open_override_with_none_yet_copies_the_generated_file_and_shows_overridden(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg", "--override"])

    assert result.exit_code == 0, result.output
    override = override_path(temp_catalog_root / "assets" / ASSET_ID, FILENAME)
    assert override.is_file()
    assert override.read_bytes() == generated_bytes
    assert recording_launcher.calls == [(None, override)]
    # provenance is recorded immediately -- this issue's own ruling.
    assert read_override_provenance(_derived_dir(temp_catalog_root), FILENAME) is not None

    asset_result = runner.invoke(app, ["asset", ASSET_ID])
    assert asset_result.exit_code == 0, asset_result.output
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "override" in cut_svg_line
    assert "needs review" in cut_svg_line


@pytest.mark.integration
def test_open_override_with_one_already_present_opens_it_without_rewriting(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    override = override_path(temp_catalog_root / "assets" / ASSET_ID, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>already hand-edited</svg>")
    bytes_before = override.read_bytes()
    mtime_before = override.stat().st_mtime_ns

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg", "--override"])

    assert result.exit_code == 0, result.output
    assert override.read_bytes() == bytes_before
    assert override.stat().st_mtime_ns == mtime_before
    assert recording_launcher.calls == [(None, override)]


@pytest.mark.integration
def test_open_override_with_a_missing_generated_derivative_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)  # nothing generated yet

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg", "--override"])

    assert result.exit_code == 1, result.output
    assert recording_launcher.calls == []


# --- acceptance criterion 4: an invalid editor value is a load error ----------------


@pytest.mark.integration
def test_open_with_an_invalid_editor_value_names_catalog_toml_and_the_field(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _append_editor(temp_catalog_root, "editor = []")
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg"])

    assert result.exit_code == 1, result.output
    assert "catalog.toml" in result.output
    assert "editor" in result.output


# --- acceptance criterion 4 (continued): missing, impossible and unknown errors -----


@pytest.mark.integration
def test_open_a_missing_derivative_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)  # nothing generated yet

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg"])

    assert result.exit_code == 1, result.output
    assert recording_launcher.calls == []


@pytest.mark.integration
def test_open_an_impossible_derivative_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "purple_sea_urchin"])  # no flatcolor source

    result = runner.invoke(app, ["open", "purple_sea_urchin", "flatcolor_svg"])

    assert result.exit_code == 1, result.output
    assert recording_launcher.calls == []


@pytest.mark.integration
def test_open_an_unknown_derivative_type_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])

    result = runner.invoke(app, ["open", ASSET_ID, "not_a_real_type"])

    assert result.exit_code == 1, result.output
    assert "Unknown derivative type" in result.output
    assert recording_launcher.calls == []


@pytest.mark.integration
def test_open_an_unknown_asset_is_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["open", "not_a_real_asset", "cut_svg"])

    assert result.exit_code == 1, result.output
    assert recording_launcher.calls == []


@pytest.mark.integration
def test_open_generated_and_override_together_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])

    result = runner.invoke(app, ["open", ASSET_ID, "cut_svg", "--generated", "--override"])

    assert result.exit_code == 2, result.output
    assert recording_launcher.calls == []
