"""``vpress build``'s preview rendering end to end, against a temporary copy
of the fixture catalog (§16, ADR 0014, ADR 0015).

Runs against a temporary copy, never the committed fixture directly, the
same reason ``test_build.py`` does (``tests/fixtures/catalog/README.md``).
Chromium actually renders here (unlike ``tests/unit/test_build_previews.py``,
which only exercises the Jinja side): these are the tests CI's own
``playwright install chromium`` step exists for.
"""

import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from vectorpress.catalog.manifests import read_manifest
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
PNG_ONLY_TOP_LEVEL = "Pacific-Coast-Tide-Pool"

EXPECTED_PREVIEWS = [
    "previews/01-main-landscape.png",
    "previews/01-main-square.png",
    "previews/02-included-landscape.png",
    "previews/02-included-square.png",
    "previews/03-formats-landscape.png",
    "previews/03-formats-square.png",
]
EXPECTED_SIZES = {
    "previews/01-main-square.png": (2000, 2000),
    "previews/01-main-landscape.png": (2400, 1600),
    "previews/02-included-square.png": (2000, 2000),
    "previews/02-included-landscape.png": (2400, 1600),
    "previews/03-formats-square.png": (2000, 2000),
    "previews/03-formats-landscape.png": (2400, 1600),
}


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _generate_and_approve_transparent_png(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.chdir(root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output


def _build_dir(root: Path, slug: str) -> Path:
    return root / "builds" / slug


def _preview_files(build_dir: Path) -> dict[str, bytes]:
    previews_dir = build_dir / "previews"
    return {
        f"previews/{path.name}": path.read_bytes()
        for path in previews_dir.iterdir()
        if path.is_file()
    }


@pytest.mark.integration
def test_build_writes_every_preview_type_at_both_canvases_never_in_the_zip_and_lists_them_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert result.exit_code == 0, result.output

    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    previews_dir = build_dir / "previews"
    assert previews_dir.is_dir()

    preview_names = sorted(p.name for p in previews_dir.iterdir() if p.is_file())
    assert preview_names == sorted(Path(rel_path).name for rel_path in EXPECTED_PREVIEWS)

    for rel_path, (expected_width, expected_height) in EXPECTED_SIZES.items():
        with Image.open(previews_dir / Path(rel_path).name) as image:
            assert image.size == (expected_width, expected_height)

    # Never inside the package or the ZIP (§14).
    package_dir = build_dir / PNG_ONLY_TOP_LEVEL
    package_files = {p.relative_to(package_dir).as_posix() for p in package_dir.rglob("*")}
    assert "previews" not in package_files
    with zipfile.ZipFile(build_dir / f"{PNG_ONLY_TOP_LEVEL}.zip") as zip_file:
        assert not any("preview" in name.lower() for name in zip_file.namelist())

    manifest = read_manifest(temp_catalog_root, PNG_ONLY_SLUG)
    assert manifest is not None
    assert manifest.previews == EXPECTED_PREVIEWS


@pytest.mark.integration
def test_catalog_override_reading_an_undefined_variable_refuses_the_build_naming_it_and_leaves_the_previous_build_intact(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    first = runner.invoke(app, ["build", PNG_ONLY_SLUG])
    assert first.exit_code == 0, first.output
    build_dir = _build_dir(temp_catalog_root, PNG_ONLY_SLUG)
    previous_previews = _preview_files(build_dir)
    previous_manifest_bytes = (build_dir / "manifest.json").read_bytes()

    override_dir = temp_catalog_root / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        "{% block content %}{{ not_a_real_context_variable }}{% endblock %}\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "main.html.j2" in result.output
    assert "not_a_real_context_variable" in result.output
    # The previous build is untouched -- same preview bytes, same manifest.
    assert _preview_files(build_dir) == previous_previews
    assert (build_dir / "manifest.json").read_bytes() == previous_manifest_bytes


@pytest.mark.integration
def test_catalog_override_referencing_a_remote_url_refuses_the_build(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _generate_and_approve_transparent_png(monkeypatch, temp_catalog_root)

    override_dir = temp_catalog_root / "templates" / "previews"
    override_dir.mkdir(parents=True)
    (override_dir / "main.html.j2").write_text(
        '{% extends "shipped/_base.html.j2" %}\n'
        '{% block content %}<img src="https://example.invalid/remote-logo.png">{% endblock %}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert "main.html.j2" in result.output
    assert "https://example.invalid/remote-logo.png" in result.output
    assert not (temp_catalog_root / "builds" / PNG_ONLY_SLUG).exists()
