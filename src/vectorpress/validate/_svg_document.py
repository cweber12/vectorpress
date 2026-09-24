# pyright: basic
"""Parse an SVG's bytes once into the :class:`SvgDocument` every
cut-file validation view (pieces, subpaths, document elements) derives from.

This is the one place that talks to ``svgelements`` (and Python's stdlib
``xml.etree.ElementTree``) directly, mirroring :mod:`vectorpress.pipeline.
_potrace_trace` and :mod:`vectorpress.pipeline._ndimage_cleanup`: every touch
of a third-party parsing API is isolated in one small module, so the rest of
:mod:`vectorpress.validate` stays plain, fully-typed code. ``svgelements``
ships no type stubs and no ``py.typed`` marker, so pyright infers its types
from source as broad ``Unknown`` unions in several places -- hence the
``# pyright: basic`` at the top of this module; every public name it exposes
is still fully, concretely typed, and none of them leaks an ``svgelements``
type.

**Library choice.** ``svgelements`` is a pure-Python SVG path parser (no C
extension) -- it parses arbitrary ``d`` strings (absolute or relative, lines,
cubic/quadratic Béziers, and elliptical arcs) into segments with a uniform
``.point(t)`` sampling API, which this module uses to flatten curves
deterministically. It ships a universal wheel, so it installs identically on
``ubuntu-latest`` and ``windows-latest`` with no system package. A
``<path>`` element's ``d`` is parsed on its own, via ``svgelements.Path(d)``
directly rather than ``svgelements.SVG.parse`` on the whole document: the
latter also applies the root ``<svg>``'s own ``viewBox``-to-viewport
transform, which would shift every coordinate away from the plain numbers
the ``d`` attribute (and :func:`svg_viewbox_longest_side`) already uses --
and a finding's location must stay in exactly the same "SVG user units" a
human or an editor already sees in the file, so it can be drawn over the SVG.

**No ``shapely``.** Every geometric question validation asks -- polygon
area, bounding box, a representative interior point, point-in-polygon
containment, segment crossings -- is plain, deterministic arithmetic, the
same style already proven byte-identical across platforms by
:mod:`vectorpress.pipeline.svg_document`'s own Bézier-extrema bounding box.
A GEOS-backed library would add a second native dependency and a second
thing to keep identical across ``ubuntu-latest``/``windows-latest`` for no
behavior this package cannot already express directly.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property

import svgelements as se

from vectorpress.domain.finding import BoundingBox
from vectorpress.domain.numeric_format import round_number

Point = tuple[float, float]

#: Fixed sample count per curved segment (cubic/quadratic Bézier, arc) when
#: flattening it to line segments -- deterministic (no adaptive subdivision
#: that could react differently to libm's last-bit platform differences),
#: matching the fixed-step style ``tests/unit/test_pipeline_cut_svg.py``'s
#: own ``_flatten_cubic`` test helper already uses to check this generator's
#: geometry.
CURVE_STEPS = 24

LENGTH_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?")
_VIEWBOX_SPLIT_RE = re.compile(r"[\s,]+")


def local_name(tag: str) -> str:
    """An XML tag's local name, stripping any ``{namespace}`` prefix
    ``ElementTree`` leaves on it."""
    return tag.rsplit("}", 1)[-1]


def parse_length(value: str) -> float:
    """The leading numeric portion of an SVG length attribute (``"12.5"``,
    ``"12.5px"``, ``"3in"``) as a plain float -- a validated SVG's ``width``/
    ``height`` are unitless numbers in practice (this codebase's own writer
    never emits a unit suffix), but a hand-edited override might."""
    match = LENGTH_RE.match(value.strip())
    if match is None:
        raise ValueError(f"not a numeric length: {value!r}")
    return float(match.group())


def bbox(min_x: float, min_y: float, max_x: float, max_y: float) -> BoundingBox:
    """A :class:`~vectorpress.domain.finding.BoundingBox` with every
    coordinate rounded to :data:`~vectorpress.domain.numeric_format.
    DECIMAL_PLACES`: a curved segment's flattened points come from
    ``svgelements``' own ``numpy``-backed ``.point(t)`` sampling, which can
    differ in its last bit between platforms' C libraries for identical
    input the same way potrace's own curve fitting can -- rounded here, at
    the point a finding's location is actually built, the same fixed-
    precision rule :mod:`vectorpress.pipeline.svg_document` already applies
    to SVG coordinate text keeps findings JSON byte-identical across ubuntu
    and windows too (§36)."""
    return BoundingBox(
        min_x=round_number(min_x),
        min_y=round_number(min_y),
        max_x=round_number(max_x),
        max_y=round_number(max_y),
    )


def polygon_bbox(points: tuple[Point, ...] | list[Point]) -> BoundingBox:
    """``points``'s tight bounding box, rounded (:func:`bbox`)."""
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return bbox(min(xs), min(ys), max(xs), max(ys))


