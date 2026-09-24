"""domain.numeric_format: the one fixed-precision rule every number this
tool writes to a file follows (§36, issue #37 fix round 1).

No I/O here (ADR 0006) -- ``format_number`` is the pre-existing rule
(``tests/unit/test_pipeline_svg_document.py`` already covers it thoroughly
through its ``pipeline.svg_document`` re-export, unchanged by the move);
this file's own focus is :func:`round_number`, the float-returning sibling
``validate`` and ``catalog.findings`` use for JSON *numbers* rather than SVG
coordinate *text*."""

from vectorpress.domain.numeric_format import format_number, round_number


def test_round_number_rounds_to_four_decimal_places() -> None:
    """The exact regression this fix addresses (issue #37 fix round 1): a
    curve-sampling library's raw, numpy-backed float -- the kind that can
    differ in its last bit between platforms -- is rounded to a stable,
    cross-platform-identical value."""
    assert round_number(57.352975173611114) == 57.353
    assert round_number(75.8666994140625) == 75.8667
    assert round_number(39.67802222222223) == 39.678


def test_round_number_returns_a_plain_float() -> None:
    result = round_number(1 / 3)

    assert isinstance(result, float)
    assert result == 0.3333


def test_round_number_is_idempotent() -> None:
    """Rounding an already-rounded number changes nothing -- the property
    ``catalog.findings``'s own belt-and-suspenders rounding at serialization
    time relies on."""
    once = round_number(57.352975173611114)

    assert round_number(once) == once


def test_round_number_of_a_whole_number_stays_a_whole_number() -> None:
    assert round_number(12.0) == 12.0


def test_round_number_preserves_a_negative_sign() -> None:
    assert round_number(-2.123456) == -2.1235


def test_round_number_normalises_negative_zero_to_zero() -> None:
    assert round_number(-0.00001) == 0.0


def test_round_number_matches_format_number_as_a_float() -> None:
    """The two functions apply the exact same precision rule -- one as
    text (for SVG coordinates), one as a float (for JSON numbers)."""
    for value in (57.352975173611114, 1 / 3, -2.5, 0.0, 12.0):
        assert round_number(value) == float(format_number(value))
