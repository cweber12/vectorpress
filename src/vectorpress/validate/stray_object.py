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
from vectorpress.validate._svg_geometry import DocumentElement

_KIND = FindingKind.STRAY_OBJECT
_CLASSIFICATION = CLASSIFICATION[_KIND]

#: Tags this detector never itself judges a stray object -- structural or
#: definition-only elements SVG (and this tool's own writer) uses
#: routinely. A rendered descendant *inside* one of these is still
#: filtered separately, by :attr:`~vectorpress.validate._svg_geometry.
#: DocumentElement.rendered`; this list additionally excludes the
#: container elements themselves, which have no meaningful "off canvas" or
#: "invisible" reading of their own.
#:
#: ``path`` is excluded too (issue #41 review fix): the main cut geometry
#: is itself a ``<path>``, and a curve potrace fits right at the source
#: raster's own edge can legitimately land a fraction of a user unit
#: outside the document's own ``viewBox`` -- confirmed against this
#: fixture catalog's own ``bat_star`` cut file, whose main body's curve
#: fitting lands at ``max_y=280.1797`` against a ``280``-tall viewBox. A
#: ``<path>``'s own geometry is :mod:`vectorpress.validate.cut_file`'s
#: other detectors' concern (piece/hole area, narrow features, complexity,
#: :mod:`vectorpress.validate.open_path`'s own "no fill" check for a
#: stroke-only path); "stray" here means an *extra* element left behind by
#: a hand edit, never the cut file's own main artwork.
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
        "path",
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
    attrib = element.attrib
    if attrib.get("display", "").strip().lower() == "none":
        return True
    if attrib.get("visibility", "").strip().lower() == "hidden":
        return True
    if _opacity_is_zero(attrib.get("opacity")):
        return True
    if _opacity_is_zero(attrib.get("fill-opacity")):
        return True
    no_fill = attrib.get("fill", "").strip().lower() == "none"
    no_stroke = attrib.get("stroke", "").strip().lower() in ("", "none")
    return no_fill and no_stroke


def _off_canvas(view_box: BoundingBox, bbox: BoundingBox) -> bool:
    return (
        bbox.min_x < view_box.min_x
        or bbox.min_y < view_box.min_y
        or bbox.max_x > view_box.max_x
        or bbox.max_y > view_box.max_y
    )


def detect(view_box: BoundingBox, elements: list[DocumentElement]) -> list[Finding]:
    """One finding per rendered element that is an empty group, a
    non-artwork element, invisible, or off canvas (§9) -- located at that
    element's own bounding box, or by element reference alone for an empty
    group (no geometry to draw a box around).

    Findings are returned in a fixed, deterministic order -- by (document)
    element index -- matching every other detector in this package (issue
    #37's own ordering rule).
    """
    findings: list[Finding] = []
    for element in elements:
        if not element.rendered or element.tag in _IGNORED_TAGS:
            continue

        if _is_empty_group(element):
            location = None
            reason = "is an empty group"
        elif element.tag in _NON_ARTWORK_TAGS:
            location = element.bbox
            reason = f"is a non-artwork <{element.tag}> element"
        elif _is_invisible(element):
            location = element.bbox
            reason = "is invisible (no fill and no stroke, zero opacity, or hidden)"
        elif element.bbox is not None and _off_canvas(view_box, element.bbox):
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
