"""Build one product into a customer package, its ZIP, and a manifest (§14,
§15, §20, §27, §35, §36, ADR 0004, ADR 0005, ADR 0008, ADR 0013).

``SVG/`` and ``PNG/`` are copied straight from their effective derivatives;
``DXF/`` is converted from the effective ``cut_svg``, else ``silhouette_svg``
(ADR 0013's fixed table, :mod:`vectorpress.build._dxf_conversion`). Every
package also carries a brand-supplied ``README.txt`` and ``LICENSE.txt`` at
its top level (§27). One function, :func:`build_product`, does the whole
thing -- ``cli`` (and later ``ui``) only render its :class:`BuildResult`.

**Listing gate (ADR 0016).** A build refuses -- writes nothing -- for a
product with no ``[listing]``: a product can load and resolve without one,
but the package name and LICENSE.txt's ``{product}`` both come from it, and
``vpress build`` never drafts or writes one itself. Checked first, since it
needs neither brand nor membership to decide.

**Brand gate.** A build refuses -- writes nothing -- without a valid
``brand.toml`` naming an existing ``license_file`` (there is no default
brand, since a default would ship as the customer's license terms), and
refuses again if that license template names a placeholder besides
``{brand}``, ``{product}``, ``{copyright}`` or ``{year}``. Checked before
membership resolves, since neither depends on it.

**Eligibility gate (§10).** A build refuses -- writes nothing -- if the
product's membership does not fully resolve. Whether an ineligible member
also refuses the build depends on ``product.ineligible_members``: the
default ``refuse`` fails the whole build naming every ineligible member and
its §10.1 reasons; ``exclude`` instead builds only the eligible members,
records each excluded one in the manifest with its reasons, and still
refuses, reporting that no member was eligible, when none are -- naming
every ineligible member below that, the same as ``refuse``.

``allow_unapproved`` (the per-build ``--allow-unapproved`` override, never
persisted) widens eligibility itself, not this gate: a ``generated`` or
``needs_review`` included derivative admits instead of blocking (§10.1's
"unless explicitly overridden"), recorded in the manifest's
``admitted_unapproved_members`` with its status at build time. It never
admits ``rejected`` or ``regenerate``, and never overrides a rights,
accuracy or licensing-notes block -- those members stay ineligible and this
gate still applies to them exactly as without the flag. Every eligible
member's rights status (§26) is recorded in the manifest's
``asset_rights_statuses`` regardless -- not only ``ai_generated`` ones --
for a later marketplace-disclosure step.

**Customer file name collisions.** Two members whose customer file names
collide within one format folder also refuse the build, before anything is
written, naming every asset ID sharing that name (§20).

**Cleanup-size and duplicate warnings (§9, §20, ADR 0012).** Two
non-blocking warnings, recorded in the manifest, never excluding or
dropping a file: a member whose included ``cut_svg`` was cleaned at a
smaller cleanup size than the product's own resolved reference size
(cleanup may have removed detail findings can't show was taken out), and a
member whose included derivatives duplicate each other's bytes (e.g. a
one-color asset's ``silhouette_svg`` and ``flatcolor_svg`` -- both still
ship, since package contents follow the product definition, not file
contents).

**DXF conversion failure.** Every ``DXF/`` file is converted while
:func:`build_product` is still only assembling its in-memory file list, so a
conversion failure (malformed path data, or the DXF writer itself failing)
refuses the whole build -- nothing written yet -- naming the asset and the
derivative type it was converting (§35).

**Preview rendering (§16, ADR 0014, ADR 0015).** Every preview type
(:mod:`vectorpress.build.previews`) renders at both fixed canvases from the
same in-memory data this function has already gathered for the package
itself -- no second read of any effective derivative. A rendering failure
(no Chromium, a catalog override with a syntax error or naming a missing
template, an undefined template variable, a template requesting a
disallowed URL) refuses the whole build the same way a DXF conversion
failure does, before anything is written; previews are never inside the
package or the ZIP (§14), and the manifest records their file names, never
image hashes -- plus the ADR 0014 presentation hash
(:attr:`~vectorpress.build.previews.PreviewRenderResult.presentation_hash`)
and the ADR 0017 listing hash (:func:`_listing_hash`), so
:mod:`~vectorpress.build.needs_rebuild` can report **previews out of date**
and **listing changed** without re-rendering anything.

**Catalog template overrides (ADR 0015).** ``BuildResult.template_overrides``
names every catalog ``templates/<kind>/`` file this build actually loaded --
today only ``previews/`` renders during a build, so it is
:func:`~vectorpress.build.previews.render_previews`'s own list; a later
export step adds its overrides to the same list, unchanged here. ``cli``
only renders it.

**Generic export (§18, §19, ADR 0017).** ``export/listing.json``
(:mod:`vectorpress.build.export`) is assembled from the product's
``[listing]``, this same manifest, its resolved eligible members and the
loaded collections, then written under the temp dir the same way previews
are -- beside ``package_dir``, never inside it, so it is never in the
package or the ZIP. No CSV. A failure assembling or writing it is not
caught specially: like every other write in the block below, it aborts the
whole build and leaves the previous build (if any) untouched (§35).

**All-or-nothing (§35).** Every file the build produces is written under a
fresh temporary directory first; only once that succeeds does it replace
``builds/<product-slug>/`` in one move, so a failure never leaves that
directory half-written and never touches any other product's build.

**Repeatable (§36).** The ZIP's entries are sorted by their path and written
with a fixed timestamp and permission bits, so unchanged inputs reproduce a
byte-identical ZIP.
"""

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from vectorpress import __version__
from vectorpress.build._dxf_conversion import DxfConversionError, svg_to_dxf_bytes
from vectorpress.build.export import (
    EXPORT_DIRNAME,
    LISTING_EXPORT_FILENAME,
    ListingExport,
    build_listing_export,
)
from vectorpress.build.previews import PreviewRenderError, PreviewRenderFailure, render_previews
from vectorpress.build.product_resolution import ProductMember, resolve_product
from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.manifests import BUILDS_DIRNAME, MANIFEST_FILENAME
from vectorpress.catalog.metadata_problem import MetadataProblem
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
from vectorpress.domain.manifest import (
    Manifest,
    ManifestAdmittedUnapproved,
    ManifestAssetRightsStatus,
    ManifestByteIdenticalDerivatives,
    ManifestCleanupSizeWarning,
    ManifestDxfMember,
    ManifestExcludedMember,
    ManifestMember,
    ManifestMemberSource,
)
from vectorpress.domain.package_naming import package_name
from vectorpress.domain.package_text import (
    UnknownLicensePlaceholderError,
    readme_wording_fingerprint,
    render_license_text,
    render_readme_text,
)
from vectorpress.domain.product import IneligibleMembersMode, Product
from vectorpress.domain.reference_size import resolve_cleanup_size_in, resolve_reference_size_in
from vectorpress.pipeline.eligibility import included_derivatives

