"""build.marketplace_limits: the one cited table of marketplace limits, and
the pure checks it drives (§19, ADR 0017).

Every check here runs against plain values -- a title, a tag list, a byte
count, image dimensions -- never a :class:`~vectorpress.build.export.
ListingExport`: that assembly is :func:`~vectorpress.build.export.
measure_export_limits`'s own job, covered in ``test_build_export.py``.
"""

from vectorpress.build.marketplace_limits import (
    DESIGN_BUNDLES_ZIP_MAX_BYTES,
    DIRECT_STORE_MAX_IMAGES,
    DIRECT_STORE_TAG_MAX_CHARS,
    DIRECT_STORE_TAG_MAX_COUNT,
    ETSY_MAX_IMAGES,
    ETSY_TAG_MAX_CHARS,
    ETSY_TAG_MAX_COUNT,
    ETSY_TITLE_MAX_CHARS,
    ETSY_ZIP_MAX_BYTES,
    MARKETPLACE_LIMITS,
    creative_fabrica_violations,
    design_bundles_violations,
    direct_store_violations,
    etsy_violations,
    has_nested_zip,
)

# --- MARKETPLACE_LIMITS ------------------------------------------------


def test_every_limit_entry_carries_a_source_url_and_the_checked_date() -> None:
    for limit in MARKETPLACE_LIMITS:
        assert limit.source_url.startswith("https://")
        assert limit.checked == "2026-09-28"


def test_marketplace_limits_matches_exactly_the_issues_own_table() -> None:
    """One row per (marketplace, field) in the issue's own table -- no more,
    no fewer (ADR 0017's "enforced, and only these")."""
    assert {(limit.marketplace, limit.field) for limit in MARKETPLACE_LIMITS} == {
        ("etsy", "title"),
        ("etsy", "tags"),
        ("etsy", "zip"),
        ("creative_fabrica", "zip"),
        ("design_bundles", "zip"),
        ("direct_store", "tags"),
    }


# --- etsy_violations -----------------------------------------------------


def test_etsy_violations_within_every_limit_is_empty() -> None:
    warnings, overflow = etsy_violations(
        title="A short title",
        tags=["cut file", "svg"],
        zip_size_bytes=1000,
        images=["01-main-square.png"],
    )
    assert warnings == []
    assert overflow == []


def test_etsy_violations_flags_a_title_over_the_character_limit() -> None:
    title = "x" * (ETSY_TITLE_MAX_CHARS + 1)
    warnings, _ = etsy_violations(title=title, tags=[], zip_size_bytes=0, images=[])
    (title_warning,) = [w for w in warnings if w.field == "title"]
    assert str(ETSY_TITLE_MAX_CHARS + 1) in title_warning.measure
    assert str(ETSY_TITLE_MAX_CHARS) in title_warning.measure


def test_etsy_violations_flags_a_restricted_symbol_used_more_than_once() -> None:
    warnings, _ = etsy_violations(
        title="50% off, then 30% off again", tags=[], zip_size_bytes=0, images=[]
    )
    (title_warning,) = [w for w in warnings if w.field == "title"]
    assert "%" in title_warning.measure


def test_etsy_violations_lists_the_fourteenth_tag_under_does_not_fit_without_dropping_it() -> None:
    tags = [f"tag{i}" for i in range(1, ETSY_TAG_MAX_COUNT + 2)]  # 14 tags
    warnings, overflow = etsy_violations(title="", tags=tags, zip_size_bytes=0, images=[])
    assert warnings == []  # every kept tag is short and clean -- only a count overflow
    (tag_overflow,) = [o for o in overflow if o.field == "tags"]
    assert tag_overflow.items == [f"tag{ETSY_TAG_MAX_COUNT + 1}"]


def test_etsy_violations_flags_a_tag_over_the_character_limit() -> None:
    long_tag = "x" * (ETSY_TAG_MAX_CHARS + 1)
    warnings, _ = etsy_violations(title="", tags=[long_tag], zip_size_bytes=0, images=[])
    (tag_warning,) = [w for w in warnings if w.field == "tags"]
    assert long_tag in tag_warning.measure


def test_etsy_violations_flags_a_tag_with_a_disallowed_character() -> None:
    warnings, _ = etsy_violations(title="", tags=["bad$tag"], zip_size_bytes=0, images=[])
    (tag_warning,) = [w for w in warnings if w.field == "tags"]
    assert "bad$tag" in tag_warning.measure


def test_etsy_violations_allows_the_trademark_copyright_and_registered_marks() -> None:
    warnings, _ = etsy_violations(
        title="", tags=["brand™", "brand©", "brand®"], zip_size_bytes=0, images=[]
    )
    assert warnings == []


def test_etsy_violations_allows_non_ascii_letters() -> None:
    """The cited Etsy OAS pattern (``\\p{L}\\p{Nd}\\p{Zs}-'™©®``) allows any
    Unicode letter, not only ASCII -- "café" and "naïve" are both clean
    tags, so flagging them would warn on a rule stricter than the one
    cited (ADR 0017)."""
    warnings, _ = etsy_violations(title="", tags=["café", "naïve"], zip_size_bytes=0, images=[])
    assert warnings == []


def test_etsy_violations_allows_a_non_latin_script_tag() -> None:
    warnings, _ = etsy_violations(title="", tags=["日本語"], zip_size_bytes=0, images=[])
    assert warnings == []


