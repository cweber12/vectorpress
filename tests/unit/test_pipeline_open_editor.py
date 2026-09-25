"""pipeline.open_editor: launching an editor, and resolving which file
'vpress open' targets (§6.8, §24, ADR 0005, ADR 0007).

``launch_editor`` and ``default_launcher`` are exercised with a recording
fake in place of ``launcher``, so nothing here ever spawns a real process or
the OS's own opener. ``resolve_open_target`` builds a real asset folder on
disk under ``tmp_path`` (a source PNG plus a fabricated
:class:`~vectorpress.domain.asset.Asset`), the same fixture-free shape
``tests/unit/test_pipeline_review.py`` uses -- catalog loading and the CLI
wiring are exercised end to end by ``tests/integration/test_open.py``.
"""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from vectorpress.catalog.overrides import override_path, read_override_provenance
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.pipeline.generate import generate_asset
from vectorpress.pipeline.open_editor import (
    OpenTarget,
    default_launcher,
    launch_editor,
    resolve_open_target,
)

SOURCES_DIRNAME = "sources"


def _write_source_png(path: Path, rgba: tuple[int, int, int, int] = (196, 93, 38, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), rgba).save(path, format="PNG")


def _asset(asset_id: str = "ochre_sea_star") -> Asset:
    return Asset(
        id=asset_id,
        common_name="Ochre sea star",
        display_name="Ochre Sea Star",
        description="A test asset.",
        subject_category="Echinoderm",
        taxonomic_group="Echinoderm",
        rights_status=RightsStatus.ORIGINAL_ARTWORK,
        accuracy_status=AccuracyStatus.NOT_REVIEWED,
        sources=[Source(role="silhouette", file="silhouette.png")],
    )


def _make_asset_dir(tmp_path: Path) -> Path:
    asset_dir = tmp_path / "ochre_sea_star"
    _write_source_png(asset_dir / SOURCES_DIRNAME / "silhouette.png")
    return asset_dir


FILENAME = "ochre-sea-star-cut.svg"


