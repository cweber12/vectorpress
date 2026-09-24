"""The ``open_path`` detector (§9, ADR 0007, issue #41).

A closed, filled path is what the §8 builder always produces (deterministic
geometric cleanup from the silhouette role) -- a subpath missing its own
closing ``Z`` (and not otherwise ending back on its own start point), or a
``<path>`` element with no fill at all, can only ever appear in a
hand-edited override (ADR 0007's "the override workflow is the expected
path"): this issue's own proof that validation still runs on any SVG
derivative, not only a generated one (§9's own scope bullet 5).

Runs over *every* subpath in the document (:mod:`vectorpress.validate.
_svg_geometry.parse_subpaths`), independent of the piece/hole containment
grouping :mod:`vectorpress.validate.cut_file`'s other detectors use -- a
subpath that fails to close, or whose own element paints no fill, cannot be
reliably classified as a piece or a hole to begin with, so this never
competes with :mod:`vectorpress.validate.accidental_dot`, :mod:`vectorpress.
validate.tiny_isolated_shape` or :mod:`vectorpress.validate.
disconnected_fragments`'s own "one kind per shape" exclusivity
(:class:`~vectorpress.domain.finding.FindingKind`'s own note) -- the same
independent-axis relationship :mod:`vectorpress.validate.narrow_feature` and
:mod:`vectorpress.validate.excessive_complexity` already have.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.validate._svg_geometry import Subpath

_KIND = FindingKind.OPEN_PATH
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(subpaths: list[Subpath]) -> list[Finding]:
    """One finding per subpath that is not closed, or whose own ``<path>``
    element paints no fill (§9), located at that subpath's own bounding
    box.

    Findings are returned in a fixed, deterministic order -- by path
    reference (element index, then subpath index) -- matching every other
    detector in this package (issue #37's own ordering rule).
    """
    findings: list[Finding] = []
    for subpath in subpaths:
        if subpath.closed and subpath.has_fill:
            continue
        reason = (
            "is not closed (no Z, and its end is not its start)"
            if not subpath.closed
            else "has no fill, where a closed filled path is expected"
        )
        findings.append(
            Finding(
                kind=_KIND,
                classification=_CLASSIFICATION,
                message=(
                    f"open path: path element {subpath.element_index}, "
                    f"subpath {subpath.subpath_index} {reason}"
                ),
                location=subpath.bbox,
                path_reference=PathReference(
                    element_index=subpath.element_index,
                    subpath_index=subpath.subpath_index,
                    id=subpath.element_id,
                ),
            )
        )

    findings.sort(
        key=lambda finding: (
            finding.path_reference.element_index,
            finding.path_reference.subpath_index,
        )
    )
    return findings
