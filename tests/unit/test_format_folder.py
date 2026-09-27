"""domain.format_folder: the ADR 0013 table filling package format folders
from derivative types, and the format/type mismatch it makes checkable."""

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.format_folder import (
    copied_folder,
    dxf_source,
    format_type_mismatch_problems,
)

# ADR 0013's table: every *_svg type copies into SVG/, transparent_png
# copies into PNG/. DXF has no entry -- its source is chosen dynamically
# (see the dxf_source tests below), not copied 1:1 from one type.
EVERY_TYPE_AND_ITS_COPIED_FOLDER: dict[DerivativeType, Format] = {
    DerivativeType.SILHOUETTE_SVG: Format.SVG,
    DerivativeType.CUT_SVG: Format.SVG,
    DerivativeType.FLATCOLOR_SVG: Format.SVG,
    DerivativeType.OUTLINE_SVG: Format.SVG,
    DerivativeType.DETAILED_MONO_SVG: Format.SVG,
    DerivativeType.LAYERED_SVG: Format.SVG,
    DerivativeType.TRANSPARENT_PNG: Format.PNG,
}


def test_every_derivative_type_has_the_documented_copied_folder() -> None:
    # Covers every member of DerivativeType, not just the ones in the
    # expectation table above, so a type added later without a table entry
    # fails this test rather than silently mapping to None.
    for derivative_type in DerivativeType:
        assert copied_folder(derivative_type) == EVERY_TYPE_AND_ITS_COPIED_FOLDER[derivative_type]


def test_copied_folder_table_has_no_extra_types() -> None:
    assert set(EVERY_TYPE_AND_ITS_COPIED_FOLDER) == set(DerivativeType)


def test_dxf_source_prefers_cut_svg_over_silhouette_svg() -> None:
    assert dxf_source([DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG]) == (
        DerivativeType.CUT_SVG
    )


def test_dxf_source_falls_back_to_silhouette_svg_without_cut_svg() -> None:
    assert dxf_source([DerivativeType.SILHOUETTE_SVG]) == DerivativeType.SILHOUETTE_SVG


def test_dxf_source_is_none_when_neither_is_included() -> None:
    assert dxf_source([DerivativeType.FLATCOLOR_SVG]) is None


def test_dxf_source_is_none_for_an_empty_type_list() -> None:
    assert dxf_source([]) is None


# --- format_type_mismatch_problems (ADR 0013's two kinds of mismatch) ------


def test_dxf_format_unfilled_by_a_non_cut_type_is_a_formats_problem() -> None:
    problems = format_type_mismatch_problems([Format.DXF], [DerivativeType.FLATCOLOR_SVG])

    assert any(field == "formats" and "dxf" in message for field, message in problems)


def test_png_format_unfilled_without_transparent_png_is_a_formats_problem() -> None:
    problems = format_type_mismatch_problems([Format.PNG], [DerivativeType.CUT_SVG])

    assert any(field == "formats" and "png" in message for field, message in problems)


def test_pdf_format_enabled_but_unfilled_is_a_formats_problem() -> None:
    """No type fills PDF in this PRD (ADR 0013), so an enabled-but-listed
    pdf format is kind (a) even though enablement itself is not the
    problem: a product cannot claim a format the build will never
    produce."""
    problems = format_type_mismatch_problems([Format.PDF], [DerivativeType.CUT_SVG])

    assert any(field == "formats" and "pdf" in message for field, message in problems)


def test_transparent_png_without_png_format_is_a_derivative_types_problem() -> None:
    problems = format_type_mismatch_problems([Format.SVG], [DerivativeType.TRANSPARENT_PNG])

    assert any(
        field == "derivative_types" and "transparent_png" in message for field, message in problems
    )


def test_cut_svg_with_neither_svg_nor_dxf_is_a_derivative_types_problem() -> None:
    problems = format_type_mismatch_problems([Format.PNG], [DerivativeType.CUT_SVG])

    assert any(field == "derivative_types" and "cut_svg" in message for field, message in problems)


def test_cut_svg_carried_by_dxf_alone_is_not_a_problem() -> None:
    """cut_svg with only dxf listed is fine: DXF/ is converted from
    cut_svg (ADR 0013), so cut_svg is carried even without svg listed."""
    problems = format_type_mismatch_problems([Format.DXF], [DerivativeType.CUT_SVG])

    assert problems == []


def test_silhouette_svg_carried_by_dxf_when_cut_svg_not_included() -> None:
    problems = format_type_mismatch_problems([Format.DXF], [DerivativeType.SILHOUETTE_SVG])

    assert problems == []


def test_silhouette_svg_not_carried_by_dxf_when_cut_svg_takes_the_slot() -> None:
    """Both cut_svg and silhouette_svg included, only dxf listed: cut_svg
    wins DXF's source slot (ADR 0013's preference order), so
    silhouette_svg -- included but shipped nowhere -- is still a
    mismatch."""
    problems = format_type_mismatch_problems(
        [Format.DXF], [DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG]
    )

    assert any(
        field == "derivative_types" and "silhouette_svg" in message for field, message in problems
    )


def test_matching_formats_and_types_have_no_problems() -> None:
    problems = format_type_mismatch_problems(
        [Format.SVG, Format.PNG, Format.DXF],
        [DerivativeType.CUT_SVG, DerivativeType.SILHOUETTE_SVG, DerivativeType.TRANSPARENT_PNG],
    )

    assert problems == []
