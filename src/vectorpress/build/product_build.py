"""Build one product into a customer package, its ZIP, and a manifest (§14,
§15, §20, §27, §35, §36, ADR 0004, ADR 0005, ADR 0008, ADR 0013).

Only ``SVG/`` and ``PNG/`` are built here (ADR 0013's fixed table); DXF
conversion and the ``exclude`` ineligibility mode are not. Every package
also carries a brand-supplied ``README.txt`` and ``LICENSE.txt`` at its top
level (§27). One function, :func:`build_product`, does the whole thing --
``cli`` (and later ``ui``) only render its :class:`BuildResult`.

**Brand gate.** A build refuses -- writes nothing -- without a valid
``brand.toml`` naming an existing ``license_file`` (there is no default
brand, since a default would ship as the customer's license terms), and
refuses again if that license template names a placeholder besides
``{brand}``, ``{product}``, ``{copyright}`` or ``{year}``. Checked before
membership resolves, since neither depends on it.

**Eligibility gate (default refuse).** A build refuses -- writes nothing --
if the product's membership does not fully resolve, or if any member is not
eligible for the product's own derivative types (§10, §10.1). Nothing about
excluding ineligible members instead (§10's ``exclude`` mode) is built yet.

**Customer file name collisions.** Two members whose customer file names
collide within one format folder also refuse the build, before anything is
written, naming every asset ID sharing that name (§20).

**All-or-nothing (§35).** Every file the build produces is written under a
fresh temporary directory first; only once that succeeds does it replace
``builds/<product-slug>/`` in one move, so a failure never leaves that
directory half-written and never touches any other product's build.

**Repeatable (§36).** The ZIP's entries are sorted by their path and written
with a fixed timestamp and permission bits, so unchanged inputs reproduce a
byte-identical ZIP.
"""

import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from vectorpress import __version__
from vectorpress.build.product_resolution import ProductMember, resolve_product
from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.overrides import effective_derivative
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.format_folder import copied_folder
from vectorpress.domain.manifest import Manifest, ManifestMember, ManifestMemberSource
from vectorpress.domain.package_naming import package_name
from vectorpress.domain.package_text import (
    UnknownLicensePlaceholderError,
    render_license_text,
    render_readme_text,
)
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_reference_size_in
from vectorpress.pipeline.eligibility import included_derivatives

#: The two brand-supplied plain-text files every package carries at its top
#: level, beside its format folders (§14, §27).
README_FILENAME = "README.txt"
LICENSE_FILENAME = "LICENSE.txt"

#: Every build's output lives under this catalog-root-relative directory,
#: never under ``sources/``, ``derived/``, ``overrides/`` or any
#: hand-authored file (ADR 0005): the package, its ZIP, and the manifest,
#: one subdirectory per product slug.
BUILDS_DIRNAME = "builds"

#: The build's own JSON manifest file, sibling to the package directory and
#: the ZIP inside ``builds/<product-slug>/``.
MANIFEST_FILENAME = "manifest.json"

#: The fixed ZIP entry timestamp (§36): the DOS epoch, the same floor
#: ``zipfile`` itself accepts, so two builds of unchanged inputs are
#: byte-identical regardless of when either ran.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: The fixed ZIP entry permission bits (§36): a regular, world-readable file
#: (``0o644``), packed into ``external_attr`` the way Unix zip tools do --
#: applied to every entry, so permissions never vary by platform or by
#: whatever the source file happened to have on disk.
_ZIP_EXTERNAL_ATTR = 0o644 << 16


@dataclass(frozen=True)
class _PlannedFile:
    """One customer file a build would write: which (asset, derivative
    type) it comes from, the format folder it belongs in (already
    uppercased, e.g. ``"SVG"``), and its customer-facing filename --
    computed from display names alone, before anything is read from disk,
    so a name collision (§20) is caught without writing anything."""

    asset_id: AssetId
    derivative_type: DerivativeType
    folder: str
    filename: str


