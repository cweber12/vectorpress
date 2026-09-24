"""The ``stray_object`` detector (§9, ADR 0007, issue #41).

Four independent problems collapse into one finding kind (§9's own single
"stray object" bullet): an element wholly or partly outside the document's
own viewBox, an invisible element (no fill and no stroke, opacity/
fill-opacity 0, ``display:none``, ``visibility:hidden``), an empty group,
or a non-artwork drawing element such as a stray ``<text>`` -- all four
read as document clutter a hand edit left behind, never something the §8
builder's own tracer emits.

Runs only over a *rendered* :mod:`vectorpress.validate._svg_geometry.
DocumentElement` (:attr:`~vectorpress.validate._svg_geometry.
DocumentElement.rendered`): an element nested inside a non-rendering
container (``<defs>``, a ``<pattern>``'s own tile, …) is never itself
drawn, so being off-canvas or "invisible" there is exactly how a
legitimate definition looks, not a mistake -- contrast :mod:`vectorpress.
validate.raster_content`, which does not apply this same filter.

**A ``<path>`` gets every one of the four checks too** (issue #41 review
fix round 1, controller ruling): a hand-edited override is overwhelmingly
likely to consist almost entirely of ``<path>`` elements (Inkscape, for
one, writes almost nothing else), so a leftover off-canvas or hidden
``<path>`` is exactly the kind of stray object this detector exists to
catch -- excluding the tag outright, as an earlier round of this issue
did, would silently pass a hand-edited override carrying one. The
invisibility checks apply to a ``<path>`` exactly as they do to any other
element (display/visibility/opacity/fill+stroke are boolean, not
measurements, so there is no noise to absorb). The off-canvas check alone
needs a tolerance for a ``<path>`` specifically: this module's own
curve-flattening (:mod:`vectorpress.validate._svg_geometry`'s fixed-step
sampling, §36) can disagree with the document's own written ``viewBox``
by a fraction of a user unit of pure floating-point rounding noise, at the
last digit :data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES`
keeps -- confirmed empirically against every fixture cut file this
catalog generates: the single largest such discrepancy is
``bat_star``'s own, about ``0.0001`` user units (roughly ``1e-6`` in at
the catalog's own 3in reference size) -- see :data:`~vectorpress.validate.
cut_file.THRESHOLDS`'s own ``stray_object_off_canvas_tolerance_in`` entry
for the chosen margin above that. Every other element tag keeps the exact,
tolerance-free check: a stray ``<rect>`` or ``<image>`` a human placed off
canvas is never a curve-fitting artifact, so any overshoot at all is
already a real one.

Checked in a fixed order per element (empty group, non-artwork element,
invisible, off canvas) so one element never carries more than one
:attr:`~vectorpress.domain.finding.FindingKind.STRAY_OBJECT` finding -- an
empty ``<g>`` that also happens to sit off canvas is reported once, as
empty, not twice.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    BoundingBox,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.validate._svg_geometry import DocumentElement, effective_attribute

_KIND = FindingKind.STRAY_OBJECT
_CLASSIFICATION = CLASSIFICATION[_KIND]

#: Tags this detector never itself judges a stray object -- structural or
#: definition-only elements SVG (and this tool's own writer) uses
#: routinely, which have no meaningful "off canvas" or "invisible" reading
#: of their own. ``path`` is deliberately **not** in this set (issue #41
#: review fix round 1, see this module's own docstring) -- a rendered
#: descendant of one of these containers is still filtered separately, by
#: :attr:`~vectorpress.validate._svg_geometry.DocumentElement.rendered`.
_IGNORED_TAGS = frozenset(
    {
        "defs",
        "metadata",
        "title",
        "desc",
        "style",
        "symbol",
        "clipPath",
        "mask",
        "marker",
        "pattern",
        "foreignObject",
    }
)

#: Tags §9's "non-artwork drawing element" names by example (a stray
#: ``<text>``) -- the §8 builder's own tracer never emits any of these.
_NON_ARTWORK_TAGS = frozenset({"text"})


def _is_empty_group(element: DocumentElement) -> bool:
    return element.tag == "g" and not element.has_children


def _opacity_is_zero(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) == 0.0
    except ValueError:
        return False


def _is_invisible(element: DocumentElement) -> bool:
    """Whether ``element`` paints nothing at all (§9's "no fill and no
    stroke, opacity/fill-opacity 0, display:none, visibility:hidden") --
    every property is read through :func:`~vectorpress.validate.
    _svg_geometry.effective_attribute` (issue #41 review fix round 1), so a
    ``style="display:none"`` declaration is caught exactly the same way
    the plain ``display="none"`` attribute is, not just the latter."""
    attrib = element.attrib
    display = effective_attribute(attrib, "display")
    if display is not None and display.strip().lower() == "none":
        return True
    visibility = effective_attribute(attrib, "visibility")
    if visibility is not None and visibility.strip().lower() == "hidden":
        return True
    if _opacity_is_zero(effective_attribute(attrib, "opacity")):
        return True
    if _opacity_is_zero(effective_attribute(attrib, "fill-opacity")):
        return True
    fill = effective_attribute(attrib, "fill")
    stroke = effective_attribute(attrib, "stroke")
    no_fill = fill is not None and fill.strip().lower() == "none"
    no_stroke = stroke is None or stroke.strip().lower() == "none"
    return no_fill and no_stroke


def _off_canvas(view_box: BoundingBox, bbox: BoundingBox, tolerance: float) -> bool:
    """Whether ``bbox`` extends past ``view_box`` by more than
    ``tolerance`` user units on any side -- ``tolerance`` is ``0.0`` for
    every element but a ``<path>`` (this module's own docstring)."""
    return (
        bbox.min_x < view_box.min_x - tolerance
        or bbox.min_y < view_box.min_y - tolerance
        or bbox.max_x > view_box.max_x + tolerance
        or bbox.max_y > view_box.max_y + tolerance
    )


def detect(
    view_box: BoundingBox,
    elements: list[DocumentElement],
    scale_user_units_per_inch: float,
    path_off_canvas_tolerance_in: float,
) -> list[Finding]:
    """One finding per rendered element that is an empty group, a
    non-artwork element, invisible, or off canvas (§9) -- located at that
    element's own bounding box, or by element reference alone for an empty
    group (no geometry to draw a box around). ``path_off_canvas_tolerance_in``
    (§9.1, converted to this document's own user units via
    ``scale_user_units_per_inch``) is the off-canvas check's own tolerance,
    applied only to a ``<path>`` element (this module's own docstring).

    Findings are returned in a fixed, deterministic order -- by (document)
    element index -- matching every other detector in this package (issue
    #37's own ordering rule).
    """
    path_tolerance_user_units = path_off_canvas_tolerance_in * scale_user_units_per_inch

    findings: list[Finding] = []
    for element in elements:
        if not element.rendered or element.tag in _IGNORED_TAGS:
            continue

        tolerance = path_tolerance_user_units if element.tag == "path" else 0.0

        if _is_empty_group(element):
            location = None
            reason = "is an empty group"
        elif element.tag in _NON_ARTWORK_TAGS:
            location = element.bbox
            reason = f"is a non-artwork <{element.tag}> element"
        elif _is_invisible(element):
            location = element.bbox
            reason = "is invisible (no fill and no stroke, zero opacity, or hidden)"
        elif element.bbox is not None and _off_canvas(view_box, element.bbox, tolerance):
            location = element.bbox
            reason = "sits wholly or partly outside the document's own viewBox"
        else:
            continue

        findings.append(
            Finding(
                kind=_KIND,
                classification=_CLASSIFICATION,
                message=f"stray object: element {element.element_index} (<{element.tag}>) {reason}",
                location=location,
                path_reference=PathReference(
                    element_index=element.element_index,
                    subpath_index=None,
                    id=element.element_id,
                ),
            )
        )

    findings.sort(key=lambda finding: finding.path_reference.element_index)
    return findings
