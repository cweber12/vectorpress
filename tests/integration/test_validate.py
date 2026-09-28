"""``vpress validate`` end to end against a temporary copy of the fixture
catalog (§9, §9.1, §9.2, §35, §36, ADR 0004, ADR 0007, issue #37, issue #39).

Runs against a temporary copy, never the committed fixture directly -- same
reason as ``tests/integration/test_generate.py``: this command writes real
findings JSON files under each asset's ``derived/``, and the fixture catalog
must never contain one.

The fixture's cut-file subjects (``tests/fixtures/catalog/generate_source_pngs.py``,
issue #36, issue #39): ``ochre_sea_star``, ``purple_sea_urchin`` and
``giant_green_anemone`` (real, hand-drawn silhouettes, each one piece), and
``owl_limpet`` (a larger canvas with cleanup noise plus a detached piece
that survives cleanup -- two pieces). ``acorn_barnacle``'s only source is
truncated (issue #27), so its ``cut_svg`` never generates at all -- it
stays ``missing``, never validated.

Issue #39 adds four more subjects, each carrying exactly one area-based
finding kind: ``gumboot_chiton`` (an accidental dot), ``bat_star`` (a tiny
isolated shape -- a sliver), ``keyhole_limpet`` (a very small hole), and
``turban_snail`` (a hole sized to pass at the catalog default but need
review at ``kelp_forest_mini_pack``'s smaller reference-size override --
see ``test_turban_snail_passes_at_the_catalog_default_and_needs_review_at_the_product_override``
below, the extra acceptance criterion reassigned to this issue by
controller ruling).

Issue #40 adds two more subjects, each carrying exactly one shape-based
finding kind: ``nudibranch`` (two lobes joined by a neck narrower than the
narrow-feature width threshold) and ``coralline_algae`` (a finely rippled
outline with far more curve nodes per inch of perimeter than the
excessive-complexity density threshold allows).

Issue #41 adds the remaining five §9 kinds (open path, raster content,
stray object, duplicate geometry, unintended overlap) -- these can only
appear in a hand-edited SVG, so this file also proves the §8 builder's own
tracer never trips any of them on a *generated* fixture cut file
(``test_every_generated_fixture_cut_file_trips_none_of_issue_41s_five_kinds``),
and exercises ``vpress validate --file`` against ``tests/fixtures/findings/``'s
own hand-authored trip SVGs (outside the fixture catalog entirely -- see
that directory's own README for which SVG trips which kind).
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from vectorpress.catalog.findings import findings_path, read_findings_report
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes, sha256_bytes
from vectorpress.cli.app import app
from vectorpress.domain import recipe as recipe_module
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.finding import FindingKind, ValidationOutcome
from vectorpress.domain.recipe import Recipe
from vectorpress.validate.cut_file import validate_cut_file

runner = CliRunner()

#: Rich (via typer's usage-error rendering) wraps a long message across
#: several lines inside a bordered panel, box-drawing characters and all,
#: and -- on a runner that detects color support, e.g. CI -- wraps
#: individual words in ANSI SGR escape sequences too, splitting an option
#: name like ``--reference-size`` across several escape-coded fragments.
#: Stripping both, then collapsing whitespace, before asserting on the
#: message text makes the check robust to exactly where the wrap falls and
#: to whether the runner colors its output -- the same helper (and the same
#: reasoning, issue #26 review fix rounds 1-2) ``tests/unit/test_cli.py``
#: already established for its own usage-error assertions; duplicated here
#: rather than imported, matching this test suite's own convention of a
#: small per-file helper over a cross-file import (e.g. every integration
#: test file's own ``temp_catalog_root`` fixture).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_BOX_DRAWING_RE = re.compile(r"[─-╿]")


def _normalized_output(output: str) -> str:
    return " ".join(_BOX_DRAWING_RE.sub(" ", _ANSI_RE.sub("", output)).split())


FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

# (asset ID, cut-file filename) -- every fixture asset with a decodable
# silhouette source, the same set ``test_generate.py``'s own
# ``FIXTURE_CUT_SVG_OUTPUTS`` validates a cut file exists for (issue #36,
# issue #39).
FIXTURE_CUT_FILES = [
    ("ochre_sea_star", "ochre-sea-star-cut.svg"),
    ("purple_sea_urchin", "purple-sea-urchin-cut.svg"),
    ("giant_green_anemone", "giant-green-anemone-cut.svg"),
    ("owl_limpet", "owl-limpet-cut.svg"),
    ("gumboot_chiton", "gumboot-chiton-cut.svg"),
    ("bat_star", "bat-star-cut.svg"),
    ("keyhole_limpet", "keyhole-limpet-cut.svg"),
    ("turban_snail", "turban-snail-cut.svg"),
    ("nudibranch", "nudibranch-cut.svg"),
    ("coralline_algae", "coralline-algae-cut.svg"),
]

# Subjects whose cut file passes at the catalog default, no findings: the
# three real-art subjects, plus turban_snail, whose one hole is sized to pass
# here but not at a smaller product size (see its dedicated test below).
FIXTURE_PASS_ASSETS = [
    "ochre_sea_star",
    "purple_sea_urchin",
    "giant_green_anemone",
    "turban_snail",
]

# Subjects whose cut file has a genuinely separate second piece -- needs
# review, one disconnected_fragments finding each.
FIXTURE_NEEDS_REVIEW_ASSETS = ["owl_limpet"]

# (asset ID, expected FindingKind value) -- issue #39's three area-finding
# fixtures, each tripping exactly the kind it is named for at the catalog
# default reference size (3.0in). Checked by
# ``test_area_finding_fixtures_need_review_with_their_intended_kind`` below.
FIXTURE_AREA_FINDING_ASSETS = [
    ("gumboot_chiton", "accidental_dot"),
    ("bat_star", "tiny_isolated_shape"),
    ("keyhole_limpet", "small_hole"),
]

# (asset ID, expected FindingKind value) -- issue #40's two shape-finding
# fixtures, each tripping exactly the kind it is named for at the catalog
# default reference size (3.0in). Checked by
# ``test_shape_finding_fixtures_need_review_with_their_intended_kind`` below.
FIXTURE_SHAPE_FINDING_ASSETS = [
    ("nudibranch", "narrow_feature"),
    ("coralline_algae", "excessive_complexity"),
]


@pytest.fixture
def temp_catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(FIXTURE_CATALOG_ROOT, root)
    return root


def _derived_dir(root: Path, asset_id: str) -> Path:
    return root / "assets" / asset_id / DERIVED_DIRNAME


def _make_kelp_forest_member(root: Path, asset_id: str) -> None:
    """Add "Kelp forest" to ``asset_id``'s own ecosystems in this temp
    catalog copy, so ``kelp_forest_mini_pack``'s rule membership resolves
    it as a member -- without touching the product or collection file."""
    toml_path = root / "assets" / asset_id / "asset.toml"
    text = toml_path.read_text(encoding="utf-8")
    start = text.index("ecosystems = [")
    end = text.index("]", start)
    old_line = text[start : end + 1]
    assert "Kelp forest" not in old_line
    new_line = old_line[:-1] + ', "Kelp forest"]'
    toml_path.write_text(text.replace(old_line, new_line, 1), encoding="utf-8")


def _add_new_kelp_forest_asset(root: Path, asset_id: str, display_name: str) -> None:
    """Clone ``bat_star`` (a minimal fixture asset with a real source
    image and a generatable cut_svg) into a new asset whose ecosystems
    match ``kelp_forest_mini_pack``'s rule -- the same technique
    ``tests/integration/test_collection_resolution.py`` uses for the
    collection rule's own analogous acceptance criterion."""
    new_dir = root / "assets" / asset_id
    shutil.copytree(root / "assets" / "bat_star", new_dir)
    toml_path = new_dir / "asset.toml"
    text = toml_path.read_text(encoding="utf-8")
    text = text.replace('display_name = "Bat Star"', f'display_name = "{display_name}"')
    text = text.replace('ecosystems = ["Subtidal", "Rocky reef"]', 'ecosystems = ["kelp forest"]')
    toml_path.write_text(text, encoding="utf-8")


