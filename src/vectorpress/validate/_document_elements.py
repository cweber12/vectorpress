"""Describe every element of a document -- its tag, bounding box, raster
content and whether it is ever rendered -- for the detectors that reason
about whole elements rather than subpaths.
"""

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass

from vectorpress.domain.finding import BoundingBox
from vectorpress.validate._svg_document import (
    LENGTH_RE,
    Point,
    SvgDocument,
    bbox,
    local_name,
    parse_length,
    polygon_bbox,
    root_bbox,
)

#: Tags this module computes a definite bounding box for -- every other tag
#: (``g``, ``text``, ``pattern``, ``foreignObject``, …) gets ``bbox=None``
#: from :func:`_generic_element_bbox`: no made-up box, only a real one when
#: the shape's own geometry is simple, closed-form arithmetic.
BBOX_TAGS = frozenset({"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "image"})

#: Tags whose own subtree is never rendered directly -- only ever
#: *referenced* (a gradient, a clip path, a pattern tile, a reusable
#: symbol) -- so an element inside one is never itself a stray object
#: (:mod:`vectorpress.validate.stray_object`): an off-canvas or seemingly
#: invisible shape *inside a ``<pattern>``'s own tile*, for example, is
#: exactly how a legitimate pattern is defined, not a mistake.
#: :mod:`vectorpress.validate.raster_content` does not consult this --
#: exactly the opposite case, a ``<pattern>`` carrying raster content, is
#: still a real problem regardless of never being rendered on its own.
_NON_RENDERING_CONTAINER_TAGS = frozenset(
    {"defs", "symbol", "clipPath", "mask", "marker", "pattern"}
)

#: Tags :func:`_inside_raster_container` walks up looking for -- the same
#: two tags :mod:`vectorpress.validate.raster_content` itself flags as
#: "carrying raster content" when their own subtree has any.
_RASTER_CONTAINER_TAGS = frozenset({"pattern", "foreignObject"})


def _parse_points_attr(value: str) -> list[Point]:
    """A ``points`` attribute (``<polyline>``/``<polygon>``) as ``(x, y)``
    pairs, tolerating either comma or whitespace separators the same way
    SVG itself does."""
    numbers = [float(match) for match in LENGTH_RE.findall(value)]
    return list(zip(numbers[0::2], numbers[1::2], strict=False))


def _generic_element_bbox(
    document: SvgDocument, element: ET.Element, tag: str
) -> BoundingBox | None:
    """``element``'s own bounding box computed from its own attributes (or,
    for a ``<path>``, its already-parsed ``d``) -- deliberately narrow: only
    the handful of shape elements a hand-edited cut-file override plausibly
    contains (:data:`BBOX_TAGS`), each a closed-form read of its own
    geometry attributes (no ``transform`` resolution -- plain user-unit
    coordinates, the same scope every other location in a findings report
    uses). Returns ``None`` for any tag not in that set, or one whose own
    attributes do not parse (a malformed override, or a required attribute
    simply absent) -- never a made-up box."""
    attrib = element.attrib
    try:
        if tag == "rect":
            x = parse_length(attrib.get("x", "0"))
            y = parse_length(attrib.get("y", "0"))
            width = parse_length(attrib["width"])
            height = parse_length(attrib["height"])
            return bbox(x, y, x + width, y + height)
        if tag == "circle":
            cx = parse_length(attrib.get("cx", "0"))
            cy = parse_length(attrib.get("cy", "0"))
            r = parse_length(attrib["r"])
            return bbox(cx - r, cy - r, cx + r, cy + r)
        if tag == "ellipse":
            cx = parse_length(attrib.get("cx", "0"))
            cy = parse_length(attrib.get("cy", "0"))
            rx = parse_length(attrib["rx"])
            ry = parse_length(attrib["ry"])
            return bbox(cx - rx, cy - ry, cx + rx, cy + ry)
        if tag == "line":
            x1 = parse_length(attrib["x1"])
            y1 = parse_length(attrib["y1"])
            x2 = parse_length(attrib["x2"])
            y2 = parse_length(attrib["y2"])
            return bbox(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        if tag in ("polyline", "polygon"):
            points = _parse_points_attr(attrib.get("points", ""))
            if not points:
                return None
            xs = [x for x, _y in points]
            ys = [y for _x, y in points]
            return bbox(min(xs), min(ys), max(xs), max(ys))
        if tag == "image":
            x = parse_length(attrib.get("x", "0"))
            y = parse_length(attrib.get("y", "0"))
            width = parse_length(attrib["width"])
            height = parse_length(attrib["height"])
            return bbox(x, y, x + width, y + height)
        if tag == "path":
            all_points = [
                point for subpath in document.path_for(element).subpaths for point in subpath.points
            ]
            if not all_points:
                return None
            return polygon_bbox(all_points)
    except (KeyError, ValueError):
        return None
    return None


def _has_own_data_uri(attrib: Mapping[str, str]) -> bool:
    """Whether any of ``attrib``'s own values contains a ``data:`` URI (§9's
    "a ``data:`` image URI anywhere") -- checked against every attribute,
    not just ``href``/``xlink:href``, since a raster image can just as well
    be smuggled in through a ``style`` declaration (``fill:url(data:...)``)."""
    return any("data:" in value for value in attrib.values())


def _subtree_has_raster(element: ET.Element) -> bool:
    """Whether ``element`` or any of its descendants is an ``<image>``, or
    carries a ``data:`` URI of its own -- the basis for "a
    pattern/foreignObject carrying raster content": a ``<pattern>`` or
    ``<foreignObject>`` is flagged when its own subtree contains either, not
    only when the element itself does."""
    for descendant in element.iter():
        if local_name(descendant.tag) == "image":
            return True
        if _has_own_data_uri(descendant.attrib):
            return True
    return False


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    """``{child: parent}`` for every element under ``root`` -- ``ElementTree``
    keeps no parent pointers of its own, so this is built once per
    document."""
    return {child: parent for parent in root.iter() for child in parent}


def _has_ancestor_tag(
    element: ET.Element, parent_map: Mapping[ET.Element, ET.Element], tags: frozenset[str]
) -> bool:
    current = parent_map.get(element)
    while current is not None:
        if local_name(current.tag) in tags:
            return True
        current = parent_map.get(current)
    return False


def _is_rendered(element: ET.Element, parent_map: Mapping[ET.Element, ET.Element]) -> bool:
    """Whether ``element`` is ever actually drawn -- ``False`` when any
    ancestor is a non-rendering container (:data:`_NON_RENDERING_CONTAINER_TAGS`)."""
    return not _has_ancestor_tag(element, parent_map, _NON_RENDERING_CONTAINER_TAGS)


def _inside_raster_container(
    element: ET.Element, parent_map: Mapping[ET.Element, ET.Element]
) -> bool:
    """Whether some ancestor of ``element`` is itself a ``<pattern>`` or
    ``<foreignObject>``: that ancestor's own subtree scan
    (:func:`_subtree_has_raster`) already finds and reports whatever raster
    content ``element`` itself might be or carry, so ``element`` is never
    *also* independently flagged -- one finding for the container, not one
    for the container and a second for each raster descendant inside it."""
    return _has_ancestor_tag(element, parent_map, _RASTER_CONTAINER_TAGS)


@dataclass(frozen=True)
class DocumentElement:
    """One element in the document, document order, root ``<svg>`` excluded
    -- the basis for :mod:`vectorpress.validate.raster_content` and
    :mod:`vectorpress.validate.stray_object`, which reason about whole
    elements (a stray ``<image>``, an empty ``<g>``, off-canvas geometry)
    rather than a ``<path>``'s own subpaths.

    ``bbox`` is ``None`` for a tag this module has no simple, closed-form
    geometry for, or one whose own attributes did not parse
    (:func:`_generic_element_bbox`) -- never a made-up box (Finding's own
    "no geometry, no bbox" rule). ``has_own_data_uri`` and
    ``subtree_has_raster`` are :func:`_has_own_data_uri`/
    :func:`_subtree_has_raster`'s own results, computed once here rather
    than re-walked per detector. ``rendered`` is :func:`_is_rendered`'s own
    result -- :mod:`vectorpress.validate.stray_object` only ever judges a
    rendered element a stray object; :mod:`vectorpress.validate.
    raster_content` ignores this field, since a pattern tile or a clip path
    can still carry raster content worth flagging even though it is never
    rendered on its own. ``inside_raster_container`` is
    :func:`_inside_raster_container`'s own result --
    :mod:`vectorpress.validate.raster_content` skips an element inside a
    ``<pattern>``/``<foreignObject>`` it already reports on its own, so
    raster content nested inside one is never double-counted."""

    element_index: int
    tag: str
    element_id: str | None
    bbox: BoundingBox | None
    has_own_data_uri: bool
    subtree_has_raster: bool
    has_children: bool
    attrib: Mapping[str, str]
    rendered: bool
    inside_raster_container: bool


def parse_document_elements(
    document: SvgDocument,
) -> tuple[BoundingBox, list[DocumentElement]]:
    """``document``'s own bounding box (:func:`~vectorpress.validate.
    _svg_document.root_bbox`), plus every element in it excluding the root
    ``<svg>`` -- the shared view :mod:`vectorpress.validate.raster_content`
    and :mod:`vectorpress.validate.stray_object` both work from.

    Raises :class:`ValueError` the same way :func:`~vectorpress.validate.
    _svg_document.root_bbox` does, for a root with neither a ``viewBox`` nor
    ``width``/``height`` (§35)."""
    root = document.root
    view_box = root_bbox(document)
    parent_map = _build_parent_map(root)

    elements: list[DocumentElement] = []
    for element_index, element in enumerate(child for child in root.iter() if child is not root):
        tag = local_name(element.tag)
        elements.append(
            DocumentElement(
                element_index=element_index,
                tag=tag,
                element_id=element.attrib.get("id"),
                bbox=_generic_element_bbox(document, element, tag),
                has_own_data_uri=_has_own_data_uri(element.attrib),
                subtree_has_raster=_subtree_has_raster(element),
                has_children=len(list(element)) > 0,
                attrib=dict(element.attrib),
                rendered=_is_rendered(element, parent_map),
                inside_raster_container=_inside_raster_container(element, parent_map),
            )
        )
    return view_box, elements
