"""``vpress listing draft`` end to end against a temporary copy of the
fixture catalog (§18, ADR 0005, ADR 0015, ADR 0016).

Runs against a temporary copy, never the committed fixture directly: this
command writes into a hand-authored product file, and the fixture catalog's
own product files must never carry a drafted listing this command didn't
put there by hand (mirrors ``tests/integration/test_build.py``'s own
reasoning for ``builds/``).

``kelp_forest_mini_pack`` (inline membership) is the main fixture: its
rule-based membership resolves to exactly one member (``purple_sea_urchin``
-- the only fixture asset tagged to the "Kelp forest" ecosystem), so its
drafted values are easy to predict by hand and it exercises the
inline-membership fallbacks (§18: ``short_title`` from the title-cased
slug, ``category = ""``). ``pacific_coast_tide_pool_png_only``
(collection_slug) covers the referenced-collection path and the
template-override and partial-listing scenarios.

Both fixture products carry their own committed, already-drafted
``[listing]`` (ADR 0016) -- every product needs one to build -- so
``temp_catalog_root`` here strips it back off its copy of each: this module
tests the draft command itself, which needs a product with no ``[listing]``
yet to draft into.
"""

import re
import shutil
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.cli.app import app

runner = CliRunner()

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

MINI_PACK_SLUG = "kelp_forest_mini_pack"
MINI_PACK_PATH = Path("products") / f"{MINI_PACK_SLUG}.toml"

PNG_ONLY_SLUG = "pacific_coast_tide_pool_png_only"
PNG_ONLY_PATH = Path("products") / f"{PNG_ONLY_SLUG}.toml"


#: The header comment `vpress listing draft` itself opens a drafted table
#: with (ADR 0016) -- the boundary stripped back off a fixture product's own
#: already-drafted listing to restore the "no [listing] yet" state this
#: module's tests need.
_DRAFTED_HEADER_MARKER = "\n# Drafted by `vpress listing draft`"


def _without_drafted_listing(text: str) -> str:
    """``text`` with its own already-drafted ``[listing]`` table (and the
    header comment above it) removed, reversing exactly what
    :func:`~vectorpress.catalog.listing_draft.append_listing` appended."""
    return text[: text.index(_DRAFTED_HEADER_MARKER)]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    for path in (root / MINI_PACK_PATH, root / PNG_ONLY_PATH):
        path.write_text(
            _without_drafted_listing(path.read_text(encoding="utf-8")), encoding="utf-8"
        )
    return root


def _to_crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


# --- acceptance: appends exactly the drafted table, byte-for-byte prefix, CRLF kept ---


@pytest.mark.integration
def test_draft_appends_exactly_the_drafted_table_and_preserves_crlf_bytes(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    product_path = temp_catalog_root / MINI_PACK_PATH
    original_lf = product_path.read_text(encoding="utf-8")
    original_crlf = _to_crlf(original_lf)
    product_path.write_bytes(original_crlf.encode("utf-8"))
    original_bytes = product_path.read_bytes()
    assert b"\r\n" in original_bytes

    monkeypatch.chdir(temp_catalog_root)
    result = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])

    assert result.exit_code == 0, result.output
    new_bytes = product_path.read_bytes()
    assert new_bytes.startswith(original_bytes)
    appended_bytes = new_bytes[len(original_bytes) :]
    # Every line the append adds uses the file's own CRLF convention.
    assert appended_bytes.replace(b"\r\n", b"").count(b"\n") == 0

    appended_text = appended_bytes.decode("utf-8")
    # The header comment names today's date (ADR 0016); normalized so the
    # snapshot does not go stale the day after it is recorded.
    normalized = re.sub(r"on \d{4}-\d{2}-\d{2}\.", "on <today>.", appended_text)
    assert normalized == snapshot


@pytest.mark.integration
def test_draft_inline_membership_short_title_and_category(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§18: an inline membership has no collection name, so short_title
    drafts from the title-cased slug and category drafts empty."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])

    assert result.exit_code == 0, result.output
    text = (temp_catalog_root / MINI_PACK_PATH).read_text(encoding="utf-8")
    assert 'short_title = "Kelp Forest Mini Pack"' in text
    assert 'category = ""' in text


# --- acceptance: running it again refuses, file byte-identical -----------------------


@pytest.mark.integration
def test_running_draft_again_refuses_and_leaves_the_file_byte_identical(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    first = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])
    assert first.exit_code == 0, first.output
    after_first = (temp_catalog_root / MINI_PACK_PATH).read_bytes()

    second = runner.invoke(app, ["listing", "draft", MINI_PACK_SLUG])

    assert second.exit_code == 1
    assert (temp_catalog_root / MINI_PACK_PATH).read_bytes() == after_first


# --- acceptance: a partial or invalid [listing] refuses, nothing changes -------------


@pytest.mark.integration
def test_a_partial_listing_refuses_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    product_path = temp_catalog_root / PNG_ONLY_PATH
    with product_path.open("a", encoding="utf-8") as handle:
        handle.write('\n[listing]\ntitle = "Only a title, nothing else"\n')
    original = product_path.read_bytes()

    monkeypatch.chdir(temp_catalog_root)
    result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])

    assert result.exit_code == 1
    assert product_path.read_bytes() == original


# --- acceptance: a catalog template override changes the drafted title/description ---


@pytest.mark.integration
def test_catalog_template_override_changes_the_drafted_title(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    override_dir = temp_catalog_root / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "title.txt.j2").write_text("{{ name }} -- Overridden Title\n", encoding="utf-8")

    monkeypatch.chdir(temp_catalog_root)
    result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    text = (temp_catalog_root / PNG_ONLY_PATH).read_text(encoding="utf-8")
    assert 'title = "Pacific Coast Tide Pool -- Overridden Title"' in text


@pytest.mark.integration
def test_catalog_template_override_changes_the_drafted_description(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    override_dir = temp_catalog_root / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "description.txt.j2").write_text("A totally custom pitch.\n", encoding="utf-8")

    monkeypatch.chdir(temp_catalog_root)
    result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    text = (temp_catalog_root / PNG_ONLY_PATH).read_text(encoding="utf-8")
    assert 'description = "A totally custom pitch."' in text


# --- acceptance: the draft names every catalog template override in use (ADR 0015, #121) --


@pytest.mark.integration
def test_a_draft_with_no_catalog_templates_reports_no_overrides(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    assert "Catalog template overrides: 0" in result.output
    assert "templates/listing/" not in result.output


@pytest.mark.integration
def test_a_catalog_title_template_override_is_named_in_the_draft_report(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    override_dir = temp_catalog_root / "templates" / "listing"
    override_dir.mkdir(parents=True)
    (override_dir / "title.txt.j2").write_text("{{ name }} -- Overridden Title\n", encoding="utf-8")

    monkeypatch.chdir(temp_catalog_root)
    result = runner.invoke(app, ["listing", "draft", PNG_ONLY_SLUG])

    assert result.exit_code == 0, result.output
    assert "Catalog template overrides: 1" in result.output
    assert "  templates/listing/title.txt.j2" in result.output