def _included_types_by_asset(
    eligible_members: list[ProductMember],
    assets_by_id: dict[AssetId, Asset],
    root: Path,
    config: CatalogConfig,
    derivative_types: list[DerivativeType],
) -> dict[AssetId, list[DerivativeType]]:
    """Every eligible member's own included derivative types, resolved the
    same way :func:`~vectorpress.build.product_resolution.resolve_product`
    resolved them to decide eligibility (:func:`~vectorpress.pipeline.
    eligibility.included_derivatives`) -- kept as a plain side table rather
    than a :class:`ProductMember` field, since product resolution itself has
    no further use for it once eligibility is decided."""
    return {
        member.asset_id: [
            item.derivative_type
            for item in included_derivatives(
                assets_by_id[member.asset_id],
                asset_dir(root, config, member.asset_id),
                derivative_types,
                config,
            )
        ]
        for member in eligible_members
    }


def _plan_files(
    eligible_members: list[ProductMember],
    included_types_by_asset: dict[AssetId, list[DerivativeType]],
    assets_by_id: dict[AssetId, Asset],
) -> list[_PlannedFile]:
    """Every customer file :func:`build_product` would write for
    ``eligible_members`` (ADR 0013, §20), computed from display names alone
    so a name collision is found before anything is read from disk."""
    planned: list[_PlannedFile] = []
    for member in eligible_members:
        asset = assets_by_id[member.asset_id]
        for derivative_type in included_types_by_asset[member.asset_id]:
            folder = copied_folder(derivative_type)
            assert folder is not None  # every derivative type fills SVG or PNG (ADR 0013)
            filename = derivative_filename(asset.display_name, derivative_type)
            planned.append(_PlannedFile(asset.id, derivative_type, folder.value.upper(), filename))
    return planned


@dataclass(frozen=True)
class NameCollision:
    """Two or more members whose customer file name collides within one
    format folder (§20): the folder, the shared filename, and every asset ID
    sharing it, sorted."""

    folder: str
    filename: str
    asset_ids: list[AssetId]


def _find_name_collisions(planned: list[_PlannedFile]) -> list[NameCollision]:
    """Every :class:`NameCollision` among ``planned`` (§20): two members
    whose display name slugifies to the same filename within the same
    format folder. Grouped by (folder, filename), sorted for a deterministic
    report."""
    by_key: dict[tuple[str, str], set[AssetId]] = {}
    for file in planned:
        by_key.setdefault((file.folder, file.filename), set()).add(file.asset_id)

    collisions = [
        NameCollision(folder, filename, sorted(asset_ids))
        for (folder, filename), asset_ids in by_key.items()
        if len(asset_ids) > 1
    ]
    collisions.sort(key=lambda collision: (collision.folder, collision.filename))
    return collisions


class BuildOutcome(StrEnum):
    """One ``vpress build`` outcome (§14, §35): built, or refused for one of
    five reasons, each leaving the previous build (if any) untouched and
    writing nothing new."""

    BUILT = "built"
    REFUSED_BRAND_PROBLEMS = "refused_brand_problems"
    REFUSED_LICENSE_TEMPLATE_PROBLEM = "refused_license_template_problem"
    REFUSED_REFERENCE_PROBLEMS = "refused_reference_problems"
    REFUSED_INELIGIBLE_MEMBERS = "refused_ineligible_members"
    REFUSED_NAME_COLLISION = "refused_name_collision"


@dataclass(frozen=True)
class BuildResult:
    """The outcome of one :func:`build_product` call. Exactly one of
    ``brand_problems``, ``unknown_license_placeholders``,
    ``reference_problems``, ``ineligible_members`` or ``name_collisions`` is
    set for its matching refusal outcome; ``manifest``/``package_dir``/
    ``zip_path`` are set exactly when ``outcome`` is
    :attr:`BuildOutcome.BUILT`."""

    outcome: BuildOutcome
    brand_problems: list[MetadataProblem] | None = None
    unknown_license_placeholders: list[str] | None = None
    reference_problems: list[MetadataProblem] | None = None
    ineligible_members: list[ProductMember] | None = None
    name_collisions: list[NameCollision] | None = None
    manifest: Manifest | None = None
    package_dir: Path | None = None
    zip_path: Path | None = None