#: The one converted (never copied) format folder (ADR 0013): every other
#: entry in a build's file list is a straight copy of an effective
#: derivative, so this is also the one marker :func:`build_product`'s main
#: loop needs to tell "convert this" apart from "copy this" for a planned
#: file.
_DXF_FOLDER = Format.DXF.value.upper()

#: The two brand-supplied plain-text files every package carries at its top
#: level, beside its format folders (§14, §27).
README_FILENAME = "README.txt"
LICENSE_FILENAME = "LICENSE.txt"

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
    formats: list[Format],
) -> list[_PlannedFile]:
    """Every customer file :func:`build_product` would write for
    ``eligible_members`` (ADR 0013, §20), computed from display names alone
    so a name collision is found before anything is read from disk.

    A member's own included types add one *copied* ``SVG/``/``PNG/`` entry
    each; when ``formats`` lists ``dxf``, one more *converted* ``DXF/``
    entry is added on top, from whichever type :func:`~vectorpress.domain.
    format_folder.dxf_source` picks for that member's own included types --
    its ``derivative_type`` names that source, not a type of its own, since
    a converted file is not itself a derivative type."""
    planned: list[_PlannedFile] = []
    for member in eligible_members:
        asset = assets_by_id[member.asset_id]
        included = included_types_by_asset[member.asset_id]
        for derivative_type in included:
            folder = copied_folder(derivative_type)
            assert folder is not None  # every derivative type fills SVG or PNG (ADR 0013)
            filename = derivative_filename(asset.display_name, derivative_type)
            planned.append(_PlannedFile(asset.id, derivative_type, folder.value.upper(), filename))

        if Format.DXF in formats:
            source_type = dxf_source(included)
            if source_type is not None:
                filename = dxf_filename(asset.display_name, source_type)
                planned.append(_PlannedFile(asset.id, source_type, _DXF_FOLDER, filename))
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


