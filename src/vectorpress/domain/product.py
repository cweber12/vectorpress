"""The product metadata model (ADR 0008, CONTEXT.md "Product").

No I/O here (ADR 0006): this module only defines and validates the shape of
one product's ``<slug>.toml``. Finding product files and reading them off
disk is the ``catalog`` layer's job.

A product is exactly one collection (referenced by slug) or an inline one
(the same ``Membership`` shape a collection file uses), plus presentation:
included derivative types, included deliverable formats, an optional
reference size override, tier and family labels, price, how an ineligible
member is handled (§10), and an optional listing (issue #7, ADR 0008).
Whether a referenced collection slug, or an inline membership's asset IDs
and collection slugs, actually exist is left to PRD 5 (this module has no
catalog awareness, per ADR 0006).
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from vectorpress.domain.collection import CollectionSlug
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.format import Format
from vectorpress.domain.format_folder import format_type_mismatch_problems
from vectorpress.domain.listing import Listing
from vectorpress.domain.membership import Membership
from vectorpress.domain.metadata_field_error import MetadataFieldError, MetadataFieldsError

#: A product's stable identifier; also its file's stem (CONTEXT.md).
ProductSlug = str


class ProductTier(StrEnum):
    """A badge/category label on a product (§13, CONTEXT.md "Tier").

    A label only, not a mechanism: membership is still declared entirely by
    ``collection_slug`` or ``membership``.
    """

    INDIVIDUAL = "individual"
    MINI_PACK = "mini_pack"
    STANDARD_PACK = "standard_pack"
    COLLECTION = "collection"
    MEGA_BUNDLE = "mega_bundle"


class IneligibleMembersMode(StrEnum):
    """How a build handles a resolved member that is not eligible for this
    product's own derivative types (§10, §10.1, CONTEXT.md "Excluded
    member"): ``refuse`` fails the whole build naming every ineligible
    member and its reasons (the default); ``exclude`` ships the eligible
    members instead, recording each excluded one in the manifest with its
    reasons, and still refuses when none are eligible.
    """

    REFUSE = "refuse"
    EXCLUDE = "exclude"


class Product(BaseModel):
    """One product's hand-authored metadata (``<slug>.toml``).

    Read-only to the tool (ADR 0005) except for ``listing``, which the tool
    drafts once on first build (PRD 7) and never touches again. ``slug`` is
    always the file's stem; the ``catalog`` layer is responsible for
    checking that a ``slug`` key present in the file agrees with the stem
    before constructing this model.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    slug: ProductSlug
    collection_slug: CollectionSlug | None = None
    membership: Membership | None = None
    # Strict mode otherwise requires actual enum instances; these come from
    # TOML as plain strings, so validate each item leniently (per-item, not
    # per-field: a field-level ``strict=False`` does not relax list items).
    derivative_types: list[Annotated[DerivativeType, Field(strict=False)]] = Field(min_length=1)
    enable_pdf_eps: bool = False
    formats: list[Annotated[Format, Field(strict=False)]] = Field(min_length=1)
    reference_size_in: float | None = None
    tier: ProductTier = Field(strict=False)
    family: str | None = None
    price: float = Field(ge=0)
    ineligible_members: IneligibleMembersMode = Field(
        default=IneligibleMembersMode.REFUSE, strict=False
    )
    listing: Listing | None = None

    @model_validator(mode="after")
    def _references_exactly_one_collection(self) -> "Product":
        if (self.collection_slug is None) == (self.membership is None):
            raise MetadataFieldError(
                "collection_slug/membership",
                "product must reference a collection slug or declare an inline "
                "collection, not both or neither",
            )
        return self

    @field_validator("formats", mode="after")
    @classmethod
    def _pdf_and_eps_require_explicit_enablement(
        cls, formats: list[Format], info: ValidationInfo
    ) -> list[Format]:
        enable_pdf_eps = info.data.get("enable_pdf_eps", False)
        if not enable_pdf_eps and any(fmt in (Format.PDF, Format.EPS) for fmt in formats):
            raise ValueError("pdf and eps formats require enable_pdf_eps = true")
        return formats

    @model_validator(mode="after")
    def _formats_and_derivative_types_agree_with_the_format_folder_table(self) -> "Product":
        """A listed format no included type fills, or an included type no
        listed format carries, is a product metadata problem at load time
        (ADR 0013), not a build failure."""
        problems = format_type_mismatch_problems(self.formats, self.derivative_types)
        if problems:
            raise MetadataFieldsError(problems)
        return self
