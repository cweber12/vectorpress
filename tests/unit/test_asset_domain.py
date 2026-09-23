"""domain.asset: the Asset metadata model, rights status and accuracy status."""

import pytest
from pydantic import ValidationError

from vectorpress.domain.asset import AccuracyStatus, Asset, RightsStatus, Source

VALID_DATA = {
    "id": "ochre_sea_star",
    "common_name": "Ochre sea star",
    "display_name": "Ochre Sea Star",
    "scientific_name": "Pisaster ochraceus",
    "description": "A common Pacific coast sea star found in the rocky intertidal.",
    "subject_category": "Echinoderm",
    "tags": ["sea star", "tide pool"],
    "regions": ["California", "Oregon"],
    "ecosystems": ["Tide pool", "Rocky intertidal"],
    "taxonomic_group": "Echinoderm",
    "product_use_categories": ["apparel", "stickers"],
    "notes": "Five-armed color variant.",
    "rights_status": "original_artwork",
    "licensing_notes": "Original illustration.",
    "accuracy_status": "approved",
}


def test_valid_asset_parses() -> None:
    asset = Asset.model_validate(VALID_DATA)

    assert asset.id == "ochre_sea_star"
    assert asset.rights_status is RightsStatus.ORIGINAL_ARTWORK
    assert asset.accuracy_status is AccuracyStatus.APPROVED
    assert asset.sources == []


def test_scientific_name_is_optional() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "scientific_name"}

    asset = Asset.model_validate(data)

    assert asset.scientific_name is None


def test_sources_parse_into_typed_source_entries() -> None:
    data = {
        **VALID_DATA,
        "sources": [{"role": "silhouette", "file": "silhouette.png"}],
    }

    asset = Asset.model_validate(data)

    assert asset.sources == [Source(role="silhouette", file="silhouette.png")]


def test_source_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        Source.model_validate({"role": "silhouette", "file": "silhouette.png", "extra": True})


def test_source_requires_role_and_file() -> None:
    with pytest.raises(ValidationError):
        Source.model_validate({"role": "silhouette"})


def test_unknown_key_is_rejected() -> None:
    data = {**VALID_DATA, "not_a_field": True}

    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_missing_required_field_is_rejected() -> None:
    data = {k: v for k, v in VALID_DATA.items() if k != "description"}

    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_rights_status_outside_the_allowed_list_is_rejected() -> None:
    data = {**VALID_DATA, "rights_status": "not_a_real_status"}

    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_accuracy_status_outside_the_allowed_list_is_rejected() -> None:
    data = {**VALID_DATA, "accuracy_status": "not_a_real_status"}

    with pytest.raises(ValidationError):
        Asset.model_validate(data)


def test_rights_status_has_exactly_the_section_26_states() -> None:
    assert {member.value for member in RightsStatus} == {
        "original_artwork",
        "licensed_source",
        "public_domain_source",
        "rights_verified",
        "rights_review_required",
        "do_not_publish",
    }


def test_accuracy_status_has_exactly_the_section_25_states() -> None:
    assert {member.value for member in AccuracyStatus} == {
        "not_reviewed",
        "reviewed",
        "approved",
        "issue_found",
    }
