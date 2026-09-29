"""Whether a product needs rebuilding (§23, §34, ADR 0004, ADR 0014, ADR
0017, CONTEXT.md "Needs rebuild").

A product needs rebuild when its last manifest no longer matches what a
build would include right now: a hash comparison, never a timestamp (ADR
0004). :func:`compute_needs_rebuild` is the one answer ``cli`` (and a
future ``ui``) render -- ``vpress product`` shows it in full, ``vpress
status`` only counts it.

Pure read: comparing a manifest already on disk to the product's current
effective derivatives writes nothing. Below ``cli`` (CLAUDE.md's layering
guardrail), built on the same :func:`~vectorpress.build.product_resolution.
resolve_product` ``vpress build`` itself resolves membership through -- no
second resolution path.

**Previews out of date** (ADR 0014) and **listing changed** (ADR 0017) are
two more hash comparisons, alongside member differences and brand wording:
the current presentation hash and listing hash, computed the same way a
build would write them, compared to what the last manifest recorded. The
presentation hash's own dry render (:func:`~vectorpress.build.previews.
current_presentation_hash`) needs the same effective-derivative bytes member
differences already reads (:func:`_current_member_content`), read once and
shared rather than twice.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.build.previews import (
    PreviewRenderError,
    PreviewRenderFailure,
    current_presentation_hash,
)
from vectorpress.build.product_resolution import ProductMember, resolve_product
from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.manifests import ManifestFormatError, read_manifest
from vectorpress.catalog.overrides import effective_derivative
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.brand import Brand
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.format import Format
from vectorpress.domain.format_folder import copied_folder, dxf_filename, dxf_source
from vectorpress.domain.listing import Listing
from vectorpress.domain.manifest import Manifest
from vectorpress.domain.package_text import readme_wording_fingerprint
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_reference_size_in


class MemberDifferenceReason(StrEnum):
    """Why one (asset, derivative type) differs between a product's last
    manifest and its current effective derivatives (§23, CONTEXT.md "Needs
    rebuild")."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True)
class MemberDifference:
    """One (asset, derivative type) that differs, and why: present now but
    not in the last manifest (``added``), present in the last manifest but
    not now (``removed`` -- a source going missing, or a member no longer
    eligible), or present in both with a different content hash
    (``changed`` -- a regenerated source, or an override appearing or
    being discarded)."""

    asset_id: AssetId
    derivative_type: DerivativeType
    reason: MemberDifferenceReason


class NeedsRebuildOutcome(StrEnum):
    """One product's needs-rebuild outcome (CONTEXT.md "Needs rebuild"):
    its last manifest still matches, it does not, or there is no last
    manifest at all -- ``never built`` is distinct from ``needs rebuild``,
    never a special case of it."""

    CURRENT = "current"
    NEEDS_REBUILD = "needs_rebuild"
    NEVER_BUILT = "never_built"


@dataclass(frozen=True)
class ReferenceSizeChange:
    """The product's resolved reference size (§9.1, ADR 0012) at its last
    build, versus what it resolves to now -- both already resolved through
    :func:`~vectorpress.domain.reference_size.resolve_reference_size_in`,
    the same value the manifest itself records and README.txt's own "Files
    checked at reference size" line renders. A product override changing,
    or being added or removed, surfaces here the same as a catalog default
    change."""

    previous_in: float
    current_in: float


