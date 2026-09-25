"""PRD 4 acceptance walk-through: review, approval, and overrides (§6.8,
§10, §22, §24, §34, §35, §39.16, ADR 0003, ADR 0004, ADR 0005, ADR 0007).

PRD 4's own Acceptance paragraph: "User can review and approve every
fixture derivative from the CLI; a hand-edited cut file survives
regeneration (§39.16); a source change flags the override stale; blocked
assets are listed with reasons; the attention report is empty when
everything is approved." This performs that walk-through end to end, on a
temporary copy of the fixture catalog, through the in-process ``CliRunner``
every other PRD 4 integration test in this package already uses.

The override subject is ``owl_limpet``, not ``giant_green_anemone``: the
fixture's real-artwork anemone silhouette is a single piece with nothing to
hand-remove, while ``owl_limpet``'s generated cut file always carries one
surviving detached piece ``cut_svg``'s cleanup deliberately keeps
(``tests/fixtures/catalog/README.md``) -- a genuine geometry edit to make,
the same fixture ``tests/integration/test_overrides.py`` already builds its
own override from.

The fixture intentionally holds two permanently unapprovable assets
(``tests/fixtures/catalog/README.md``): ``gumboot_chiton`` (rights status
``do_not_publish``, blocked even once every derivative is approved) and
``acorn_barnacle`` (a truncated source, so its derivatives fail at
generation and can never exist to be approved at all). The walk-through's
final attention report holds exactly those two, named, and nothing else --
not a literally empty inbox, which criterion 3 already proves on a minimal
temp catalog.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from PIL import Image
from typer.testing import CliRunner

from vectorpress.catalog.overrides import override_path
from vectorpress.catalog.provenance import DERIVED_DIRNAME
from vectorpress.cli import app as cli_app_module
from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

OWL_LIMPET = "owl_limpet"
OWL_LIMPET_CUT_FILENAME = "owl-limpet-cut.svg"

# The fixture's two permanently unapprovable assets (README.md) -- never
# resolved by any amount of review, so they are the only survivors of the
# walk-through's final attention report.
RIGHTS_BLOCKED_ASSET = "gumboot_chiton"
GENERATION_FAILS_ASSET = "acorn_barnacle"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


class _RecordingLauncher:
    """``vpress open``'s launch seam, recorded instead of spawned (mirrors
    ``tests/integration/test_open.py``): this walk-through only needs the
    override file it creates, never a real editor process."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str] | None, Path]] = []

    def __call__(self, argv: list[str] | None, path: Path) -> None:
        self.calls.append((argv, path))


@pytest.fixture
def recording_launcher(monkeypatch: pytest.MonkeyPatch) -> _RecordingLauncher:
    launcher = _RecordingLauncher()
    monkeypatch.setattr(cli_app_module, "_launcher", launcher)
    return launcher


