"""``vpress attention`` and ``vpress status``'s §34 counts end to end,
against a temporary copy of the fixture catalog (§34, §24, CONTEXT.md
"Attention report / Inbox").

Runs against a temporary copy, never the committed fixture directly: several
of these tests generate and review real derivatives, writing files under
each asset's ``derived/`` (``tests/fixtures/catalog/README.md``).
"""

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _section(output: str, header: str) -> list[str]:
    """Every line of one section of ``vpress attention``'s text output,
    from a line starting with ``header`` up to (not including) the next
    top-level (non-indented) line."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    return lines[start:end]


def _item_lines(section_lines: list[str]) -> list[str]:
    """The item lines of a section (two-space indented, not the deeper
    four-space "resolve:" line under each)."""
    return [line for line in section_lines if line.startswith("  ") and not line.startswith("    ")]


# --- acceptance criterion 1: every existing derivative, missing types, metadata -----


@pytest.mark.integration
def test_attention_lists_needs_review_after_generate_all(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    needs_review_lines = _item_lines(_section(result.stdout, "Needs review:"))
    # every asset but acorn_barnacle (nothing generated for it) has at least
    # one existing, unapproved derivative right after generate --all.
    asset_ids_seen = {line.strip().split("\t")[0] for line in needs_review_lines}
    assert "ochre_sea_star" in asset_ids_seen
    assert "gumboot_chiton" in asset_ids_seen
    assert "acorn_barnacle" not in asset_ids_seen
    for line in needs_review_lines:
        assert "needs review" in line
    assert "ochre_sea_star\tcut_svg\tneeds review" in result.stdout


@pytest.mark.integration
def test_attention_lists_acorn_barnacles_missing_derivatives_from_its_truncated_source(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["attention"])

    missing_lines = _item_lines(_section(result.stdout, "Missing derivatives:"))
    acorn_lines = [line for line in missing_lines if line.strip().startswith("acorn_barnacle")]
    assert acorn_lines
    for line in acorn_lines:
        assert "\tmissing" in line


@pytest.mark.integration
def test_attention_names_the_resolving_command_for_each_kind(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["attention"])

    assert "resolve: vpress approve ochre_sea_star cut_svg" in result.stdout
    assert "resolve: vpress generate acorn_barnacle" in result.stdout
    assert "resolve: edit assets/gumboot_chiton/asset.toml" in result.stdout


def _blank_owl_limpets_licensing_notes(root: Path) -> None:
    """Blank ``owl_limpet``'s ``licensing_notes`` in a temp catalog copy
    alone -- ``root`` is always a ``temp_catalog_root``, never
    ``FIXTURE_CATALOG_ROOT`` itself. The committed fixture keeps
    ``owl_limpet``'s notes non-empty; the empty-notes case (§26) is
    test-only, the same as ``tests/integration/test_eligibility.py``'s own
    helper of the same name."""
    path = root / "assets" / "owl_limpet" / "asset.toml"
    text = path.read_text(encoding="utf-8")
    assert 'rights_status = "ai_generated"\n' in text
    before = (
        'licensing_notes = "Generated with Midjourney (v6) under its commercial-use terms '
        'for paid subscribers; the ai_generated rights-status fixture (§26)."\n'
    )
    assert before in text
    path.write_text(text.replace(before, 'licensing_notes = ""\n'), encoding="utf-8")


@pytest.mark.integration
def test_attention_lists_an_ai_generated_asset_with_empty_notes_as_blocked(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§26's new blocking-reason kind is asset-level (``domain.eligibility.
    ASSET_LEVEL_BLOCKING_REASON_KINDS``), so it surfaces in ``vpress
    attention``'s "Blocked assets" section the same way a rights block
    already does -- no generation needed, the same as ``gumboot_chiton``'s
    own committed rights block."""
    _blank_owl_limpets_licensing_notes(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert (
        "  owl_limpet\tlicensing notes: must name the AI tool and its terms "
        "(rights status: ai generated)" in result.stdout
    )
    assert (
        "    resolve: edit assets/owl_limpet/asset.toml's"
        " rights_status/accuracy_status/licensing_notes" in result.stdout
    )


@pytest.mark.integration
def test_attention_on_the_clean_fixture_reports_no_metadata_problems(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert "Missing metadata: 0" in result.stdout


# --- acceptance criterion 2: --json is snapshot-locked, no absolute paths/separators --


@pytest.mark.integration
def test_attention_json_shape_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    """A fully deterministic scenario -- nothing generated, so every group
    is built from committed ``asset.toml`` data alone, never from traced
    SVG bytes or a raster hash -- so this snapshot cannot drift between
    ubuntu and windows for image-processing reasons (only ``needs_review``
    and ``stale_overrides`` ever depend on generated bytes, and both are
    empty here)."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == snapshot
    # never an absolute path, an OS path separator, or a leading catalog
    # root fragment -- every path is posix-relative (cli._attention_report_to_json).
    for problem in payload["missing_metadata"]:
        assert "\\" not in problem["path"]
        assert not Path(problem["path"]).is_absolute()


# --- acceptance criterion 3: an empty inbox on a minimal, fully-resolved catalog ----


def _write_minimal_catalog(root: Path) -> None:
    asset_dir = root / "assets" / "test_asset"
    (asset_dir / "sources").mkdir(parents=True)
    (root / "catalog.toml").write_text('name = "Minimal Catalog"\n', encoding="utf-8")

    image = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((8, 8, 39, 39), fill=(30, 60, 90, 255))
    image.save(asset_dir / "sources" / "silhouette.png", format="PNG")

    Image.new("RGBA", (4, 4), (10, 10, 10, 255)).save(root / "mark.png", format="PNG")
    (root / "license_template.txt").write_text(
        "{brand} license for {product}. {copyright} {year}\n", encoding="utf-8"
    )
    (root / "brand.toml").write_text(
        "\n".join(
            [
                'name = "Minimal Catalog"',
                'mark_file = "mark.png"',
                'standard_wording = "Test wording."',
                'license_name = "Test License"',
                'license_file = "license_template.txt"',
                'copyright_wording = "(c) Test."',
                'readme_text = "Test readme."',
                "",
                "[typography]",
                'heading_font = "Sans"',
                'body_font = "Sans"',
                "",
                "[card_style]",
                'background_color = "#FFFFFF"',
                'accent_color = "#000000"',
                'text_color = "#000000"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    (asset_dir / "asset.toml").write_text(
        "\n".join(
            [
                'common_name = "Test subject"',
                'display_name = "Test Asset"',
                'description = "A minimal test asset."',
                'subject_category = "Test"',
                'taxonomic_group = "Test"',
                'rights_status = "original_artwork"',
                'accuracy_status = "approved"',
                "",
                "[[sources]]",
                'role = "silhouette"',
                'file = "silhouette.png"',
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture
def minimal_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "minimal_catalog"
    _write_minimal_catalog(root)
    return root


@pytest.mark.integration
def test_nothing_needs_attention_on_a_fully_resolved_minimal_catalog(
    monkeypatch: pytest.MonkeyPatch, minimal_catalog_root: Path
) -> None:
    monkeypatch.chdir(minimal_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert "nothing needs attention" in result.stdout


@pytest.mark.integration
def test_a_catalog_with_a_pending_review_is_not_empty(
    monkeypatch: pytest.MonkeyPatch, minimal_catalog_root: Path
) -> None:
    monkeypatch.chdir(minimal_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert "nothing needs attention" not in result.stdout


# --- acceptance criterion 4: vpress status agrees with vpress attention -------------


@pytest.mark.integration
def test_vpress_status_blocked_count_matches_attentions_blocked_assets(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    status_result = runner.invoke(app, ["status"])
    attention_result = runner.invoke(app, ["attention"])

    assert status_result.exit_code == 0, status_result.output
    blocked_line = next(
        line for line in status_result.stdout.splitlines() if line.startswith("Blocked assets:")
    )
    blocked_count = int(blocked_line.split(":")[1].strip())

    blocked_items = _item_lines(_section(attention_result.stdout, "Blocked assets:"))
    assert blocked_count == len(blocked_items)
    assert blocked_count == 1  # gumboot_chiton alone (rights-blocked, README)


@pytest.mark.integration
def test_vpress_status_points_at_attention_only_when_something_is_outstanding(
    monkeypatch: pytest.MonkeyPatch, minimal_catalog_root: Path
) -> None:
    monkeypatch.chdir(minimal_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    pending_result = runner.invoke(app, ["status"])
    assert "vpress attention" in pending_result.stdout

    runner.invoke(app, ["validate", "--all"])
    runner.invoke(app, ["approve", "--all"])

    clean_result = runner.invoke(app, ["status"])
    assert "vpress attention" not in clean_result.stdout


@pytest.mark.integration
def test_vpress_status_asset_publication_counts_on_the_minimal_catalog(
    monkeypatch: pytest.MonkeyPatch, minimal_catalog_root: Path
) -> None:
    monkeypatch.chdir(minimal_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])
    runner.invoke(app, ["approve", "--all"])

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "Approved assets: 1" in result.stdout
    assert "Assets awaiting review: 0" in result.stdout
    assert "Blocked assets: 0" in result.stdout
