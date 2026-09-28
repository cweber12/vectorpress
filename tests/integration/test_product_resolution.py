"""``vpress product`` end to end, against a temporary copy of the fixture
catalog (§7, §10, §10.1, §13, §28, ADR 0008, ADR 0011).

Runs against a temporary copy, never the committed fixture directly: these
tests generate and approve real derivatives, writing files under each
asset's ``derived/`` (``tests/fixtures/catalog/README.md``).

``pacific_coast_tide_pool_standard_pack`` and ``pacific_coast_tide_pool_png_only``
share the identical ``pacific_coast_tide_pool`` membership (three explicit
members) but declare different ``derivative_types``, so the same underlying
assets resolve to a different eligible/excluded breakdown depending which
product asks (§10: "the same asset ships PNG-only while its cut file is
still being fixed").
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

PACIFIC_COAST_MEMBERS = ("ochre_sea_star", "giant_green_anemone", "purple_sea_urchin")

#: Same normalisation CLAUDE.md prescribes for CLI output assertions: CI
#: runners detect color support and split words across ANSI escape codes,
#: and Rich box-drawing shows up in usage-error panels -- neither should be
#: able to break a full-output snapshot (see
#: tests/integration/test_validate.py's own ``_normalized_output``).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_DRAWING_RE = re.compile(r"[─-╿]")


def _normalized_output(output: str) -> str:
    return " ".join(_BOX_DRAWING_RE.sub(" ", _ANSI_RE.sub("", output)).split("\n"))


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _section(output: str, header: str) -> str:
    """Every line from a line starting with ``header`` up to (not
    including) the next un-indented line -- the same slicing
    ``test_attention.py``'s own ``_section`` uses."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header))
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    return "\n".join(lines[start:end])


# --- acceptance criterion 1: excluded with one reason per unapproved type -----------


@pytest.mark.integration
def test_standard_pack_lists_its_three_members_excluded_after_generate_all(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)

    result = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])

    assert result.exit_code == 0, result.output
    assert "Members: 3" in result.stdout
    assert "Eligible: 0" in result.stdout
    assert "Excluded: 3" in result.stdout
    expected_blocked = (
        "    blocked: cut_svg: needs review; silhouette_svg: needs review; "
        "transparent_png: needs review"
    )
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"  {asset_id}\texplicit\texcluded" in result.stdout
    assert result.stdout.count(expected_blocked) == 3
    # every included type is CURRENT right after generate --all, so nothing
    # is missing for these three members.
    assert "Missing required derivatives: 0" in result.stdout


# --- acceptance criterion 2: PNG-only eligible while the standard pack stays excluded --


@pytest.mark.integration
def test_png_only_product_is_eligible_once_transparent_png_is_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    approve_result = runner.invoke(app, ["approve", "--all", "--type", "transparent_png"])
    assert approve_result.exit_code == 0, approve_result.output

    png_result = runner.invoke(app, ["product", "pacific_coast_tide_pool_png_only"])
    assert png_result.exit_code == 0, png_result.output
    assert "Eligible: 3" in png_result.stdout
    assert "Excluded: 0" in png_result.stdout
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"{asset_id}\texplicit\teligible" in png_result.stdout

    standard_result = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])
    assert standard_result.exit_code == 0, standard_result.output
    assert "Eligible: 0" in standard_result.stdout
    assert "Excluded: 3" in standard_result.stdout
    for asset_id in PACIFIC_COAST_MEMBERS:
        assert f"{asset_id}\texplicit\texcluded" in standard_result.stdout
        assert "cut_svg: needs review" in standard_result.stdout


# --- acceptance criterion 3: a rights-blocked asset stays excluded even fully approved --


def _add_rights_blocked_test_product(root: Path) -> None:
    """A temp-only product (not part of the committed fixture) whose sole
    member is ``gumboot_chiton``, the fixture's permanently rights-blocked
    asset (``rights_status = "do_not_publish"``)."""
    text = (
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership]\n"
        'asset_ids = ["gumboot_chiton"]\n'
    )
    (root / "products" / "gumboot_chiton_test_product.toml").write_text(text, encoding="utf-8")


