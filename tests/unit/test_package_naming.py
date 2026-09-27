"""domain.package_naming: the ADR-decided Title-Case-Hyphen name a build's
package directory, ZIP and ZIP top-level folder all share (§15, §20)."""

from vectorpress.domain.package_naming import package_name, title_case_hyphen


def test_title_case_hyphen_on_a_snake_case_slug() -> None:
    assert title_case_hyphen("rock_climbing_icons") == "Rock-Climbing-Icons"


def test_title_case_hyphen_on_a_spaced_title() -> None:
    assert title_case_hyphen("tide pool collection") == "Tide-Pool-Collection"


def test_title_case_hyphen_lowercases_the_rest_of_each_word() -> None:
    # Capitalizes rather than merely uppercasing the first letter: an
    # all-caps word in a hand-authored title still comes out as one
    # capitalized word, never ALL-CAPS or Mi-Xed-Case.
    assert title_case_hyphen("SVG bundle") == "Svg-Bundle"


def test_package_name_prefers_short_title_over_slug() -> None:
    assert package_name("Tide Pool Collection", "pacific_coast_tide_pool_standard_pack") == (
        "Tide-Pool-Collection"
    )


def test_package_name_falls_back_to_slug_when_short_title_is_none() -> None:
    assert package_name(None, "pacific_coast_tide_pool_png_only") == (
        "Pacific-Coast-Tide-Pool-Png-Only"
    )


def test_package_name_falls_back_to_slug_when_short_title_is_empty() -> None:
    assert package_name("", "kelp_forest_mini_pack") == "Kelp-Forest-Mini-Pack"
