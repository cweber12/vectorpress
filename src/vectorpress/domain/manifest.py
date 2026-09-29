"""The build manifest's shape (§14, ADR 0004, ADR 0005, CONTEXT.md
"Manifest").

A manifest is a tool-owned record of exactly what one build contained:
every included (asset, derivative type) with its effective-derivative
source and content hash, plus the product slug, the resolved reference
size, the calendar year substituted into LICENSE.txt's ``{year}``
placeholder (§27), and the tool version (ADR 0004's "a build is a pure
function of its manifest inputs"). This module only defines that shape;
``build`` resolves it from disk, serializes it to JSON, and writes it
(ADR 0006 -- domain has no I/O).

Deliberately minimal: further facts extend this shape as additional
optional fields, never by reshaping ``members`` itself.
"""

from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import AssetId, RightsStatus
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import BlockingReason
from vectorpress.domain.product import ProductSlug
from vectorpress.domain.status import Status


class ManifestMemberSource(StrEnum):
    """Which file one manifest member's content hash describes (CONTEXT.md
    "Effective derivative"): the hand-edited override, or the generated
    derivative -- never both, since the override is always the effective
    one when present."""

    GENERATED = "generated"
    OVERRIDE = "override"


@dataclass(frozen=True)
class ManifestMember:
    """One (asset, derivative type) a build included: which file was
    effective, its content hash, and its customer path within the
    package's own top-level folder (e.g. ``"PNG/ochre-sea-star-color.png"``,
    never including the package name itself -- that name comes from the
    product's listing, not from what the build actually contains)."""

    asset_id: AssetId
    derivative_type: DerivativeType
    source: ManifestMemberSource
    content_hash: str
    package_path: str


@dataclass(frozen=True)
class ManifestDxfMember:
    """One ``DXF/`` file a build produced (ADR 0013): the (asset, derivative
    type) it was converted from, that derivative's own content hash, this
    DXF's own content hash, and its customer path.

    A separate list from :class:`ManifestMember` rather than another entry
    in it (this module's own "extend... never by reshaping ``members``
    itself"): a copied file's one hash describes the one file it is: a
    converted one has two -- the source it came from, and its own -- and
    ``ManifestMember`` has no field for a second hash.
    """

    asset_id: AssetId
    source_derivative_type: DerivativeType
    source_content_hash: str
    content_hash: str
    package_path: str


@dataclass(frozen=True)
class ManifestAdmittedUnapproved:
    """One (asset, derivative type) a build shipped despite it not being
    approved, under a per-build ``--allow-unapproved`` override (§10.1's
    "unless explicitly overridden"): its status at build time, so the
    manifest alone shows exactly what shipped unreviewed. Never a
    ``rejected`` or ``regenerate`` status -- those still exclude their
    member regardless of the override."""

    asset_id: AssetId
    derivative_type: DerivativeType
    status: Status


@dataclass(frozen=True)
class ManifestExcludedMember:
    """One member an ``exclude`` build left out (§10, CONTEXT.md "Excluded
    member"): the asset ID and every §10.1 blocking reason product
    resolution found for it, so a build's manifest alone answers "why isn't
    this asset in this pack" without re-resolving the product."""

    asset_id: AssetId
    blocking_reasons: list[BlockingReason]


@dataclass(frozen=True)
class ManifestAssetRightsStatus:
    """One included asset's rights status (§26, CONTEXT.md "Rights
    status"): recorded for every shipped member, not only ``ai_generated``
    ones, so a later marketplace disclosure step never has to re-open
    ``asset.toml`` to learn whether an asset shipped was AI-generated."""

    asset_id: AssetId
    rights_status: RightsStatus


@dataclass(frozen=True)
class ManifestCleanupSizeWarning:
    """One eligible member whose included ``cut_svg`` was cleaned at a
    smaller **cleanup size** than the product's own resolved reference size
    (ADR 0012, CONTEXT.md "Cleanup size"): a non-blocking build warning,
    since cleanup may have removed detail that would cut cleanly at the
    larger size and findings cannot show what was taken out."""

    asset_id: AssetId
    cleanup_size_in: float


@dataclass(frozen=True)
class ManifestByteIdenticalDerivatives:
    """One member whose included derivatives are byte-identical for two or
    more derivative types (e.g. a one-color asset's ``silhouette_svg`` and
    ``flatcolor_svg``): a non-blocking build warning -- both still ship,
    since package contents follow the product definition, not file
    contents. ``derivative_types`` is sorted and holds every type sharing
    ``content_hash``, not only the first pair found."""

    asset_id: AssetId
    derivative_types: list[DerivativeType]
    content_hash: str


@dataclass(frozen=True)
class Manifest:
    """One build's complete record (§14, §23, ADR 0004): the product it
    built, the reference size it was built at, the LICENSE.txt build year,
    the tool version that built it, every included member, every excluded
    one (empty unless the product is set to ``exclude``, §10), every
    converted ``DXF/`` file, and every derivative admitted despite not
    being approved (empty unless the build ran with ``--allow-unapproved``).
    ``members`` and ``dxf_members`` are each sorted by (asset ID, derivative
    type), ``excluded_members`` by asset ID, and
    ``admitted_unapproved_members`` by (asset ID, derivative type), so two
    builds of unchanged inputs produce an identical manifest (§36).
    ``license_year`` is the one field expected to change on its own with no
    other input changing -- once a calendar year turns over -- which is why
    it is recorded rather than left implicit (§27's "must not break the
    rebuild-is-identical rule within a year").

    ``license_template_hash`` and ``readme_wording_hash`` are content
    hashes of the brand's own license template and README wording (§27) --
    recorded so needs-rebuild (§23, CONTEXT.md "Needs rebuild") can detect a
    brand edit that touches no member at all. ``allow_unapproved`` records
    whether this build ran with ``--allow-unapproved``, so needs-rebuild can
    re-resolve eligibility under the identical setting rather than showing
    this build's own admitted members as spuriously ``removed``.

    ``asset_rights_statuses`` records every eligible member's own rights
    status (§26), one entry per asset ID (not per member row: an asset with
    several included derivative types still gets one entry), sorted by
    asset ID -- the input a later marketplace-disclosure step reads rather
    than re-loading every member's own ``asset.toml``.

    ``cleanup_size_warnings`` and ``byte_identical_derivatives`` are two
    non-blocking build warnings (§9, §20, ADR 0012): a member sold larger
    than its cut file's own cleanup size, and a member whose included
    derivatives duplicate each other's bytes. Neither excludes or drops a
    file -- both are reported for a human to act on, or not.

    ``previews`` is every preview file this build rendered (§16, ADR 0014),
    each path relative to the build directory (e.g.
    ``"previews/01-main-square.png"``), sorted for a deterministic manifest
    (§36) -- never an image hash: previews are not held to byte-identical
    output (ADR 0014), so needs-rebuild compares a separate presentation
    hash, not these file names, once that slice lands.
    """

    product_slug: ProductSlug
    reference_size_in: float
    license_year: int
    tool_version: str
    license_template_hash: str
    readme_wording_hash: str
    allow_unapproved: bool
    members: list[ManifestMember]
    dxf_members: list[ManifestDxfMember]
    excluded_members: list[ManifestExcludedMember]
    admitted_unapproved_members: list[ManifestAdmittedUnapproved]
    asset_rights_statuses: list[ManifestAssetRightsStatus]
    cleanup_size_warnings: list[ManifestCleanupSizeWarning]
    byte_identical_derivatives: list[ManifestByteIdenticalDerivatives]
    previews: list[str]
