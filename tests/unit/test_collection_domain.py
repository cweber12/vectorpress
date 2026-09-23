"""domain.collection: the Collection metadata model (§11, ADR 0008, issue #5)."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.collection import Collection
from vectorpress.domain.membership import MembershipForm

VALID_DATA = {
    "slug": "pacific_coast_tide_pool",
    "name": "Pacific Coast Tide Pool",
    "description": "Tide pool subjects along the Pacific coast.",
    "tags": ["tide pool", "pacific coast"],
    "marketplace_category": "Nature & Wildlife",
    "membership": {"asset_ids": ["ochre_sea_star", "purple_sea_urchin"]},
}


def test_valid_collection_parses() -> None:
    collection = Collection.model_validate(VALID_DATA)

    assert collection.slug == "pacific_coast_tide_pool"
    assert collection.name == "Pacific Coast Tide Pool"
    assert collection.membership.form is MembershipForm.EXPLICIT


def test_tags_default_to_empty() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "tags"}

    collection = Collection.model_validate(data)

    assert collection.tags == []


def test_unknown_key_is_rejected() -> None:
    data = {**VALID_DATA, "not_a_field": True}

    with pytest.raises(ValidationError):
        Collection.model_validate(data)


def test_missing_required_field_is_rejected() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "description"}

    with pytest.raises(ValidationError):
        Collection.model_validate(data)


def test_missing_membership_is_rejected() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "membership"}

    with pytest.raises(ValidationError):
        Collection.model_validate(data)


@pytest.mark.parametrize(
    "excluded_field",
    ["included_variants", "included_formats", "tier", "price", "version"],
)
def test_fields_moved_to_product_or_dropped_are_not_accepted(excluded_field: str) -> None:
    """ADR 0008 moves included variants/formats/tier/price to the product;
    "version" is not a field at all (ADR 0004, content-addressed
    provenance).
    """
    data = {**VALID_DATA, excluded_field: ["x"]}

    with pytest.raises(ValidationError):
        Collection.model_validate(data)
