"""Product resolution: one product's effective contents (§7, §10, §10.1,
§13, §28, ADR 0008).

Below ``cli`` (CLAUDE.md's layering guardrail), so a future ``ui`` and PRD
6's build call the same one function. Lives in ``build``, not ``pipeline``,
because it needs :mod:`vectorpress.pipeline.eligibility` and ``pipeline``
cannot import its own sibling ``build`` -- the same reasoning ADR 0011 gives
for drawing this line here rather than in ``catalog``.

A product's membership resolves through exactly the same path a
collection's does: :func:`~vectorpress.catalog.collection_resolution.
resolve_collection` when it references a collection by ``collection_slug``,
or :func:`~vectorpress.domain.collection_resolution.resolve_membership`
directly -- the identical pure decision, not a second one -- when it
declares an inline ``membership``. Either way membership is live (§10.1:
products are unfrozen in this PRD): nothing here caches or freezes it.

Each member is run through the existing eligibility pair --
:func:`~vectorpress.pipeline.eligibility.included_derivatives` for the
product's own ``derivative_types``, then :func:`~vectorpress.domain.
eligibility.asset_eligibility` -- and comes back ``eligible`` or
``excluded``, carrying every §10.1 blocking reason when excluded and every
warning either way (a warning never excludes). Separately, every (asset,
derivative type) whose state is ``missing`` or ``impossible`` is gathered
as the actionable input to a later ``generate`` run. Neither list takes
precedence over the other -- §10's "unless explicitly overridden" is still
not built.

:func:`resolve_validation_scope` is the analogous decision for ``vpress
validate --product``: which members to validate, or why none -- built on
:func:`resolve_product`, never a second resolution. ``cli`` only renders
its result, the same "cli is thin" shape :func:`~vectorpress.build.
product_build.build_product` already established for ``vpress build``.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from vectorpress.catalog.assets import asset_dir
from vectorpress.catalog.collection_resolution import (
    membership_reference_problems,
    product_collection_slug_reference_problem,
    resolve_collection,
)
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.products import product_toml_path
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.collection_resolution import ResolvedMember, WayIn, resolve_membership
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import (
    AdmittedUnapproved,
    BlockingReason,
    Eligibility,
    asset_eligibility,
    missing_optional_metadata_fields,
)
from vectorpress.domain.product import Product
from vectorpress.pipeline.eligibility import included_derivatives

#: The field a product's ``[previews] featured`` reference problem is
#: attributed to (:func:`featured_reference_problems`), mirroring
#: ``PRODUCT_COLLECTION_SLUG_FIELD`` and the ``membership.*`` fields
#: :mod:`~vectorpress.catalog.collection_resolution` already uses.
FEATURED_FIELD = "previews.featured"


class MemberEligibility(StrEnum):
    """Whether one resolved member may ship in this product (§10, §10.1,
    CONTEXT.md "Eligible", "Blocked")."""

    ELIGIBLE = "eligible"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class ProductMember:
    """One member of a product's resolved membership: how it got in (the
    same ``ways_in`` a resolved collection carries), whether it is eligible
    for this product's own ``derivative_types``, every blocking reason when
    excluded, every warning either way, and every derivative
    ``allow_unapproved`` admitted for it (empty unless the caller passed
    ``allow_unapproved=True`` to :func:`resolve_product`)."""

    asset_id: AssetId
    ways_in: tuple[WayIn, ...]
    eligibility: MemberEligibility
    blocking_reasons: list[BlockingReason]
    warnings: list[str]
    admitted_unapproved: list[AdmittedUnapproved]


@dataclass(frozen=True)
class MissingRequiredDerivative:
    """One (asset, derivative type) pair this product needs but does not
    have: ``state`` is ``MISSING`` (a source is selectable but nothing has
    been generated) or ``IMPOSSIBLE`` (no declared source can ever produce
    it) -- the actionable input to a later ``generate`` run."""

    asset_id: AssetId
    derivative_type: DerivativeType
    state: DerivativeState


@dataclass(frozen=True)
class ResolvedProduct:
    """One product's effective contents: every resolved member with its
    eligible/excluded breakdown, every missing required derivative, and
    every reference problem found resolving its membership (an unknown
    ``collection_slug``, or -- for an inline membership -- an unknown asset
    ID, unknown collection slug, or cycle in its own union). ``members`` is
    sorted by asset ID, the same order :func:`~vectorpress.catalog.
    collection_resolution.resolve_collection`'s own members use."""

    product: Product
    members: list[ProductMember]
    missing_required_derivatives: list[MissingRequiredDerivative]
    reference_problems: list[MetadataProblem]

    @property
    def eligible_members(self) -> list[ProductMember]:
        return [
            member for member in self.members if member.eligibility is MemberEligibility.ELIGIBLE
        ]

    @property
    def excluded_members(self) -> list[ProductMember]:
        return [
            member for member in self.members if member.eligibility is MemberEligibility.EXCLUDED
        ]


