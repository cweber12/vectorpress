"""domain.package_text: LICENSE.txt and README.txt composition (§27)."""

import pytest

from vectorpress.domain.package_text import (
    UnknownLicensePlaceholderError,
    render_license_text,
    render_readme_text,
)


def test_render_license_text_substitutes_every_placeholder() -> None:
    template = "{brand} grants {product} under this license. {copyright} {year}"

    rendered = render_license_text(
        template,
        brand_name="Tide Pool Studio",
        product_title="Tide Pool Collection",
        copyright_wording="© Tide Pool Studio. All rights reserved.",
        year=2026,
    )

    assert rendered == (
        "Tide Pool Studio grants Tide Pool Collection under this license. "
        "© Tide Pool Studio. All rights reserved. 2026"
    )


def test_render_license_text_raises_on_an_unknown_placeholder() -> None:
    with pytest.raises(UnknownLicensePlaceholderError) as exc_info:
        render_license_text(
            "{brand} -- {unexpected}",
            brand_name="Tide Pool Studio",
            product_title="Tide Pool Collection",
            copyright_wording="© Tide Pool Studio.",
            year=2026,
        )

    assert exc_info.value.placeholders == ["unexpected"]


def test_render_license_text_names_every_unknown_placeholder_sorted() -> None:
    with pytest.raises(UnknownLicensePlaceholderError) as exc_info:
        render_license_text(
            "{zeta} and {alpha}",
            brand_name="Tide Pool Studio",
            product_title="Tide Pool Collection",
            copyright_wording="© Tide Pool Studio.",
            year=2026,
        )

    assert exc_info.value.placeholders == ["alpha", "zeta"]


def test_render_license_text_leaves_ordinary_braced_text_alone_when_it_is_not_a_bare_word() -> None:
    # A template with no `{word}`-shaped token at all substitutes nothing
    # and raises nothing -- only an actual placeholder-shaped token is ever
    # flagged as unknown.
    rendered = render_license_text(
        "See clause {1} for details.",
        brand_name="Tide Pool Studio",
        product_title="Tide Pool Collection",
        copyright_wording="© Tide Pool Studio.",
        year=2026,
    )

    assert rendered == "See clause {1} for details."


def test_render_readme_text_lists_files_by_folder_and_reference_size() -> None:
    text = render_readme_text(
        intro="Thank you for your purchase!",
        standard_wording="Hand-illustrated cut files.",
        copyright_wording="© Tide Pool Studio.",
        included_formats=["png", "svg"],
        files_by_folder={
            "SVG": ["ochre-sea-star-cut.svg"],
            "PNG": ["ochre-sea-star-color.png", "giant-green-anemone-color.png"],
        },
        reference_size_in=3.0,
    )

    assert "Thank you for your purchase!" in text
    assert "Hand-illustrated cut files." in text
    assert "Included formats: png, svg" in text
    assert "PNG/" in text
    assert "  giant-green-anemone-color.png" in text
    assert "  ochre-sea-star-color.png" in text
    assert "SVG/" in text
    assert "  ochre-sea-star-cut.svg" in text
    assert "Files checked at reference size: 3in" in text
    assert "© Tide Pool Studio." in text


def test_render_readme_text_orders_formats_folders_and_files_alphabetically() -> None:
    text = render_readme_text(
        intro="intro",
        standard_wording="wording",
        copyright_wording="copyright",
        included_formats=["svg", "png"],
        files_by_folder={"SVG": ["b.svg", "a.svg"], "PNG": ["c.png"]},
        reference_size_in=3.0,
    )

    assert "Included formats: png, svg" in text
    lines = text.splitlines()
    assert lines.index("PNG/") < lines.index("SVG/")
    assert lines.index("  a.svg") < lines.index("  b.svg")
