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


# --- per-size coexistence (§9.1, ADR 0008, issue #38) -----------------------------------


def test_findings_path_with_no_size_is_unchanged_from_before_issue_38(tmp_path: Path) -> None:
    """The catalog-default path must stay byte-identical where it is (issue
    #38): calling ``findings_path`` with no ``at_size`` at all keeps
    returning exactly the same bare path it always has."""
    bare = findings_path(tmp_path, "ochre-sea-star-cut.svg")

    assert bare == tmp_path / "ochre-sea-star-cut.svg.findings.json"


def test_findings_path_at_a_size_differs_from_the_bare_path(tmp_path: Path) -> None:
    bare = findings_path(tmp_path, "ochre-sea-star-cut.svg")
    sized = findings_path(tmp_path, "ochre-sea-star-cut.svg", at_size=1.5)

    assert sized != bare


def test_findings_path_at_different_sizes_differ_from_each_other(tmp_path: Path) -> None:
    at_one = findings_path(tmp_path, "ochre-sea-star-cut.svg", at_size=1.0)
    at_two = findings_path(tmp_path, "ochre-sea-star-cut.svg", at_size=2.0)

    assert at_one != at_two


def test_write_then_read_round_trips_a_sized_report(tmp_path: Path) -> None:
    report = _report(reference_size_in=1.5)

    write_findings_report(tmp_path, report, at_size=1.5)
    reread = read_findings_report(tmp_path, report.validated_file, at_size=1.5)

    assert reread == report
    # and it never touched the bare, catalog-default path.
    assert read_findings_report(tmp_path, report.validated_file) is None


def test_a_sized_report_coexists_with_the_bare_report_without_overwriting_it(
    tmp_path: Path,
) -> None:
    default_report = _report(reference_size_in=3.0, result=ValidationOutcome.PASS, findings=())
    sized_report = _report(reference_size_in=1.0)

    write_findings_report(tmp_path, default_report)
    write_findings_report(tmp_path, sized_report, at_size=1.0)

    assert read_findings_report(tmp_path, default_report.validated_file) == default_report
    assert read_findings_report(tmp_path, sized_report.validated_file, at_size=1.0) == sized_report

    # the reverse order holds too: rewriting the bare report afterwards
    # leaves the sized one untouched.
    write_findings_report(tmp_path, default_report)
    assert read_findings_report(tmp_path, sized_report.validated_file, at_size=1.0) == sized_report
