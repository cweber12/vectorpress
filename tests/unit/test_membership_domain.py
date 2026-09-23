"""domain.membership: the reusable membership declaration (explicit list,
metadata rule, union of collection slugs, or a mix) shared by collections
and, inline, by products (ADR 0008, issue #5).
"""

import pytest
from pydantic import ValidationError

from vectorpress.domain.membership import (
    ClassificationField,
    Membership,
    MembershipForm,
    MembershipRule,
)

# --- MembershipRule -----------------------------------------------------------------


def test_valid_rule_parses() -> None:
    rule = MembershipRule.model_validate({"field": "ecosystems", "values": ["Kelp forest"]})

    assert rule.field is ClassificationField.ECOSYSTEMS
    assert rule.values == ["Kelp forest"]


def test_rule_rejects_an_unknown_classification_field() -> None:
    with pytest.raises(ValidationError):
        MembershipRule.model_validate({"field": "not_a_real_field", "values": ["x"]})


def test_rule_rejects_empty_values() -> None:
    with pytest.raises(ValidationError):
        MembershipRule.model_validate({"field": "tags", "values": []})


def test_rule_rejects_a_blank_value() -> None:
    with pytest.raises(ValidationError):
        MembershipRule.model_validate({"field": "tags", "values": ["  "]})


def test_rule_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        MembershipRule.model_validate({"field": "tags", "values": ["a"], "not_a_field": True})


def test_classification_field_has_exactly_the_documented_fields() -> None:
    assert {member.value for member in ClassificationField} == {
        "tags",
        "regions",
        "ecosystems",
        "group",
        "category",
    }


# --- Membership: form ----------------------------------------------------------------


def test_explicit_only_membership_has_explicit_form() -> None:
    membership = Membership.model_validate({"asset_ids": ["ochre_sea_star"]})

    assert membership.form is MembershipForm.EXPLICIT


def test_rule_only_membership_has_rule_form() -> None:
    membership = Membership.model_validate(
        {"rule": {"field": "ecosystems", "values": ["Kelp forest"]}}
    )

    assert membership.form is MembershipForm.RULE


def test_union_only_membership_has_union_form() -> None:
    membership = Membership.model_validate({"collection_slugs": ["other_collection"]})

    assert membership.form is MembershipForm.UNION


def test_membership_combining_two_forms_is_mixed() -> None:
    membership = Membership.model_validate(
        {
            "asset_ids": ["ochre_sea_star"],
            "rule": {"field": "tags", "values": ["tide pool"]},
        }
    )

    assert membership.form is MembershipForm.MIXED


def test_membership_combining_all_three_forms_is_mixed() -> None:
    membership = Membership.model_validate(
        {
            "asset_ids": ["ochre_sea_star"],
            "rule": {"field": "tags", "values": ["tide pool"]},
            "collection_slugs": ["other_collection"],
        }
    )

    assert membership.form is MembershipForm.MIXED


def test_empty_membership_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Membership.model_validate({})


def test_membership_rejects_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        Membership.model_validate({"asset_ids": ["a"], "not_a_field": True})
