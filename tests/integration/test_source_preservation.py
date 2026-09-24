"""Every ``vpress`` command run so far never touches a source image (§21).

Hashes every file under every asset's ``sources/`` directory in a temporary
copy of the fixture catalog, runs every CLI command that exists -- including
``generate``, which writes under ``derived/`` (issue #23) -- and asserts the
source hashes are unchanged: the integration-level proof behind ADR 0003 and
ADR 0007's "sources/ is read-only to the tool" (issue #4).

Runs against a temporary copy rather than the committed fixture directly
(issue #23): ``generate`` writes real files under each asset's ``derived/``,
and the committed fixture must never contain one (this directory's README).

The fixture's fourth asset, ``acorn_barnacle``, has a deliberately truncated
source (issue #27, §35): a ``generate`` that reaches it fails without ever
touching a byte under ``sources/`` -- exercised directly below alongside the
successful commands, since source preservation must hold on the failure path
too, not just the happy one.
"""

import hashlib
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

FIXTURE_ASSET_IDS = ["ochre_sea_star", "purple_sea_urchin", "giant_green_anemone"]


def _hash_all_sources(root: Path) -> dict[Path, str]:
    hashes: dict[Path, str] = {}
    for sources_dir in sorted(root.glob("assets/*/sources")):
        for source_file in sorted(sources_dir.iterdir()):
            if source_file.is_file():
                hashes[source_file] = hashlib.sha256(source_file.read_bytes()).hexdigest()
    return hashes


@pytest.mark.integration
def test_every_cli_command_leaves_source_images_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    monkeypatch.chdir(root)
    before = _hash_all_sources(root)
    assert before, "fixture catalog should have committed source images to hash"

    succeeding_results = [
        runner.invoke(app, ["status"]),
        runner.invoke(app, ["assets"]),
        *(runner.invoke(app, ["asset", asset_id]) for asset_id in FIXTURE_ASSET_IDS),
        *(runner.invoke(app, ["generate", asset_id]) for asset_id in FIXTURE_ASSET_IDS),
    ]
    for result in succeeding_results:
        assert result.exit_code == 0, result.output

    # generate --all, and generating acorn_barnacle directly, both exit
    # non-zero (issue #27): its only source is a deliberately truncated PNG,
    # so transparent_png and silhouette_svg fail to generate. §35's "a
    # failure involving one asset should not silently corrupt unrelated
    # products" -- proven here as "does not touch a single source byte,
    # including its own" -- holds on this failing path too, not only the
    # successful commands above.
    failing_results = [
        runner.invoke(app, ["generate", "--all"]),
        runner.invoke(app, ["generate", "acorn_barnacle"]),
    ]
    for result in failing_results:
        assert result.exit_code == 1, result.output

    after = _hash_all_sources(root)
    assert after == before
