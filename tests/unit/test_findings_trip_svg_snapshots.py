"""Findings JSON snapshots for every issue #41 trip SVG (§9, §9.1, ADR
0007, issue #41's own acceptance criterion: "Snapshot tests lock the
findings JSON output of every trip SVG, byte-identical on ubuntu and
windows").

``tests/fixtures/findings/`` holds hand-authored SVGs that live outside
the fixture catalog (unlike the catalog's own subject assets): each trips
exactly one of the five §9 kinds only a hand-edited SVG can trip (open
path, raster content, stray object, duplicate geometry, unintended
overlap), plus a clean SVG that passes -- see ``tests/fixtures/findings/
README.md`` for the mapping. A trip SVG is never written into any catalog
and never passes through ``vpress validate``'s own file-write path, so this
snapshots :func:`~vectorpress.catalog.findings.finding_to_dict`'s own JSON
shape directly, the same shape a catalog asset's own persisted findings
report uses (:mod:`vectorpress.catalog.findings`)."""

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from vectorpress.catalog.findings import finding_to_dict
from vectorpress.domain.finding import ValidationOutcome
from vectorpress.validate.cut_file import validate_cut_file

REFERENCE_SIZE_IN = 3.0

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "findings"

TRIP_SVGS = [
    "open_path",
    "raster_content",
    "stray_object",
    "duplicate_geometry",
    "overlap",
    "clean",
]


@pytest.mark.parametrize("name", TRIP_SVGS)
def test_trip_svg_findings_json_is_locked_by_snapshot(
    snapshot: SnapshotAssertion, name: str
) -> None:
    svg_bytes = (FIXTURES_DIR / f"{name}.svg").read_bytes()

    result = validate_cut_file(
        svg_bytes, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN
    )

    payload = {
        "result": result.outcome.value,
        "findings": [finding_to_dict(finding) for finding in result.findings],
    }
    assert payload == snapshot


def test_clean_svg_passes_with_no_findings() -> None:
    svg_bytes = (FIXTURES_DIR / "clean.svg").read_bytes()

    result = validate_cut_file(
        svg_bytes, REFERENCE_SIZE_IN, catalog_reference_size_in=REFERENCE_SIZE_IN
    )

    assert result.outcome is ValidationOutcome.PASS
    assert result.findings == ()
