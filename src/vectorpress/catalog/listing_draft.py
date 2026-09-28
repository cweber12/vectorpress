"""Append a drafted ``[listing]`` table to a product's TOML file (§18,
ADR 0016) -- the tool's one sanctioned write into a hand-authored file
(ADR 0005).

Create-only: refuses whenever a ``listing`` key is already present in the
file, valid or not (checked on the raw parsed dict, never on a validated
``Product`` -- an invalid ``[listing]`` would otherwise fail the whole
product's validation before this ever got a chance to say why). The write
itself is a raw append: every existing byte, including the file's own line
endings, is left untouched, and the combined text is re-parsed and
validated as a ``Product`` before :func:`~vectorpress.catalog.atomic_write.
atomic_write_bytes` replaces the file -- so a bug in the drafted values can
never corrupt a hand-authored file.
"""

import tomllib
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.atomic_write import atomic_write_bytes
from vectorpress.catalog.products import product_toml_path
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.listing import Listing
from vectorpress.domain.product import Product, ProductSlug

#: The command name the appended header comment credits (§18, ADR 0016).
COMMAND_NAME = "vpress listing draft"


class ListingAppendOutcome(StrEnum):
    """One :func:`append_listing` outcome (ADR 0016): appended, or refused
    -- writing nothing -- for one of four reasons."""

    APPENDED = "appended"
    REFUSED_FILE_NOT_FOUND = "refused_file_not_found"
    REFUSED_SYNTAX_ERROR = "refused_syntax_error"
    REFUSED_ALREADY_HAS_LISTING = "refused_already_has_listing"
    REFUSED_REVALIDATION_FAILED = "refused_revalidation_failed"


@dataclass(frozen=True)
class ListingAppendResult:
    """The outcome of one :func:`append_listing` call. ``detail`` carries
    the syntax or validation error text for the two outcomes that have one;
    ``None`` for the other three."""

    outcome: ListingAppendOutcome
    detail: str | None = None


def _detect_newline(data: bytes) -> bytes:
    """The line ending already used in ``data``: CRLF if any line uses it,
    else LF -- so the appended text matches the file's own convention
    instead of introducing a mixed-ending file (ADR 0016's "keeps the
    file's line endings")."""
    return b"\r\n" if b"\r\n" in data else b"\n"


#: TOML basic-string escapes for the characters with a short form (the TOML
#: spec's own table); every other control character falls through to
#: ``_toml_string``'s ``\\u00XX`` case below.
_TOML_SHORT_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_string(value: str) -> str:
    """One TOML basic string for ``value``.

    Only backslash, double quote, and control characters (``U+0000``-
    ``U+001F`` and ``U+007F``) need escaping; every other character --
    including one outside the Basic Multilingual Plane, like an emoji -- is
    written out literally, since a TOML file is UTF-8 text and a basic
    string may hold any Unicode scalar value as-is. ``json.dumps`` looks
    equivalent but is not: its default ``ensure_ascii=True`` re-encodes a
    non-BMP character as a UTF-16 surrogate pair, and TOML has no such
    escape -- ``tomllib`` rejects it as "not a Unicode scalar value", so a
    display name or collection description with an emoji would fail this
    module's own pre-write revalidation on every draft.
    """
    escaped: list[str] = []
    for char in value:
        short = _TOML_SHORT_ESCAPES.get(char)
        if short is not None:
            escaped.append(short)
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04x}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _toml_array(values: list[str]) -> str:
    """One single-line TOML array of strings."""
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _listing_table_text(listing: Listing, drafted_on: date) -> str:
    """The appended ``[listing]`` table's text (LF-joined; the caller
    translates to the file's own line ending), opening with the header
    comment ADR 0016 requires: naming the command, the date, and that the
    tool never rewrites this table again."""
    lines = [
        f"# Drafted by `{COMMAND_NAME}` on {drafted_on.isoformat()}.",
        "# The tool never rewrites this table -- edit it by hand, or delete",
        "# it and run the command again to redraft.",
        "[listing]",
        f"title = {_toml_string(listing.title)}",
        f"short_title = {_toml_string(listing.short_title)}",
        f"description = {_toml_string(listing.description)}",
        f"tags = {_toml_array(listing.tags)}",
        f"search_terms = {_toml_array(listing.search_terms)}",
        f"intended_uses = {_toml_array(listing.intended_uses)}",
    ]
    if listing.region is not None:
        lines.append(f"region = {_toml_string(listing.region)}")
    lines.extend(
        [
            f"species_names = {_toml_array(listing.species_names)}",
            f"category = {_toml_string(listing.category)}",
            f"license_type = {_toml_string(listing.license_type)}",
            f"marketplace_notes = {_toml_string(listing.marketplace_notes)}",
        ]
    )
    return "\n".join(lines) + "\n"


def append_listing(
    root: Path,
    config: CatalogConfig,
    slug: ProductSlug,
    listing: Listing,
    *,
    today: date | None = None,
) -> ListingAppendResult:
    """Append ``listing`` to ``products/<slug>.toml`` as its ``[listing]``
    table, create-only (ADR 0016): refuses and writes nothing when the file
    does not exist, fails to parse, or already has a ``listing`` key --
    valid or not.

    The combined text is re-parsed and validated as a ``Product`` before
    the atomic replace; a failure there also writes nothing (this should
    never happen for a ``listing`` this module itself built, but is the
    hard safety net ADR 0016 asks for regardless of what the caller already
    checked).
    """
    full_path = root / product_toml_path(config, slug)
    if not full_path.is_file():
        return ListingAppendResult(ListingAppendOutcome.REFUSED_FILE_NOT_FOUND)

    original = full_path.read_bytes()
    try:
        data = tomllib.loads(original.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return ListingAppendResult(ListingAppendOutcome.REFUSED_SYNTAX_ERROR, detail=str(exc))

    if "listing" in data:
        return ListingAppendResult(ListingAppendOutcome.REFUSED_ALREADY_HAS_LISTING)

    newline = _detect_newline(original)
    appended = _listing_table_text(listing, today if today is not None else date.today())
    appended_bytes = appended.encode("utf-8").replace(b"\n", newline)

    combined = original
    if not combined.endswith(newline):
        combined += newline
    combined += newline + appended_bytes

    try:
        combined_data = tomllib.loads(combined.decode("utf-8"))
        combined_data.pop("slug", None)
        Product.model_validate({**combined_data, "slug": slug})
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        return ListingAppendResult(
            ListingAppendOutcome.REFUSED_REVALIDATION_FAILED, detail=str(exc)
        )

    atomic_write_bytes(full_path, combined)
    return ListingAppendResult(ListingAppendOutcome.APPENDED)