def test_etsy_violations_allows_a_unicode_space_separator() -> None:
    """``\\p{Zs}`` (Etsy's own cited category) covers every Unicode space
    separator, not only the ASCII space -- e.g. U+00A0 NO-BREAK SPACE."""
    nbsp_tag = "tag" + "\u00a0" + "two"  # a real Unicode space separator, not ASCII
    warnings, _ = etsy_violations(title="", tags=[nbsp_tag], zip_size_bytes=0, images=[])
    assert warnings == []


def test_etsy_violations_still_flags_punctuation_outside_the_allowed_set() -> None:
    warnings, _ = etsy_violations(title="", tags=["#tag", "tag!"], zip_size_bytes=0, images=[])
    (tag_warning,) = [w for w in warnings if w.field == "tags"]
    assert "#tag" in tag_warning.measure
    assert "tag!" in tag_warning.measure


def test_etsy_violations_flags_a_zip_over_the_size_limit() -> None:
    warnings, _ = etsy_violations(
        title="", tags=[], zip_size_bytes=ETSY_ZIP_MAX_BYTES + 1, images=[]
    )
    (zip_warning,) = [w for w in warnings if w.field == "zip"]
    assert "20" in zip_warning.measure


def test_etsy_violations_lists_images_past_the_count_limit_under_does_not_fit() -> None:
    images = [f"img{i}.png" for i in range(1, ETSY_MAX_IMAGES + 2)]  # 21 images
    _, overflow = etsy_violations(title="", tags=[], zip_size_bytes=0, images=images)
    (image_overflow,) = [o for o in overflow if o.field == "images"]
    assert image_overflow.items == [f"img{ETSY_MAX_IMAGES + 1}.png"]


# --- creative_fabrica_violations -------------------------------------------


def test_creative_fabrica_violations_within_every_limit_is_empty() -> None:
    assert creative_fabrica_violations(False, 2400, 1600) == []


def test_creative_fabrica_violations_flags_a_nested_zip() -> None:
    warnings = creative_fabrica_violations(True, 2400, 1600)
    (zip_warning,) = [w for w in warnings if w.field == "zip"]
    assert "nested ZIP" in zip_warning.measure


def test_creative_fabrica_violations_flags_an_image_not_shaped_three_by_two() -> None:
    warnings = creative_fabrica_violations(False, 1000, 1000)
    (image_warning,) = [w for w in warnings if w.field == "images"]
    assert "1000x1000" in image_warning.measure


def test_creative_fabrica_violations_flags_an_image_under_the_minimum_size() -> None:
    warnings = creative_fabrica_violations(False, 599, 399)
    (image_warning,) = [w for w in warnings if w.field == "images"]
    assert "599x399" in image_warning.measure


# --- design_bundles_violations ----------------------------------------------


def test_design_bundles_violations_within_every_limit_is_empty() -> None:
    assert design_bundles_violations(False, 1000) == []


def test_design_bundles_violations_flags_a_zip_at_or_over_one_gigabyte() -> None:
    warnings = design_bundles_violations(False, DESIGN_BUNDLES_ZIP_MAX_BYTES)
    (zip_warning,) = warnings
    assert zip_warning.field == "zip"


def test_design_bundles_violations_flags_a_nested_zip() -> None:
    warnings = design_bundles_violations(True, 1000)
    assert any("nested ZIP" in w.measure for w in warnings)


# --- direct_store_violations -------------------------------------------------


def test_direct_store_violations_within_every_limit_is_empty() -> None:
    warnings, overflow = direct_store_violations(tags=["a", "b"], images=["01-main-square.png"])
    assert warnings == []
    assert overflow == []


def test_direct_store_violations_lists_tags_past_the_count_limit_under_does_not_fit() -> None:
    tags = [f"tag{i}" for i in range(1, DIRECT_STORE_TAG_MAX_COUNT + 2)]
    _, overflow = direct_store_violations(tags=tags, images=[])
    (tag_overflow,) = [o for o in overflow if o.field == "tags"]
    assert tag_overflow.items == [f"tag{DIRECT_STORE_TAG_MAX_COUNT + 1}"]


def test_direct_store_violations_flags_a_tag_over_the_character_limit() -> None:
    long_tag = "x" * (DIRECT_STORE_TAG_MAX_CHARS + 1)
    warnings, _ = direct_store_violations(tags=[long_tag], images=[])
    (tag_warning,) = warnings
    assert long_tag in tag_warning.measure


def test_direct_store_violations_lists_cover_images_past_the_count_limit_under_does_not_fit() -> (
    None
):
    images = [f"img{i}.png" for i in range(1, DIRECT_STORE_MAX_IMAGES + 2)]
    _, overflow = direct_store_violations(tags=[], images=images)
    (image_overflow,) = overflow
    assert image_overflow.items == [f"img{DIRECT_STORE_MAX_IMAGES + 1}.png"]


# --- has_nested_zip ----------------------------------------------------------


def test_has_nested_zip_is_false_for_ordinary_customer_files() -> None:
    assert has_nested_zip(["SVG/a-cut.svg", "PNG/a-color.png", "README.txt"]) is False


def test_has_nested_zip_is_true_when_any_file_ends_in_dot_zip() -> None:
    assert has_nested_zip(["SVG/a-cut.svg", "bonus/extra.zip"]) is True