@dataclass(frozen=True)
class NeedsRebuildResult:
    """The result of :func:`compute_needs_rebuild`. ``member_differences``,
    ``license_template_changed``, ``readme_wording_changed``,
    ``reference_size_change``, ``previews_out_of_date`` and
    ``listing_changed`` are each empty/``False``/``None`` unless ``outcome``
    is :attr:`NeedsRebuildOutcome.NEEDS_REBUILD` -- together, every reason
    the product needs rebuilding. ``manifest_format_outdated`` is the one
    exception: set on its own, with every other field at its empty value,
    when the last manifest could not be read back at all (a real catalog's
    own build history predating a field this version added, CONTEXT.md
    "Needs rebuild") -- there is nothing to compare it against, so this is
    reported instead of any comparison.

    ``previews_out_of_date`` (ADR 0014) and ``listing_changed`` (ADR 0017)
    are both ``False`` -- not compared at all -- when the catalog currently
    has no valid brand or the product has no ``[listing]``: an actual
    rebuild would refuse on its own gate before ever reaching previews,
    which is not this comparison's concern (the same reasoning
    :func:`_brand_wording_differences` already applies to a missing
    brand).

    ``previews_render_failure`` is set only when computing the *current*
    presentation hash itself failed to render: a catalog override -- or a
    shipped template it extends -- with a syntax error, a missing file, or
    an undefined variable (the same :class:`~vectorpress.build.previews.
    PreviewRenderError` a real build would refuse on). ``previews_out_of_date``
    is then also ``True`` -- a build would refuse identically, so this is
    reported as the same reason rather than raised: needs-rebuild is a
    read-only comparison (this module's own docstring), and a broken
    catalog override must never crash ``vpress status`` or ``vpress
    product``."""

    outcome: NeedsRebuildOutcome
    member_differences: list[MemberDifference]
    license_template_changed: bool
    readme_wording_changed: bool
    reference_size_change: ReferenceSizeChange | None
    manifest_format_outdated: bool
    previews_out_of_date: bool
    listing_changed: bool
    previews_render_failure: PreviewRenderFailure | None


def _current_member_content(
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    root: Path,
    config: CatalogConfig,
    derivative_types: list[DerivativeType],
) -> dict[AssetId, dict[DerivativeType, bytes]]:
    """Every currently eligible member's own included derivative types'
    effective bytes, read the same way :func:`~vectorpress.build.
    product_build.build_product` reads them for the manifest and previews it
    writes: eligibility already means every one of a product's own
    ``derivative_types`` is approved (or admitted) and on disk for that
    member (§10), so the effective derivative is always found here. Shared
    by member-difference hashing (:func:`_current_member_hashes`) and the
    presentation hash's own dry render (:func:`~vectorpress.build.previews.
    current_presentation_hash`, ADR 0014), which needs the identical bytes
    to satisfy previews' fixed context -- read once, not twice."""
    content: dict[AssetId, dict[DerivativeType, bytes]] = {}
    for member in eligible_members:
        asset = assets_by_id[member.asset_id]
        asset_dir_path = asset_dir(root, config, asset.id)
        for derivative_type in derivative_types:
            filename = derivative_filename(asset.display_name, derivative_type)
            effective = effective_derivative(asset_dir_path, filename)
            assert effective is not None  # eligible => approved => the file exists on disk
            content.setdefault(asset.id, {})[derivative_type] = effective.bytes
    return content