def flatten_subpath(subpath: se.Subpath) -> tuple[Point, ...]:
    """One subpath's geometry as a flat polygon ring: every corner vertex
    directly, every curved segment sampled at :data:`CURVE_STEPS` fixed
    steps (never a raw control point, which is generally not on the curve
    itself -- the same reasoning :mod:`vectorpress.pipeline.svg_document`'s
    own bounding-box code documents)."""
    points: list[Point] = []
    for segment in subpath:
        if isinstance(segment, se.Move | se.Line | se.Close):
            end = segment.end
            # every Move/Line/Close this module ever sees is a concrete,
            # anchored point -- never svgelements' own "unspecified" sentinel.
            assert end is not None
            assert end.x is not None
            assert end.y is not None
            points.append((float(end.x), float(end.y)))
            continue
        for step in range(1, CURVE_STEPS + 1):
            # ``svgelements`` samples a curved segment's ``.point()`` with
            # numpy internally, returning ``numpy.float64`` rather than a
            # plain ``float`` -- coerced here, once, so every coordinate
            # downstream (bounding boxes included) is plain-``float``,
            # JSON-serializable without a custom encoder.
            sampled = segment.point(step / CURVE_STEPS)
            points.append((float(sampled.x), float(sampled.y)))
    return tuple(points)


def _node_count(subpath: se.Subpath) -> int:
    """The number of anchor points a human editor would see on ``subpath``
    (§9's "excessive geometric complexity"): every ``Move``, ``Line``, curve
    or ``Arc`` segment contributes one node at its own end point -- a
    ``Move`` plus ``n`` further segments describes ``n + 1`` distinct
    anchors -- while ``Close`` (a zero-length return to the subpath's start,
    never a new anchor of its own) is not counted. This is the *authored*
    node count -- ``svgelements``' own segment list, exactly as potrace's
    curve fitting (or a hand-authored override) wrote it -- never
    :func:`flatten_subpath`'s fixed-step curve sampling, which would report
    the same, constant :data:`CURVE_STEPS`-per-curve count for every path
    regardless of how few or many curves it actually has."""
    return sum(1 for segment in subpath if not isinstance(segment, se.Close))


@dataclass(frozen=True)
class ParsedSubpath:
    """One subpath of a ``<path>``'s ``d``, as authored: its flattened ring
    (:func:`flatten_subpath`), its authored node count, and whether it ends
    in an explicit ``Z``."""

    points: tuple[Point, ...]
    node_count: int
    has_close_segment: bool


@dataclass(frozen=True)
class PathElement:
    """One ``<path>`` element, in document order among every ``<path>`` in
    the document (``element_index``), with its ``d`` parsed once into
    :class:`ParsedSubpath`\\ s."""

    element_index: int
    element_id: str | None
    attrib: Mapping[str, str]
    subpaths: tuple[ParsedSubpath, ...]


def _parse_path_element(element_index: int, element: ET.Element) -> PathElement:
    subpaths = tuple(
        ParsedSubpath(
            points=flatten_subpath(subpath),
            node_count=_node_count(subpath),
            has_close_segment=any(isinstance(segment, se.Close) for segment in subpath),
        )
        for subpath in se.Path(element.attrib.get("d", "")).as_subpaths()
    )
    return PathElement(
        element_index=element_index,
        element_id=element.attrib.get("id"),
        attrib=element.attrib,
        subpaths=subpaths,
    )


class SvgDocument:
    """One SVG's parsed XML tree, plus every ``<path>`` element's parsed
    ``d`` (:attr:`paths`).

    Path data is parsed on first access of :attr:`paths`, not at
    construction, so a caller that checks the document's scale first
    (:func:`svg_viewbox_longest_side`) reports a missing ``viewBox`` before
    it reports unparseable path data."""

    def __init__(self, root: ET.Element) -> None:
        self.root = root

    @cached_property
    def paths(self) -> tuple[PathElement, ...]:
        """Every ``<path>`` element under (and including) the root, in
        document order.

        Raises :class:`ValueError` (from ``svgelements``) on unparseable
        path data (§35)."""
        return tuple(self._path_by_element.values())

    @cached_property
    def _path_by_element(self) -> dict[ET.Element, PathElement]:
        path_elements = [
            element for element in self.root.iter() if local_name(element.tag) == "path"
        ]
        return {
            element: _parse_path_element(element_index, element)
            for element_index, element in enumerate(path_elements)
        }

    def path_for(self, element: ET.Element) -> PathElement:
        """The parsed :class:`PathElement` for ``element``, a ``<path>`` in
        this document's own tree."""
        return self._path_by_element[element]


