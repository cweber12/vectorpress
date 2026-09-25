"""The membership declaration shared by collections and (inline, per #7)
products: an explicit list of asset IDs, a metadata rule over asset
classifications, a union of other collection slugs, or a mix of any of
those (ADR 0008, CONTEXT.md "Collection").

No I/O here (ADR 0006): this only defines and validates shape. Resolving a
rule or union into actual members — checking that asset IDs and collection
slugs exist, evaluating a rule against loaded assets, and following a union
recursively — is ``domain.collection_resolution.resolve_membership``, wired
to a loaded catalog by ``catalog.collection_resolution`` (ADR 0011).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vectorpress.domain.asset import AssetId


class ClassificationField(StrEnum):
    """Asset classification fields a metadata rule may match on (§11).

    Named for what a rule matches against, not for the ``Asset`` attribute
    names: ``group`` and ``category`` stand for ``taxonomic_group`` and
    ``subject_category`` respectively. The mapping from rule field to asset
    attribute lives in ``domain.collection_resolution._asset_values_for_field``
    (this module has no catalog awareness, per ADR 0006).
    """

    TAGS = "tags"
    REGIONS = "regions"
    ECOSYSTEMS = "ecosystems"
    GROUP = "group"
    CATEGORY = "category"


class MembershipForm(StrEnum):
    """How a membership declares its members, for display (``vpress collections``)."""

    EXPLICIT = "explicit"
    RULE = "rule"
    UNION = "union"
    MIXED = "mixed"


class MembershipRule(BaseModel):
    """One metadata rule: an asset classification field and the values it
    must match.

    Parsed and validated for shape only (known classification field,
    non-empty values); whether any asset actually matches is
    ``domain.collection_resolution.resolve_rule``'s job.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    # Strict mode otherwise requires an actual enum instance; this comes
    # from TOML as a plain string, so validate it by value instead.
    field: ClassificationField = Field(strict=False)
    values: list[str] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def _values_are_not_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("values must not be blank")
        return values


class Membership(BaseModel):
    """Explicit list, metadata rule, union of collection slugs, or a mix
    (ADR 0008).

    At least one of ``asset_ids``, ``rule`` or ``collection_slugs`` must be
    present. Whether the referenced asset IDs or collection slugs exist is
    ``domain``/``catalog``'s ``collection_resolution``'s job (this module
    has no catalog awareness, per ADR 0006).
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    asset_ids: list[AssetId] = Field(default_factory=list)
    rule: MembershipRule | None = None
    collection_slugs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _declares_at_least_one_form(self) -> "Membership":
        if not self.asset_ids and self.rule is None and not self.collection_slugs:
            raise ValueError("membership must declare asset_ids, a rule, or collection_slugs")
        return self

    @property
    def form(self) -> MembershipForm:
        """Which membership form(s) this declaration uses, for display."""
        forms_used = (bool(self.asset_ids), self.rule is not None, bool(self.collection_slugs))
        if sum(forms_used) > 1:
            return MembershipForm.MIXED
        if self.asset_ids:
            return MembershipForm.EXPLICIT
        if self.rule is not None:
            return MembershipForm.RULE
        return MembershipForm.UNION