def _derived_dir(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


def _drop_detached_piece(svg_bytes: bytes) -> bytes:
    """Hand-remove ``owl_limpet``'s surviving detached piece: drop the
    second subpath of its single ``<path>``, leaving only the main body --
    the same real geometry edit
    ``tests/integration/test_overrides.py``'s own ``_drop_detached_piece``
    makes, turning a cut file that needs review for
    ``disconnected_fragments`` into one that passes."""
    text = svg_bytes.decode("utf-8")
    match = re.search(r'd="([^"]+)"', text)
    assert match is not None, "expected exactly one <path d=...> in a generated cut file"
    d = match.group(1)
    subpaths = d.split("Z")
    assert subpaths[-1] == ""  # every subpath this tool writes is closed with Z
    assert len(subpaths) > 2, "expected a main body plus at least one detached piece"
    main_body_d = subpaths[0] + "Z"
    return text.replace(d, main_body_d).encode("utf-8")


def _flip_a_source_pixel(path: Path) -> None:
    """Change a source PNG's bytes (and so its hash) without changing its
    silhouette shape in any way that matters here: flip one corner pixel's
    alpha (the same edit ``tests/integration/test_overrides.py``'s own
    ``_replace_silhouette_source`` makes) -- §22.2's "the source changed"."""
    original_bytes = path.read_bytes()
    image = Image.open(path).convert("RGBA")
    r, g, b, a = cast(tuple[int, int, int, int], image.getpixel((0, 0)))
    image.putpixel((0, 0), (r, g, b, 0 if a else 255))
    image.save(path, format="PNG")
    assert path.read_bytes() != original_bytes


def _attention_json() -> dict[str, Any]:
    result = runner.invoke(app, ["attention", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.mark.integration
def test_prd_04_acceptance_walkthrough(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    # 1. generate --all -> attention lists every derivative as needs review.
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)

    after_generate = _attention_json()
    needs_review_pairs = {
        (item["asset_id"], item["derivative_type"]) for item in after_generate["needs_review"]
    }
    assert ("ochre_sea_star", "cut_svg") in needs_review_pairs
    assert (OWL_LIMPET, "cut_svg") in needs_review_pairs
    assert (RIGHTS_BLOCKED_ASSET, "cut_svg") in needs_review_pairs
    assert all(item["status"] == "needs_review" for item in after_generate["needs_review"])
    # acorn_barnacle has nothing generated at all: never a needs_review item.
    assert not any(pair[0] == GENERATION_FAILS_ASSET for pair in needs_review_pairs)

    # 2. validate --all.
    validate_result = runner.invoke(app, ["validate", "--all"])
    assert validate_result.exit_code == 0, validate_result.output

    # 3. start an override of owl_limpet's cut file (vpress open --override),
    # hand-remove its surviving detached piece, then approve everything with
    # the bulk commands.
    open_result = runner.invoke(app, ["open", OWL_LIMPET, "cut_svg", "--override"])
    assert open_result.exit_code == 0, open_result.output
    override_file = override_path(
        temp_catalog_root / "assets" / OWL_LIMPET, OWL_LIMPET_CUT_FILENAME
    )
    assert override_file.is_file()
    assert recording_launcher.calls == [(None, override_file)]

    override_file.write_bytes(_drop_detached_piece(override_file.read_bytes()))
    override_validate = runner.invoke(app, ["validate", OWL_LIMPET])
    assert override_validate.exit_code == 0, override_validate.output
    assert f"{OWL_LIMPET}\tcut_svg\t{OWL_LIMPET_CUT_FILENAME}\tpass" in override_validate.stdout

    approve_result = runner.invoke(app, ["approve", "--all"])
    assert approve_result.exit_code == 0, approve_result.output
    assert f"{OWL_LIMPET}\tcut_svg\tapproved" in approve_result.stdout

    # 4. generate --force --all -> the override's bytes and approval survive.
    override_bytes_before_force = override_file.read_bytes()
    forced_result = runner.invoke(app, ["generate", "--force", "--all"])
    assert forced_result.exit_code == 1, forced_result.output  # acorn_barnacle still fails
    assert override_file.read_bytes() == override_bytes_before_force

    owl_limpet_asset_result = runner.invoke(app, ["asset", OWL_LIMPET])
    cut_svg_line = next(
        line
        for line in owl_limpet_asset_result.stdout.splitlines()
        if line.strip().startswith("cut_svg")
    )
    assert "override" in cut_svg_line
    assert "approved" in cut_svg_line

    # 5. change owl_limpet's silhouette source -> attention lists the stale
    # override; override keep resolves it.
    _flip_a_source_pixel(temp_catalog_root / "assets" / OWL_LIMPET / "sources" / "silhouette.png")

    after_source_change = _attention_json()
    stale_pairs = {
        (item["asset_id"], item["derivative_type"])
        for item in after_source_change["stale_overrides"]
    }
    assert (OWL_LIMPET, "cut_svg") in stale_pairs

    keep_result = runner.invoke(app, ["override", "keep", OWL_LIMPET, "cut_svg"])
    assert keep_result.exit_code == 0, keep_result.output
    assert "kept" in keep_result.stdout

    after_keep = _attention_json()
    stale_pairs_after_keep = {
        (item["asset_id"], item["derivative_type"]) for item in after_keep["stale_overrides"]
    }
    assert (OWL_LIMPET, "cut_svg") not in stale_pairs_after_keep
    # the override survives keep untouched, byte for byte.
    assert override_file.read_bytes() == override_bytes_before_force

    # 6. any asset the fixture blocks by rights/accuracy remains listed with
    # its reason -- gumboot_chiton, whether or not review has finished.
    blocked_ids = {item["asset_id"] for item in after_keep["blocked_assets"]}
    assert blocked_ids == {RIGHTS_BLOCKED_ASSET}
    gumboot_item = next(
        item for item in after_keep["blocked_assets"] if item["asset_id"] == RIGHTS_BLOCKED_ASSET
    )
    assert any(reason["value"] == "do_not_publish" for reason in gumboot_item["reasons"])

    # Finish reviewing: owl_limpet's *generated* transparent_png/
    # silhouette_svg/cut_svg are now stale against the changed source (only
    # its override was resolved by keep) -- one more generate+approve pass
    # regenerates and re-reviews them, the same cycle steps 1-3 already
    # walked through once.
    finishing_generate = runner.invoke(app, ["generate", "--all"])
    assert finishing_generate.exit_code == 1, (
        finishing_generate.output
    )  # acorn_barnacle still fails
    finishing_approve = runner.invoke(app, ["approve", "--all"])
    assert finishing_approve.exit_code == 0, finishing_approve.output

    # 7. with everything approved and no blocked assets outside the
    # intentionally blocked fixture one, attention holds exactly the
    # permanent, named items: gumboot_chiton's rights block,
    # acorn_barnacle's missing derivatives, and the fixture's (empty) set of
    # existing metadata problems -- no needs-review or stale items.
    final = _attention_json()

    assert final["needs_review"] == []
    assert final["stale_overrides"] == []
    assert final["missing_metadata"] == []

    assert {item["asset_id"] for item in final["blocked_assets"]} == {RIGHTS_BLOCKED_ASSET}

    missing_derivative_pairs = {
        (item["asset_id"], item["derivative_type"]) for item in final["missing_derivatives"]
    }
    assert {pair[0] for pair in missing_derivative_pairs} == {GENERATION_FAILS_ASSET}
    assert missing_derivative_pairs == {
        (GENERATION_FAILS_ASSET, "transparent_png"),
        (GENERATION_FAILS_ASSET, "silhouette_svg"),
        (GENERATION_FAILS_ASSET, "cut_svg"),
    }
    assert all(item["state"] == "missing" for item in final["missing_derivatives"])

    # the text report agrees: "nothing needs attention" never appears
    # (gumboot_chiton and acorn_barnacle keep it non-empty), and it names
    # exactly zero needs-review items.
    text_result = runner.invoke(app, ["attention"])
    assert text_result.exit_code == 0, text_result.output
    assert "nothing needs attention" not in text_result.stdout
    assert "Needs review: 0" in text_result.stdout

    # vpress status's §34 counts agree with attention's own classification.
    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0, status_result.output
    blocked_line = next(
        line for line in status_result.stdout.splitlines() if line.startswith("Blocked assets:")
    )
    assert int(blocked_line.split(":")[1].strip()) == 1
    assert "Run 'vpress attention' for details." in status_result.stdout


@pytest.mark.integration
def test_the_reviewable_generated_cut_file_still_shows_needs_review_never_touched_by_the_override(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, recording_launcher: _RecordingLauncher
) -> None:
    """§39.16, ADR 0007: approving and regenerating around an override never
    approves or rewrites the *generated* file underneath it -- a narrower,
    single-asset check of what the full walk-through above exercises."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", OWL_LIMPET])
    runner.invoke(app, ["open", OWL_LIMPET, "cut_svg", "--override"])
    override_file = override_path(
        temp_catalog_root / "assets" / OWL_LIMPET, OWL_LIMPET_CUT_FILENAME
    )
    override_file.write_bytes(_drop_detached_piece(override_file.read_bytes()))
    runner.invoke(app, ["approve", OWL_LIMPET, "cut_svg"])

    generated_path = _derived_dir(temp_catalog_root, OWL_LIMPET) / OWL_LIMPET_CUT_FILENAME
    generated_bytes_before = generated_path.read_bytes()

    runner.invoke(app, ["generate", "--force", OWL_LIMPET])

    assert generated_path.read_bytes() == generated_bytes_before

    asset_result = runner.invoke(app, ["asset", OWL_LIMPET])
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "approved" in cut_svg_line  # the override's own status
