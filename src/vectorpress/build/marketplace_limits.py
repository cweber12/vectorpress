"""Cited marketplace limits (§19, ADR 0017): one table in code, and the
pure checks it drives.

Every entry in :data:`MARKETPLACE_LIMITS` names its own source URL and the
date it was checked -- ADR 0017's "a limit with no primary source is not
enforced; no number is guessed." The table enforces exactly the limits it
lists and no others: title and tag shape for Etsy, ZIP size and image count
for Etsy, ZIP contents and image shape for Creative Fabrica, ZIP size and
contents for Design Bundles, tag and cover-image counts for a direct store
(Shopify/Gumroad). Description length is not enforced anywhere -- there is
no primary source for it on any of the four marketplaces.

Every check function here is pure: it takes plain values (a title string, a
tag list, a byte count, image dimensions) and returns violations as plain
text, never touching a :class:`~vectorpress.build.export.ListingExport` or
any other build type itself. :func:`~vectorpress.build.export.
measure_export_limits` is the one place that pulls those plain values out
of one build's own export and canvas data and calls these.

A violation is *reported, never enforced*: nothing here truncates a title,
drops a tag or refuses a build (ADR 0017). Two shapes of report follow the
same split the PRD draws:

- A :class:`FieldViolation` is a field whose own text or file is over a
  limit -- the field still ships unchanged; the violation just says by how
  much.
- A :class:`CountOverflow` is the *items* past a count limit (Etsy's 14th
  tag, a direct store's 9th cover image) -- also still shipped unchanged;
  ``items`` names exactly the ones that don't fit, so nothing is dropped or
  silently truncated to make the count.
"""

import re
from dataclasses import dataclass

#: The date every :data:`MARKETPLACE_LIMITS` entry was checked against its
#: own source URL. One constant, not per-entry text, so re-checking the
#: whole table is one edit.
CHECKED = "2026-09-28"


@dataclass(frozen=True)
class MarketplaceLimit:
    """One cited marketplace limit: which marketplace, which field it
    constrains, the rule in human words, and where it was read (ADR 0017).
    Data only -- no marketplace's own numeric limit is enforced anywhere
    outside this module and the constants beside it."""

    marketplace: str
    field: str
    rule: str
    source_url: str
    checked: str


@dataclass(frozen=True)
class FieldViolation:
    """One field over its own cited limit (ADR 0017's "marketplace, field,
    measure"): ``field`` names which one, ``measure`` is the concrete
    number or text found -- never a signal to change the field itself."""

    field: str
    measure: str


@dataclass(frozen=True)
class CountOverflow:
    """Every item of ``field`` past a cited count limit (ADR 0017's "listed
    under 'does not fit', not dropped"): the field's own list still ships
    every item unchanged; these are only the ones past the limit, named so
    a human can see which ones would not fit a real listing."""

    field: str
    items: list[str]


# --- Etsy (help.etsy.com/hc/en-us/articles/115015628707,
# help.etsy.com/hc/en-us/articles/115015628347,
# etsy.com/openapi/generated/oas/3.0.0.json) -----------------------------

ETSY_TITLE_MAX_CHARS = 140
#: Symbols Etsy's own listing API allows at most once each in a title.
ETSY_TITLE_RESTRICTED_SYMBOLS = ("%", ":", "&", "+")
ETSY_TITLE_SYMBOL_MAX_COUNT = 1
ETSY_TAG_MAX_COUNT = 13
ETSY_TAG_MAX_CHARS = 20
#: Letters, digits, space, hyphen, apostrophe, and the trademark/copyright/
#: registered marks -- Etsy's own allowed tag character set.
ETSY_TAG_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9 '\-™©®]+$")
ETSY_ZIP_MAX_BYTES = 20 * 1024 * 1024
ETSY_MAX_IMAGES = 20

# --- Creative Fabrica (help.creativefabrica.com/hc/en-us/articles/
# 25796577543196, help.creativefabrica.com/hc/en-us/articles/360021068439) -

CREATIVE_FABRICA_IMAGE_ASPECT = (3, 2)
CREATIVE_FABRICA_IMAGE_MIN_WIDTH = 600
CREATIVE_FABRICA_IMAGE_MIN_HEIGHT = 400

# --- Design Bundles (fontbundles.freshdesk.com/en/support/solutions/
# articles/42000103843) ----------------------------------------------------

DESIGN_BUNDLES_ZIP_MAX_BYTES = 1024**3  # < 1 GB, strictly

# --- Direct store: Shopify (shopify.dev/docs/api/admin-rest/latest/
# resources/product), Gumroad (gumroad.com/help/article/60-adding-a-cover-
# image) ---------------------------------------------------------------