def _resolved_members_and_reference_problems(
    product: Product,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
) -> tuple[list[ResolvedMember], list[MetadataProblem]]:
    """A product's membership resolved to its current members, plus every
    reference problem found doing so -- the collection-slug path and the
    inline-membership path, each reusing the same machinery a collection
    itself uses (ADR 0011)."""
    if product.collection_slug is not None:
        problem = product_collection_slug_reference_problem(product, config, known_collections)
        if problem is not None:
            return [], [problem]
        collection = next(c for c in known_collections if c.slug == product.collection_slug)
        resolved = resolve_collection(collection, config, known_assets, known_collections)
        return resolved.members, resolved.reference_problems

    assert product.membership is not None  # enforced by Product's own validation
    collections_by_slug = {c.slug: c.membership for c in known_collections}
    # An inline membership has no slug of its own to seed the cycle path
    # with (vectorpress.domain.membership's own docstring).
    resolution = resolve_membership(
        product.membership, known_assets, collections_by_slug, own_slug=None
    )
    path = product_toml_path(config, product.slug)
    return resolution.members, membership_reference_problems(path, resolution)


def featured_reference_problems(
    product: Product, resolved_members: list[ResolvedMember], config: CatalogConfig
) -> list[MetadataProblem]:
    """A ``[previews] featured`` asset ID that names no resolved member
    (§16, CONTEXT.md "Featured member") is a product metadata problem
    naming the ID -- checked here rather than on the domain model, since
    only resolution knows the product's current membership. Not scoped to
    eligible members: a featured ID resolved but excluded from one build is
    a per-build preview concern (:func:`~vectorpress.build.previews
    ._featured_asset_ids`), never a reference problem.
    """
    if product.previews is None:
        return []
    resolved_ids = {member.asset_id for member in resolved_members}
    path = product_toml_path(config, product.slug)
    return [
        MetadataProblem(path, FEATURED_FIELD, f"unknown asset ID: {asset_id!r}")
        for asset_id in product.previews.featured
        if asset_id not in resolved_ids
    ]


def resolve_product(
    product: Product,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
    allow_unapproved: bool = False,
) -> ResolvedProduct:
    """Resolve one product's effective contents (§7, §10, §10.1, §13, §28).

    ``known_assets`` and ``known_collections`` are the catalog layer's own
    loaded, never-failed inventories -- the same contract :func:`~vectorpress.
    catalog.collection_resolution.resolve_collection` already requires, so a
    future caller cannot forget to pass every loaded collection (needed for
    a union, or to tell an unknown ``collection_slug`` from a loaded one)
    and silently lose part of the resolution.

    ``allow_unapproved`` is the per-build ``--allow-unapproved`` override
    (§10.1's "unless explicitly overridden"), threaded straight into
    :func:`~vectorpress.domain.eligibility.asset_eligibility` -- an option
    on the one eligibility decision, not a second one.
    """
    resolved_members, reference_problems = _resolved_members_and_reference_problems(
        product, config, known_assets, known_collections
    )
    reference_problems = [
        *reference_problems,
        *featured_reference_problems(product, resolved_members, config),
    ]
    assets_by_id = {asset.id: asset for asset in known_assets}

    members: list[ProductMember] = []
    missing: list[MissingRequiredDerivative] = []
    for resolved_member in resolved_members:
        asset = assets_by_id[resolved_member.asset_id]
        asset_dir_path = asset_dir(root, config, asset.id)
        included = included_derivatives(asset, asset_dir_path, product.derivative_types, config)
        result = asset_eligibility(
            asset.rights_status,
            asset.accuracy_status,
            missing_optional_metadata_fields(asset),
            included,
            licensing_notes=asset.licensing_notes,
            allow_unapproved=allow_unapproved,
        )
        eligibility = (
            MemberEligibility.ELIGIBLE
            if result.eligibility is Eligibility.ELIGIBLE
            else MemberEligibility.EXCLUDED
        )
        members.append(
            ProductMember(
                asset_id=asset.id,
                ways_in=resolved_member.ways_in,
                eligibility=eligibility,
                blocking_reasons=result.blocking_reasons,
                warnings=result.warnings,
                admitted_unapproved=result.admitted_unapproved,
            )
        )
        missing.extend(
            MissingRequiredDerivative(asset.id, one.derivative_type, one.state)
            for one in included
            if one.state in (DerivativeState.MISSING, DerivativeState.IMPOSSIBLE)
        )

    return ResolvedProduct(
        product=product,
        members=members,
        missing_required_derivatives=missing,
        reference_problems=reference_problems,
    )


