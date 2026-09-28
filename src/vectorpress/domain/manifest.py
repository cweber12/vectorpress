"""The build manifest's shape (§14, ADR 0004, ADR 0005, CONTEXT.md
"Manifest").

A manifest is a tool-owned record of exactly what one build contained:
every included (asset, derivative type) with its effective-derivative
source and content hash, plus the product slug, the resolved reference
size, and the tool version (ADR 0004's "a build is a pure function of its
manifest inputs"). This module only defines that shape; ``build`` resolves
it from disk, serializes it to JSON, and writes it (ADR 0006 -- domain has
no I/O).

Deliberately minimal: excluded members and their reasons, admitted-
unapproved derivatives, rights status and warnings extend this shape as
further optional fields, never by reshaping ``members`` itself.
"""

from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import AssetId
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.product import ProductSlug


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
class Manifest:
    """One build's complete record (§14, ADR 0004): the product it built,
    the reference size it was built at, the tool version that built it, and
    every included member. ``members`` is sorted by (asset ID, derivative
    type) so two builds of unchanged inputs produce an identical manifest
    (§36)."""

    product_slug: ProductSlug
    reference_size_in: float
    tool_version: str
    members: list[ManifestMember]