@pytest.mark.integration
def test_a_rights_blocked_asset_stays_excluded_even_fully_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _add_rights_blocked_test_product(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "gumboot_chiton"])
    approve_result = runner.invoke(app, ["approve", "gumboot_chiton", "--all-types"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["product", "gumboot_chiton_test_product"])

    assert result.exit_code == 0, result.output
    assert "Eligible: 0" in result.stdout
    assert "Excluded: 1" in result.stdout
    assert "gumboot_chiton\texplicit\texcluded" in result.stdout
    assert "rights status: do not publish" in result.stdout
    # every existing derivative is approved: no per-derivative reason left.
    member_section = _section(result.stdout, "  gumboot_chiton")
    assert "needs review" not in member_section
    assert "missing" not in member_section


# --- acceptance criterion 5 (§26): an ai_generated member with empty ------
# --- licensing notes stays excluded even fully approved --------------------


def _add_ai_generated_test_product(root: Path) -> None:
    """A temp-only product (not part of the committed fixture) whose sole
    member is ``owl_limpet``, the fixture's ``ai_generated`` asset, with its
    ``licensing_notes`` blanked in this same temp copy -- mirroring
    ``_add_rights_blocked_test_product`` above for the new §26 block."""
    path = root / "assets" / "owl_limpet" / "asset.toml"
    text = path.read_text(encoding="utf-8")
    assert 'rights_status = "ai_generated"\n' in text
    before = (
        'licensing_notes = "Generated with Midjourney (v6) under its commercial-use terms '
        'for paid subscribers; the ai_generated rights-status fixture (§26)."\n'
    )
    assert before in text
    path.write_text(text.replace(before, 'licensing_notes = ""\n'), encoding="utf-8")

    product_text = (
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership]\n"
        'asset_ids = ["owl_limpet"]\n'
    )
    (root / "products" / "owl_limpet_test_product.toml").write_text(product_text, encoding="utf-8")


@pytest.mark.integration
def test_an_ai_generated_member_with_empty_notes_stays_excluded_even_fully_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _add_ai_generated_test_product(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "owl_limpet"])
    approve_result = runner.invoke(app, ["approve", "owl_limpet", "--all-types"])
    assert approve_result.exit_code == 0, approve_result.output

    result = runner.invoke(app, ["product", "owl_limpet_test_product"])

    assert result.exit_code == 0, result.output
    assert "Eligible: 0" in result.stdout
    assert "Excluded: 1" in result.stdout
    assert "owl_limpet\texplicit\texcluded" in result.stdout
    assert (
        "licensing notes: must name the AI tool and its terms (rights status: ai generated)"
        in result.stdout
    )
    # every existing derivative is approved: no per-derivative reason left.
    member_section = _section(result.stdout, "  owl_limpet")
    assert "needs review" not in member_section
    assert "missing" not in member_section


