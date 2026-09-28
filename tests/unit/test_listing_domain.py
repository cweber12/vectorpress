"""domain.listing: a product's ``[listing]`` table, the §18 fields
(issue #7).
"""

import pytest
from pydantic import ValidationError

from vectorpress.domain.listing import Listing

VALID_DATA = {
    "title": "Pacific Coast Tide Pool Cut File Collection",
    "short_title": "Tide Pool Collection",
    "description": "A hand-illustrated set of Pacific coast tide pool species.",
    "tags": ["tide pool", "pacific coast"],
    "search_terms": ["tide pool svg"],
    "intended_uses": ["vinyl cutting"],
    "region": "Pacific Coast",
    "species_names": ["Ochre Sea Star"],
    "category": "Nature & Wildlife",
    "license_type": "Personal & Small Business Use",
    "marketplace_notes": "Feature with the rest of the family.",
}


def test_valid_listing_parses() -> None:
    listing = Listing.model_validate(VALID_DATA)

    assert listing.title == "Pacific Coast Tide Pool Cut File Collection"


def test_region_and_species_names_are_optional() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k not in {"region", "species_names"}}

    listing = Listing.model_validate(data)

    assert listing.region is None
    assert listing.species_names == []


def test_marketplace_notes_defaults_to_empty() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "marketplace_notes"}

    listing = Listing.model_validate(data)

    assert listing.marketplace_notes == ""


def test_missing_required_field_is_rejected() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "description"}

    with pytest.raises(ValidationError):
        Listing.model_validate(data)


def test_suggested_price_is_rejected_as_an_unknown_field() -> None:
    """§18: ``product.price`` is the one price; ``Listing`` carries no price
    field of its own at all."""
    data = {**VALID_DATA, "suggested_price": 12.0}

    with pytest.raises(ValidationError):
        Listing.model_validate(data)


def test_unknown_key_is_rejected() -> None:
    data = {**VALID_DATA, "not_a_field": True}

    with pytest.raises(ValidationError):
        Listing.model_validate(data)


@pytest.mark.parametrize(
    "excluded_field",
    ["asset_count", "included_formats", "asset_names", "collection_name", "version", "updated_at"],
)
def test_derived_listing_values_are_not_accepted(excluded_field: str) -> None:
    """§18 lists asset count, included formats, asset names, collection
    name, product version, and creation/update date among "listing
    metadata" — but issue #7 says these are computed at build time in
    later PRDs, not stored here.
    """
    data = {**VALID_DATA, excluded_field: "x"}

    with pytest.raises(ValidationError):
        Listing.model_validate(data)
