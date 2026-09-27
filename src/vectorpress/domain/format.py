"""Customer deliverable file formats (§7, CONTEXT.md "Product").

Split out from :mod:`vectorpress.domain.product` so
:mod:`vectorpress.domain.format_folder`'s ADR 0013 table can name a format
without importing ``product`` -- which itself imports ``format_folder`` for
its load-time format/type mismatch check -- and forming an import cycle.
"""

from enum import StrEnum


class Format(StrEnum):
    """A customer deliverable file format (§7).

    SVG, PNG and DXF are supported without further configuration; PDF and
    EPS are disabled by default and accepted on a product only when it
    explicitly sets ``enable_pdf_eps``.
    """

    SVG = "svg"
    PNG = "png"
    DXF = "dxf"
    PDF = "pdf"
    EPS = "eps"
