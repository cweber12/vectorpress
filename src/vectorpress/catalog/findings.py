"""Tool-owned findings reports for validated derivatives (ADR 0004, ADR
0005, ADR 0007, ADR 0008, CONTEXT.md "Findings", §9, §9.1, §9.2, issue #37,
issue #38).

Findings are produced by pure functions in :mod:`vectorpress.validate` from
an effective derivative's own bytes plus a reference size, and persisted
here as JSON state beside the file they validate, under ``derived/`` --
never inside the SVG itself, never in hand-authored TOML (ADR 0005's
"tool-owned: JSON", ADR 0007). Only ``catalog`` touches catalog files (ADR
0006): this module owns every byte crossing the boundary between disk and a
findings report, mirroring :mod:`vectorpress.catalog.provenance`'s own split
for generated derivatives -- deliberately its own small module rather than
folded into ``provenance``, since a findings report is not provenance (it
records what a *check* found, not what *generated* the file, and validates
an override's bytes exactly the same way, ADR 0007).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from vectorpress.catalog.atomic_write import atomic_write_bytes
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.finding import (
    BoundingBox,
    Finding,
    FindingClassification,
    FindingKind,
    PathReference,
    ValidationOutcome,
)
from vectorpress.domain.numeric_format import format_number, round_number

#: A findings report for ``<name>`` is a plain-JSON file named
#: ``<name>.findings.json`` beside it, so it never collides with the
#: derivative's own filename or its ``.provenance.json`` record (mirrors
#: :mod:`vectorpress.catalog.provenance`'s own ``_PROVENANCE_SUFFIX``).
_FINDINGS_SUFFIX = ".findings.json"

#: A findings report computed at some *other* reference size than the one
#: ``findings_path`` above names (issue #38's "per-size coexistence") lives
#: beside it too, keyed by that size, so validating a product's override
#: never overwrites or invalidates the catalog-default report and the
#: reverse holds too -- "a findings report is per (cut file, reference
#: size)". ``format_number`` (the same fixed-precision, trailing-zero-
#: trimmed rule every number this tool writes to a file already follows,
#: §36) keeps the token stable and byte-identical across platforms.
_SIZED_FINDINGS_INFIX = ".findings.at-"
_SIZED_FINDINGS_SUFFIX = "in.json"

#: An override's findings report (ADR 0007's "validated the same way as
#: generated files") is keyed by this infix instead, so it coexists
#: beside the generated derivative's own report rather than colliding with
#: or overwriting it -- the effective derivative's findings currency follows
#: the override's bytes, never the generated file's.
_OVERRIDE_FINDINGS_INFIX = ".override"


def findings_path(
    derived_dir: Path,
    validated_filename: str,
    *,
    at_size: float | None = None,
    is_override: bool = False,
) -> Path:
    """Where one derivative's findings report lives, beside it.

    ``is_override`` (§6.8) selects the override's own coexisting report
    instead of the generated derivative's -- the effective derivative is
    validated the same way either way, only the path differs, so the two
    never collide and neither invalidates the other. ``at_size`` is ``None``
    for the one report every existing caller already reads and writes --
    ``<name>.findings.json`` (``<name>.override.findings.json`` when
    ``is_override``), unchanged for the non-override case (issue #38's "the
    catalog-default report must stay byte-identical where it is"). Given a
    reference size, the path is keyed
    by it instead (``<name>.findings.at-<size>in.json``), so a report
    computed at any other size than the caller's usual one coexists beside
    it rather than colliding with or overwriting it; both keys combine when
    both apply.
    """
    stem = f"{validated_filename}{_OVERRIDE_FINDINGS_INFIX}" if is_override else validated_filename
    if at_size is None:
        return derived_dir / f"{stem}{_FINDINGS_SUFFIX}"
    size_token = format_number(at_size)
    return derived_dir / f"{stem}{_SIZED_FINDINGS_INFIX}{size_token}{_SIZED_FINDINGS_SUFFIX}"


@dataclass(frozen=True)
class FindingsReport:
    """One derivative's tool-owned findings report (issue #37).

    ``validated_file`` and ``content_hash`` identify the effective
    derivative's bytes this report was computed from -- content-addressed,
    like :class:`~vectorpress.catalog.provenance.Provenance` (ADR 0004):
    currency is a hash comparison, never a timestamp. ``reference_size_in``
    and ``thresholds`` are recorded verbatim (§9.1's "the reference size
    used should be recorded with the validation result") so a later change
    to either is detectable the same way a recipe change is for provenance.

    ``excessive_complexity_reference_size_in`` is the cut file's own
    **cleanup size** that kind alone was measured at (ADR 0010 as amended by
    ADR 0012) -- the asset's own ``[derivatives.cut_svg] reference_size_in``
    when it set one, else the catalog default; the same value at every
    reference size this cut file is ever validated at, catalog default or
    product override alike.
    """

    validated_file: str
    content_hash: str
    reference_size_in: float
    excessive_complexity_reference_size_in: float
    thresholds: dict[str, float]
    result: ValidationOutcome
    findings: tuple[Finding, ...]


def _bounding_box_to_dict(location: BoundingBox) -> dict[str, object]:
    return {
        "min_x": round_number(location.min_x),
        "min_y": round_number(location.min_y),
        "max_x": round_number(location.max_x),
        "max_y": round_number(location.max_y),
    }


def _path_reference_to_dict(reference: PathReference) -> dict[str, object]:
    return {
        "element_index": reference.element_index,
        "subpath_index": reference.subpath_index,
        "id": reference.id,
    }


def finding_to_dict(finding: Finding) -> dict[str, object]:
    """``finding`` as a JSON-ready dict, every number rounded to
    :data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES` (issue #37 fix
    round 1's "every number written to findings" rule) -- a second,
    belt-and-suspenders application of :func:`~vectorpress.domain.
    numeric_format.round_number` at the one point every finding must pass
    through to become JSON, on top of :mod:`vectorpress.validate.
    _svg_geometry`'s own rounding at the point a location is first computed:
    idempotent on an already-rounded number, so this holds the invariant
    even for a future detector kind that forgets to round its own
    ``measured_value``/``threshold`` before building a :class:`~vectorpress.
    domain.finding.Finding`.

    ``related_path_reference`` (issue #41, :attr:`FindingKind.OVERLAP` only)
    is written as a key only when it is set, and ``location`` as JSON
    ``null`` when there is no geometry to draw -- every finding kind that
    predates issue #41 always sets both, so this stays byte-identical to
    what it wrote before issue #41 for every one of those (locked by
    ``tests/integration/test_validate.py``'s own findings-JSON snapshots).

    Public (no leading underscore, issue #41) so a trip SVG validated
    through ``vpress validate --file`` -- never written to any catalog, so
    never passing through :class:`FindingsReport`/:func:`write_findings_report`
    at all -- can still be snapshotted in exactly the same JSON shape a
    catalog asset's own findings report uses (``tests/unit/
    test_validate_open_path.py`` and its four sibling test modules)."""
    data: dict[str, object] = {
        "kind": finding.kind.value,
        "classification": finding.classification.value,
        "message": finding.message,
        "location": (None if finding.location is None else _bounding_box_to_dict(finding.location)),
        "path_reference": _path_reference_to_dict(finding.path_reference),
        "measured_value": (
            None if finding.measured_value is None else round_number(finding.measured_value)
        ),
        "threshold": None if finding.threshold is None else round_number(finding.threshold),
    }
    if finding.related_path_reference is not None:
        data["related_path_reference"] = _path_reference_to_dict(finding.related_path_reference)
    return data


def _bounding_box_from_dict(data: Mapping[str, object]) -> BoundingBox:
    return BoundingBox(
        min_x=float(data["min_x"]),  # type: ignore[arg-type]
        min_y=float(data["min_y"]),  # type: ignore[arg-type]
        max_x=float(data["max_x"]),  # type: ignore[arg-type]
        max_y=float(data["max_y"]),  # type: ignore[arg-type]
    )


def _path_reference_from_dict(data: Mapping[str, object]) -> PathReference:
    element_id = data["id"]
    assert element_id is None or isinstance(element_id, str)
    subpath_index_raw = data["subpath_index"]
    subpath_index = None if subpath_index_raw is None else int(subpath_index_raw)  # type: ignore[arg-type]
    return PathReference(
        element_index=int(data["element_index"]),  # type: ignore[arg-type]
        subpath_index=subpath_index,
        id=element_id,
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _finding_from_dict(data: Mapping[str, object]) -> Finding:
    location = data["location"]
    path_reference = data["path_reference"]
    assert location is None or isinstance(location, dict)
    assert isinstance(path_reference, dict)
    related_path_reference_data = data.get("related_path_reference")
    assert related_path_reference_data is None or isinstance(related_path_reference_data, dict)
    return Finding(
        kind=FindingKind(data["kind"]),  # type: ignore[arg-type]
        classification=FindingClassification(data["classification"]),  # type: ignore[arg-type]
        message=str(data["message"]),
        location=(
            None
            if location is None
            else _bounding_box_from_dict(cast("Mapping[str, object]", location))
        ),
        path_reference=_path_reference_from_dict(cast("Mapping[str, object]", path_reference)),
        measured_value=_optional_float(data.get("measured_value")),
        threshold=_optional_float(data.get("threshold")),
        related_path_reference=(
            None
            if related_path_reference_data is None
            else _path_reference_from_dict(
                cast("Mapping[str, object]", related_path_reference_data)
            )
        ),
    )


def _report_payload(report: FindingsReport) -> bytes:
    """``report`` serialized deterministically: sorted object keys, so byte
    equality (the idempotence check below, and cross-OS snapshot tests) does
    not depend on incidental dict insertion order -- the same rule
    :func:`vectorpress.catalog.provenance.write_derivative`'s provenance
    payload follows."""
    payload = {
        "validated_file": report.validated_file,
        "content_hash": report.content_hash,
        "reference_size_in": report.reference_size_in,
        "excessive_complexity_reference_size_in": report.excessive_complexity_reference_size_in,
        "thresholds": report.thresholds,
        "result": report.result.value,
        "findings": [finding_to_dict(finding) for finding in report.findings],
    }
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def read_findings_report(
    derived_dir: Path,
    validated_filename: str,
    *,
    at_size: float | None = None,
    is_override: bool = False,
) -> FindingsReport | None:
    """The findings report for one derivative, or ``None`` if it has never
    been validated at that path (issue #38's ``at_size``, ``is_override``
    per §6.8, see :func:`findings_path`)."""
    path = findings_path(derived_dir, validated_filename, at_size=at_size, is_override=is_override)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return FindingsReport(
        validated_file=data["validated_file"],
        content_hash=data["content_hash"],
        reference_size_in=data["reference_size_in"],
        # A report written before ADR 0010 lacks the key; every such report
        # measured complexity at its own reference size.
        excessive_complexity_reference_size_in=data.get(
            "excessive_complexity_reference_size_in", data["reference_size_in"]
        ),
        thresholds=data["thresholds"],
        result=ValidationOutcome(data["result"]),
        findings=tuple(_finding_from_dict(f) for f in data["findings"]),
    )


def write_findings_report(
    derived_dir: Path,
    report: FindingsReport,
    *,
    at_size: float | None = None,
    is_override: bool = False,
) -> None:
    """Persist one findings report (§35, §36, issue #37).

    Idempotent like :func:`vectorpress.catalog.provenance.write_derivative`:
    when the payload about to be written already matches what is on disk
    byte-for-byte, the file is left untouched -- a second ``vpress validate``
    with nothing changed rewrites nothing.

    ``at_size`` selects which coexisting path this report is written to
    (issue #38, see :func:`findings_path`) -- the caller already knows
    whether this report is "the" catalog-default one or a size-keyed one;
    this never re-derives that from ``report.reference_size_in`` itself,
    since a product's override can equal the catalog default too.
    ``is_override`` (§6.8) selects the override's own coexisting path
    instead of the generated derivative's -- the caller already knows which
    file it validated."""
    path = findings_path(
        derived_dir, report.validated_file, at_size=at_size, is_override=is_override
    )
    payload = _report_payload(report)
    if not (path.is_file() and path.read_bytes() == payload):
        atomic_write_bytes(path, payload)


class FindingsCurrencyState(StrEnum):
    """Whether an on-disk findings report still reflects the derivative it
    was computed from (ADR 0004, issue #37): ``NOT_VALIDATED`` (no report
    exists yet), ``CURRENT`` (its recorded content hash, reference size and
    thresholds all still match), or ``STALE`` (a report exists but at least
    one of those has since changed -- the derivative was regenerated, hand-
    edited on disk, the catalog's reference size changed, or a threshold
    changed)."""

    NOT_VALIDATED = "not_validated"
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True)
class FindingsCurrency:
    """One derivative's findings currency (issue #37). ``result`` is set
    exactly when ``state`` is ``CURRENT`` -- the up-to-date pass/needs-review
    roll-up a caller can show without re-running validation."""

    state: FindingsCurrencyState
    result: ValidationOutcome | None


def findings_currency(
    derived_dir: Path,
    validated_filename: str,
    svg_bytes: bytes,
    reference_size_in: float,
    thresholds: Mapping[str, float],
    *,
    is_override: bool = False,
) -> FindingsCurrency:
    """A findings report is current iff its recorded content hash,
    reference size and thresholds all match ``svg_bytes``,
    ``reference_size_in`` and ``thresholds`` as given (issue #37's "A
    findings report is current iff its recorded SVG hash, reference size and
    threshold identity all match"). ``is_override`` (§6.8) checks the
    override's own coexisting report instead of the generated derivative's."""
    report = read_findings_report(derived_dir, validated_filename, is_override=is_override)
    if report is None:
        return FindingsCurrency(FindingsCurrencyState.NOT_VALIDATED, None)

    if (
        report.content_hash != sha256_bytes(svg_bytes)
        or report.reference_size_in != reference_size_in
        or report.thresholds != dict(thresholds)
    ):
        return FindingsCurrency(FindingsCurrencyState.STALE, None)

    return FindingsCurrency(FindingsCurrencyState.CURRENT, report.result)