def _current_year() -> int:
    """The calendar year LICENSE.txt's ``{year}`` placeholder substitutes
    (§27): a thin wrapper around ``date.today()`` so tests can fix the year
    (monkeypatching this function) without waiting for a real year
    boundary to prove the "unchanged rebuild" repeatability rule holds
    within one."""
    return date.today().year


def _product_title(product: Product) -> str:
    """LICENSE.txt's ``{product}`` placeholder (§27): the product's listing
    title, else its slug -- the same fallback ``vpress product`` already
    uses for a product with no ``[listing]`` drafted yet."""
    return product.listing.title if product.listing is not None else product.slug


def _manifest_json_bytes(manifest: Manifest) -> bytes:
    """``manifest`` as deterministic JSON bytes (§36): sorted keys, a fixed
    2-space indent, and ``members`` already sorted by :func:`build_product`
    -- so unchanged inputs serialize identically every time."""
    payload = {
        "product_slug": manifest.product_slug,
        "reference_size_in": manifest.reference_size_in,
        "license_year": manifest.license_year,
        "tool_version": manifest.tool_version,
        "members": [
            {
                "asset_id": member.asset_id,
                "derivative_type": member.derivative_type.value,
                "source": member.source.value,
                "content_hash": member.content_hash,
                "package_path": member.package_path,
            }
            for member in manifest.members
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _write_deterministic_zip(
    zip_path: Path, top_level_name: str, files: list[tuple[str, bytes]]
) -> None:
    """Write ``files`` (each ``(path relative to the top-level folder,
    bytes)``) to ``zip_path`` as one ZIP whose single top-level folder is
    ``top_level_name`` (§15), with entries sorted by path and a fixed
    timestamp and permission bits (§36) so unchanged ``files`` always
    produce byte-identical output."""
    with zipfile.ZipFile(zip_path, "w") as zip_file:
        for rel_path, data in sorted(files, key=lambda entry: entry[0]):
            info = zipfile.ZipInfo(f"{top_level_name}/{rel_path}", date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _ZIP_EXTERNAL_ATTR
            info.create_system = 0
            zip_file.writestr(info, data)


def _swap_into_place(tmp_dir: Path, target_dir: Path) -> None:
    """Replace ``target_dir`` with ``tmp_dir`` in as close to one atomic
    step as the filesystem allows (§35): a previous build is renamed aside,
    ``tmp_dir`` takes its place, and only then is the old one removed. A
    failure renaming ``tmp_dir`` into place renames the old build straight
    back to ``target_dir`` before re-raising, so it is always found at its
    own canonical path afterward -- never stranded under its temporary
    name -- whether the swap succeeded or not."""
    if not target_dir.exists():
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir.rename(target_dir)
        return

    backup_dir = target_dir.with_name(f".old-{target_dir.name}-{uuid4().hex}")
    target_dir.rename(backup_dir)
    try:
        tmp_dir.rename(target_dir)
    except BaseException:
        backup_dir.rename(target_dir)
        raise
    shutil.rmtree(backup_dir)


def build_product(
    product: Product,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
) -> BuildResult:
    """Build ``product`` into ``builds/<product.slug>/`` (§14): a package
    directory holding its ``SVG/`` and ``PNG/`` folders, that same package
    zipped, and a manifest -- or refuse and write nothing (§35), per this
    module's own docstring.

    Membership resolves exactly the way ``vpress product`` shows it
    (:func:`~vectorpress.build.product_resolution.resolve_product`, ADR
    0011): no second resolution path.
    """
    brand_result = load_brand(root)
    if brand_result.brand is None:
        return BuildResult(
            BuildOutcome.REFUSED_BRAND_PROBLEMS, brand_problems=brand_result.problems
        )
    brand = brand_result.brand

    license_year = _current_year()
    license_template = (root / brand.license_file).read_text(encoding="utf-8")
    try:
        license_text = render_license_text(
            license_template,
            brand_name=brand.name,
            product_title=_product_title(product),
            copyright_wording=brand.copyright_wording,
            year=license_year,
        )
    except UnknownLicensePlaceholderError as exc:
        return BuildResult(
            BuildOutcome.REFUSED_LICENSE_TEMPLATE_PROBLEM,
            unknown_license_placeholders=exc.placeholders,
        )

    resolved = resolve_product(product, root, config, known_assets, known_collections)

    if resolved.reference_problems:
        return BuildResult(
            BuildOutcome.REFUSED_REFERENCE_PROBLEMS,
            reference_problems=resolved.reference_problems,
        )
    if resolved.excluded_members:
        return BuildResult(
            BuildOutcome.REFUSED_INELIGIBLE_MEMBERS,
            ineligible_members=resolved.excluded_members,
        )

    assets_by_id = {asset.id: asset for asset in known_assets}
    included_types_by_asset = _included_types_by_asset(
        resolved.eligible_members, assets_by_id, root, config, product.derivative_types
    )

    planned = _plan_files(resolved.eligible_members, included_types_by_asset, assets_by_id)
    collisions = _find_name_collisions(planned)
    if collisions:
        return BuildResult(BuildOutcome.REFUSED_NAME_COLLISION, name_collisions=collisions)

    reference_size_in = resolve_reference_size_in(config, product)
    top_level_name = package_name(
        product.listing.short_title if product.listing is not None else None, product.slug
    )

    package_files: list[tuple[str, bytes]] = []
    manifest_members: list[ManifestMember] = []
    for file in planned:
        asset_dir_path = asset_dir(root, config, file.asset_id)
        effective = effective_derivative(asset_dir_path, file.filename)
        assert effective is not None  # eligible => approved => the file exists on disk
        rel_path = f"{file.folder}/{file.filename}"
        package_files.append((rel_path, effective.bytes))
        manifest_members.append(
            ManifestMember(
                asset_id=file.asset_id,
                derivative_type=file.derivative_type,
                source=(
                    ManifestMemberSource.OVERRIDE
                    if effective.is_override
                    else ManifestMemberSource.GENERATED
                ),
                content_hash=sha256_bytes(effective.bytes),
                package_path=rel_path,
            )
        )

    files_by_folder: dict[str, list[str]] = {}
    for rel_path, _ in package_files:
        folder, _, filename = rel_path.partition("/")
        files_by_folder.setdefault(folder, []).append(filename)

    readme_text = render_readme_text(
        intro=brand.readme_text,
        standard_wording=brand.standard_wording,
        copyright_wording=brand.copyright_wording,
        included_formats=list(files_by_folder),
        files_by_folder=files_by_folder,
        reference_size_in=reference_size_in,
    )
    package_files.append((README_FILENAME, readme_text.encode("utf-8")))
    package_files.append((LICENSE_FILENAME, license_text.encode("utf-8")))

    manifest_members.sort(key=lambda member: (member.asset_id, member.derivative_type.value))
    manifest = Manifest(
        product_slug=product.slug,
        reference_size_in=reference_size_in,
        license_year=license_year,
        tool_version=__version__,
        members=manifest_members,
    )

    builds_dir = root / BUILDS_DIRNAME
    builds_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = builds_dir / f".tmp-{product.slug}-{uuid4().hex}"
    tmp_dir.mkdir()
    try:
        package_dir = tmp_dir / top_level_name
        for rel_path, data in package_files:
            file_path = package_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(data)

        zip_path = tmp_dir / f"{top_level_name}.zip"
        _write_deterministic_zip(zip_path, top_level_name, package_files)

        (tmp_dir / MANIFEST_FILENAME).write_bytes(_manifest_json_bytes(manifest))

        target_dir = builds_dir / product.slug
        _swap_into_place(tmp_dir, target_dir)
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    final_dir = builds_dir / product.slug
    return BuildResult(
        BuildOutcome.BUILT,
        manifest=manifest,
        package_dir=final_dir / top_level_name,
        zip_path=final_dir / f"{top_level_name}.zip",
    )