def _cleanup_size_warnings(
    eligible_members: list[ProductMember],
    included_types_by_asset: dict[AssetId, list[DerivativeType]],
    assets_by_id: dict[AssetId, Asset],
    config: CatalogConfig,
    reference_size_in: float,
) -> list[ManifestCleanupSizeWarning]:
    """One :class:`~vectorpress.domain.manifest.ManifestCleanupSizeWarning`
    per eligible member whose included ``cut_svg`` was cleaned at a smaller
    cleanup size than ``reference_size_in`` (ADR 0012): cleanup may have
    removed detail that would cut cleanly at the larger size, and findings
    can't show what was taken out. Sorted by asset ID (§36)."""
    warnings: list[ManifestCleanupSizeWarning] = []
    for member in eligible_members:
        if DerivativeType.CUT_SVG not in included_types_by_asset[member.asset_id]:
            continue
        cleanup_size_in = resolve_cleanup_size_in(config, assets_by_id[member.asset_id])
        if cleanup_size_in < reference_size_in:
            warnings.append(
                ManifestCleanupSizeWarning(
                    asset_id=member.asset_id, cleanup_size_in=cleanup_size_in
                )
            )
    warnings.sort(key=lambda warning: warning.asset_id)
    return warnings


def _byte_identical_derivative_warnings(
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]],
) -> list[ManifestByteIdenticalDerivatives]:
    """One :class:`~vectorpress.domain.manifest.ManifestByteIdenticalDerivatives`
    per group of two or more of one member's included derivatives that
    hash identically (e.g. a one-color asset's ``silhouette_svg`` and
    ``flatcolor_svg``): both still ship -- package contents follow the
    product definition, not file contents -- but the duplicate is worth a
    human's attention; the catalog-side fix is declaring no source for the
    redundant type, making it impossible instead of a duplicate. Sorted by
    (asset ID, first duplicated type) (§36)."""
    warnings: list[ManifestByteIdenticalDerivatives] = []
    for asset_id, content_by_type in content_by_member.items():
        by_hash: dict[str, list[DerivativeType]] = {}
        for derivative_type, content in content_by_type.items():
            by_hash.setdefault(sha256_bytes(content), []).append(derivative_type)
        for content_hash, derivative_types in by_hash.items():
            if len(derivative_types) < 2:
                continue
            warnings.append(
                ManifestByteIdenticalDerivatives(
                    asset_id=asset_id,
                    derivative_types=sorted(derivative_types, key=lambda t: t.value),
                    content_hash=content_hash,
                )
            )
    warnings.sort(key=lambda warning: (warning.asset_id, warning.derivative_types[0].value))
    return warnings


#: A preview file's own name (``build.previews.render_previews``):
#: ``previews/<nn>-<name>[-<page>]-<canvas>.png``. ``<page>`` is only ever
#: present for a paginated type (``contents``).
_PREVIEW_FILENAME_RE = re.compile(
    r"^previews/(?P<number>\d+)-[a-z]+(?:-(?P<page>\d+))?-(?P<canvas>[a-z]+)\.png$"
)


def _preview_upload_order_key(rel_path: str) -> tuple[int, int, str]:
    """Sort key for the manifest's own preview list: type number, then page
    number, then canvas name (§16) -- upload order, never a lexicographic
    sort of the whole file name, which would put ``05-contents-10`` before
    ``05-contents-2`` once a product's ``contents`` runs past nine pages."""
    match = _PREVIEW_FILENAME_RE.match(rel_path)
    assert match is not None  # every entry comes from render_previews's own naming
    return (int(match["number"]), int(match["page"] or 0), match["canvas"])