# --- acceptance criterion 1: pass / needs review, with a located finding ------------------


@pytest.mark.integration
def test_validate_all_reports_pass_or_needs_review_for_every_cut_file(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle still fails

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    for asset_id in FIXTURE_PASS_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tpass" in result.stdout
    for asset_id in FIXTURE_NEEDS_REVIEW_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tneeds review" in result.stdout
        assert "disconnected_fragments" in result.stdout


@pytest.mark.integration
def test_owl_limpets_detached_piece_is_flagged_at_its_own_real_bbox(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 1: ``owl_limpet``'s detached piece (issue #36's
    cleanup fixture) survives cleanup and is flagged as a disconnected
    fragment -- the CLI's reported location matches what
    calling the (separately unit-tested) pure ``validate_cut_file`` function
    directly on the same generated bytes produces."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, "owl_limpet") / "owl-limpet-cut.svg"
    expected = validate_cut_file(svg_path.read_bytes(), 3.0, catalog_reference_size_in=3.0)
    assert len(expected.findings) == 1  # sanity: the fixture really has one extra piece
    expected_bbox = expected.findings[0].location
    assert expected_bbox is not None

    result = runner.invoke(app, ["validate", "owl_limpet"])

    assert result.exit_code == 0, result.output
    finding_line = next(
        line
        for line in result.stdout.splitlines()
        if line.strip().startswith("disconnected_fragments")
    )
    assert (
        f"({expected_bbox.min_x},{expected_bbox.min_y})-({expected_bbox.max_x},{expected_bbox.max_y})"
        in (finding_line)
    )


@pytest.mark.integration
def test_vpress_asset_shows_the_findings_result(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])

    ochre = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert ochre.exit_code == 0, ochre.output
    # the review-status column ("needs review", never approved) sits before
    # the findings result ("pass") -- distinct columns, PRD 4.
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tneeds review\tpass" in ochre.stdout

    limpet = runner.invoke(app, ["asset", "owl_limpet"])
    assert limpet.exit_code == 0, limpet.output
    assert "cut_svg\tcurrent\towl-limpet-cut.svg\tneeds review\tneeds review" in limpet.stdout


# --- issue #39: area-based findings (accidental dot, tiny isolated shape, small hole) -----


