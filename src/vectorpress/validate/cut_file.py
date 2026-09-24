"""``vectorpress.validate.cut_file``: the cut-file findings-report entry
point (§9, §9.1, ADR 0006, ADR 0007, issue #37).

A pure function from an effective derivative's own SVG bytes plus a
reference size to a :class:`~vectorpress.domain.finding.ValidationResult`
(ADR 0006's "validate: pure functions from geometry to findings") -- takes
bytes, not :mod:`vectorpress.pipeline`'s in-memory ``Subpath``, so a
hand-edited override (PRD 4) is checked by exactly the same code a generated
cut file is. This module (and everything under ``vectorpress.validate``)
never imports :mod:`vectorpress.pipeline`, and :mod:`vectorpress.pipeline.
generate` never calls this: ``pipeline`` and ``validate`` are independent
sibling layers (CLAUDE.md, ``pyproject.toml``'s import-linter contract).
"""

from vectorpress.domain.finding import Finding, ValidationResult
from vectorpress.validate import disconnected_fragments
from vectorpress.validate._svg_geometry import parse_cut_file

#: Every physical-unit threshold this issue's detectors use, keyed by name,
#: recorded verbatim with every findings report (issue #37's "the thresholds
#: used"). Empty for now: :mod:`vectorpress.validate.disconnected_fragments`
#: has no size threshold of its own -- "more than one piece" is a count, not
#: a measurement against a physical size. Later issues populate this as
#: their own detectors land (a small hole's minimum area, a narrow feature's
#: minimum width, and so on).
THRESHOLDS: dict[str, float] = {}


def validate_cut_file(svg_bytes: bytes, reference_size_in: float) -> ValidationResult:
    """Validate one cut file's bytes against every landed §9 detector, at
    ``reference_size_in`` physical inches (§9.1) -- issue #37 lands only
    :func:`vectorpress.validate.disconnected_fragments.detect`; later issues
    add the rest of §9's list here, each contributing its own findings to
    the same result.

    Raises :class:`ValueError` (propagated from :func:`vectorpress.validate.
    _svg_geometry.parse_cut_file`) for an SVG with no ``viewBox`` and no
    ``width``/``height`` to establish a scale from, or that otherwise fails
    to parse -- a validation failure (§35), never reported as passing.
    """
    parsed = parse_cut_file(svg_bytes, reference_size_in)
    findings: list[Finding] = [*disconnected_fragments.detect(parsed.pieces)]
    return ValidationResult(findings=tuple(findings))