class BuildOutcome(StrEnum):
    """One ``vpress build`` outcome (§14, §35): built, or refused for one of
    eight reasons, each leaving the previous build (if any) untouched and
    writing nothing new."""

    BUILT = "built"
    REFUSED_NO_LISTING = "refused_no_listing"
    REFUSED_BRAND_PROBLEMS = "refused_brand_problems"
    REFUSED_LICENSE_TEMPLATE_PROBLEM = "refused_license_template_problem"
    REFUSED_REFERENCE_PROBLEMS = "refused_reference_problems"
    REFUSED_INELIGIBLE_MEMBERS = "refused_ineligible_members"
    REFUSED_NAME_COLLISION = "refused_name_collision"
    REFUSED_DXF_CONVERSION_FAILURE = "refused_dxf_conversion_failure"
    REFUSED_PREVIEW_RENDER_FAILURE = "refused_preview_render_failure"


@dataclass(frozen=True)
class DxfConversionFailure:
    """One member's ``DXF/`` conversion failure (§35): which asset and
    source derivative type was being converted when it failed, and the
    underlying error."""

    asset_id: AssetId
    source_derivative_type: DerivativeType
    message: str


@dataclass(frozen=True)
class BuildResult:
    """The outcome of one :func:`build_product` call. Exactly one of
    ``brand_problems``, ``unknown_license_placeholders``,
    ``reference_problems``, ``ineligible_members``, ``name_collisions``,
    ``dxf_conversion_failure`` or ``preview_render_failure`` is set for its
    matching refusal outcome (:attr:`BuildOutcome.REFUSED_NO_LISTING`
    carries none -- the slug the caller already has is enough to name the
    draft command); ``manifest``/``package_dir``/``zip_path``/
    ``template_overrides`` are set exactly when ``outcome`` is
    :attr:`BuildOutcome.BUILT`."""

    outcome: BuildOutcome
    brand_problems: list[MetadataProblem] | None = None
    unknown_license_placeholders: list[str] | None = None
    reference_problems: list[MetadataProblem] | None = None
    ineligible_members: list[ProductMember] | None = None
    name_collisions: list[NameCollision] | None = None
    dxf_conversion_failure: DxfConversionFailure | None = None
    preview_render_failure: PreviewRenderFailure | None = None
    manifest: Manifest | None = None
    package_dir: Path | None = None
    zip_path: Path | None = None
    template_overrides: list[str] | None = None


def _current_year() -> int:
    """The calendar year LICENSE.txt's ``{year}`` placeholder substitutes
    (§27): a thin wrapper around ``date.today()`` so tests can fix the year
    (monkeypatching this function) without waiting for a real year
    boundary to prove the "unchanged rebuild" repeatability rule holds
    within one."""
    return date.today().year


def _product_title(product: Product) -> str:
    """LICENSE.txt's ``{product}`` placeholder (§27): the product's listing
    title -- always set here, since :func:`build_product`'s own listing gate
    already refused a product with no ``[listing]`` before this is called."""
    assert product.listing is not None  # build_product's listing gate already refused
    return product.listing.title


def _license_template_hash(license_template: str) -> str:
    """The license template's own content hash (§23, §27, ADR 0004): the
    raw, unsubstituted template text, not the per-build rendered
    LICENSE.txt -- so a real calendar year turning over ``{year}`` never
    reads as a template edit (needs-rebuild compares this separately from
    ``license_year``)."""
    return sha256_bytes(license_template.encode("utf-8"))


def _readme_wording_hash(brand: Brand) -> str:
    """The brand's own README wording's content hash (§23, §27, ADR 0004):
    :func:`~vectorpress.domain.package_text.readme_wording_fingerprint` of
    the brand fields README.txt renders verbatim, hashed the same way every
    other manifest content hash is."""
    return sha256_bytes(
        readme_wording_fingerprint(
            brand.readme_text, brand.standard_wording, brand.copyright_wording
        ).encode("utf-8")
    )


