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
class Manifest:
    """One build's complete record (§14, ADR 0004): the product it built,
    the reference size it was built at, the LICENSE.txt build year,
    the tool version that built it, every included member, and every
    converted ``DXF/`` file. ``members`` and ``dxf_members`` are each sorted
    by (asset ID, derivative type) so two builds of unchanged inputs produce
    an identical manifest (§36). ``license_year`` is the one field expected
    to change on its own with no other input changing -- once a calendar
    year turns over -- which is why it is recorded rather than left implicit
    (§27's "must not break the rebuild-is-identical rule within a year")."""

    product_slug: ProductSlug
    reference_size_in: float
    license_year: int
    tool_version: str
    members: list[ManifestMember]
    dxf_members: list[ManifestDxfMember]
