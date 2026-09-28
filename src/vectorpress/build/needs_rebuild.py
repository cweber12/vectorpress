"""Whether a product needs rebuilding (§23, §34, ADR 0004, CONTEXT.md
"Needs rebuild").

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
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.build.product_resolution import ProductMember, resolve_product
from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.manifests import read_manifest
from vectorpress.catalog.overrides import effective_derivative
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.manifest import Manifest
from vectorpress.domain.package_text import readme_wording_fingerprint
from vectorpress.domain.product import Product


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
class NeedsRebuildResult:
    """The result of :func:`compute_needs_rebuild`. ``member_differences``,
    ``license_template_changed`` and ``readme_wording_changed`` are each
    empty/``False`` unless ``outcome`` is
    :attr:`NeedsRebuildOutcome.NEEDS_REBUILD` -- together, every reason the
    product needs rebuilding."""

    outcome: NeedsRebuildOutcome
    member_differences: list[MemberDifference]
    license_template_changed: bool
    readme_wording_changed: bool


def _current_member_hashes(
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    root: Path,
    config: CatalogConfig,
    derivative_types: list[DerivativeType],
) -> dict[tuple[AssetId, DerivativeType], str]:
    """Every currently eligible member's own included derivative types,
    hashed the same way :func:`~vectorpress.build.product_build.
    build_product` hashes them for the manifest it writes: eligibility
    already means every one of a product's own ``derivative_types`` is
    approved (or admitted) and on disk for that member (§10), so the
    effective derivative is always found here."""
    hashes: dict[tuple[AssetId, DerivativeType], str] = {}
    for member in eligible_members:
        asset = assets_by_id[member.asset_id]
        asset_dir_path = asset_dir(root, config, asset.id)
        for derivative_type in derivative_types:
            filename = derivative_filename(asset.display_name, derivative_type)
            effective = effective_derivative(asset_dir_path, filename)
            assert effective is not None  # eligible => approved => the file exists on disk
            hashes[(asset.id, derivative_type)] = sha256_bytes(effective.bytes)
    return hashes


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


def _brand_wording_differences(root: Path, manifest: Manifest) -> tuple[bool, bool]:
    """Whether the brand's license template or README wording (§27) has
    changed since ``manifest`` was written. ``False`` for both when the
    catalog currently has no valid ``brand.toml`` at all, or the license
    template it names is missing -- either way an actual rebuild would
    refuse on its own brand gate, which is not this function's concern."""
    brand_result = load_brand(root)
    brand = brand_result.brand
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
    """
    manifest = read_manifest(root, product.slug)
    if manifest is None:
        return NeedsRebuildResult(NeedsRebuildOutcome.NEVER_BUILT, [], False, False)

    resolved = resolve_product(
        product,
        root,
        config,
        known_assets,
        known_collections,
        allow_unapproved=manifest.allow_unapproved,
    )
    assets_by_id = {asset.id: asset for asset in known_assets}
    current_hashes = _current_member_hashes(
        resolved.eligible_members, assets_by_id, root, config, product.derivative_types
    )
    member_differences = _member_differences(manifest, current_hashes)
    license_template_changed, readme_wording_changed = _brand_wording_differences(root, manifest)

    if not member_differences and not license_template_changed and not readme_wording_changed:
        return NeedsRebuildResult(NeedsRebuildOutcome.CURRENT, [], False, False)

    return NeedsRebuildResult(
        NeedsRebuildOutcome.NEEDS_REBUILD,
        member_differences,
        license_template_changed,
        readme_wording_changed,
    )