class ValidationScopeOutcome(StrEnum):
    """One outcome of scoping ``vpress validate --product`` to a product's
    resolved membership (§9, §13, ADR 0012): a member list to validate, or a
    refusal/report for one of three reasons."""

    SCOPED = "scoped"
    REFUSED_REFERENCE_PROBLEMS = "refused_reference_problems"
    NOTHING_TO_VALIDATE = "nothing_to_validate"
    REFUSED_NOT_A_MEMBER = "refused_not_a_member"


@dataclass(frozen=True)
class ValidationScope:
    """The result of :func:`resolve_validation_scope`. Exactly one of
    ``reference_problems``, ``asset_id`` or ``member_asset_ids`` is set,
    matching ``outcome``."""

    outcome: ValidationScopeOutcome
    reference_problems: list[MetadataProblem] | None = None
    asset_id: AssetId | None = None
    member_asset_ids: list[AssetId] | None = None


def resolve_validation_scope(
    product: Product,
    root: Path,
    config: CatalogConfig,
    known_assets: list[Asset],
    known_collections: list[Collection],
    asset_id: AssetId | None,
) -> ValidationScope:
    """Scope ``vpress validate --product`` to ``product``'s resolved
    membership (§9, §13): every resolved member -- eligible or excluded
    alike, since findings are independent of eligibility (CONTEXT.md
    "Findings") -- or, when ``asset_id`` is given, just that one member.

    Resolves through :func:`resolve_product` (no second resolution path,
    the same membership ``vpress product`` and ``vpress build`` show), and
    refuses on the identical unresolved-membership condition
    :func:`~vectorpress.build.product_build.build_product` refuses a build
    on. Reports :attr:`ValidationScopeOutcome.NOTHING_TO_VALIDATE` for a
    product with no ``cut_svg`` among its ``derivative_types``, and
    :attr:`ValidationScopeOutcome.REFUSED_NOT_A_MEMBER` when ``asset_id`` is
    given but is not one of the resolved members, rather than silently
    validating it at the product's size.
    """
    resolved = resolve_product(product, root, config, known_assets, known_collections)
    if resolved.reference_problems:
        return ValidationScope(
            ValidationScopeOutcome.REFUSED_REFERENCE_PROBLEMS,
            reference_problems=resolved.reference_problems,
        )
    if DerivativeType.CUT_SVG not in product.derivative_types:
        return ValidationScope(ValidationScopeOutcome.NOTHING_TO_VALIDATE)
    if asset_id is not None:
        member = next((m for m in resolved.members if m.asset_id == asset_id), None)
        if member is None:
            return ValidationScope(ValidationScopeOutcome.REFUSED_NOT_A_MEMBER, asset_id=asset_id)
        return ValidationScope(ValidationScopeOutcome.SCOPED, member_asset_ids=[member.asset_id])
    return ValidationScope(
        ValidationScopeOutcome.SCOPED,
        member_asset_ids=[member.asset_id for member in resolved.members],
    )