def _set_accuracy_status_issue_found(root: Path, asset_id: str) -> None:
    """Turn one fixture asset's accuracy status blocking (§10.1,
    ``AccuracyStatus.ISSUE_FOUND``), the asset-level counterpart to
    ``_add_rights_blocked_test_product``'s rights block -- on a real
    ``pacific_coast_tide_pool`` member, so both products already over that
    collection (different ``derivative_types``) both see it excluded."""
    path = root / "assets" / asset_id / "asset.toml"
    text = path.read_text(encoding="utf-8")
    assert 'accuracy_status = "reviewed"\n' in text
    path.write_text(
        text.replace('accuracy_status = "reviewed"\n', 'accuracy_status = "issue_found"\n'),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_an_accuracy_blocked_member_stays_excluded_in_both_products_even_fully_approved(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§10.1's asset-level accuracy block, distinct from the rights-status
    one above: ``purple_sea_urchin`` is a member of both
    ``pacific_coast_tide_pool_standard_pack`` and
    ``pacific_coast_tide_pool_png_only`` (different derivative types, same
    underlying collection) -- an accuracy-blocked member stays excluded in
    both, even with every one of its derivatives approved."""
    _set_accuracy_status_issue_found(temp_catalog_root, "purple_sea_urchin")
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle fails (§35)
    approve_result = runner.invoke(app, ["approve", "--all"])
    assert approve_result.exit_code == 0, approve_result.output

    for product_slug in (
        "pacific_coast_tide_pool_standard_pack",
        "pacific_coast_tide_pool_png_only",
    ):
        result = runner.invoke(app, ["product", product_slug])

        assert result.exit_code == 0, result.output
        assert "purple_sea_urchin\texplicit\texcluded" in result.stdout
        assert "accuracy status: issue found" in result.stdout
        # every existing derivative is approved: no per-derivative reason left.
        member_section = _section(result.stdout, "  purple_sea_urchin")
        assert "needs review" not in member_section
        assert "missing" not in member_section
        # the other two members are unaffected.
        assert "ochre_sea_star\texplicit\teligible" in result.stdout
        assert "giant_green_anemone\texplicit\teligible" in result.stdout


# --- acceptance criterion 4: inline rule membership is live -------------------------


def _add_kelp_forest_asset(root: Path, asset_id: str, ecosystems_toml_value: str) -> None:
    source_dir = root / "assets" / "bat_star"
    new_dir = root / "assets" / asset_id
    shutil.copytree(source_dir, new_dir)
    toml_path = new_dir / "asset.toml"
    text = toml_path.read_text(encoding="utf-8")
    assert 'ecosystems = ["Subtidal", "Rocky reef"]' in text
    text = text.replace('ecosystems = ["Subtidal", "Rocky reef"]', ecosystems_toml_value)
    toml_path.write_text(text, encoding="utf-8")


@pytest.mark.integration
def test_kelp_forest_mini_pack_gains_a_new_matching_asset_without_editing_the_product(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    product_toml_before = (temp_catalog_root / "products" / "kelp_forest_mini_pack.toml").read_text(
        encoding="utf-8"
    )
    _add_kelp_forest_asset(temp_catalog_root, "sunflower_star", 'ecosystems = ["kelp forest"]')
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["product", "kelp_forest_mini_pack"])

    assert result.exit_code == 0, result.output
    assert "sunflower_star\trule" in result.stdout
    assert "purple_sea_urchin\trule" in result.stdout
    assert "Members: 2" in result.stdout
    product_toml_after = (temp_catalog_root / "products" / "kelp_forest_mini_pack.toml").read_text(
        encoding="utf-8"
    )
    assert product_toml_after == product_toml_before


# --- acceptance criterion 5: unknown slug, failed-to-load, unknown collection_slug ---


@pytest.mark.integration
def test_an_unknown_product_slug_exits_1_with_its_own_message(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["product", "not_a_real_product"])

    assert result.exit_code == 1
    assert "Unknown product: 'not_a_real_product'" in result.output


@pytest.mark.integration
def test_a_product_that_failed_to_load_exits_1_with_a_distinct_message(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    path = temp_catalog_root / "products" / "pacific_coast_tide_pool_standard_pack.toml"
    text = path.read_text(encoding="utf-8")
    # Anchored on the leading newline so this only matches the top-level
    # ``price`` field, not ``[listing]``'s own ``suggested_price``.
    assert "\nprice = 12.00\n" in text
    path.write_text(text.replace("\nprice = 12.00\n", "\n"), encoding="utf-8")
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])

    assert result.exit_code == 1
    assert "Unknown product" not in result.output
    assert str(Path("products") / "pacific_coast_tide_pool_standard_pack.toml") in result.output
    assert "price" in result.output


@pytest.mark.integration
def test_an_unknown_collection_slug_is_a_reference_problem_with_no_members(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    path = temp_catalog_root / "products" / "pacific_coast_tide_pool_standard_pack.toml"
    text = path.read_text(encoding="utf-8")
    assert 'collection_slug = "pacific_coast_tide_pool"\n' in text
    path.write_text(
        text.replace(
            'collection_slug = "pacific_coast_tide_pool"\n',
            'collection_slug = "not_a_real_collection"\n',
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])

    assert result.exit_code == 0, result.output
    assert "Members: 0" in result.stdout
    assert "Reference problems: 1" in result.stdout
    assert "collection_slug" in result.stdout
    assert "not_a_real_collection" in result.stdout


# --- acceptance criterion 6: snapshot-locked output for both fixture products --------


@pytest.mark.integration
def test_standard_pack_output_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])

    assert result.exit_code == 0, result.output
    assert _normalized_output(result.stdout) == snapshot


@pytest.mark.integration
def test_png_only_output_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["product", "pacific_coast_tide_pool_png_only"])

    assert result.exit_code == 0, result.output
    assert _normalized_output(result.stdout) == snapshot


# --- an empty membership is valid: zero members, zero counts, shown as such ---------


@pytest.mark.integration
def test_an_empty_membership_is_shown_as_zero_members_and_zero_counts(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    text = (
        'derivative_types = ["cut_svg"]\n'
        'formats = ["svg"]\n'
        'tier = "individual"\n'
        "price = 1.00\n\n"
        "[membership.rule]\n"
        'field = "ecosystems"\n'
        'values = ["Nowhere at all"]\n'
    )
    (temp_catalog_root / "products" / "empty_test_product.toml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["product", "empty_test_product"])

    assert result.exit_code == 0, result.output
    assert "Members: 0" in result.stdout
    assert "Eligible: 0" in result.stdout
    assert "Excluded: 0" in result.stdout
    assert "Missing required derivatives: 0" in result.stdout


# --- a product's own reference problem shows wherever reference problems show today --


def _break_the_standard_packs_collection_slug(root: Path) -> None:
    path = root / "products" / "pacific_coast_tide_pool_standard_pack.toml"
    text = path.read_text(encoding="utf-8")
    assert 'collection_slug = "pacific_coast_tide_pool"\n' in text
    path.write_text(
        text.replace(
            'collection_slug = "pacific_coast_tide_pool"\n',
            'collection_slug = "not_a_real_collection"\n',
        ),
        encoding="utf-8",
    )


@pytest.mark.integration
def test_status_shows_a_products_reference_problem_without_changing_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _break_the_standard_packs_collection_slug(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "Metadata problems: none" in result.stdout
    assert "Reference problems: 1" in result.stdout
    assert "collection_slug" in result.stdout
    assert "not_a_real_collection" in result.stdout


@pytest.mark.integration
def test_attention_folds_a_products_reference_problem_into_missing_metadata(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    _break_the_standard_packs_collection_slug(temp_catalog_root)
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["attention"])

    assert result.exit_code == 0, result.output
    assert "Missing metadata: 1" in result.stdout
    assert "collection_slug" in result.stdout
    assert "not_a_real_collection" in result.stdout


# --- ineligible_members header (§10) -----------------------------------------


@pytest.mark.integration
def test_product_header_names_its_ineligible_members_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'vpress product' names the product's own ineligible_members mode in
    its header (§10) -- the default 'refuse', and kelp_forest_mini_pack's
    committed 'exclude' -- since a build's refuse-vs-exclude behavior on an
    ineligible member depends on it."""
    monkeypatch.chdir(FIXTURE_CATALOG_ROOT)

    standard_pack = runner.invoke(app, ["product", "pacific_coast_tide_pool_standard_pack"])
    mini_pack = runner.invoke(app, ["product", "kelp_forest_mini_pack"])

    assert standard_pack.exit_code == 0, standard_pack.output
    assert mini_pack.exit_code == 0, mini_pack.output
    assert "Ineligible members: refuse" in standard_pack.stdout
    assert "Ineligible members: exclude" in mini_pack.stdout
