"""The ``raster_content`` detector (§9, ADR 0007, issue #41).

A vector deliverable must never rely on embedded raster content (§8): a
``<image>`` element, a ``data:`` URI anywhere in the document, or a
``<pattern>``/``<foreignObject>`` whose own subtree carries either, can
only ever appear in a hand-edited override -- the §8 builder's own tracer
never emits any of these.

Runs over every :mod:`vectorpress.validate._svg_geometry.DocumentElement`
in the document, including one inside a non-rendering container such as
``<defs>`` (unlike :mod:`vectorpress.validate.stray_object`): a raster
image hidden inside a ``<pattern>`` definition is still shipped inside the
file, and still a real problem, even though the pattern element itself is
never drawn on its own. An element nested inside a ``<pattern>``/
``<foreignObject>`` that already gets its own finding below is skipped
(:attr:`~vectorpress.validate._svg_geometry.DocumentElement.
inside_raster_container`) -- one finding for the container, not one for
the container and a second for each raster descendant inside it.
"""

from vectorpress.domain.finding import (
    CLASSIFICATION,
    Finding,
    FindingKind,
    PathReference,
)
from vectorpress.validate._svg_geometry import DocumentElement

_KIND = FindingKind.RASTER_CONTENT
_CLASSIFICATION = CLASSIFICATION[_KIND]


def detect(elements: list[DocumentElement]) -> list[Finding]:
    """One finding per element that is itself an ``<image>``, carries a
    ``data:`` URI in one of its own attributes, or -- for a ``<pattern>``/
    ``<foreignObject>`` -- has either somewhere in its own subtree (§9),
    located at that element's own bounding box when this module can
    compute one (:mod:`vectorpress.validate._svg_geometry`'s
    :data:`~vectorpress.validate._svg_geometry._BBOX_TAGS`), by element
    reference alone otherwise (a ``<pattern>``/``<foreignObject>`` has no
    simple geometry of its own).

    Findings are returned in a fixed, deterministic order -- by (document)
    element index -- matching every other detector in this package (issue
    #37's own ordering rule, extended here to a document-order element
    index rather than a ``<path>``-only one, since these findings are
    never about a ``<path>``'s own subpath).
    """
    findings: list[Finding] = []
    for element in elements:
        if element.inside_raster_container:
            # A raster element (or a nested data: URI) inside a <pattern>/
            # <foreignObject> is already covered by that container's own
            # finding below -- never double-counted (issue #41 review
            # fix).
            continue
        if element.tag == "image":
            reason = "is a raster <image> element"
        elif element.has_own_data_uri:
            reason = "carries a data: URI"
        elif element.tag in ("pattern", "foreignObject") and element.subtree_has_raster:
            reason = f"is a <{element.tag}> carrying raster content"
        else:
            continue

        findings.append(
            Finding(
                kind=_KIND,
                classification=_CLASSIFICATION,
                message=(
                    f"raster content: element {element.element_index} (<{element.tag}>) {reason}"
                ),
                location=element.bbox,
                path_reference=PathReference(
                    element_index=element.element_index,
                    subpath_index=None,
                    id=element.element_id,
                ),
            )
        )

    findings.sort(key=lambda finding: finding.path_reference.element_index)
    return findings