def _current_member_hashes(
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> dict[tuple[AssetId, DerivativeType], str]:
    """:func:`_current_member_content`'s own bytes, hashed the same way
    :func:`~vectorpress.build.product_build.build_product` hashes them for
    the manifest it writes."""
    return {
        (asset_id, derivative_type): sha256_bytes(content)
        for asset_id, content_by_type in content_by_member.items()
        for derivative_type, content in content_by_type.items()
    }


def _current_files_by_folder(
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
    assets_by_id: dict[AssetId, Asset],
    formats: list[Format],
) -> dict[str, list[str]]:
    """A ``files_by_folder`` for the presentation hash's own dry render
    (ADR 0014): every eligible member includes the identical set of
    derivative types (eligibility's own guarantee, :func:`_current_member_content`'s
    own docstring), so this mirrors :func:`~vectorpress.build.product_build.
    build_product`'s file planning without a second read of any file
    already loaded into ``content_by_member``. Never part of the
    presentation hash itself -- only a value previews' fixed context reads
    (``product.formats[].file_count``), which this function's one caller
    then discards along with the rest of the dry render's HTML."""
    files_by_folder: dict[str, list[str]] = {}
    for asset_id, content_by_type in content_by_member.items():
        asset = assets_by_id[asset_id]
        for derivative_type in content_by_type:
            folder = copied_folder(derivative_type)
            assert folder is not None  # every derivative type fills SVG or PNG (ADR 0013)
            filename = derivative_filename(asset.display_name, derivative_type)
            files_by_folder.setdefault(folder.value.upper(), []).append(filename)
        if Format.DXF in formats:
            source_type = dxf_source(content_by_type)
            if source_type is not None:
                filename = dxf_filename(asset.display_name, source_type)
                files_by_folder.setdefault(Format.DXF.value.upper(), []).append(filename)
    return files_by_folder


def _listing_hash(listing: Listing) -> str:
    """The ADR 0017 listing hash, computed the same way
    :func:`~vectorpress.build.product_build.build_product` computes it for
    the manifest it writes."""
    return sha256_bytes(json.dumps(listing.model_dump(), sort_keys=True).encode("utf-8"))


def _member_differences(
    manifest: Manifest, current_hashes: dict[tuple[AssetId, DerivativeType], str]
) -> list[MemberDifference]:
    """Every :class:`MemberDifference` between ``manifest``'s own members
    and ``current_hashes`` (§23), sorted by (asset ID, derivative type) for
    a deterministic report."""
    last_hashes = {
        (member.asset_id, member.derivative_type): member.content_hash
        for member in manifest.members
    }

    differences: list[MemberDifference] = []
    for key in sorted(set(current_hashes) | set(last_hashes)):
        asset_id, derivative_type = key
        if key not in last_hashes:
            differences.append(
                MemberDifference(asset_id, derivative_type, MemberDifferenceReason.ADDED)
            )
        elif key not in current_hashes:
            differences.append(
                MemberDifference(asset_id, derivative_type, MemberDifferenceReason.REMOVED)
            )
        elif current_hashes[key] != last_hashes[key]:
            differences.append(
                MemberDifference(asset_id, derivative_type, MemberDifferenceReason.CHANGED)
            )
    return differences


def _brand_wording_differences(
    root: Path, brand: Brand | None, manifest: Manifest
) -> tuple[bool, bool]:
    """Whether the brand's license template or README wording (§27) has
    changed since ``manifest`` was written. ``False`` for both when the
    catalog currently has no valid ``brand.toml`` at all, or the license
    template it names is missing -- either way an actual rebuild would
    refuse on its own brand gate, which is not this function's concern."""
    if brand is None:
        return False, False

    license_template_changed = False
    license_path = root / brand.license_file
    if license_path.is_file():
        current_hash = sha256_bytes(license_path.read_text(encoding="utf-8").encode("utf-8"))
        license_template_changed = current_hash != manifest.license_template_hash

    current_readme_hash = sha256_bytes(
        readme_wording_fingerprint(
            brand.readme_text, brand.standard_wording, brand.copyright_wording
        ).encode("utf-8")
    )
    readme_wording_changed = current_readme_hash != manifest.readme_wording_hash

    return license_template_changed, readme_wording_changed


def _presentation_and_listing_differences(
    root: Path,
    config: CatalogConfig,
    product: Product,
    brand: Brand | None,
    manifest: Manifest,
    resolved_eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> tuple[bool, bool, PreviewRenderFailure | None]:
    """Whether the presentation hash (ADR 0014) or the listing hash (ADR
    0017) has changed since ``manifest`` was written. Both ``False``, and
    no failure -- not compared at all -- when the catalog currently has no
    valid brand or the product has no ``[listing]``: either way an actual
    rebuild would refuse on its own listing/brand gate before ever reaching
    previews, which is not this function's concern (the same reasoning
    :func:`_brand_wording_differences` already applies to a missing
    brand).

    The listing hash is compared independently of whether the presentation
    hash's own dry render succeeds: a broken catalog override says nothing
    about whether ``[listing]`` also changed, and an edited listing field
    must still be reported even when previews cannot currently render.

    A :class:`~vectorpress.build.previews.PreviewRenderError` from the dry
    render itself (a catalog override, or a shipped template it extends,
    with a syntax error, a missing file, or an undefined variable) is
    caught here, never left to propagate: it is reported as
    ``previews_out_of_date=True`` with its own
    :class:`~vectorpress.build.previews.PreviewRenderFailure` detail,
    exactly the reason an actual rebuild would refuse for -- a read-only
    command must never crash over a catalog problem a build would simply
    name.
    """
    if brand is None or product.listing is None:
        return False, False, None

    listing_changed = _listing_hash(product.listing) != manifest.listing_hash

    files_by_folder = _current_files_by_folder(content_by_member, assets_by_id, product.formats)
    try:
        current_presentation = current_presentation_hash(
            root,
            product,
            brand,
            resolved_eligible_members,
            assets_by_id,
            content_by_member,
            files_by_folder,
        )
    except PreviewRenderError as exc:
        failure = PreviewRenderFailure(template_name=exc.template_name, message=str(exc))
        return True, listing_changed, failure

    previews_out_of_date = current_presentation != manifest.presentation_hash
    return previews_out_of_date, listing_changed, None


def _empty_result(
    outcome: NeedsRebuildOutcome, *, manifest_format_outdated: bool = False
) -> NeedsRebuildResult:
    """A :class:`NeedsRebuildResult` with no comparison at all -- every
    outcome that has nothing to compare against (never built, or the
    manifest predating the current format) shares this empty shape, so each
    caller states only the one field that actually differs from it."""
    return NeedsRebuildResult(
        outcome,
        member_differences=[],
        license_template_changed=False,
        readme_wording_changed=False,
        reference_size_change=None,
        manifest_format_outdated=manifest_format_outdated,
        previews_out_of_date=False,
        listing_changed=False,
        previews_render_failure=None,
    )


def compute_needs_rebuild(
    product: Product,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
) -> NeedsRebuildResult:
    """Whether ``product`` needs rebuilding (§23, ADR 0004): compares its
    last manifest (:func:`~vectorpress.catalog.manifests.read_manifest`) to
    its current effective derivatives.

    Membership re-resolves through :func:`~vectorpress.build.
    product_resolution.resolve_product`, the same one path ``vpress build``
    itself uses -- with ``allow_unapproved`` set to whatever the last build
    itself recorded, not always ``False``: a build made with
    ``--allow-unapproved`` must not show its own admitted members as
    ``removed`` merely because this check forgot the flag that build used.

    A last manifest that exists but no longer parses (§23, a real catalog's
    own build history predating a field a newer tool version added) reports
    :attr:`NeedsRebuildOutcome.NEEDS_REBUILD` with
    ``manifest_format_outdated`` set instead of raising -- there is nothing
    on record to compare against, so no other field is populated.

    Two more hash comparisons join member differences and brand wording:
    the current presentation hash (ADR 0014) against a brand edit, a
    catalog template override, or a replaced mark or font file --
    **previews out of date** -- and the current ``[listing]`` hash (ADR
    0017) against an edited listing field -- **listing changed**. A catalog
    override that fails to render at all is reported as the same
    **previews out of date** reason, with its own detail
    (:attr:`NeedsRebuildResult.previews_render_failure`), never raised.
    """
    try:
        manifest = read_manifest(root, product.slug)
    except ManifestFormatError:
        return _empty_result(NeedsRebuildOutcome.NEEDS_REBUILD, manifest_format_outdated=True)
    if manifest is None:
        return _empty_result(NeedsRebuildOutcome.NEVER_BUILT)

    resolved = resolve_product(
        product,
        root,
        config,
        known_assets,
        known_collections,
        allow_unapproved=manifest.allow_unapproved,
    )
    assets_by_id = {asset.id: asset for asset in known_assets}
    content_by_member = _current_member_content(
        resolved.eligible_members, assets_by_id, root, config, product.derivative_types
    )
    current_hashes = _current_member_hashes(content_by_member)
    member_differences = _member_differences(manifest, current_hashes)

    brand_result = load_brand(root)
    brand = brand_result.brand
    license_template_changed, readme_wording_changed = _brand_wording_differences(
        root, brand, manifest
    )
    previews_out_of_date, listing_changed, previews_render_failure = (
        _presentation_and_listing_differences(
            root,
            config,
            product,
            brand,
            manifest,
            resolved.eligible_members,
            assets_by_id,
            content_by_member,
        )
    )

    current_reference_size_in = resolve_reference_size_in(config, product)
    reference_size_change = (
        ReferenceSizeChange(manifest.reference_size_in, current_reference_size_in)
        if current_reference_size_in != manifest.reference_size_in
        else None
    )

    if (
        not member_differences
        and not license_template_changed
        and not readme_wording_changed
        and reference_size_change is None
        and not previews_out_of_date
        and not listing_changed
    ):
        return _empty_result(NeedsRebuildOutcome.CURRENT)

    return NeedsRebuildResult(
        NeedsRebuildOutcome.NEEDS_REBUILD,
        member_differences=member_differences,
        license_template_changed=license_template_changed,
        readme_wording_changed=readme_wording_changed,
        reference_size_change=reference_size_change,
        manifest_format_outdated=False,
        previews_out_of_date=previews_out_of_date,
        listing_changed=listing_changed,
        previews_render_failure=previews_render_failure,
    )