class _RecordingLauncher:
    """A fake launcher: records every call instead of spawning anything."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str] | None, Path]] = []

    def __call__(self, argv: list[str] | None, path: Path) -> None:
        self.calls.append((argv, path))


# --- launch_editor: the exact command, via an injected launcher ---------------------


def test_launch_editor_appends_the_path_to_the_configured_editor_command(tmp_path: Path) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    launcher = _RecordingLauncher()

    launch_editor(path, ["myeditor", "--flag"], launcher=launcher)

    assert launcher.calls == [(["myeditor", "--flag", str(path)], path)]


def test_launch_editor_with_no_editor_configured_signals_the_os_default(tmp_path: Path) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    launcher = _RecordingLauncher()

    launch_editor(path, None, launcher=launcher)

    assert launcher.calls == [(None, path)]


def test_launch_editor_defaults_to_the_default_launcher_when_none_is_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    calls: list[tuple[list[str] | None, Path]] = []

    def fake_default_launcher(argv: list[str] | None, p: Path) -> None:
        calls.append((argv, p))

    monkeypatch.setattr("vectorpress.pipeline.open_editor.default_launcher", fake_default_launcher)

    launch_editor(path, ["myeditor"])

    assert calls == [(["myeditor", str(path)], path)]


# --- default_launcher: real OS dispatch, with subprocess.Popen/os.startfile faked ---


def test_default_launcher_with_an_editor_command_spawns_it_via_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    popen_calls: list[list[str]] = []

    def fake_popen(argv: list[str]) -> None:
        popen_calls.append(argv)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    default_launcher(["myeditor", "--flag", str(path)], path)

    assert popen_calls == [["myeditor", "--flag", str(path)]]


def test_default_launcher_with_no_editor_uses_os_startfile_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    monkeypatch.setattr("vectorpress.pipeline.open_editor.sys.platform", "win32")
    startfile_calls: list[Path] = []

    def fake_startfile(p: Path) -> None:
        startfile_calls.append(p)

    monkeypatch.setattr("os.startfile", fake_startfile, raising=False)

    default_launcher(None, path)

    assert startfile_calls == [path]


def test_default_launcher_with_no_editor_uses_open_on_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    monkeypatch.setattr("vectorpress.pipeline.open_editor.sys.platform", "darwin")
    popen_calls: list[list[str]] = []

    def fake_popen(argv: list[str]) -> None:
        popen_calls.append(argv)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    default_launcher(None, path)

    assert popen_calls == [["open", str(path)]]


def test_default_launcher_with_no_editor_uses_xdg_open_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ochre-sea-star-cut.svg"
    monkeypatch.setattr("vectorpress.pipeline.open_editor.sys.platform", "linux")
    popen_calls: list[list[str]] = []

    def fake_popen(argv: list[str]) -> None:
        popen_calls.append(argv)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    default_launcher(None, path)

    assert popen_calls == [["xdg-open", str(path)]]


# --- resolve_open_target: default (effective), --generated, --override --------------


def test_resolve_open_target_is_an_error_for_a_missing_derivative(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)  # nothing generated yet

    target, error = resolve_open_target(_asset(), asset_dir, DerivativeType.CUT_SVG, None)

    assert target is None
    assert error is not None
    assert "missing" in error


def test_resolve_open_target_is_an_error_for_an_impossible_derivative(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)  # only a silhouette source

    target, error = resolve_open_target(_asset(), asset_dir, DerivativeType.FLATCOLOR_SVG, None)

    assert target is None
    assert error is not None
    assert "impossible" in error


def test_resolve_open_target_defaults_to_the_generated_file_with_no_override(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)

    target, error = resolve_open_target(_asset(), asset_dir, DerivativeType.CUT_SVG, None)

    assert error is None
    assert target == OpenTarget(asset_dir / DERIVED_DIRNAME / FILENAME, is_override=False)


def test_resolve_open_target_defaults_to_the_override_when_one_exists(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    override = override_path(asset_dir, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>hand-edited</svg>")

    target, error = resolve_open_target(_asset(), asset_dir, DerivativeType.CUT_SVG, None)

    assert error is None
    assert target == OpenTarget(override, is_override=True)


def test_generated_only_targets_the_generated_file_even_with_an_override(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    override = override_path(asset_dir, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>hand-edited</svg>")

    target, error = resolve_open_target(
        _asset(), asset_dir, DerivativeType.CUT_SVG, None, generated_only=True
    )

    assert error is None
    assert target == OpenTarget(asset_dir / DERIVED_DIRNAME / FILENAME, is_override=False)


def test_start_override_with_no_override_copies_the_generated_file_and_records_provenance(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    generated_bytes = (asset_dir / DERIVED_DIRNAME / FILENAME).read_bytes()

    target, error = resolve_open_target(
        _asset(), asset_dir, DerivativeType.CUT_SVG, None, start_override=True
    )

    assert error is None
    assert target is not None
    assert target.is_override is True
    assert target.path == override_path(asset_dir, FILENAME)
    assert target.path.read_bytes() == generated_bytes
    # the ruling behind this issue: provenance is recorded immediately, not
    # deferred to a later validate/approve.
    assert read_override_provenance(asset_dir / DERIVED_DIRNAME, FILENAME) is not None


def test_start_override_with_an_existing_override_opens_it_without_rewriting(
    tmp_path: Path,
) -> None:
    asset_dir = _make_asset_dir(tmp_path)
    generate_asset(_asset(), asset_dir)
    override = override_path(asset_dir, FILENAME)
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_bytes(b"<svg>already hand-edited</svg>")
    mtime_before = override.stat().st_mtime_ns

    target, error = resolve_open_target(
        _asset(), asset_dir, DerivativeType.CUT_SVG, None, start_override=True
    )

    assert error is None
    assert target == OpenTarget(override, is_override=True)
    assert override.read_bytes() == b"<svg>already hand-edited</svg>"
    assert override.stat().st_mtime_ns == mtime_before


def test_start_override_is_an_error_when_the_generated_file_is_missing(tmp_path: Path) -> None:
    asset_dir = _make_asset_dir(tmp_path)  # nothing generated yet

    target, error = resolve_open_target(
        _asset(), asset_dir, DerivativeType.CUT_SVG, None, start_override=True
    )

    assert target is None
    assert error is not None
    assert "missing" in error
