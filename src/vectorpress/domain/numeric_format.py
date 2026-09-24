"""The one fixed-precision rule every number this tool writes to a file --
SVG coordinate text or findings JSON alike -- follows (§36, issue #37 fix
round 1).

No I/O here (ADR 0006): plain arithmetic on a float. Lives in ``domain``,
not ``pipeline`` (where this rule originated, in
:mod:`vectorpress.pipeline.svg_document`), so :mod:`vectorpress.validate`
can reuse the exact same rule without importing its independent sibling
layer ``pipeline`` (CLAUDE.md's layering guardrail) -- ``pipeline`` and
``catalog`` both sit below ``validate`` in the layer stack
(``pyproject.toml``'s import-linter contract), so either can import this
module freely; :mod:`vectorpress.pipeline.svg_document` now does too, so
there is exactly one rule, not two copies that could quietly drift apart.
"""

#: Decimal places kept when rounding or serialising a number this tool
#: writes to a file. Fixed, low precision is deliberate (not just tidy): it
#: is what makes serialisation byte-identical across ubuntu and windows CI.
#: A curve-fitting or curve-sampling library's own libm calls
#: (``math.sqrt``/``atan2``/``cos``, or ``numpy``'s equivalents) can differ
#: in their last bit between platforms' C libraries for the same input, and
#: any such difference is many orders of magnitude smaller than one
#: ten-thousandth of a unit -- rounding here absorbs it before it can reach
#: an output file.
DECIMAL_PLACES = 4


def format_number(value: float) -> str:
    """``value`` formatted deterministically: fixed precision, then
    trailing zeros (and a trailing ``.``) trimmed, and ``-0`` normalised to
    ``0`` -- so identical geometry always serialises to identical text (§36)
    regardless of which platform produced the float. Used directly for SVG
    coordinate text (:mod:`vectorpress.pipeline.svg_document`); see
    :func:`round_number` for a findings JSON *number*, not text.
    """
    text = f"{value:.{DECIMAL_PLACES}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def round_number(value: float) -> float:
    """``value`` rounded to the same fixed precision :func:`format_number`
    uses, returned as a float rather than serialised text -- for JSON state
    (a findings report's bounding boxes, and any future measured value or
    threshold) where the number must round-trip as a JSON number, not a
    string, but still needs the identical cross-platform-determinism
    guarantee (issue #37 fix round 1: a curve-sampling library's numpy-backed
    ``.point(t)`` can differ in its last bit between platforms, the same
    concern :func:`format_number` exists to absorb for SVG text).
    """
    return float(format_number(value))