def _listing_hash(listing: Listing) -> str:
    """The ADR 0017 listing hash: a content hash of the whole ``[listing]``
    table (§23, §34), so any field edit -- not only ``title``/``short_title``,
    the two the previews themselves print -- flags "listing changed",
    distinct from "previews out of date" (ADR 0014's own, narrower hash)."""
    return sha256_bytes(json.dumps(listing.model_dump(), sort_keys=True).encode("utf-8"))


def _manifest_json_bytes(manifest: Manifest) -> bytes:
    """``manifest`` as deterministic JSON bytes (§36): sorted keys, a fixed
    2-space indent, and ``members``/``excluded_members`` already sorted by
    :func:`build_product` -- so unchanged inputs serialize identically every
    time."""
    payload = {
        "product_slug": manifest.product_slug,
        "reference_size_in": manifest.reference_size_in,
        "license_year": manifest.license_year,
        "tool_version": manifest.tool_version,
        "license_template_hash": manifest.license_template_hash,
        "readme_wording_hash": manifest.readme_wording_hash,
        "allow_unapproved": manifest.allow_unapproved,
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
        "dxf_members": [
            {
                "asset_id": member.asset_id,
                "source_derivative_type": member.source_derivative_type.value,
                "source_content_hash": member.source_content_hash,
                "content_hash": member.content_hash,
                "package_path": member.package_path,
            }
            for member in manifest.dxf_members
        ],
        "excluded_members": [
            {
                "asset_id": member.asset_id,
                "blocking_reasons": [
                    {
                        "kind": reason.kind.value,
                        "derivative_type": (
                            reason.derivative_type.value
                            if reason.derivative_type is not None
                            else None
                        ),
                        "value": reason.value,
                    }
                    for reason in member.blocking_reasons
                ],
            }
            for member in manifest.excluded_members
        ],
        "admitted_unapproved_members": [
            {
                "asset_id": member.asset_id,
                "derivative_type": member.derivative_type.value,
                "status": member.status.value,
            }
            for member in manifest.admitted_unapproved_members
        ],
        "asset_rights_statuses": [
            {
                "asset_id": entry.asset_id,
                "rights_status": entry.rights_status.value,
            }
            for entry in manifest.asset_rights_statuses
        ],
        "cleanup_size_warnings": [
            {
                "asset_id": warning.asset_id,
                "cleanup_size_in": warning.cleanup_size_in,
            }
            for warning in manifest.cleanup_size_warnings
        ],
        "byte_identical_derivatives": [
            {
                "asset_id": warning.asset_id,
                "derivative_types": [t.value for t in warning.derivative_types],
                "content_hash": warning.content_hash,
            }
            for warning in manifest.byte_identical_derivatives
        ],
        "previews": manifest.previews,
        "presentation_hash": manifest.presentation_hash,
        "listing_hash": manifest.listing_hash,
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _listing_export_json_bytes(export: ListingExport) -> bytes:
    """``export`` as deterministic JSON bytes (§36), the same shape
    :func:`_manifest_json_bytes` gives ``manifest.json``: sorted keys, a
    fixed 2-space indent, a trailing newline -- so unchanged inputs
    serialize identically every time."""
    payload = {
        "listing": export.listing.model_dump(),
        "member_count": export.member_count,
        "formats": export.formats,
        "asset_names": export.asset_names,
        "collection_name": export.collection_name,
        "contents_summary": {
            "member_count": export.contents_summary.member_count,
            "formats": export.contents_summary.formats,
            "file_names": export.contents_summary.file_names,
            "reference_size_in": export.contents_summary.reference_size_in,
        },
        "price": export.price,
        "previews": export.previews,
        "zip_name": export.zip_name,
        "zip_size_bytes": export.zip_size_bytes,
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
    allow_unapproved: bool = False,
) -> BuildResult:
    """Build ``product`` into ``builds/<product.slug>/`` (§14): a package
    directory holding its ``SVG/`` and ``PNG/`` folders, that same package
    zipped, and a manifest -- or refuse and write nothing (§35), per this
    module's own docstring.

    Membership resolves exactly the way ``vpress product`` shows it
    (:func:`~vectorpress.build.product_resolution.resolve_product`, ADR
    0011): no second resolution path. ``allow_unapproved`` is this one
    build's ``--allow-unapproved`` override, passed straight through to it
    and never persisted.
    """
    if product.listing is None:
        return BuildResult(BuildOutcome.REFUSED_NO_LISTING)

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

    resolved = resolve_product(
        product, root, config, known_assets, known_collections, allow_unapproved=allow_unapproved
    )

    if resolved.reference_problems:
        return BuildResult(
            BuildOutcome.REFUSED_REFERENCE_PROBLEMS,
            reference_problems=resolved.reference_problems,
        )
    # refuse (the default) fails on any ineligible member; exclude only
    # fails when that would leave nothing to build (§10).
    should_refuse = (
        bool(resolved.excluded_members)
        if product.ineligible_members is IneligibleMembersMode.REFUSE
        else not resolved.eligible_members
    )
    if should_refuse:
        return BuildResult(
            BuildOutcome.REFUSED_INELIGIBLE_MEMBERS,
            ineligible_members=resolved.excluded_members,
        )

    assets_by_id = {asset.id: asset for asset in known_assets}
    included_types_by_asset = _included_types_by_asset(
        resolved.eligible_members, assets_by_id, root, config, product.derivative_types
    )

    planned = _plan_files(
        resolved.eligible_members, included_types_by_asset, assets_by_id, product.formats
    )
    collisions = _find_name_collisions(planned)
    if collisions:
        return BuildResult(BuildOutcome.REFUSED_NAME_COLLISION, name_collisions=collisions)

    reference_size_in = resolve_reference_size_in(config, product)
    assert product.listing is not None  # build_product's listing gate already refused
    top_level_name = package_name(product.listing.short_title, product.slug)

    package_files: list[tuple[str, bytes]] = []
    manifest_members: list[ManifestMember] = []
    dxf_manifest_members: list[ManifestDxfMember] = []
    # Every eligible member's own copied (never converted) derivative bytes,
    # keyed by its derivative type -- the input _byte_identical_derivative_
    # warnings compares, gathered here since every one is already read once
    # for its own package_files/manifest_members entry below.
    content_by_member: dict[AssetId, dict[DerivativeType, bytes]] = {}
    for file in planned:
        asset_dir_path = asset_dir(root, config, file.asset_id)
        rel_path = f"{file.folder}/{file.filename}"

        if file.folder == _DXF_FOLDER:
            # file.derivative_type names the *source* type (dxf_source's
            # pick), not a type of its own -- its own effective derivative
            # is that source's own customer file, already computed the
            # same way any copied SVG/ entry for it would be.
            asset = assets_by_id[file.asset_id]
            source_filename = derivative_filename(asset.display_name, file.derivative_type)
            source = effective_derivative(asset_dir_path, source_filename)
            assert source is not None  # eligible => approved => the file exists on disk
            try:
                dxf_bytes = svg_to_dxf_bytes(source.bytes)
            except DxfConversionError as exc:
                return BuildResult(
                    BuildOutcome.REFUSED_DXF_CONVERSION_FAILURE,
                    dxf_conversion_failure=DxfConversionFailure(
                        asset_id=file.asset_id,
                        source_derivative_type=file.derivative_type,
                        message=str(exc),
                    ),
                )
            package_files.append((rel_path, dxf_bytes))
            dxf_manifest_members.append(
                ManifestDxfMember(
                    asset_id=file.asset_id,
                    source_derivative_type=file.derivative_type,
                    source_content_hash=sha256_bytes(source.bytes),
                    content_hash=sha256_bytes(dxf_bytes),
                    package_path=rel_path,
                )
            )
            continue

        effective = effective_derivative(asset_dir_path, file.filename)
        assert effective is not None  # eligible => approved => the file exists on disk
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
        content_by_member.setdefault(file.asset_id, {})[file.derivative_type] = effective.bytes

    files_by_folder: dict[str, list[str]] = {}
    for rel_path, _ in package_files:
        folder, _, filename = rel_path.partition("/")
        files_by_folder.setdefault(folder, []).append(filename)

    try:
        preview_result = render_previews(
            root,
            product,
            brand,
            resolved.eligible_members,
            assets_by_id,
            content_by_member,
            files_by_folder,
        )
    except PreviewRenderError as exc:
        return BuildResult(
            BuildOutcome.REFUSED_PREVIEW_RENDER_FAILURE,
            preview_render_failure=PreviewRenderFailure(
                template_name=exc.template_name, message=str(exc)
            ),
        )
    preview_files = preview_result.files
    # previews/ is the only kind vpress build renders today (ADR 0015): a
    # later export step's own overrides join this same list unchanged here.
    template_overrides = sorted(preview_result.template_overrides)

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
    dxf_manifest_members.sort(
        key=lambda member: (member.asset_id, member.source_derivative_type.value)
    )
    # Only ever non-empty for ineligible_members = "exclude": the refuse
    # gate above already returned when resolved.excluded_members is
    # non-empty in refuse mode.
    excluded_manifest_members = [
        ManifestExcludedMember(asset_id=member.asset_id, blocking_reasons=member.blocking_reasons)
        for member in resolved.excluded_members
    ]
    excluded_manifest_members.sort(key=lambda member: member.asset_id)
    # Only ever non-empty under --allow-unapproved: without it, nothing
    # unapproved is ever eligible to admit.
    admitted_unapproved_members = [
        ManifestAdmittedUnapproved(
            asset_id=member.asset_id,
            derivative_type=admitted.derivative_type,
            status=admitted.status,
        )
        for member in resolved.eligible_members
        for admitted in member.admitted_unapproved
    ]
    admitted_unapproved_members.sort(
        key=lambda member: (member.asset_id, member.derivative_type.value)
    )
    asset_rights_statuses = [
        ManifestAssetRightsStatus(
            asset_id=member.asset_id, rights_status=assets_by_id[member.asset_id].rights_status
        )
        for member in resolved.eligible_members
    ]
    asset_rights_statuses.sort(key=lambda entry: entry.asset_id)
    cleanup_size_warnings = _cleanup_size_warnings(
        resolved.eligible_members, included_types_by_asset, assets_by_id, config, reference_size_in
    )
    byte_identical_derivatives = _byte_identical_derivative_warnings(content_by_member)
    previews = sorted((rel_path for rel_path, _ in preview_files), key=_preview_upload_order_key)
    assert product.listing is not None  # build_product's own listing gate already refused
    manifest = Manifest(
        product_slug=product.slug,
        reference_size_in=reference_size_in,
        license_year=license_year,
        tool_version=__version__,
        license_template_hash=_license_template_hash(license_template),
        readme_wording_hash=_readme_wording_hash(brand),
        allow_unapproved=allow_unapproved,
        members=manifest_members,
        dxf_members=dxf_manifest_members,
        excluded_members=excluded_manifest_members,
        admitted_unapproved_members=admitted_unapproved_members,
        asset_rights_statuses=asset_rights_statuses,
        cleanup_size_warnings=cleanup_size_warnings,
        byte_identical_derivatives=byte_identical_derivatives,
        previews=previews,
        presentation_hash=preview_result.presentation_hash,
        listing_hash=_listing_hash(product.listing),
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

        # Previews live beside the package, never inside it (§14, ADR 0014):
        # written straight under tmp_dir, not package_dir, so they are never
        # part of package_files and never enter the ZIP below.
        for rel_path, data in preview_files:
            file_path = tmp_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(data)

        zip_path = tmp_dir / f"{top_level_name}.zip"
        _write_deterministic_zip(zip_path, top_level_name, package_files)

        listing_export = build_listing_export(
            product,
            manifest,
            known_collections,
            resolved.eligible_members,
            assets_by_id,
            zip_name=zip_path.name,
            zip_size_bytes=zip_path.stat().st_size,
        )
        export_path = tmp_dir / EXPORT_DIRNAME / LISTING_EXPORT_FILENAME
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_bytes(_listing_export_json_bytes(listing_export))

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
        template_overrides=template_overrides,
    )
