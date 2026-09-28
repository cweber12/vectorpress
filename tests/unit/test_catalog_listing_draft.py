"""catalog.listing_draft: the tool's one sanctioned write into a
hand-authored file -- appending a drafted ``[listing]`` table, create-only,
raw-text, re-validated before the atomic replace (§18, ADR 0005, ADR 0016).

Builds product files directly under ``tmp_path`` rather than the fixture
catalog: this module's job is the append mechanics (byte preservation, line
endings, the create-only gate, the revalidation safety net), not catalog
loading (``tests/integration`` covers the CLI end to end).
"""

from pathlib import Path

from vectorpress.catalog.listing_draft import (
    COMMAND_NAME,
    ListingAppendOutcome,
    append_listing,
)
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.listing import Listing

CONFIG = CatalogConfig(name="Test Catalog")

LISTING = Listing(
    title="Test Product \u2013 SVG Cut Files",
    short_title="Test Product",
    description="A pitch for the test product.",
    tags=["tag one", "tag two"],
    search_terms=["term one"],
    intended_uses=["vinyl cutting"],
    region="Pacific Coast",
    species_names=["Species one"],
    category="Nature & Wildlife",
    license_type="Personal Use",
    marketplace_notes="",
)

_BASE_PRODUCT_TOML = """\
# Hand-authored product metadata.
derivative_types = ["cut_svg"]
formats = ["svg"]
tier = "individual"
price = 5.0

[membership]
asset_ids = ["ochre_sea_star"]
"""


def _write_product(root: Path, slug: str, text: str) -> Path:
    products_dir = root / "products"
    products_dir.mkdir(parents=True, exist_ok=True)
    path = products_dir / f"{slug}.toml"
    path.write_bytes(text.encode("utf-8"))
    return path


def test_appends_the_listing_table_and_preserves_every_existing_byte(tmp_path: Path) -> None:
    path = _write_product(tmp_path, "test_product", _BASE_PRODUCT_TOML)
    original = path.read_bytes()

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.APPENDED
    new_bytes = path.read_bytes()
    assert new_bytes.startswith(original)
    assert new_bytes != original
    text = new_bytes.decode("utf-8")
    assert f"# Drafted by `{COMMAND_NAME}` on" in text
    assert "never rewrites this table" in text
    assert "[listing]" in text
    # A non-ASCII character (the en dash) is written out literally, not
    # escaped: TOML is UTF-8 text, and only control characters and the two
    # syntax characters ("\", '"') need escaping.
    assert 'title = "Test Product \u2013 SVG Cut Files"' in text
    assert 'region = "Pacific Coast"' in text


def test_appended_text_reparses_to_the_same_listing(tmp_path: Path) -> None:
    import tomllib

    path = _write_product(tmp_path, "test_product", _BASE_PRODUCT_TOML)
    append_listing(tmp_path, CONFIG, "test_product", LISTING)

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["listing"]["title"] == LISTING.title
    assert data["listing"]["tags"] == LISTING.tags
    assert data["listing"]["region"] == LISTING.region


def test_a_non_bmp_character_round_trips_through_the_appended_toml(tmp_path: Path) -> None:
    """``json.dumps``'s default ``ensure_ascii=True`` would re-encode a
    non-BMP character (an emoji) as a UTF-16 surrogate pair; TOML has no
    such escape and ``tomllib`` rejects it as "not a Unicode scalar value",
    so a display name or description with an emoji would previously fail
    this module's own pre-write revalidation on every draft."""
    import tomllib

    emoji_listing = LISTING.model_copy(update={"title": "Ocean \U0001f30a Pack"})
    path = _write_product(tmp_path, "test_product", _BASE_PRODUCT_TOML)

    result = append_listing(tmp_path, CONFIG, "test_product", emoji_listing)

    assert result.outcome is ListingAppendOutcome.APPENDED
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["listing"]["title"] == "Ocean \U0001f30a Pack"


def test_running_it_again_refuses_and_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    path = _write_product(tmp_path, "test_product", _BASE_PRODUCT_TOML)
    first = append_listing(tmp_path, CONFIG, "test_product", LISTING)
    assert first.outcome is ListingAppendOutcome.APPENDED
    after_first = path.read_bytes()

    second = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert second.outcome is ListingAppendOutcome.REFUSED_ALREADY_HAS_LISTING
    assert path.read_bytes() == after_first


def test_a_partial_listing_already_present_refuses_and_changes_nothing(tmp_path: Path) -> None:
    text = _BASE_PRODUCT_TOML + '\n[listing]\ntitle = "Only a title"\n'
    path = _write_product(tmp_path, "test_product", text)
    original = path.read_bytes()

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.REFUSED_ALREADY_HAS_LISTING
    assert path.read_bytes() == original


def test_unknown_product_file_refuses(tmp_path: Path) -> None:
    (tmp_path / "products").mkdir()

    result = append_listing(tmp_path, CONFIG, "no_such_product", LISTING)

    assert result.outcome is ListingAppendOutcome.REFUSED_FILE_NOT_FOUND


def test_toml_syntax_error_refuses_and_changes_nothing(tmp_path: Path) -> None:
    text = "this is not [valid toml"
    path = _write_product(tmp_path, "test_product", text)
    original = path.read_bytes()

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.REFUSED_SYNTAX_ERROR
    assert result.detail is not None
    assert path.read_bytes() == original


def test_a_product_that_would_still_be_invalid_refuses_and_changes_nothing(tmp_path: Path) -> None:
    """The combined text is re-parsed and validated as a Product before the
    write (ADR 0016's safety net): a base file missing required fields
    besides ``listing`` still fails, even though the create-only gate alone
    would have let it through."""
    text = "# missing every required Product field\n"
    path = _write_product(tmp_path, "test_product", text)
    original = path.read_bytes()

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.REFUSED_REVALIDATION_FAILED
    assert result.detail is not None
    assert path.read_bytes() == original


def test_preserves_crlf_line_endings(tmp_path: Path) -> None:
    text = _BASE_PRODUCT_TOML.replace("\n", "\r\n")
    path = _write_product(tmp_path, "test_product", text)
    original = path.read_bytes()
    assert b"\r\n" in original

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.APPENDED
    new_bytes = path.read_bytes()
    assert new_bytes.startswith(original)
    appended = new_bytes[len(original) :]
    assert b"\n" not in appended.replace(b"\r\n", b"")
    assert appended.count(b"\r\n") == appended.count(b"\n")


def test_preserves_lf_line_endings(tmp_path: Path) -> None:
    path = _write_product(tmp_path, "test_product", _BASE_PRODUCT_TOML)
    original = path.read_bytes()
    assert b"\r\n" not in original

    result = append_listing(tmp_path, CONFIG, "test_product", LISTING)

    assert result.outcome is ListingAppendOutcome.APPENDED
    new_bytes = path.read_bytes()
    appended = new_bytes[len(original) :]
    assert b"\r" not in appended