DIRECT_STORE_TAG_MAX_COUNT = 250
DIRECT_STORE_TAG_MAX_CHARS = 255
DIRECT_STORE_MAX_IMAGES = 8


MARKETPLACE_LIMITS: tuple[MarketplaceLimit, ...] = (
    MarketplaceLimit(
        marketplace="etsy",
        field="title",
        rule=(
            f"title ≤ {ETSY_TITLE_MAX_CHARS} chars; "
            f"{', '.join(ETSY_TITLE_RESTRICTED_SYMBOLS)} at most once each"
        ),
        source_url=(
            "https://help.etsy.com/hc/en-us/articles/115015628707; "
            "https://www.etsy.com/openapi/generated/oas/3.0.0.json"
        ),
        checked=CHECKED,
    ),
    MarketplaceLimit(
        marketplace="etsy",
        field="tags",
        rule=(
            f"≤ {ETSY_TAG_MAX_COUNT} tags, each ≤ {ETSY_TAG_MAX_CHARS} chars, only "
            "letters, digits, space, -, ', ™©®"
        ),
        source_url=(
            "https://help.etsy.com/hc/en-us/articles/115015628707; "
            "https://www.etsy.com/openapi/generated/oas/3.0.0.json"
        ),
        checked=CHECKED,
    ),
    MarketplaceLimit(
        marketplace="etsy",
        field="zip",
        rule=f"ZIP ≤ 20 MB; ≤ {ETSY_MAX_IMAGES} images",
        source_url=(
            "https://help.etsy.com/hc/en-us/articles/115015628347; "
            "https://help.etsy.com/hc/en-us/articles/115015628707"
        ),
        checked=CHECKED,
    ),
    MarketplaceLimit(
        marketplace="creative_fabrica",
        field="zip",
        rule="one ZIP, no ZIP inside it; images 3:2, ≥ 600x400",
        source_url=(
            "https://help.creativefabrica.com/hc/en-us/articles/25796577543196; "
            "https://help.creativefabrica.com/hc/en-us/articles/360021068439"
        ),
        checked=CHECKED,
    ),
    MarketplaceLimit(
        marketplace="design_bundles",
        field="zip",
        rule="ZIP < 1 GB, no ZIP inside it",
        source_url="https://fontbundles.freshdesk.com/en/support/solutions/articles/42000103843",
        checked=CHECKED,
    ),
    MarketplaceLimit(
        marketplace="direct_store",
        field="tags",
        rule=(
            f"≤ {DIRECT_STORE_TAG_MAX_COUNT} tags, each ≤ {DIRECT_STORE_TAG_MAX_CHARS} "
            f"chars (Shopify); ≤ {DIRECT_STORE_MAX_IMAGES} cover images (Gumroad)"
        ),
        source_url=(
            "https://shopify.dev/docs/api/admin-rest/latest/resources/product; "
            "https://gumroad.com/help/article/60-adding-a-cover-image"
        ),
        checked=CHECKED,
    ),
)


def _format_bytes_mb(size_bytes: int) -> str:
    """``size_bytes`` as whole-number megabytes text, e.g. ``"21 MB"``."""
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_bytes_gb(size_bytes: int) -> str:
    """``size_bytes`` as fixed-precision gigabytes text, e.g. ``"1.02 GB"``."""
    return f"{size_bytes / 1024**3:.2f} GB"


def etsy_violations(
    title: str, tags: list[str], zip_size_bytes: int, images: list[str]
) -> tuple[list[FieldViolation], list[CountOverflow]]:
    """Etsy's own :data:`MARKETPLACE_LIMITS` rows measured against one
    build's title, tags, ZIP size and bundle images. Tags and images past
    their count limits are returned as :class:`CountOverflow`, never
    dropped from ``tags``/``images`` themselves."""
    warnings: list[FieldViolation] = []
    overflow: list[CountOverflow] = []

    title_problems: list[str] = []
    if len(title) > ETSY_TITLE_MAX_CHARS:
        title_problems.append(f"{len(title)} characters (limit {ETSY_TITLE_MAX_CHARS})")
    for symbol in ETSY_TITLE_RESTRICTED_SYMBOLS:
        count = title.count(symbol)
        if count > ETSY_TITLE_SYMBOL_MAX_COUNT:
            title_problems.append(
                f"'{symbol}' appears {count} times (limit {ETSY_TITLE_SYMBOL_MAX_COUNT})"
            )
    if title_problems:
        warnings.append(FieldViolation("title", "; ".join(title_problems)))

    kept_tags = tags[:ETSY_TAG_MAX_COUNT]
    extra_tags = tags[ETSY_TAG_MAX_COUNT:]
    if extra_tags:
        overflow.append(CountOverflow("tags", extra_tags))
    tag_problems = [
        f"'{tag}' is {len(tag)} characters (limit {ETSY_TAG_MAX_CHARS})"
        for tag in kept_tags
        if len(tag) > ETSY_TAG_MAX_CHARS
    ]
    tag_problems += [
        f"'{tag}' has a character Etsy tags don't allow"
        for tag in kept_tags
        if len(tag) <= ETSY_TAG_MAX_CHARS and not ETSY_TAG_ALLOWED_CHARS.match(tag)
    ]
    if tag_problems:
        warnings.append(FieldViolation("tags", "; ".join(tag_problems)))

    if zip_size_bytes > ETSY_ZIP_MAX_BYTES:
        warnings.append(
            FieldViolation(
                "zip",
                f"{_format_bytes_mb(zip_size_bytes)} "
                f"(limit {ETSY_ZIP_MAX_BYTES // (1024 * 1024)} MB)",
            )
        )

    extra_images = images[ETSY_MAX_IMAGES:]
    if extra_images:
        overflow.append(CountOverflow("images", extra_images))

    return warnings, overflow