@pytest.mark.integration
def test_area_finding_fixtures_need_review_with_their_intended_kind(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #39 acceptance criterion 1: on a temp fixture copy, ``vpress
    generate --all`` then ``vpress validate --all`` shows each new subject
    (``gumboot_chiton``, ``bat_star``, ``keyhole_limpet``) as ``needs
    review``, with its intended finding kind and a location -- and with no
    other finding kind mixed in, since each fixture was built to trip
    exactly one (``tests/fixtures/catalog/README.md``)."""
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle still fails

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    for asset_id, expected_kind in FIXTURE_AREA_FINDING_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tneeds review" in result.stdout

        header_index = next(i for i, line in enumerate(lines) if line.startswith(f"{asset_id}\t"))
        finding_line = lines[header_index + 1].strip()
        assert finding_line.startswith(expected_kind), finding_line
        # a location: an "(x,y)-(x,y)" bbox, the same shape every other
        # detector's finding already carries (issue #37).
        assert re.search(r"\(-?[\d.]+,-?[\d.]+\)-\(-?[\d.]+,-?[\d.]+\)", finding_line)
        # exactly one finding line -- no other kind mixed in for this asset.
        next_header_index = next(
            (
                i
                for i in range(header_index + 1, len(lines))
                if "\t" in lines[i] and not lines[i].startswith(" ")
            ),
            len(lines),
        )
        assert next_header_index == header_index + 2


@pytest.mark.integration
def test_shape_finding_fixtures_need_review_with_their_intended_kind(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #40 acceptance criterion 1: on a temp fixture copy, ``vpress
    generate --all`` then ``vpress validate --all`` shows each new subject
    (``nudibranch``, ``coralline_algae``) as ``needs review``, with its
    intended finding kind and a location -- and with no other finding kind
    mixed in, since each fixture was built to trip exactly one
    (``tests/fixtures/catalog/README.md``)."""
    monkeypatch.chdir(temp_catalog_root)
    generate_result = runner.invoke(app, ["generate", "--all"])
    assert generate_result.exit_code == 1, generate_result.output  # acorn_barnacle still fails

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    for asset_id, expected_kind in FIXTURE_SHAPE_FINDING_ASSETS:
        _, filename = next(f for f in FIXTURE_CUT_FILES if f[0] == asset_id)
        assert f"{asset_id}\tcut_svg\t{filename}\tneeds review" in result.stdout

        header_index = next(i for i, line in enumerate(lines) if line.startswith(f"{asset_id}\t"))
        finding_line = lines[header_index + 1].strip()
        assert finding_line.startswith(expected_kind), finding_line
        # a location: an "(x,y)-(x,y)" bbox, the same shape every other
        # detector's finding already carries (issue #37).
        assert re.search(r"\(-?[\d.]+,-?[\d.]+\)-\(-?[\d.]+,-?[\d.]+\)", finding_line)
        # exactly one finding line -- no other kind mixed in for this asset.
        next_header_index = next(
            (
                i
                for i in range(header_index + 1, len(lines))
                if "\t" in lines[i] and not lines[i].startswith(" ")
            ),
            len(lines),
        )
        assert next_header_index == header_index + 2


@pytest.mark.integration
def test_turban_snail_passes_at_the_catalog_default_and_needs_review_at_the_product_override(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """The extra acceptance criterion reassigned to issue #39 by controller
    ruling: a fixture cut file that is ``pass`` at the catalog default
    (3.0in) and ``needs review`` at ``kelp_forest_mini_pack``'s override
    size (1.0in) -- §9.1's own point that a threshold is only meaningful at
    a known output size. ``turban_snail``'s one hole (about 0.069in^2 at
    3in, about 0.008in^2 at 1in) is sized exactly for this, using the real
    small_hole detector, not a synthetic one. Made a ``kelp_forest_mini_pack``
    member for this temp copy only (its ecosystems otherwise deliberately
    match no rule-based fixture collection), so ``--product`` scoped to
    membership still validates it."""
    _make_kelp_forest_member(temp_catalog_root, "turban_snail")
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    at_default = runner.invoke(app, ["validate", "turban_snail"])
    assert at_default.exit_code == 0, at_default.output
    assert "turban_snail\tcut_svg\tturban-snail-cut.svg\tpass" in at_default.stdout

    at_product_size = runner.invoke(
        app, ["validate", "turban_snail", "--product", "kelp_forest_mini_pack"]
    )
    assert at_product_size.exit_code == 0, at_product_size.output
    assert (
        "turban_snail\tcut_svg\tturban-snail-cut.svg\tneeds review\t"
        "(at 1in, product kelp_forest_mini_pack)" in at_product_size.stdout
    )
    assert "small_hole" in at_product_size.stdout

    default_report = read_findings_report(
        _derived_dir(temp_catalog_root, "turban_snail"), "turban-snail-cut.svg"
    )
    assert default_report is not None
    assert default_report.result is ValidationOutcome.PASS

    sized_report = read_findings_report(
        _derived_dir(temp_catalog_root, "turban_snail"), "turban-snail-cut.svg", at_size=1.0
    )
    assert sized_report is not None
    assert sized_report.result is ValidationOutcome.NEEDS_REVIEW
    assert len(sized_report.findings) == 1
    assert sized_report.findings[0].kind is FindingKind.SMALL_HOLE


# --- acceptance criterion 2: findings JSON, nothing written inside the SVG or TOML --------


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_findings_json_records_hash_reference_size_and_thresholds(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, asset_id: str, filename: str
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, asset_id) / filename

    result = runner.invoke(app, ["validate", asset_id])
    assert result.exit_code == 0, result.output

    report = read_findings_report(_derived_dir(temp_catalog_root, asset_id), filename)
    assert report is not None
    assert report.validated_file == filename
    assert report.content_hash == sha256_bytes(svg_path.read_bytes())
    assert report.reference_size_in == 3.0  # the catalog default (§9.1)
    assert isinstance(report.thresholds, dict)


@pytest.mark.integration
def test_excessive_complexity_reference_size_in_follows_the_assets_own_cleanup_size(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 3 (ADR 0010 as amended by ADR 0012):
    ``ochre_sea_star``'s own cleanup size (6.0in, its committed fixture
    setting) is what the findings JSON records for
    ``excessive_complexity_reference_size_in``, at the catalog-default
    validation size and unaffected by a product override either -- every
    other asset here has no cleanup size of its own, so its findings still
    record the catalog default (3.0in). Made a ``kelp_forest_mini_pack``
    member for this temp copy only, so ``--product`` scoped to membership
    still validates it."""
    _make_kelp_forest_member(temp_catalog_root, "ochre_sea_star")
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    default_result = runner.invoke(app, ["validate", "--all"])
    assert default_result.exit_code == 0, default_result.output
    product_result = runner.invoke(
        app, ["validate", "ochre_sea_star", "--product", "kelp_forest_mini_pack"]
    )
    assert product_result.exit_code == 0, product_result.output

    ochre_default = read_findings_report(
        _derived_dir(temp_catalog_root, "ochre_sea_star"), "ochre-sea-star-cut.svg"
    )
    assert ochre_default is not None
    assert ochre_default.reference_size_in == 3.0
    assert ochre_default.excessive_complexity_reference_size_in == 6.0

    ochre_product = read_findings_report(
        _derived_dir(temp_catalog_root, "ochre_sea_star"), "ochre-sea-star-cut.svg", at_size=1.0
    )
    assert ochre_product is not None
    assert ochre_product.reference_size_in == 1.0
    assert ochre_product.excessive_complexity_reference_size_in == 6.0

    for asset_id, filename in FIXTURE_CUT_FILES:
        if asset_id == "ochre_sea_star":
            continue
        other = read_findings_report(_derived_dir(temp_catalog_root, asset_id), filename)
        assert other is not None
        assert other.excessive_complexity_reference_size_in == 3.0


def _assert_at_most_four_decimal_places(value: object, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return
    rounded = float(f"{float(value):.4f}")
    assert value == rounded, f"{where} has more than 4 decimal places: {value!r}"


@pytest.mark.integration
def test_owl_limpets_findings_json_numbers_are_rounded_to_four_decimal_places(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #37 fix round 1: ``owl_limpet``'s detached-piece bbox comes
    from ``svgelements``' own numpy-backed curve sampling, which produced
    raw, many-decimal floats (e.g. ``57.352975173611114``) before this fix --
    exactly the cross-platform risk §36's fixed-precision rule exists to
    prevent. Every number in the persisted findings JSON must round-trip
    through the same 4-decimal-place rule
    :mod:`vectorpress.pipeline.svg_document` already applies to SVG
    coordinate text."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "owl_limpet"])
    assert result.exit_code == 0, result.output

    path = findings_path(_derived_dir(temp_catalog_root, "owl_limpet"), "owl-limpet-cut.svg")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["findings"], "sanity: owl_limpet must have at least one finding to check"

    location = data["findings"][0]["location"]
    assert location["min_x"] == 75.8667
    assert location["min_y"] == 39.678
    assert location["max_x"] == 93.2
    assert location["max_y"] == 57.353
    for key, value in location.items():
        _assert_at_most_four_decimal_places(value, f"location.{key}")


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_every_number_in_a_findings_json_has_at_most_four_decimal_places(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, asset_id: str, filename: str
) -> None:
    """A general property, not just the one fixture that happened to expose
    the bug: every numeric field written to any findings JSON -- location
    coordinates, ``reference_size_in``, any future ``measured_value``/
    ``threshold`` -- follows the same fixed-precision rule (§36, issue #37
    fix round 1)."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", asset_id])
    assert result.exit_code == 0, result.output

    path = findings_path(_derived_dir(temp_catalog_root, asset_id), filename)
    data = json.loads(path.read_text(encoding="utf-8"))

    _assert_at_most_four_decimal_places(data["reference_size_in"], "reference_size_in")
    for finding in data["findings"]:
        _assert_at_most_four_decimal_places(finding["measured_value"], "measured_value")
        _assert_at_most_four_decimal_places(finding["threshold"], "threshold")
        for key, value in finding["location"].items():
            _assert_at_most_four_decimal_places(value, f"location.{key}")


