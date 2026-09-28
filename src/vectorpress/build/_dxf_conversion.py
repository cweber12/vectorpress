# pyright: basic
"""Convert an SVG's closed subpaths into a deterministic DXF (ADR 0013, §7,
§35, §36).

``DXF/`` is the package's one *converted* format folder -- every closed
subpath of the effective ``cut_svg`` (or ``silhouette_svg`` when ``cut_svg``
is not included, :mod:`vectorpress.domain.format_folder`) becomes one DXF
polyline. Curves are flattened at a fixed step count, never adaptively, the
same reasoning :mod:`vectorpress.pipeline.svg_document` and
:mod:`vectorpress.validate` already apply: adaptive subdivision could react
differently to a curve-sampling library's own last-bit differences between
platforms' C libraries, where a fixed step count cannot. Every flattened
coordinate is additionally rounded to
:data:`~vectorpress.domain.numeric_format.DECIMAL_PLACES` for the same
reason those modules round theirs -- ``svgelements``' curve sampling is
``numpy``-backed. Holes and islands are both closed subpaths in their own
right, so both keep their own polyline, never merged or dropped (ADR 0013:
"Holes and islands keep their structure").

This module never rasterizes or vectorizes (ADR 0013): it only walks
already-vector ``<path>`` geometry a generator or a human already produced,
the one thing a "format conversion" is allowed to do.

**Determinism.** ``ezdxf`` (added via ``uv add``) is this build's DXF
writer. Three of its defaults are not reproducible run to run and are all
avoided here rather than patched after the fact:

- ``ezdxf.new()`` stamps a wall-clock creation/update timestamp and random
  ``$FINGERPRINTGUID``/``$VERSIONGUID`` header values. ``ezdxf.options.
  write_fixed_meta_data_for_testing`` is ``ezdxf``'s own switch for fixing
  both (despite its "for_testing" name, it exists precisely for
  reproducible output) -- set once, at import time, for every document this
  module ever writes.
- ``ezdxf.new()`` also auto-creates two layout objects whose relative order
  in the OBJECTS section depends on Python's per-process string hash seed,
  varying between interpreter runs even with fixed metadata. Building the
  document with :class:`ezdxf.document.Drawing.new` directly (bypassing
  ``ezdxf.new()``'s convenience wrapper) targets DXF R12, which predates
  paper space layouts entirely -- sidestepping that ordering rather than
  fixing it. R12 also never writes ``$INSUNITS``, matching this module's
  own rule that a DXF carries no more physical sizing than its source SVG.
- ``Drawing.saveas`` opens its output file in text mode, so its line
  endings follow the running platform's own newline convention. Writing
  through :func:`Drawing.write` to an in-memory text stream instead, then
  encoding the result ourselves, keeps every line ending ``\\n`` regardless
  of platform.

``svgelements`` ships no type stubs (:mod:`vectorpress.validate._svg_document`'s
own docstring says why); this module's own touch of it is the same kind, so
it carries the same ``# pyright: basic`` this file starts with.
"""

import io
import xml.etree.ElementTree as ET

import ezdxf
import svgelements as se
from ezdxf.document import Drawing

from vectorpress.domain.numeric_format import round_number

Point = tuple[float, float]

#: Fixed sample count per curved segment when flattening it to straight
#: polyline segments -- matches :data:`vectorpress.validate._svg_document.
#: CURVE_STEPS`'s own reasoning (deterministic, no adaptive subdivision),
#: kept as this module's own constant rather than imported cross-package
#: (CLAUDE.md's layering guardrail keeps ``build``'s own third-party-parsing
#: touch self-contained, the same way each of ``pipeline`` and ``validate``
#: already keeps its own).
CURVE_STEPS = 24

#: A subpath's own flattened end landing within this many user units of its
#: own start still counts as closed even without an explicit ``Z`` -- an
#: override might close a shape by repeating its start coordinate as its
#: last ``L`` instead. Mirrors :mod:`vectorpress.validate._subpaths`'
#: ``_CLOSE_TOLERANCE``.
_CLOSE_TOLERANCE = 1e-6

#: ``ezdxf``'s own deterministic-output switch (see this module's
#: docstring). Set once at import time: every :class:`Drawing` this module
#: creates picks it up automatically.
ezdxf.options.write_fixed_meta_data_for_testing = True  # pyright: ignore[reportPrivateImportUsage]