def creative_fabrica_violations(
    nested_zip_present: bool, image_width: int, image_height: int
) -> list[FieldViolation]:
    """Creative Fabrica's own row measured against whether the built ZIP
    holds a nested ZIP, and this bundle's own image dimensions -- both
    still ship unchanged; a violation is only ever reported."""
    warnings: list[FieldViolation] = []
    if nested_zip_present:
        warnings.append(FieldViolation("zip", "ZIP contains a nested ZIP file"))

    aspect_w, aspect_h = CREATIVE_FABRICA_IMAGE_ASPECT
    wrong_aspect = image_width * aspect_h != image_height * aspect_w
    too_small = (
        image_width < CREATIVE_FABRICA_IMAGE_MIN_WIDTH
        or image_height < CREATIVE_FABRICA_IMAGE_MIN_HEIGHT
    )
    if wrong_aspect or too_small:
        problems: list[str] = []
        if wrong_aspect:
            problems.append(f"{image_width}x{image_height} px is not {aspect_w}:{aspect_h}")
        if too_small:
            problems.append(
                f"{image_width}x{image_height} px is under "
                f"{CREATIVE_FABRICA_IMAGE_MIN_WIDTH}x{CREATIVE_FABRICA_IMAGE_MIN_HEIGHT}"
            )
        warnings.append(FieldViolation("images", "; ".join(problems)))
    return warnings


def design_bundles_violations(
    nested_zip_present: bool, zip_size_bytes: int
) -> list[FieldViolation]:
    """Design Bundles' own row measured against the built ZIP's size and
    whether it holds a nested ZIP."""
    warnings: list[FieldViolation] = []
    if zip_size_bytes >= DESIGN_BUNDLES_ZIP_MAX_BYTES:
        warnings.append(
            FieldViolation("zip", f"{_format_bytes_gb(zip_size_bytes)} (limit under 1.00 GB)")
        )
    if nested_zip_present:
        warnings.append(FieldViolation("zip", "ZIP contains a nested ZIP file"))
    return warnings


def direct_store_violations(
    tags: list[str], images: list[str]
) -> tuple[list[FieldViolation], list[CountOverflow]]:
    """A direct store's own row (Shopify tags, Gumroad cover images)
    measured against one build's tags and bundle images. Items past either
    count limit are returned as :class:`CountOverflow`, never dropped."""
    warnings: list[FieldViolation] = []
    overflow: list[CountOverflow] = []

    kept_tags = tags[:DIRECT_STORE_TAG_MAX_COUNT]
    extra_tags = tags[DIRECT_STORE_TAG_MAX_COUNT:]
    if extra_tags:
        overflow.append(CountOverflow("tags", extra_tags))
    tag_problems = [
        f"'{tag}' is {len(tag)} characters (limit {DIRECT_STORE_TAG_MAX_CHARS})"
        for tag in kept_tags
        if len(tag) > DIRECT_STORE_TAG_MAX_CHARS
    ]
    if tag_problems:
        warnings.append(FieldViolation("tags", "; ".join(tag_problems)))

    extra_images = images[DIRECT_STORE_MAX_IMAGES:]
    if extra_images:
        overflow.append(CountOverflow("images", extra_images))

    return warnings, overflow


def has_nested_zip(file_names: list[str]) -> bool:
    """Whether any of a build's own customer file names is itself a ZIP
    (Creative Fabrica's and Design Bundles' own "no ZIP inside it")."""
    return any(name.lower().endswith(".zip") for name in file_names)
