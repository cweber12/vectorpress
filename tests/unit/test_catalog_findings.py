"""catalog.findings: tool-owned findings reports (ADR 0004, ADR 0005, ADR
0007, CONTEXT.md "Findings", issue #37).

Only this module reads or writes a findings report (ADR 0006's "catalog...
the only layer touching catalog files") -- read/write round trip, atomic and
idempotent writes, and currency, exercised directly against hand-built
:class:`~vectorpress.domain.finding.Finding` values (``tests/integration/
test_validate.py`` exercises the whole ``vpress validate`` path end to
end)."""

import json
from pathlib import Path

from vectorpress.catalog.findings import (
    FindingsCurrencyState,
    FindingsReport,
    findings_currency,
    findings_path,
    read_findings_report,
    write_findings_report,
)
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.finding import (
    BoundingBox,
    Finding,
    FindingClassification,
    FindingKind,
    PathReference,
    ValidationOutcome,
)

SVG_BYTES = b"<svg>fake but stable bytes</svg>"


def _finding() -> Finding:
    return Finding(
        kind=FindingKind.DISCONNECTED_FRAGMENTS,
        classification=FindingClassification.NEEDS_REVIEW,
        message="disconnected fragment",
        location=BoundingBox(min_x=1.0, min_y=2.0, max_x=3.0, max_y=4.0),
        path_reference=PathReference(element_index=0, subpath_index=1, id="p1"),
    )


def _report(**overrides: object) -> FindingsReport:
    defaults: dict[str, object] = {
        "validated_file": "ochre-sea-star-cut.svg",
        "content_hash": sha256_bytes(SVG_BYTES),
        "reference_size_in": 3.0,
        "thresholds": {},
        "result": ValidationOutcome.NEEDS_REVIEW,
        "findings": (_finding(),),
    }
    defaults.update(overrides)
    return FindingsReport(**defaults)  # type: ignore[arg-type]


# --- read/write round trip -------------------------------------------------------------


def test_write_then_read_round_trips_the_report(tmp_path: Path) -> None:
    report = _report()

    write_findings_report(tmp_path, report)
    reread = read_findings_report(tmp_path, report.validated_file)

    assert reread == report


def test_read_findings_report_returns_none_when_never_validated(tmp_path: Path) -> None:
    assert read_findings_report(tmp_path, "does-not-exist-cut.svg") is None


def test_findings_report_lives_beside_the_derivative_never_inside_it(tmp_path: Path) -> None:
    report = _report()

    write_findings_report(tmp_path, report)

    path = findings_path(tmp_path, report.validated_file)
    assert path != tmp_path / report.validated_file
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["content_hash"] == report.content_hash
    assert data["reference_size_in"] == 3.0


def test_a_pass_report_with_no_findings_round_trips_too(tmp_path: Path) -> None:
    report = _report(result=ValidationOutcome.PASS, findings=())

    write_findings_report(tmp_path, report)
    reread = read_findings_report(tmp_path, report.validated_file)

    assert reread == report
    assert reread is not None
    assert reread.findings == ()


# --- atomic, idempotent writes ----------------------------------------------------------


def test_write_findings_report_does_not_rewrite_when_the_payload_already_matches(
    tmp_path: Path,
) -> None:
    """§36-style idempotence, matching
    ``catalog.provenance.write_derivative``'s own: a second ``vpress
    validate`` with nothing changed rewrites nothing."""
    report = _report()
    write_findings_report(tmp_path, report)
    path = findings_path(tmp_path, report.validated_file)
    mtime_before = path.stat().st_mtime_ns
    bytes_before = path.read_bytes()

    write_findings_report(tmp_path, report)

    assert path.stat().st_mtime_ns == mtime_before
    assert path.read_bytes() == bytes_before


def test_write_findings_report_rewrites_when_the_result_changes(tmp_path: Path) -> None:
    report = _report()
    write_findings_report(tmp_path, report)
    path = findings_path(tmp_path, report.validated_file)

    changed = _report(result=ValidationOutcome.PASS, findings=())
    write_findings_report(tmp_path, changed)

    assert json.loads(path.read_text(encoding="utf-8"))["result"] == "pass"


def test_write_findings_report_creates_the_derived_directory(tmp_path: Path) -> None:
    report = _report()
    derived_dir = tmp_path / "derived"

    write_findings_report(derived_dir, report)

    assert findings_path(derived_dir, report.validated_file).is_file()


def test_write_findings_report_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    report = _report()

    write_findings_report(tmp_path, report)

    leftover = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftover == []


# --- currency (ADR 0004, issue #37) ------------------------------------------------------


def test_currency_is_not_validated_when_no_report_exists(tmp_path: Path) -> None:
    currency = findings_currency(tmp_path, "ochre-sea-star-cut.svg", SVG_BYTES, 3.0, {})

    assert currency.state is FindingsCurrencyState.NOT_VALIDATED
    assert currency.result is None


def test_currency_is_current_right_after_validation(tmp_path: Path) -> None:
    report = _report()
    write_findings_report(tmp_path, report)

    currency = findings_currency(tmp_path, report.validated_file, SVG_BYTES, 3.0, {})

    assert currency.state is FindingsCurrencyState.CURRENT
    assert currency.result is ValidationOutcome.NEEDS_REVIEW


def test_currency_is_stale_when_the_svg_bytes_changed(tmp_path: Path) -> None:
    """Regenerating the cut file (or hand-editing it on disk) changes its
    content hash, so its findings report no longer matches (issue #37's "A
    findings report is current iff its recorded SVG hash ... matches")."""
    report = _report()
    write_findings_report(tmp_path, report)

    currency = findings_currency(
        tmp_path, report.validated_file, b"<svg>different bytes now</svg>", 3.0, {}
    )

    assert currency.state is FindingsCurrencyState.STALE
    assert currency.result is None


def test_currency_is_stale_when_the_reference_size_changed(tmp_path: Path) -> None:
    report = _report()
    write_findings_report(tmp_path, report)

    currency = findings_currency(tmp_path, report.validated_file, SVG_BYTES, 6.0, {})

    assert currency.state is FindingsCurrencyState.STALE


def test_currency_is_stale_when_the_thresholds_changed(tmp_path: Path) -> None:
    report = _report(thresholds={"island_min_area_in2": 0.01})
    write_findings_report(tmp_path, report)

    currency = findings_currency(
        tmp_path, report.validated_file, SVG_BYTES, 3.0, {"island_min_area_in2": 0.5}
    )

    assert currency.state is FindingsCurrencyState.STALE
