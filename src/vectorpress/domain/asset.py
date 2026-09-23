"""The asset metadata model.

No I/O here (ADR 0006): this module only defines and validates the shape of
one asset's ``asset.toml``. Finding asset folders and reading files off disk
is the ``catalog`` layer's job.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The stable snake_case identifier of an asset; also its folder name
#: (CONTEXT.md). Never customer-facing.
AssetId = str


class RightsStatus(StrEnum):
    """Asset-level licensing state (§26). Hand-authored (ADR 0005)."""

    ORIGINAL_ARTWORK = "original_artwork"
    LICENSED_SOURCE = "licensed_source"
    PUBLIC_DOMAIN_SOURCE = "public_domain_source"
    RIGHTS_VERIFIED = "rights_verified"
    RIGHTS_REVIEW_REQUIRED = "rights_review_required"
    DO_NOT_PUBLISH = "do_not_publish"


class AccuracyStatus(StrEnum):
    """Asset-level scientific-accuracy state (§25). Hand-authored (ADR 0005)."""

    NOT_REVIEWED = "not_reviewed"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ISSUE_FOUND = "issue_found"


class Asset(BaseModel):
    """One asset's hand-authored metadata (``asset.toml``).

    Read-only to the tool (ADR 0005): loading validates this shape, nothing
    in this codebase writes it back. ``id`` is always the asset's folder
    name (CONTEXT.md); the ``catalog`` layer is responsible for checking
    that an ``id`` key present in the file agrees with the folder before
    constructing this model.

    Source images are not parsed yet: ``sources`` is passed through
    untouched, one raw table per ``[[sources]]`` entry.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    id: AssetId
    common_name: str
    display_name: str
    scientific_name: str | None = None
    description: str
    subject_category: str
    tags: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    ecosystems: list[str] = Field(default_factory=list)
    taxonomic_group: str
    product_use_categories: list[str] = Field(default_factory=list)
    notes: str = ""
    # Strict mode otherwise requires an actual enum instance; these come from
    # TOML as plain strings, so validate them by value instead.
    rights_status: RightsStatus = Field(strict=False)
    licensing_notes: str = ""
    accuracy_status: AccuracyStatus = Field(strict=False)
    sources: list[dict[str, Any]] = Field(default_factory=lambda: [])
