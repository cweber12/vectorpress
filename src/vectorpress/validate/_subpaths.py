"""List every subpath in a document exactly as authored, without grouping
any into pieces or holes.

:mod:`vectorpress.validate.open_path`, :mod:`vectorpress.validate.
duplicate_geometry` and :mod:`vectorpress.validate.overlap` work from this
view rather than :mod:`vectorpress.validate._pieces`' containment-parity
grouping: the "well-nested, non-overlapping" simplification that grouping
relies on does not hold for a document that is, by definition, possibly
malformed.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from vectorpress.domain.finding import BoundingBox
from vectorpress.validate._svg_document import (
    ParsedSubpath,
    Point,
    SvgDocument,
    effective_attribute,
    polygon_bbox,
)

#: A subpath's own end point landing on its own start within this many user
#: units still counts as closed even without an explicit ``Z`` -- a
#: hand-authored override might close a shape by repeating the start
#: coordinate as its last ``L`` instead. Deliberately tiny: this is a
#: tolerance for "the same point written twice", not a snapping distance.
_CLOSE_TOLERANCE = 1e-6


def _element_has_fill(attrib: Mapping[str, str]) -> bool:
    """Whether a ``<path>`` element's own attributes paint a fill at all
    (§9's "a path with no fill, where a closed filled path is expected") --
    SVG's own default (no ``fill`` attribute, no ``style`` override) is a
    *filled* black shape, so only an explicit ``none`` (the ``fill``
    attribute, or a ``fill`` declaration inside ``style``) counts as "no
    fill"."""
    effective = effective_attribute(attrib, "fill")
    return effective is None or effective.strip().lower() != "none"


def _subpath_is_closed(subpath: ParsedSubpath) -> bool:
    """Whether ``subpath`` is closed (§9's "a subpath that is not closed --
    no Z and its end is not its start"): an explicit ``Close`` segment, or
    its own flattened end point landing back on its own start point within
    :data:`_CLOSE_TOLERANCE`."""
    if subpath.has_close_segment:
        return True
    points = subpath.points
    if len(points) < 2:
        return False
    (start_x, start_y), (end_x, end_y) = points[0], points[-1]
    return abs(start_x - end_x) < _CLOSE_TOLERANCE and abs(start_y - end_y) < _CLOSE_TOLERANCE


@dataclass(frozen=True)
class Subpath:
    """One subpath's own raw geometry: every subpath any ``<path>`` element
    in the document has, independent of the piece/hole containment-parity
    grouping :class:`~vectorpress.validate._pieces.Piece`/
    :class:`~vectorpress.validate._pieces.Hole` use --
    :mod:`vectorpress.validate.open_path`, :mod:`vectorpress.validate.
    duplicate_geometry` and :mod:`vectorpress.validate.overlap` all need
    every subpath exactly as authored: the last two by design (their own
    module docstrings say why grouping is the wrong basis for them), the
    first because a genuinely unclosed subpath cannot be reliably
    classified as a piece or a hole to begin with."""

    element_index: int
    subpath_index: int
    element_id: str | None
    points: tuple[Point, ...]
    bbox: BoundingBox
    closed: bool
    has_fill: bool


def parse_subpaths(document: SvgDocument) -> list[Subpath]:
    """Every subpath in ``document``, in document order, exactly as
    authored.

    Only a truly empty subpath (a bare ``Move`` with nothing after it, no
    points at all -- ``len(points) < 2``) is dropped here: a two-point
    subpath, a bare open line segment such as ``<path d="M0,0 L50,50"/>``,
    is kept -- it is exactly §9's simplest "a subpath that is not closed"
    case, and dropping it here would hide it from :mod:`vectorpress.
    validate.open_path` entirely, the one detector that needs to see it.
    :mod:`vectorpress.validate.duplicate_geometry` and :mod:`vectorpress.
    validate.overlap` filter a fewer-than-three-point subpath back out
    themselves (their own modules' docstrings): neither "the same geometry"
    nor "a self-intersecting ring" means anything for a shape with no real
    interior.

    Raises :class:`ValueError` (from ``svgelements``) on unparseable path
    data (§35)."""
    subpaths: list[Subpath] = []
    for path in document.paths:
        has_fill = _element_has_fill(path.attrib)
        for subpath_index, subpath in enumerate(path.subpaths):
            if len(subpath.points) < 2:
                continue  # truly empty: a bare Move with nothing after it
            subpaths.append(
                Subpath(
                    element_index=path.element_index,
                    subpath_index=subpath_index,
                    element_id=path.element_id,
                    points=subpath.points,
                    bbox=polygon_bbox(subpath.points),
                    closed=_subpath_is_closed(subpath),
                    has_fill=has_fill,
                )
            )
    return subpaths