class DxfConversionError(Exception):
    """``svg_bytes`` could not be converted to DXF (§35): unparseable XML or
    path data, or the DXF writer itself failing. Fails the whole product
    build, naming the asset it happened for -- the caller's job, since this
    module has no asset context of its own."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _flatten_subpath(subpath: se.Subpath) -> tuple[Point, ...]:
    """One subpath's geometry as a flat polygon ring: every corner vertex
    directly, every curved segment sampled at :data:`CURVE_STEPS` fixed
    steps, every coordinate rounded (this module's own docstring)."""
    points: list[Point] = []
    for segment in subpath:
        if isinstance(segment, se.Move | se.Line | se.Close):
            end = segment.end
            # a stray Close with nothing yet to close back to (no Move ever
            # anchored this subpath) carries no real point -- left out
            # rather than crashing the conversion; the subpath it belongs
            # to is filtered out below anyway, by having too few points to
            # be a real ring.
            if end is None or end.x is None or end.y is None:
                continue
            points.append((round_number(float(end.x)), round_number(float(end.y))))
            continue
        for step in range(1, CURVE_STEPS + 1):
            sampled = segment.point(step / CURVE_STEPS)
            points.append((round_number(float(sampled.x)), round_number(float(sampled.y))))
    return tuple(points)


def _is_closed(subpath: se.Subpath, points: tuple[Point, ...]) -> bool:
    if any(isinstance(segment, se.Close) for segment in subpath):
        return True
    if len(points) < 2:
        return False
    (start_x, start_y), (end_x, end_y) = points[0], points[-1]
    return abs(start_x - end_x) < _CLOSE_TOLERANCE and abs(start_y - end_y) < _CLOSE_TOLERANCE


def closed_rings(svg_bytes: bytes) -> list[tuple[Point, ...]]:
    """Every closed subpath in ``svg_bytes``'s ``<path>`` elements, flattened
    to a polygon ring, in document order (§7's "convert every closed path"):
    an explicit ``Z``, or a flattened end landing back on its own start
    within :data:`_CLOSE_TOLERANCE`. An open subpath -- one a human approved
    despite it -- is left out rather than failing the conversion: nothing
    about "closed path" fits it either way. A degenerate subpath (fewer than
    three distinct points once flattened) is left out too: neither a line
    nor a point is geometry a DXF polyline entity can usefully carry.

    Raises :class:`DxfConversionError` on malformed XML or unparseable path
    data (§35).
    """
    try:
        root = ET.fromstring(svg_bytes)
    except ET.ParseError as exc:
        raise DxfConversionError(f"not a valid SVG document: {exc}") from exc

    rings: list[tuple[Point, ...]] = []
    for element in root.iter():
        if _local_name(element.tag) != "path":
            continue
        d = element.attrib.get("d", "")
        try:
            path = se.Path(d)
        except Exception as exc:
            raise DxfConversionError(f"unparseable path data {d!r}: {exc}") from exc
        for subpath in path.as_subpaths():
            points = _flatten_subpath(subpath)
            if len(points) < 3:
                continue
            if _is_closed(subpath, points):
                rings.append(points)
    return rings


def svg_to_dxf_bytes(svg_bytes: bytes) -> bytes:
    """``svg_bytes`` converted to a deterministic DXF (ADR 0013): one closed
    2D polyline per closed subpath (:func:`closed_rings`), in the SVG's own
    coordinate units -- no physical scale is added. Two calls on identical
    ``svg_bytes`` always return identical bytes (this module's docstring),
    so an unchanged rebuild's DXF is byte-identical (§36).

    Raises :class:`DxfConversionError` on malformed input or a DXF-writer
    failure (§35).
    """
    rings = closed_rings(svg_bytes)

    doc = Drawing.new("R12")
    modelspace = doc.modelspace()
    for ring in rings:
        modelspace.add_polyline2d(list(ring), close=True)

    stream = io.StringIO()
    try:
        doc.write(stream)
    except Exception as exc:
        raise DxfConversionError(f"DXF writer failed: {exc}") from exc
    return stream.getvalue().encode("ascii")
