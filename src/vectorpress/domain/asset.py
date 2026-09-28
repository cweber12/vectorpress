"""The asset metadata model.

No I/O here (ADR 0006): this module only defines and validates the shape of
one asset's ``asset.toml``. Finding asset folders and reading files off disk
is the ``catalog`` layer's job.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

#: The stable snake_case identifier of an asset; also its folder name
#: (CONTEXT.md). Never customer-facing.
AssetId = str


class RightsStatus(StrEnum):
    """Asset-level licensing state (§26). Hand-authored (ADR 0005)."""

    ORIGINAL_ARTWORK = "original_artwork"
    LICENSED_SOURCE = "licensed_source"
    PUBLIC_DOMAIN_SOURCE = "public_domain_source"
    AI_GENERATED = "ai_generated"
    RIGHTS_VERIFIED = "rights_verified"
    RIGHTS_REVIEW_REQUIRED = "rights_review_required"
    DO_NOT_PUBLISH = "do_not_publish"


class AccuracyStatus(StrEnum):
    """Asset-level scientific-accuracy state (§25). Hand-authored (ADR 0005)."""

    NOT_REVIEWED = "not_reviewed"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ISSUE_FOUND = "issue_found"


class Source(BaseModel):
    """One preserved source image and its role (ADR 0003, CONTEXT.md).

    ``file`` names a file relative to the asset's ``sources/`` directory,
    never modified by the tool (§21). ``role`` is one of the built-in
    roles or one a catalog adds via ``catalog.toml``'s ``extra_roles``;
    checking that is the ``catalog`` layer's job, since this module has no
    catalog awareness (ADR 0006) and is validated as a plain string here.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    role: str
    file: str


class DerivativePin(BaseModel):
    """A ``[derivatives.<type>]`` table of per-asset settings for one
    derivative type (ADR 0003, ADR 0012, CONTEXT.md "Recipe", "Cleanup
    size"): a source pin, a cleanup-size override, or neither (an empty
    table is valid and means no settings).

    ``source``, when set, names a file the same way ``Source.file`` does:
    relative to the asset's ``sources/`` directory. Checking that it names a
    declared source whose role the type's recipe accepts, and that the type
    has a recipe at all, is the ``catalog`` layer's job (this module has no
    recipe or filesystem awareness, per ADR 0006); an asset with an invalid
    pin does not load (same rule declared sources follow).

    ``reference_size_in`` is the asset's own **cleanup size** for
    ``cut_svg`` -- the size its one cut file is cleaned at in place of the
    catalog default. Checking that it is only ever set on ``cut_svg`` is
    also the ``catalog`` layer's job, for the same reason: this model has no
    idea which type's table it is. Enforced here regardless of type: a
    non-positive size cleans nothing.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source: str | None = None
    reference_size_in: float | None = Field(default=None, gt=0)


class Asset(BaseModel):
    """One asset's hand-authored metadata (``asset.toml``).

    Read-only to the tool (ADR 0005): loading validates this shape, nothing
    in this codebase writes it back. ``id`` is always the asset's folder
    name (CONTEXT.md); the ``catalog`` layer is responsible for checking
    that an ``id`` key present in the file agrees with the folder before
    constructing this model.

    ``sources`` is one entry per ``[[sources]]`` table; validating each
    source's role and file against the filesystem and the catalog's
    accepted roles is the ``catalog`` layer's job (this module has no
    catalog or filesystem awareness, per ADR 0006).

    ``derivatives`` maps a derivative type's name (a
    :class:`~vectorpress.domain.derivative_type.DerivativeType` value, e.g.
    ``"transparent_png"``) to its per-asset settings, one entry per
    ``[derivatives.<type>]`` table (ADR 0012). Kept a plain ``str`` key here
    rather than ``DerivativeType`` for the same reason ``Source.role`` is a
    plain ``str``: whether the key names a real derivative type with a
    recipe, whether a source pin is valid, and whether a setting like
    ``reference_size_in`` applies to that type at all, is the ``catalog``
    layer's job.
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
    sources: list[Source] = Field(default_factory=lambda: [])
    derivatives: dict[str, DerivativePin] = Field(default_factory=dict)
