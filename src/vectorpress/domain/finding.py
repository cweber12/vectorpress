"""Findings: structured cut-file quality problems, located, and classified
into pass or needs review (CONTEXT.md "Findings", §9, §9.2, ADR 0007, issue
#37).

No I/O here (ADR 0006): a finding is fixed domain data produced by a pure
function in :mod:`vectorpress.validate` from an effective derivative's bytes
plus a reference size, and persisted by :mod:`vectorpress.catalog.findings` --
this module owns none of that, only the shape.

A findings result is **not** the derivative's Status (CONTEXT.md "Status"):
nothing here writes it, and :class:`ValidationOutcome` is a different axis
entirely -- Status is a human review decision, tracked separately (PRD 4);
``pass``/``needs_review`` is a mechanical roll-up of what was found.
"""

from dataclasses import dataclass
from enum import StrEnum


class FindingKind(StrEnum):
    """Every §9 cut-file quality problem this tool names, in the order §9
    lists them, whether or not a detector for it has landed yet (issue #37
    detects only :attr:`DISCONNECTED_FRAGMENTS`; later issues add the rest to
    this same fixed list -- a finding's ``kind`` is always one of these
    eleven, never an ad hoc string)."""

    OPEN_PATH = "open_path"
    TINY_ISOLATED_SHAPE = "tiny_isolated_shape"
    ACCIDENTAL_DOT = "accidental_dot"
    SMALL_HOLE = "small_hole"
    NARROW_FEATURE = "narrow_feature"
    EXCESSIVE_COMPLEXITY = "excessive_complexity"
    STRAY_OBJECT = "stray_object"
    DUPLICATE_GEOMETRY = "duplicate_geometry"
    OVERLAP = "overlap"
    DISCONNECTED_FRAGMENTS = "disconnected_fragments"
    RASTER_CONTENT = "raster_content"

    # One kind per shape (issue #39): a cut piece (one candidate cut-file
    # subpath, :class:`~vectorpress.validate._svg_geometry.Piece`) is
    # reported as at most one of :attr:`ACCIDENTAL_DOT`,
    # :attr:`TINY_ISOLATED_SHAPE` or :attr:`DISCONNECTED_FRAGMENTS`, never
    # more than one -- these three are the only kinds that classify a
    # *piece* rather than a hole or the document as a whole, and
    # :mod:`vectorpress.validate.cut_file` checks a piece against them in
    # that fixed order (dot, then tiny shape, then disconnected fragment),
    # removing whichever piece a detector already claimed before offering
    # what remains to the next one. :attr:`SMALL_HOLE` classifies holes, an
    # independent axis that never competes with a piece's own kind.


class FindingClassification(StrEnum):
    """How one :class:`FindingKind` rolls up into a file's pass/needs-review
    result (§9.2). Only one value exists today -- every §9 kind this tool
    names is a genuine manufacturability problem -- but :data:`CLASSIFICATION`
    stays a table, not a hardcoded rule, so a future kind could classify
    differently without changing how the result is computed."""

    NEEDS_REVIEW = "needs_review"


#: The one fixed table mapping every :class:`FindingKind` to its
#: :class:`FindingClassification` (issue #37's "one fixed table mapping each
#: kind to its classification"). Covers all eleven kinds up front, not just
#: the ones with a detector yet, so the table -- and
#: :func:`vectorpress.domain.finding` completeness -- never has to change
#: shape as later issues add detectors.
CLASSIFICATION: dict[FindingKind, FindingClassification] = {
    kind: FindingClassification.NEEDS_REVIEW for kind in FindingKind
}


@dataclass(frozen=True)
class BoundingBox:
    """A finding's location, in the SVG's own user units (the same
    coordinate space its ``viewBox`` and path data are already expressed in,
    issue #37: "so it can be drawn over the SVG")."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float


@dataclass(frozen=True)
class PathReference:
    """Where in the SVG document a finding's geometry came from, so an
    editor can navigate to it (issue #37): the ``<path>`` element's index in
    document order, the offending subpath's index within that element, and
    that element's ``id`` attribute when it has one (``None`` otherwise)."""

    element_index: int
    subpath_index: int
    id: str | None = None


@dataclass(frozen=True)
class Finding:
    """One located, classified cut-file quality problem (§9, issue #37).

    ``measured_value`` and ``threshold`` are set together for a finding kind
    whose detection compares a measurement against a threshold; both are
    ``None`` for a kind with no such threshold (:attr:`FindingKind.
    DISCONNECTED_FRAGMENTS`: "more than one piece" has no size threshold to
    record)."""

    kind: FindingKind
    classification: FindingClassification
    message: str
    location: BoundingBox
    path_reference: PathReference
    measured_value: float | None = None
    threshold: float | None = None


class ValidationOutcome(StrEnum):
    """A cut file's §9.2 roll-up: ``pass`` or ``needs_review``."""

    PASS = "pass"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class ValidationResult:
    """Every finding from validating one effective derivative, plus the
    §9.2 roll-up computed from them (issue #37).

    ``findings`` is already in the deterministic order the caller (:mod:`
    vectorpress.validate`) produced -- this class does not re-sort."""

    findings: tuple[Finding, ...]

    @property
    def outcome(self) -> ValidationOutcome:
        """``NEEDS_REVIEW`` iff at least one finding classifies as needing
        review (§9.2's "A file is needs_review iff it has at least one
        finding the table classifies as needing review"); ``PASS``
        otherwise, including when there are no findings at all."""
        needs_review = any(
            CLASSIFICATION[finding.kind] is FindingClassification.NEEDS_REVIEW
            for finding in self.findings
        )
        return ValidationOutcome.NEEDS_REVIEW if needs_review else ValidationOutcome.PASS