@pytest.mark.integration
def test_nothing_is_written_inside_the_svg_or_any_toml_file(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = (
        _derived_dir(temp_catalog_root, "giant_green_anemone") / "giant-green-anemone-cut.svg"
    )
    svg_before = svg_path.read_bytes()
    toml_paths = sorted(temp_catalog_root.rglob("*.toml"))
    toml_before = {path: path.read_bytes() for path in toml_paths}

    result = runner.invoke(app, ["validate", "--all"])
    assert result.exit_code == 0, result.output

    assert svg_path.read_bytes() == svg_before
    for path in toml_paths:
        assert path.read_bytes() == toml_before[path]
    # ADR 0007: findings are JSON state beside the derivative, never inside it.
    assert findings_path(
        _derived_dir(temp_catalog_root, "giant_green_anemone"), "giant-green-anemone-cut.svg"
    ).is_file()


# --- snapshot: findings JSON locked, byte-identical across platforms (acceptance criterion 3) --


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_findings_json_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", asset_id])
    assert result.exit_code == 0, result.output

    path = findings_path(_derived_dir(temp_catalog_root, asset_id), filename)
    # content_hash is a function of the (already snapshot-locked) SVG bytes,
    # so it is itself already implicitly locked -- but pretty-printed here
    # for a readable diff if the SVG generator, or this issue's own findings
    # shape, ever changes it.
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot


# --- acceptance criterion 4: idempotent, and staleness ------------------------------------


@pytest.mark.integration
def test_second_validate_all_rewrites_nothing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    first = runner.invoke(app, ["validate", "--all"])
    assert first.exit_code == 0, first.output

    before: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.glob("*.findings.json")):
            before[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert before, "validate --all should have written at least one findings report"

    second = runner.invoke(app, ["validate", "--all"])
    assert second.exit_code == 0, second.output

    after: dict[Path, tuple[bytes, int]] = {}
    for derived_dir in sorted(temp_catalog_root.glob("assets/*/derived")):
        for entry in sorted(derived_dir.glob("*.findings.json")):
            after[entry] = (entry.read_bytes(), entry.stat().st_mtime_ns)
    assert after == before


@pytest.mark.integration
def test_hand_editing_the_cut_file_makes_its_findings_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: ``vpress asset`` shows ``findings stale``
    after the validated SVG's bytes change on disk, until ``validate`` runs
    again."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    validated = runner.invoke(app, ["validate", "ochre_sea_star"])
    assert validated.exit_code == 0, validated.output
    before = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tneeds review\tpass" in before.stdout

    svg_path = _derived_dir(temp_catalog_root, "ochre_sea_star") / "ochre-sea-star-cut.svg"
    svg_path.write_text(
        svg_path.read_text(encoding="utf-8").replace("<svg ", '<svg data-hand-edited="1" '),
        encoding="utf-8",
    )

    after = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert after.exit_code == 0, after.output
    # the derivative's own status also follows the bytes (ADR 0004): still
    # "needs review" here since it was never approved.
    assert (
        "cut_svg\tstale (output changed on disk)\tochre-sea-star-cut.svg\t"
        "needs review\tfindings stale" in after.stdout
    )

    revalidated = runner.invoke(app, ["validate", "ochre_sea_star"])
    assert revalidated.exit_code == 0, revalidated.output
    settled = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "findings stale" not in settled.stdout


@pytest.mark.integration
def test_regenerating_with_a_changed_recipe_makes_findings_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: forcing regeneration under a changed recipe
    parameter (the same monkeypatch style ``test_generate.py`` uses) changes
    the cut file's bytes, so its earlier findings report no longer matches."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "giant_green_anemone"])
    before = runner.invoke(app, ["asset", "giant_green_anemone"])
    assert "giant-green-anemone-cut.svg\tneeds review\tpass" in before.stdout

    original = recipe_module.RECIPES[DerivativeType.CUT_SVG]
    changed = Recipe(
        derivative_type=original.derivative_type,
        accepted_roles=original.accepted_roles,
        generator=original.generator,
        parameters={**original.parameters, "curve_tolerance": 0.05},
    )
    monkeypatch.setitem(recipe_module.RECIPES, DerivativeType.CUT_SVG, changed)
    forced = runner.invoke(app, ["generate", "--force", "giant_green_anemone"])
    assert forced.exit_code == 0, forced.output

    after = runner.invoke(app, ["asset", "giant_green_anemone"])

    assert after.exit_code == 0, after.output
    assert "findings stale" in after.stdout


@pytest.mark.integration
def test_reference_size_change_makes_every_findings_report_stale(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Acceptance criterion 4: §9.1's reference size is part of what
    ``findings_currency`` compares -- changing the catalog default is
    detected the same way a changed SVG hash is, even when the cut file
    itself did not change."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "ochre_sea_star"])

    catalog_toml = temp_catalog_root / "catalog.toml"
    catalog_toml.write_text(
        catalog_toml.read_text(encoding="utf-8") + "\nreference_size_in = 6.0\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["asset", "ochre_sea_star"])

    assert result.exit_code == 0, result.output
    assert "findings stale" in result.stdout


# --- acceptance criterion 6/7: missing/impossible cut files, and usage errors -------------


@pytest.mark.integration
def test_an_asset_with_no_cut_file_yet_is_reported_missing_not_crashed_on(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Before generation, every asset's ``cut_svg`` is ``missing`` -- issue
    #37's "An asset whose cut file is missing or impossible is reported as
    such and not validated"."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tcut_svg\tmissing" in result.stdout


@pytest.mark.integration
def test_acorn_barnacles_never_generated_cut_file_is_reported_missing(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``acorn_barnacle``'s only source is truncated (issue #27), so
    ``cut_svg`` never generates; ``validate --all`` still reports it, rather
    than crashing on a missing file, and the run overall still exits 0 (a
    missing cut file is not a validation failure)."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "acorn_barnacle\tcut_svg\tmissing" in result.stdout


@pytest.mark.integration
def test_validate_requires_exactly_one_of_asset_id_or_all(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    neither = runner.invoke(app, ["validate"])
    assert neither.exit_code != 0

    both = runner.invoke(app, ["validate", "ochre_sea_star", "--all"])
    assert both.exit_code != 0


@pytest.mark.integration
def test_validate_all_skips_and_names_an_asset_that_failed_to_load(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    broken_toml = temp_catalog_root / "assets" / "ochre_sea_star" / "asset.toml"
    broken_toml.write_text(
        broken_toml.read_text(encoding="utf-8").replace('subject_category = "Echinoderm"\n', ""),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 0, result.output
    assert "ochre_sea_star\tskipped: failed to load" in result.stdout


@pytest.mark.integration
def test_validate_unknown_asset_id_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["validate", "no_such_asset"])

    assert result.exit_code == 1
    assert "Unknown asset" in result.stdout + result.output


# --- a validation failure is reported on stderr and the run still exits 1 ------------------


@pytest.mark.integration
def test_an_unparseable_cut_file_is_reported_on_stderr_and_the_run_exits_1(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """§35: a hand-edited override that no longer parses is a validation
    failure, named with asset, file and cause -- and, unlike a needs-review
    result, makes the whole run exit non-zero, after every other asset was
    still attempted."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    svg_path = _derived_dir(temp_catalog_root, "ochre_sea_star") / "ochre-sea-star-cut.svg"
    svg_path.write_bytes(b"not valid xml at all <<<")

    result = runner.invoke(app, ["validate", "--all"])

    assert result.exit_code == 1, result.output
    assert "ochre_sea_star" in result.output
    assert "ochre-sea-star-cut.svg" in result.output
    # every other asset was still attempted despite the one failure.
    assert "owl_limpet\tcut_svg\towl-limpet-cut.svg\tneeds review" in result.stdout


# --- --product: reference-size resolution, per-size coexistence (issue #38) --------------


@pytest.mark.integration
def test_validate_with_product_resolves_the_products_reference_size(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``kelp_forest_mini_pack`` overrides the catalog's 3.0 in default down
    to 1.0 in, and ``purple_sea_urchin`` (ecosystems include "Kelp forest")
    is one of its resolved members -- ``--product`` validates it at that
    resolved size, and the report it writes records that size.
    ``purple_sea_urchin`` passes at the catalog default, but its spines are
    too thin to cut at 1 in, so the product-size result needs review."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])  # the catalog-default report, first

    result = runner.invoke(
        app, ["validate", "purple_sea_urchin", "--product", "kelp_forest_mini_pack"]
    )

    assert result.exit_code == 0, result.output
    assert "purple_sea_urchin\tcut_svg\tpurple-sea-urchin-cut.svg\tneeds review" in result.stdout
    assert "narrow_feature" in result.stdout
    assert "product kelp_forest_mini_pack" in result.stdout

    sized_report = read_findings_report(
        _derived_dir(temp_catalog_root, "purple_sea_urchin"),
        "purple-sea-urchin-cut.svg",
        at_size=1.0,
    )
    assert sized_report is not None
    assert sized_report.reference_size_in == 1.0


def _complexity_values(
    root: Path, asset_id: str, filename: str, at_size: float | None
) -> list[float | None]:
    report = read_findings_report(_derived_dir(root, asset_id), filename, at_size=at_size)
    assert report is not None
    return [f.measured_value for f in report.findings if f.kind is FindingKind.EXCESSIVE_COMPLEXITY]


@pytest.mark.integration
def test_excessive_complexity_is_judged_at_the_catalog_size_under_a_product_override(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0010: the cut file is traced at its own cleanup size, so
    ``excessive_complexity`` is judged there even under
    ``kelp_forest_mini_pack``'s 1in override. ``coralline_algae`` reads the
    same ~13.4 nodes/in at both sizes; the real-art subjects, whose density
    used to rise ~3x at 1in, are never flagged for complexity. Their other
    1in findings (the urchin's narrow spines) are still judged at 1in.

    The per-run header names no specific size (ADR 0012): naming the
    catalog default here would be wrong for ``ochre_sea_star``, whose own
    cleanup size is 6in -- see
    ``test_excessive_complexity_message_names_no_size_when_an_asset_has_its_own_cleanup_size``
    below for that case directly.

    ``coralline_algae``, ``ochre_sea_star`` and ``giant_green_anemone`` are
    made ``kelp_forest_mini_pack`` members for this temp copy only (only
    ``purple_sea_urchin`` matches its rule on the committed fixture), so
    ``--product`` scoped to membership still validates all four."""
    _make_kelp_forest_member(temp_catalog_root, "coralline_algae")
    _make_kelp_forest_member(temp_catalog_root, "ochre_sea_star")
    _make_kelp_forest_member(temp_catalog_root, "giant_green_anemone")
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    header = "excessive_complexity is measured at each cut file's own cleanup size"
    at_default = runner.invoke(app, ["validate", "--all"])
    assert at_default.exit_code == 0, at_default.output
    assert header not in at_default.stdout
    at_product = runner.invoke(app, ["validate", "--all", "--product", "kelp_forest_mini_pack"])
    assert at_product.exit_code == 0, at_product.output
    lines = at_product.stdout.splitlines()
    assert lines[0] == header
    assert at_product.stdout.count(header) == 1

    coralline_default = _complexity_values(
        temp_catalog_root, "coralline_algae", "coralline-algae-cut.svg", None
    )
    coralline_product = _complexity_values(
        temp_catalog_root, "coralline_algae", "coralline-algae-cut.svg", 1.0
    )
    assert len(coralline_default) == 1
    assert coralline_product == coralline_default
    assert coralline_default[0] == pytest.approx(13.4, abs=0.05)

    for asset_id, filename in [
        ("ochre_sea_star", "ochre-sea-star-cut.svg"),
        ("giant_green_anemone", "giant-green-anemone-cut.svg"),
        ("purple_sea_urchin", "purple-sea-urchin-cut.svg"),
    ]:
        assert _complexity_values(temp_catalog_root, asset_id, filename, None) == []
        assert _complexity_values(temp_catalog_root, asset_id, filename, 1.0) == []

    urchin = read_findings_report(
        _derived_dir(temp_catalog_root, "purple_sea_urchin"),
        "purple-sea-urchin-cut.svg",
        at_size=1.0,
    )
    assert urchin is not None
    assert urchin.reference_size_in == 1.0
    assert urchin.excessive_complexity_reference_size_in == 3.0
    assert FindingKind.NARROW_FEATURE in {f.kind for f in urchin.findings}


@pytest.mark.integration
def test_excessive_complexity_message_names_no_size_when_an_asset_has_its_own_cleanup_size(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """ADR 0010 as amended by ADR 0012: ``ochre_sea_star``'s own cleanup
    size is 6in, not the 3in catalog default -- naming "3in" in the
    per-run header would be wrong for it, so the header names the rule
    instead of a number. Made a ``kelp_forest_mini_pack`` member for this
    temp copy only, so ``--product`` scoped to membership still validates
    it."""
    _make_kelp_forest_member(temp_catalog_root, "ochre_sea_star")
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(
        app, ["validate", "ochre_sea_star", "--product", "kelp_forest_mini_pack"]
    )

    assert result.exit_code == 0, result.output
    assert "3in catalog size" not in result.stdout
    assert "excessive_complexity is measured at each cut file's own cleanup size" in result.stdout


@pytest.mark.integration
def test_validate_with_product_never_touches_the_catalog_default_report(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #38's coexistence: the catalog-default report -- already
    written by a plain ``validate --all`` -- stays byte-unchanged and still
    current after a ``--product`` validation at a different size."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    runner.invoke(app, ["validate", "--all"])
    derived_dir = _derived_dir(temp_catalog_root, "purple_sea_urchin")
    default_path = findings_path(derived_dir, "purple-sea-urchin-cut.svg")
    default_bytes_before = default_path.read_bytes()

    result = runner.invoke(
        app, ["validate", "purple_sea_urchin", "--product", "kelp_forest_mini_pack"]
    )

    assert result.exit_code == 0, result.output
    assert default_path.read_bytes() == default_bytes_before
    asset_result = runner.invoke(app, ["asset", "purple_sea_urchin"])
    assert "cut_svg\tcurrent\tpurple-sea-urchin-cut.svg\tneeds review\tpass" in asset_result.stdout
    assert "findings stale" not in asset_result.stdout


@pytest.mark.integration
def test_validate_product_scopes_to_exactly_the_products_resolved_members(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``kelp_forest_mini_pack``'s rule (ecosystems include "Kelp forest")
    resolves to exactly ``purple_sea_urchin`` among the committed fixture
    assets -- the same membership ``vpress product kelp_forest_mini_pack``
    lists. Bare ``--product`` validates that one cut file and no other."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--product", "kelp_forest_mini_pack"])

    assert result.exit_code == 0, result.output
    assert "purple_sea_urchin\tcut_svg\tpurple-sea-urchin-cut.svg" in result.stdout
    for asset_id, filename in FIXTURE_CUT_FILES:
        if asset_id == "purple_sea_urchin":
            continue
        assert filename not in result.stdout


@pytest.mark.integration
def test_validate_product_with_all_adds_nothing_beyond_its_members(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``--all`` given alongside ``--product`` is a harmless no-op: the
    product's own resolved membership decides the scope either way, so the
    two runs report the same assets."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    bare = runner.invoke(app, ["validate", "--product", "kelp_forest_mini_pack"])
    with_all = runner.invoke(app, ["validate", "--all", "--product", "kelp_forest_mini_pack"])

    assert bare.exit_code == 0, bare.output
    assert with_all.exit_code == 0, with_all.output
    assert bare.stdout == with_all.stdout


@pytest.mark.integration
def test_unknown_product_slug_is_an_actionable_error_and_writes_no_toml(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])
    toml_paths = sorted(temp_catalog_root.rglob("*.toml"))
    toml_before = {path: path.read_bytes() for path in toml_paths}

    result = runner.invoke(app, ["validate", "--all", "--product", "not_a_real_product"])

    assert result.exit_code == 1
    assert "Unknown product" in result.stdout + result.output
    for path in toml_paths:
        assert path.read_bytes() == toml_before[path]


@pytest.mark.integration
def test_a_product_that_failed_to_load_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    product_toml = temp_catalog_root / "products" / "kelp_forest_mini_pack.toml"
    product_toml.write_text(
        product_toml.read_text(encoding="utf-8").replace('formats = ["svg"]', 'formats = ["webp"]'),
        encoding="utf-8",
    )
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(
        app, ["validate", "purple_sea_urchin", "--product", "kelp_forest_mini_pack"]
    )

    assert result.exit_code == 1
    assert "kelp_forest_mini_pack" in (result.stdout + result.output)


# --- --product: scoped to resolved membership (§9, §13, ADR 0012) -----------------------


@pytest.mark.integration
def test_validate_product_reports_a_newly_matching_asset_without_editing_the_product(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """A new asset whose ecosystems match ``kelp_forest_mini_pack``'s rule
    appears in the next ``--product`` run without editing the product --
    membership is live (``build.product_resolution.resolve_product``), the
    same acceptance criterion ``test_collection_resolution.py`` proves for a
    bare collection."""
    product_path = temp_catalog_root / "products" / "kelp_forest_mini_pack.toml"
    product_toml_before = product_path.read_text(encoding="utf-8")
    _add_new_kelp_forest_asset(temp_catalog_root, "sunflower_star", "Sunflower Star")
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--product", "kelp_forest_mini_pack"])

    assert result.exit_code == 0, result.output
    assert "sunflower_star\tcut_svg\tsunflower-star-cut.svg" in result.stdout
    assert product_path.read_text(encoding="utf-8") == product_toml_before


@pytest.mark.integration
def test_validate_product_with_no_cut_svg_reports_nothing_to_validate(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``pacific_coast_tide_pool_png_only`` includes only ``transparent_png``
    -- no cut_svg to validate at all -- so the run says so and exits 0
    without touching any asset."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--product", "pacific_coast_tide_pool_png_only"])

    assert result.exit_code == 0, result.output
    assert "nothing to validate" in result.stdout
    for _, filename in FIXTURE_CUT_FILES:
        assert filename not in result.stdout


@pytest.mark.integration
def test_validate_product_combined_with_a_non_member_asset_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """``ochre_sea_star``'s ecosystems do not include "Kelp forest" on the
    committed fixture, so it is not one of ``kelp_forest_mini_pack``'s
    resolved members -- combining it with ``--product`` is refused rather
    than silently validated at the product's size."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(
        app, ["validate", "ochre_sea_star", "--product", "kelp_forest_mini_pack"]
    )

    assert result.exit_code != 0
    combined = result.stdout + result.output
    assert "ochre_sea_star" in combined
    assert "kelp_forest_mini_pack" in combined
    assert "not a member" in combined


@pytest.mark.integration
def test_validate_product_refuses_when_membership_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Unresolved membership refuses the run the same way ``vpress build``
    refuses a build (``build.product_build.build_product``'s
    ``REFUSED_REFERENCE_PROBLEMS``): an unknown ``collection_slug`` is a
    reference problem, not a load failure, and validation never starts."""
    monkeypatch.chdir(temp_catalog_root)
    product_path = temp_catalog_root / "products" / "pacific_coast_tide_pool_png_only.toml"
    before = 'collection_slug = "pacific_coast_tide_pool"'
    text = product_path.read_text(encoding="utf-8")
    assert before in text
    product_path.write_text(
        text.replace(before, 'collection_slug = "no_such_collection"'), encoding="utf-8"
    )
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--product", "pacific_coast_tide_pool_png_only"])

    assert result.exit_code == 1
    combined = result.stdout + result.output
    assert "Reference problems" in combined
    assert "no_such_collection" in combined


@pytest.mark.integration
def test_validate_product_scoped_output_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, snapshot: SnapshotAssertion
) -> None:
    """Locks the scoped ``--product`` report's shape: the header note, the
    one resolved member's line, and nothing for any other fixture asset."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", "--product", "kelp_forest_mini_pack"])

    assert result.exit_code == 0, result.output
    assert _normalized_output(result.stdout) == snapshot


# --- snapshot: product-size findings JSON locked, byte-identical across platforms --------


@pytest.mark.integration
@pytest.mark.parametrize("asset_id,filename", FIXTURE_CUT_FILES)
def test_product_size_findings_json_is_locked_by_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    snapshot: SnapshotAssertion,
    asset_id: str,
    filename: str,
) -> None:
    # Only purple_sea_urchin actually matches kelp_forest_mini_pack's rule
    # on the committed fixture; every other subject is made a member for
    # this temp copy only, so this parametrization can lock every fixture
    # cut file's product-size findings JSON.
    if asset_id != "purple_sea_urchin":
        _make_kelp_forest_member(temp_catalog_root, asset_id)
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    result = runner.invoke(app, ["validate", asset_id, "--product", "kelp_forest_mini_pack"])
    assert result.exit_code == 0, result.output

    path = findings_path(_derived_dir(temp_catalog_root, asset_id), filename, at_size=1.0)
    assert json.loads(path.read_text(encoding="utf-8")) == snapshot


@pytest.mark.integration
def test_generate_still_never_validates(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #37: ``vpress generate`` is unchanged and does not validate --
    no findings report exists until ``validate`` itself runs."""
    monkeypatch.chdir(temp_catalog_root)

    result = runner.invoke(app, ["generate", "--all"])

    assert result.exit_code == 1, result.output  # acorn_barnacle still fails to generate
    for asset_id, filename in FIXTURE_CUT_FILES:
        assert not findings_path(_derived_dir(temp_catalog_root, asset_id), filename).exists()
    asset_result = runner.invoke(app, ["asset", "ochre_sea_star"])
    assert "cut_svg\tcurrent\tochre-sea-star-cut.svg\tneeds review\tnot validated" in (
        asset_result.stdout
    )


# --- issue #41: none of the five new kinds ever trips on a generated cut file --------------

FINDINGS_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "findings"

#: Every §9 kind only a hand-edited SVG can trip (issue #41's own "can only
#: ever appear in a hand-edited override"): the §8 builder's own tracer
#: always emits closed, filled, non-overlapping, non-duplicated paths with
#: no raster content and no stray elements.
ISSUE_41_KINDS = {
    FindingKind.OPEN_PATH,
    FindingKind.RASTER_CONTENT,
    FindingKind.STRAY_OBJECT,
    FindingKind.DUPLICATE_GEOMETRY,
    FindingKind.OVERLAP,
}


@pytest.mark.integration
def test_every_generated_fixture_cut_file_trips_none_of_issue_41s_five_kinds(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    """Issue #41 acceptance criterion 3: proven against every fixture
    asset's own real, generated cut file (not a hand-written stand-in) --
    the §8 builder rules these five out by construction, and this keeps it
    true."""
    monkeypatch.chdir(temp_catalog_root)
    runner.invoke(app, ["generate", "--all"])

    for asset_id, filename in FIXTURE_CUT_FILES:
        svg_bytes = read_derivative_bytes(_derived_dir(temp_catalog_root, asset_id), filename)
        assert svg_bytes is not None, asset_id
        result = validate_cut_file(svg_bytes, 3.0, catalog_reference_size_in=3.0)
        tripped = {finding.kind for finding in result.findings} & ISSUE_41_KINDS
        assert not tripped, (asset_id, tripped)


# --- issue #41: vpress validate --file --------------------------------------------------------

#: (trip SVG name, the one §9 kind it trips) -- ``tests/fixtures/findings/
#: README.md`` documents each in full.
TRIP_SVG_KINDS = [
    ("open_path", FindingKind.OPEN_PATH),
    ("raster_content", FindingKind.RASTER_CONTENT),
    ("stray_object", FindingKind.STRAY_OBJECT),
    ("duplicate_geometry", FindingKind.DUPLICATE_GEOMETRY),
    ("overlap", FindingKind.OVERLAP),
]


def _all_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def temp_findings_dir(tmp_path: Path) -> Path:
    """A throwaway copy of ``tests/fixtures/findings/`` (issue #41 review
    fix round 1): a ``--file`` "writes nothing" test must check the trip
    SVG's own directory, not only the catalog root -- a findings report
    written *beside the validated file itself* (exactly what catalog
    validation does, so the likeliest possible regression) would slip past
    a check that only snapshots ``temp_catalog_root``. Validating straight
    out of the committed ``tests/fixtures/findings/`` directory would also
    risk writing into the real repo checkout if such a regression ever
    happened -- this copy is never that directory."""
    dest = tmp_path / "findings"
    shutil.copytree(FINDINGS_FIXTURES_DIR, dest)
    return dest


@pytest.mark.integration
@pytest.mark.parametrize("name,expected_kind", TRIP_SVG_KINDS)
def test_validate_file_reports_exactly_the_trip_svgs_own_kind(
    monkeypatch: pytest.MonkeyPatch,
    temp_catalog_root: Path,
    temp_findings_dir: Path,
    name: str,
    expected_kind: FindingKind,
) -> None:
    """Issue #41's own acceptance criterion: ``vpress validate --file
    <trip svg> --reference-size 3`` reports exactly that kind with a
    location and ``needs review``, and writes nothing anywhere -- neither
    in the catalog nor beside the trip SVG itself (issue #41 review fix
    round 1)."""
    monkeypatch.chdir(temp_catalog_root)
    svg_path = temp_findings_dir / f"{name}.svg"
    before_catalog = _all_files(temp_catalog_root)
    before_findings_dir = _all_files(temp_findings_dir)

    result = runner.invoke(app, ["validate", "--file", str(svg_path), "--reference-size", "3"])

    assert result.exit_code == 0, result.output
    assert "needs review" in result.stdout
    finding_lines = [line for line in result.stdout.splitlines() if line.startswith("  ")]
    assert len(finding_lines) == 1
    assert finding_lines[0].startswith(f"  {expected_kind.value}\t")
    assert re.search(r"\(-?[\d.]+,-?[\d.]+\)-\(-?[\d.]+,-?[\d.]+\)|\(no bbox\)", finding_lines[0])
    assert _all_files(temp_catalog_root) == before_catalog  # writes nothing in the catalog
    assert _all_files(temp_findings_dir) == before_findings_dir  # nor beside the trip SVG


@pytest.mark.integration
def test_validate_file_on_the_clean_svg_passes(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, temp_findings_dir: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    svg_path = temp_findings_dir / "clean.svg"
    before_catalog = _all_files(temp_catalog_root)
    before_findings_dir = _all_files(temp_findings_dir)

    result = runner.invoke(app, ["validate", "--file", str(svg_path), "--reference-size", "3"])

    assert result.exit_code == 0, result.output
    assert "\tpass" in result.stdout
    assert "needs review" not in result.stdout
    assert _all_files(temp_catalog_root) == before_catalog
    assert _all_files(temp_findings_dir) == before_findings_dir


@pytest.mark.integration
def test_validate_file_defaults_the_reference_size_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path, temp_findings_dir: Path
) -> None:
    """Inside a catalog, ``--file`` falls back to the catalog default
    reference size (3.0in here) when ``--reference-size`` is not given."""
    monkeypatch.chdir(temp_catalog_root)
    svg_path = temp_findings_dir / "open_path.svg"

    result = runner.invoke(app, ["validate", "--file", str(svg_path)])

    assert result.exit_code == 0, result.output
    assert "open_path" in result.stdout


@pytest.mark.integration
def test_validate_file_outside_any_catalog_requires_reference_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no catalog.toml anywhere above this
    svg_path = FINDINGS_FIXTURES_DIR / "clean.svg"

    result = runner.invoke(app, ["validate", "--file", str(svg_path)])

    assert result.exit_code != 0
    assert "--reference-size" in _normalized_output(result.output)


@pytest.mark.integration
def test_validate_file_outside_any_catalog_works_when_reference_size_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, temp_findings_dir: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    svg_path = temp_findings_dir / "clean.svg"

    result = runner.invoke(app, ["validate", "--file", str(svg_path), "--reference-size", "3"])

    assert result.exit_code == 0, result.output
    assert "\tpass" in result.stdout


@pytest.mark.integration
def test_validate_file_on_an_unparseable_svg_exits_1_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    bad_svg = tmp_path / "bad.svg"
    bad_svg.write_bytes(b"not an svg document at all")
    before = _all_files(tmp_path)

    result = runner.invoke(app, ["validate", "--file", str(bad_svg), "--reference-size", "3"])

    assert result.exit_code == 1
    assert "bad.svg" in result.output
    assert _all_files(tmp_path) == before


@pytest.mark.integration
def test_validate_file_on_a_missing_file_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["validate", "--file", str(tmp_path / "nope.svg"), "--reference-size", "3"]
    )

    assert result.exit_code == 1
    assert "no such file" in result.output


@pytest.mark.integration
def test_validate_file_rejects_combination_with_asset_id(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    svg_path = FINDINGS_FIXTURES_DIR / "clean.svg"

    result = runner.invoke(
        app, ["validate", "ochre_sea_star", "--file", str(svg_path), "--reference-size", "3"]
    )

    assert result.exit_code != 0


@pytest.mark.integration
def test_validate_file_rejects_all_assets_option(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    svg_path = FINDINGS_FIXTURES_DIR / "clean.svg"

    result = runner.invoke(
        app, ["validate", "--all", "--file", str(svg_path), "--reference-size", "3"]
    )

    assert result.exit_code != 0


@pytest.mark.integration
def test_validate_file_rejects_product_option(
    monkeypatch: pytest.MonkeyPatch, temp_catalog_root: Path
) -> None:
    monkeypatch.chdir(temp_catalog_root)
    svg_path = FINDINGS_FIXTURES_DIR / "clean.svg"

    result = runner.invoke(
        app,
        [
            "validate",
            "--file",
            str(svg_path),
            "--reference-size",
            "3",
            "--product",
            "kelp_forest_mini_pack",
        ],
    )

    assert result.exit_code != 0
