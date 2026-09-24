"""domain.derivative_type: customer-facing filenames (§20, issue #23)."""

import pytest

from vectorpress.domain.derivative_type import DerivativeType, derivative_filename, slugify


def test_slugify_lowercases_and_hyphenates() -> None:
    assert slugify("Ochre Sea Star") == "ochre-sea-star"


def test_slugify_strips_punctuation_and_collapses_runs() -> None:
    assert slugify("Anemone (Giant Green)!!") == "anemone-giant-green"


def test_slugify_folds_non_ascii_characters() -> None:
    assert slugify("Café Ñandú") == "cafe-nandu"


def test_slugify_strips_leading_and_trailing_hyphens() -> None:
    assert slugify("  -Sea Star-  ") == "sea-star"


def test_derivative_filename_uses_display_name_never_the_asset_id() -> None:
    filename = derivative_filename("Ochre Sea Star", DerivativeType.TRANSPARENT_PNG)

    assert filename == "ochre-sea-star-color.png"
    assert "ochre_sea_star" not in filename


def test_derivative_filename_raises_for_a_type_with_no_suffix_yet() -> None:
    with pytest.raises(KeyError):
        derivative_filename("Purple Sea Urchin", DerivativeType.SILHOUETTE_SVG)
