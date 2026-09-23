"""Every ``vpress`` command run so far never touches a source image (§21).

Hashes every file under every asset's ``sources/`` directory in the fixture
catalog, runs every CLI command that exists, and asserts the hashes are
unchanged — the integration-level proof behind ADR 0003 and ADR 0007's
"sources/ is read-only to the tool" (issue #4).
"""

import hashlib
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)
    before = _hash_all_sources(FIXTURE_CATALOG_ROOT)
    assert before, "fixture catalog should have committed source images to hash"

    results = [
        runner.invoke(app, ["status"]),
        runner.invoke(app, ["assets"]),
        *(runner.invoke(app, ["asset", asset_id]) for asset_id in FIXTURE_ASSET_IDS),
    ]

    for result in results:
        assert result.exit_code == 0, result.output

    after = _hash_all_sources(FIXTURE_CATALOG_ROOT)
    assert after == before
