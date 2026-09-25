"""The override tracer end to end, against a temporary copy of the fixture
catalog (§6.8, §39.16, ADR 0003, ADR 0004, ADR 0005, ADR 0007).

Runs against a temporary copy, never the committed fixture directly -- same
reason as ``tests/integration/test_generate.py``: this exercises real
``derived/`` and ``overrides/`` folders, and the fixture catalog must never
contain either.

``owl_limpet``'s generated cut file always carries one surviving detached
piece cut_svg's cleanup deliberately keeps (``tests/fixtures/catalog/README.md``),
so it needs review for ``disconnected_fragments`` before any override
exists -- the fixture this module's own "does an override actually change
the validation outcome" tests build a real override from: the generated
cut file with that detached piece's own subpath dropped, a genuine
geometry edit (never an XML comment), which passes.

Tests that only need *some* override on disk, regardless of what it
validates to, use ``giant_green_anemone`` instead (its cut file is a
single piece, already ``pass``) with a harmless trailing XML comment, so
they never depend on ``owl_limpet``'s specific geometry.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vectorpress.catalog.findings import findings_path
from vectorpress.catalog.overrides import (
    override_path,
    override_provenance_path,
    read_override_provenance,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_provenance, sha256_bytes
from vectorpress.catalog.status import read_status
from vectorpress.cli.app import app
from vectorpress.domain.derivative_type import DerivativeType

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# "some override" fixture: a single-piece cut file, already pass, edited
# only cosmetically.
ASSET_ID = "giant_green_anemone"
FILENAME = "giant-green-anemone-cut.svg"

# "the override actually changes the outcome" fixture: two pieces (main
# body plus a surviving detached piece), needs review until the override
# drops the second one.
PASS_ASSET_ID = "owl_limpet"
PASS_FILENAME = "owl-limpet-cut.svg"


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _derived_dir(root: Path, asset_id: str = ASSET_ID) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


def _hand_edit(svg_bytes: bytes, comment: bytes = b"<!-- hand-edited -->") -> bytes:
    """A trivial, geometry-preserving edit: append an XML comment just
    before the closing tag. Never touches the traced path data, so an
    override built this way validates identically to the generated file it
    started from."""
    text = svg_bytes.decode("utf-8")
    assert "</svg>" in text
    return text.replace("</svg>", comment.decode("utf-8") + "</svg>").encode("utf-8")


def _drop_detached_piece(svg_bytes: bytes) -> bytes:
    """A real geometry edit: drop the cut file's own detached subpath --
    the surviving piece cut_svg's cleanup deliberately keeps
    (``tests/fixtures/catalog/README.md``) -- leaving only the main body.
    Turns a generated cut file that needs review for
    ``disconnected_fragments`` into one that passes, the same repair a
    human would make in an SVG editor.

    ``render_svg`` (§8) writes one ``<path>`` per fill, each subpath closed
    with an absolute ``Z``; every subpath but the last (main body first, by
    construction) is dropped here, leaving the closing quote's document
    otherwise byte-identical.
    """
    text = svg_bytes.decode("utf-8")
    match = re.search(r'd="([^"]+)"', text)
    assert match is not None, "expected exactly one <path d=...> in a generated cut file"
    d = match.group(1)
    subpaths = d.split("Z")
    assert subpaths[-1] == ""  # every subpath this tool writes is closed with Z
    assert len(subpaths) > 2, "expected a main body plus at least one detached piece"
    main_body_d = subpaths[0] + "Z"
    return text.replace(d, main_body_d).encode("utf-8")


def _write_override(
    root: Path, data: bytes, asset_id: str = ASSET_ID, filename: str = FILENAME
) -> Path:
    path = override_path(root / "assets" / asset_id, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- acceptance criterion 1: detection, own status, validated as pass --------------


@pytest.mark.integration
def test_the_generated_cut_file_needs_review_before_any_override_exists(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Establishes the starting point the rest of this scenario depends on:
    owl_limpet's generated cut file is not pass on its own."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", PASS_ASSET_ID])

    result = runner.invoke(app, ["validate", PASS_ASSET_ID])

    assert result.exit_code == 0, result.output
    assert f"{PASS_ASSET_ID}\tcut_svg\t{PASS_FILENAME}\tneeds review" in result.stdout
    assert "disconnected_fragments" in result.stdout


@pytest.mark.integration
def test_an_override_shows_overridden_and_needs_review_and_validates_pass(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", PASS_ASSET_ID])
    generated_before = runner.invoke(app, ["validate", PASS_ASSET_ID])
    assert "needs review" in generated_before.stdout  # the starting point (see test above)
    generated_findings_before = findings_path(
        _derived_dir(temp_catalog_root, PASS_ASSET_ID), PASS_FILENAME
    ).read_bytes()

    generated_bytes = (_derived_dir(temp_catalog_root, PASS_ASSET_ID) / PASS_FILENAME).read_bytes()
    _write_override(
        temp_catalog_root,
        _drop_detached_piece(generated_bytes),
        asset_id=PASS_ASSET_ID,
        filename=PASS_FILENAME,
    )

    asset_result = runner.invoke(app, ["asset", PASS_ASSET_ID])
    assert asset_result.exit_code == 0, asset_result.output
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "override" in cut_svg_line
    assert "needs review" in cut_svg_line

    validate_result = runner.invoke(app, ["validate", PASS_ASSET_ID])
    assert validate_result.exit_code == 0, validate_result.output
    assert f"{PASS_ASSET_ID}\tcut_svg\t{PASS_FILENAME}\tpass" in validate_result.stdout
    assert "(override)" in validate_result.stdout

    # the generated file's own findings report is unchanged by validating
    # the override -- the override's report lives at its own coexisting
    # path (catalog.findings.findings_path's is_override).
    generated_findings_after = findings_path(
        _derived_dir(temp_catalog_root, PASS_ASSET_ID), PASS_FILENAME
    ).read_bytes()
    assert generated_findings_after == generated_findings_before


# --- acceptance criterion 2: approve the override; --force leaves it untouched (§39.16) --


@pytest.mark.integration
def test_approve_approves_the_override_and_force_regenerate_leaves_it_untouched(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", PASS_ASSET_ID])
    generated_bytes = (_derived_dir(temp_catalog_root, PASS_ASSET_ID) / PASS_FILENAME).read_bytes()
    override_bytes = _drop_detached_piece(generated_bytes)
    override_file = _write_override(
        temp_catalog_root, override_bytes, asset_id=PASS_ASSET_ID, filename=PASS_FILENAME
    )
    runner.invoke(app, ["validate", PASS_ASSET_ID])  # writes the override's findings report

    approve_result = runner.invoke(app, ["approve", PASS_ASSET_ID, "cut_svg"])
    assert approve_result.exit_code == 0, approve_result.output
    assert "approved" in approve_result.stdout

    override_bytes_before = override_file.read_bytes()
    findings_report_path = findings_path(
        _derived_dir(temp_catalog_root, PASS_ASSET_ID), PASS_FILENAME, is_override=True
    )
    findings_before = findings_report_path.read_bytes()

    forced = runner.invoke(app, ["generate", "--force", PASS_ASSET_ID])
    assert forced.exit_code == 0, forced.output

    # the override's own file, status, and findings are all untouched --
    # the generated file may have been rewritten (idempotently), but never
    # the override's.
    assert override_file.read_bytes() == override_bytes_before
    assert findings_report_path.read_bytes() == findings_before

    asset_result = runner.invoke(app, ["asset", PASS_ASSET_ID])
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "approved" in cut_svg_line

    # the generated file's own status is untouched by the override's approval.
    generated_status = read_status(
        _derived_dir(temp_catalog_root, PASS_ASSET_ID), DerivativeType.CUT_SVG
    )
    assert generated_status is None or generated_status.status.value != "approved"


# --- acceptance criterion 3: editing the override returns it to needs review --------


@pytest.mark.integration
def test_editing_the_override_returns_it_to_needs_review_and_stales_its_findings(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()
    override_file = _write_override(temp_catalog_root, _hand_edit(generated_bytes))
    runner.invoke(app, ["validate", ASSET_ID])
    runner.invoke(app, ["approve", ASSET_ID, "cut_svg"])

    approved = runner.invoke(app, ["asset", ASSET_ID])
    approved_line = next(
        line for line in approved.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "approved" in approved_line

    override_file.write_bytes(_hand_edit(generated_bytes, comment=b"<!-- edited again -->"))

    asset_result = runner.invoke(app, ["asset", ASSET_ID])
    cut_svg_line = next(
        line for line in asset_result.stdout.splitlines() if line.strip().startswith("cut_svg")
    )
    assert "needs review" in cut_svg_line
    assert "approved" not in cut_svg_line
    assert "findings stale" in cut_svg_line


# --- acceptance criterion 4: override provenance; overrides/ is never written -------


@pytest.mark.integration
def test_override_provenance_records_the_source_hash_it_was_edited_against(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    generated_provenance = read_provenance(_derived_dir(temp_catalog_root), FILENAME)
    assert generated_provenance is not None
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()
    override_bytes = _hand_edit(generated_bytes)
    _write_override(temp_catalog_root, override_bytes)

    approve_result = runner.invoke(app, ["approve", ASSET_ID, "cut_svg"])
    assert approve_result.exit_code == 0, approve_result.output

    override_provenance = read_override_provenance(_derived_dir(temp_catalog_root), FILENAME)
    assert override_provenance is not None
    assert override_provenance.source_hash == generated_provenance.source_hash
    assert override_provenance.output_hash == sha256_bytes(override_bytes)

    provenance_path = override_provenance_path(_derived_dir(temp_catalog_root), FILENAME)
    assert provenance_path.parent == _derived_dir(temp_catalog_root)


@pytest.mark.integration
def test_nothing_is_ever_written_under_overrides(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()
    override_bytes = _hand_edit(generated_bytes)
    override_file = _write_override(temp_catalog_root, override_bytes)
    overrides_dir = override_file.parent
    before = {p: p.read_bytes() for p in overrides_dir.iterdir() if p.is_file()}

    runner.invoke(app, ["asset", ASSET_ID])
    runner.invoke(app, ["validate", ASSET_ID])
    runner.invoke(app, ["approve", ASSET_ID, "cut_svg"])
    runner.invoke(app, ["generate", "--force", ASSET_ID])

    after = {p: p.read_bytes() for p in overrides_dir.iterdir() if p.is_file()}
    assert after == before


# --- acceptance criterion 5: an unrecognised override file is reported, not crashed -


@pytest.mark.integration
def test_an_unrecognized_override_file_is_reported_not_an_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    stray_path = temp_catalog_root / "assets" / ASSET_ID / "overrides" / "not-a-real-derivative.svg"
    stray_path.parent.mkdir(parents=True, exist_ok=True)
    stray_path.write_text("<svg></svg>", encoding="utf-8")

    result = runner.invoke(app, ["asset", ASSET_ID])

    assert result.exit_code == 0, result.output
    assert "not-a-real-derivative.svg" in result.stdout
    assert "ignored" in result.stdout


# --- vpress status: the override's status is what is counted (§6.8) ----------------


@pytest.mark.integration
def test_vpress_status_counts_the_overrides_status_not_the_generated_files(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    runner.invoke(app, ["approve", ASSET_ID, "cut_svg"])  # approves the generated file
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()
    _write_override(temp_catalog_root, _hand_edit(generated_bytes))

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0, status_result.output
    # the override is newly seen (needs_review), even though the generated
    # file underneath it was approved.
    status_lines = status_result.stdout.splitlines()
    needs_review_line = next(line for line in status_lines if line.startswith("Needs review:"))
    approved_line = next(line for line in status_lines if line.startswith("Approved:"))
    assert int(needs_review_line.split(":")[1].strip()) >= 1
    assert int(approved_line.split(":")[1].strip()) == 0


# Acceptance criterion 6 (unit-level effective-derivative resolution: override
# present / absent / generated missing) lives in
# tests/unit/test_catalog_overrides.py.


@pytest.mark.integration
def test_generated_files_own_state_json_is_untouched_by_an_overrides_approval(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Approving an override writes only the override's own state file --
    the generated file's own ``_state.json`` (locked byte-for-byte by
    ``tests/integration/test_review.py``'s
    ``test_state_json_shape_is_locked_by_snapshot``) never gains an
    override-shaped entry."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", ASSET_ID])
    generated_state_path = _derived_dir(temp_catalog_root) / "_state.json"
    bytes_before = generated_state_path.read_bytes()
    generated_bytes = (_derived_dir(temp_catalog_root) / FILENAME).read_bytes()
    _write_override(temp_catalog_root, _hand_edit(generated_bytes))

    runner.invoke(app, ["approve", ASSET_ID, "cut_svg"])

    assert generated_state_path.read_bytes() == bytes_before
    override_state_path = _derived_dir(temp_catalog_root) / "_overrides_state.json"
    assert override_state_path.is_file()
    data = json.loads(override_state_path.read_text(encoding="utf-8"))
    assert data["cut_svg"]["status"] == "approved"
