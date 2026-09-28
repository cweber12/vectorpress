"""Reading a product's last build manifest back off disk (§14, §23, ADR
0004, ADR 0005, CONTEXT.md "Manifest", "Needs rebuild").

Only ``catalog`` touches catalog files (ADR 0006): this is the one place
that parses ``builds/<slug>/manifest.json`` back into a
:class:`~vectorpress.domain.manifest.Manifest`, the inverse of
``build.product_build``'s own serialization. A pure read -- nothing here
writes anything -- and the manifest's own directory and file names live
here, so ``build`` (which writes them) and this module (which reads them
back) agree on one definition instead of two.
"""

import json
from pathlib import Path

from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import BlockingReason, BlockingReasonKind
from vectorpress.domain.manifest import (
    Manifest,
    ManifestAdmittedUnapproved,
    ManifestDxfMember,
    ManifestExcludedMember,
    ManifestMember,
    ManifestMemberSource,
)
from vectorpress.domain.product import ProductSlug
from vectorpress.domain.status import Status

#: Every build's output lives under this catalog-root-relative directory
#: (§14), never under ``sources/``, ``derived/``, ``overrides/`` or any
#: hand-authored file (ADR 0005): the package, its ZIP, and the manifest,
#: one subdirectory per product slug.
BUILDS_DIRNAME = "builds"

#: The build's own JSON manifest file, sibling to the package directory and
#: the ZIP inside ``builds/<product-slug>/``.
MANIFEST_FILENAME = "manifest.json"


def manifest_json_path(root: Path, slug: ProductSlug) -> Path:
    """Where one product's last build manifest would live, whether or not
    it has ever been built."""
    return root / BUILDS_DIRNAME / slug / MANIFEST_FILENAME


def read_manifest(root: Path, slug: ProductSlug) -> Manifest | None:
    """The product's last build manifest, or ``None`` when it has never
    been built (CONTEXT.md "Needs rebuild": never built is distinct from
    needs rebuild). A pure read: never writes, never re-derives anything --
    just the JSON :func:`~vectorpress.build.product_build.build_product`
    itself last wrote, parsed back into the same shape."""
    path = manifest_json_path(root, slug)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))

    return Manifest(
        product_slug=data["product_slug"],
        reference_size_in=data["reference_size_in"],
        license_year=data["license_year"],
        tool_version=data["tool_version"],
        license_template_hash=data["license_template_hash"],
        readme_wording_hash=data["readme_wording_hash"],
        allow_unapproved=data["allow_unapproved"],
        members=[
            ManifestMember(
                asset_id=member["asset_id"],
                derivative_type=DerivativeType(member["derivative_type"]),
                source=ManifestMemberSource(member["source"]),
                content_hash=member["content_hash"],
                package_path=member["package_path"],
            )
            for member in data["members"]
        ],
        dxf_members=[
            ManifestDxfMember(
                asset_id=member["asset_id"],
                source_derivative_type=DerivativeType(member["source_derivative_type"]),
                source_content_hash=member["source_content_hash"],
                content_hash=member["content_hash"],
                package_path=member["package_path"],
            )
            for member in data["dxf_members"]
        ],
        excluded_members=[
            ManifestExcludedMember(
                asset_id=member["asset_id"],
                blocking_reasons=[
                    BlockingReason(
                        kind=BlockingReasonKind(reason["kind"]),
                        derivative_type=(
                            DerivativeType(reason["derivative_type"])
                            if reason["derivative_type"] is not None
                            else None
                        ),
                        value=reason["value"],
                    )
                    for reason in member["blocking_reasons"]
                ],
            )
            for member in data["excluded_members"]
        ],
        admitted_unapproved_members=[
            ManifestAdmittedUnapproved(
                asset_id=member["asset_id"],
                derivative_type=DerivativeType(member["derivative_type"]),
                status=Status(member["status"]),
            )
            for member in data["admitted_unapproved_members"]
        ],
    )
