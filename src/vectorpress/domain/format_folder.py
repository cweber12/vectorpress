"""The fixed table filling package format folders from derivative types
(ADR 0013): ``SVG/`` from every included ``*_svg`` type, ``PNG/`` from
``transparent_png``, ``DXF/`` converted from ``cut_svg``, else
``silhouette_svg``. No rasterizing, no vectorizing.

One definition, in ``domain`` (ADR 0006): the load-time format/type
mismatch check below reads it, and so will the build layer's format
conversion and its DXF slice, rather than each keeping its own copy.
"""

from collections.abc import Iterable

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format

#: Every derivative type copied straight into a format folder (ADR 0013).
#: DXF has no entry here: its source is chosen dynamically, in preference
#: order, by :func:`dxf_source` -- it is converted, not copied 1:1 from
#: one type.
_COPIED_FOLDER: dict[DerivativeType, Format] = {
    DerivativeType.SILHOUETTE_SVG: Format.SVG,
    DerivativeType.CUT_SVG: Format.SVG,
    DerivativeType.FLATCOLOR_SVG: Format.SVG,
    DerivativeType.OUTLINE_SVG: Format.SVG,
    DerivativeType.DETAILED_MONO_SVG: Format.SVG,
    DerivativeType.LAYERED_SVG: Format.SVG,
    DerivativeType.TRANSPARENT_PNG: Format.PNG,
}

#: DXF's source, in preference order (ADR 0013): ``cut_svg`` if included,
#: else ``silhouette_svg``.
_DXF_SOURCE_PREFERENCE: tuple[DerivativeType, ...] = (
    DerivativeType.CUT_SVG,
    DerivativeType.SILHOUETTE_SVG,
)


def copied_folder(derivative_type: DerivativeType) -> Format | None:
    """The format folder ``derivative_type`` is copied into, or ``None``
    for a type this table does not copy anywhere (DXF is converted, not
    copied -- see :func:`dxf_source`)."""
    return _COPIED_FOLDER.get(derivative_type)


def dxf_source(included_types: Iterable[DerivativeType]) -> DerivativeType | None:
    """Which included type ``DXF/`` is converted from (ADR 0013): ``cut_svg``
    if included, else ``silhouette_svg`` if included, else ``None`` when
    neither is included -- nothing fills ``DXF/``."""
    included = set(included_types)
    for candidate in _DXF_SOURCE_PREFERENCE:
        if candidate in included:
            return candidate
    return None


def format_type_mismatch_problems(
    formats: Iterable[Format], derivative_types: Iterable[DerivativeType]
) -> list[tuple[str, str]]:
    """Every ADR 0013 mismatch between listed ``formats`` and included
    ``derivative_types``, as ``(field, message)`` pairs (§7): kind (a) a
    listed format no included type fills, kind (b) an included type no
    listed format carries.

    PDF and EPS are always kind (a) when listed, even with
    ``enable_pdf_eps`` set: no type fills them in this PRD, so a product
    cannot claim a format the build will never produce.
    """
    formats = list(formats)
    types = list(derivative_types)
    dxf_fills = dxf_source(types)

    problems: list[tuple[str, str]] = []

    for fmt in formats:
        filled = (
            dxf_fills is not None
            if fmt is Format.DXF
            else any(copied_folder(dtype) is fmt for dtype in types)
        )
        if not filled:
            problems.append(
                ("formats", f"format {fmt.value!r} is not filled by any included derivative type")
            )

    for dtype in types:
        folder = copied_folder(dtype)
        carried = folder is not None and folder in formats
        if not carried and dtype in _DXF_SOURCE_PREFERENCE and Format.DXF in formats:
            carried = dxf_fills is dtype
        if not carried:
            problems.append(
                (
                    "derivative_types",
                    f"derivative type {dtype.value!r} is not carried by any included format",
                )
            )

    return problems