def parse_svg_document(svg_bytes: bytes) -> SvgDocument:
    """Parse ``svg_bytes``'s XML -- the only ``ElementTree.fromstring`` a
    cut-file validation makes.

    Raises :class:`xml.etree.ElementTree.ParseError` on malformed XML."""
    return SvgDocument(ET.fromstring(svg_bytes))


def _view_box_parts(root: ET.Element) -> tuple[float, float, float, float] | None:
    view_box = root.attrib.get("viewBox")
    if view_box is None:
        return None
    parts = [p for p in _VIEWBOX_SPLIT_RE.split(view_box.strip()) if p]
    if len(parts) != 4:
        return None
    min_x, min_y, width, height = (float(p) for p in parts)
    return min_x, min_y, width, height


def svg_viewbox_longest_side(document: SvgDocument) -> float:
    """The longest side of the root ``<svg>``'s ``viewBox``, falling back to
    its ``width``/``height``: the basis for converting a physical-unit
    threshold (§9.1) into this document's own user units, the same role
    :mod:`vectorpress.pipeline.cut_svg`'s own ``_bbox_longest_side_px``
    plays for the source raster at generation time.

    Raises :class:`ValueError` when the root element has neither -- there is
    no scale to validate physical thresholds against, so the caller must
    treat this as a validation failure (§35), never a passing result.
    """
    root = document.root
    view_box = _view_box_parts(root)
    if view_box is not None:
        _min_x, _min_y, width, height = view_box
        return max(width, height)

    sides = [
        parse_length(value)
        for value in (root.attrib.get("width"), root.attrib.get("height"))
        if value is not None
    ]
    if sides:
        return max(sides)

    raise ValueError("SVG has neither a viewBox nor width/height to establish a scale from")


def root_bbox(document: SvgDocument) -> BoundingBox:
    """The root ``<svg>``'s own bounding box, from its ``viewBox`` (its own
    ``min-x``/``min-y``/width/height, so an offset viewBox is honored, not
    assumed to start at the origin) or, failing that, ``width``/``height``
    starting at the origin. Unlike :func:`svg_viewbox_longest_side`, which
    needs one number and tolerates a single ``width`` *or* ``height``, an
    "off canvas" test needs a real 2-D box, so this requires both ``width``
    and ``height`` together when there is no ``viewBox``.

    Raises :class:`ValueError` for a root with neither (§35)."""
    root = document.root
    view_box = _view_box_parts(root)
    if view_box is not None:
        min_x, min_y, width, height = view_box
        return BoundingBox(min_x=min_x, min_y=min_y, max_x=min_x + width, max_y=min_y + height)

    width_attr = root.attrib.get("width")
    height_attr = root.attrib.get("height")
    if width_attr is not None and height_attr is not None:
        width = parse_length(width_attr)
        height = parse_length(height_attr)
        return BoundingBox(min_x=0.0, min_y=0.0, max_x=width, max_y=height)

    raise ValueError("SVG has neither a viewBox nor width/height to establish a scale from")


def parse_style_declarations(attrib: Mapping[str, str]) -> dict[str, str]:
    """``style``'s own ``property: value`` declarations, so a caller can
    check a declaration with the same "a style declaration wins over the
    plain attribute" precedence SVG itself gives it."""
    style = attrib.get("style", "")
    declarations: dict[str, str] = {}
    for declaration in style.split(";"):
        name, _sep, value = declaration.partition(":")
        name = name.strip().lower()
        if name:
            declarations[name] = value.strip()
    return declarations


def effective_attribute(attrib: Mapping[str, str], name: str) -> str | None:
    """``attrib``'s own effective value for presentation attribute
    ``name``: a ``style`` declaration wins over the plain attribute (SVG's
    own precedence), falling back to the plain attribute, then ``None`` when
    neither is set."""
    declarations = parse_style_declarations(attrib)
    if name in declarations:
        return declarations[name]
    return attrib.get(name)
