"""build.product_resolution: a product's effective contents -- its resolved
membership run through the eligible/excluded breakdown for the product's
own derivative types, plus its missing required derivatives (§7, §10,
§10.1, §13, §28, ADR 0008, ADR 0011).

Runs against the real, committed fixture catalog directly rather than a
temporary copy: resolution is read-only (it never generates or writes
anything), so every asset's derivatives read as ``missing`` (a source is
selectable, nothing has been generated yet) -- exactly the state
``pacific_coast_tide_pool_standard_pack``'s own acceptance walkthrough
starts from before ``generate --all`` runs. The generated/approved
scenarios (§10's "the same asset ships PNG-only while its cut file is
under review", and a rights-blocked asset staying excluded even fully
approved) are covered end to end by ``tests/integration/
test_product_resolution.py``, which writes real files under a temporary
catalog copy.
"""

from pathlib import Path

from vectorpress.build.product_resolution import (
    MemberEligibility,
    MissingRequiredDerivative,
    ValidationScopeOutcome,
    resolve_product,
    resolve_validation_scope,
)
from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.collection_resolution import PRODUCT_COLLECTION_SLUG_FIELD
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.load import load_catalog_config
from vectorpress.catalog.products import find_product, load_products
from vectorpress.domain.collection_resolution import WayIn, WayInKind
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import BlockingReasonKind
from vectorpress.domain.membership import ClassificationField, Membership, MembershipRule
from vectorpress.domain.product import Product

FIXTURE_CATALOG_ROOT = Path(__file__).parents[1] / "fixtures" / "catalog"

PACIFIC_COAST_MEMBERS = {"ochre_sea_star", "giant_green_anemone", "purple_sea_urchin"}


def _product(**overrides: object) -> Product:
    fields: dict[str, object] = {
        "slug": "test_product",
        "membership": Membership(asset_ids=["ochre_sea_star"]),
        "derivative_types": ["cut_svg"],
        "formats": ["svg"],
        "tier": "individual",
        "price": 1.0,
    }
    fields.update(overrides)
    return Product(**fields)  # type: ignore[arg-type]


# --- over a collection slug, on a nothing-generated-yet catalog ---------------------


def test_resolving_the_standard_pack_lists_its_three_members_all_excluded() -> None:
    """Nothing has been generated: every included type reads ``missing``
    for every member, so every member is excluded with one blocking reason
    per type -- the same shape the acceptance walkthrough starts from
    before ``generate --all`` runs."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    product = find_product(
        load_products(FIXTURE_CATALOG_ROOT, config), "pacific_coast_tide_pool_standard_pack"
    )
    assert product is not None

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections
    )

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert resolved.eligible_members == []
    assert len(resolved.excluded_members) == 3
    for member in resolved.members:
        assert member.eligibility is MemberEligibility.EXCLUDED
        assert {reason.derivative_type for reason in member.blocking_reasons} == {
            DerivativeType.CUT_SVG,
            DerivativeType.SILHOUETTE_SVG,
            DerivativeType.TRANSPARENT_PNG,
        }
        assert all(
            reason.kind is BlockingReasonKind.DERIVATIVE_STATE and reason.value == "missing"
            for reason in member.blocking_reasons
        )
    assert resolved.reference_problems == []
    assert len(resolved.missing_required_derivatives) == 9


def test_the_png_only_product_over_the_same_collection_reads_the_same_members() -> None:
    """The identical membership, a different product: still ``missing`` (not
    approved) for the one type this product cares about."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    product = find_product(
        load_products(FIXTURE_CATALOG_ROOT, config), "pacific_coast_tide_pool_png_only"
    )
    assert product is not None

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections
    )

    assert {member.asset_id for member in resolved.members} == PACIFIC_COAST_MEMBERS
    assert resolved.eligible_members == []
    for member in resolved.members:
        assert [reason.derivative_type for reason in member.blocking_reasons] == [
            DerivativeType.TRANSPARENT_PNG
        ]
    assert [item.derivative_type for item in resolved.missing_required_derivatives] == [
        DerivativeType.TRANSPARENT_PNG
    ] * 3


# --- inline membership resolves through the identical pure decision -----------------


def test_resolving_the_kelp_forest_mini_pack_resolves_its_inline_rule() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    product = find_product(load_products(FIXTURE_CATALOG_ROOT, config), "kelp_forest_mini_pack")
    assert product is not None

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections
    )

    assert [member.asset_id for member in resolved.members] == ["purple_sea_urchin"]
    assert resolved.members[0].ways_in == (WayIn(WayInKind.RULE),)
    assert resolved.reference_problems == []


# --- unknown collection_slug: no members, one reference problem ---------------------


def test_an_unknown_collection_slug_resolves_to_no_members_with_a_reference_problem() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=None, collection_slug="not_a_real_collection", slug="unknown_ref_product"
    )

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections=[]
    )

    assert resolved.members == []
    assert resolved.missing_required_derivatives == []
    assert len(resolved.reference_problems) == 1
    problem = resolved.reference_problems[0]
    assert problem.field == PRODUCT_COLLECTION_SLUG_FIELD
    assert "not_a_real_collection" in problem.message


# --- an asset-level block excludes regardless of derivative state -------------------


def test_a_rights_blocked_member_is_excluded_with_a_rights_status_reason() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["gumboot_chiton"]), derivative_types=["cut_svg"]
    )

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections=[]
    )

    assert len(resolved.members) == 1
    member = resolved.members[0]
    assert member.eligibility is MemberEligibility.EXCLUDED
    assert any(
        reason.kind is BlockingReasonKind.RIGHTS_STATUS and reason.value == "do_not_publish"
        for reason in member.blocking_reasons
    )


# --- missing vs impossible: a type with no matching source is impossible ------------


def test_a_type_with_no_matching_source_is_impossible_not_missing() -> None:
    """``giant_green_anemone`` has no ``flatcolor`` source, so
    ``flatcolor_svg`` can never exist for it (§10.1) -- reported
    ``impossible``, distinct from a type that merely has not been generated
    yet."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["giant_green_anemone"]),
        derivative_types=["flatcolor_svg"],
    )

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections=[]
    )

    assert resolved.missing_required_derivatives == [
        MissingRequiredDerivative(
            "giant_green_anemone", DerivativeType.FLATCOLOR_SVG, DerivativeState.IMPOSSIBLE
        )
    ]


# --- an empty membership is valid: zero members, zero counts ------------------------


def test_a_membership_matching_nothing_resolves_to_an_empty_but_valid_product() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(
            rule=MembershipRule(field=ClassificationField.ECOSYSTEMS, values=["Nowhere at all"])
        )
    )

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections=[]
    )

    assert resolved.members == []
    assert resolved.eligible_members == []
    assert resolved.excluded_members == []
    assert resolved.missing_required_derivatives == []
    assert resolved.reference_problems == []


# --- resolve_validation_scope: the decision behind `vpress validate --product` ------

# CLAUDE.md's layering guardrail ("cli and ui are thin: they call the same
# functions") puts this decision here, alongside resolve_product, rather
# than in cli.app -- the same shape build.product_build.build_product
# already established for `vpress build`.


def test_validation_scope_includes_an_excluded_member_not_only_eligible_ones() -> None:
    """Findings are independent of eligibility (CONTEXT.md "Findings"):
    ``gumboot_chiton`` is rights-blocked (``do_not_publish``), so
    ``resolve_product`` excludes it -- but the validation scope still
    carries it, since a build-eligibility exclusion is not a reason to
    leave a cut file unvalidated."""
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["gumboot_chiton"]), derivative_types=["cut_svg"]
    )

    resolved = resolve_product(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections=[]
    )
    assert resolved.members[0].eligibility is MemberEligibility.EXCLUDED  # sanity

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, [], asset_id=None
    )

    assert scope.outcome is ValidationScopeOutcome.SCOPED
    assert scope.member_asset_ids == ["gumboot_chiton"]


def test_validation_scope_given_no_asset_id_lists_every_resolved_member() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    known_collections = load_collections(FIXTURE_CATALOG_ROOT, config).collections
    product = find_product(load_products(FIXTURE_CATALOG_ROOT, config), "kelp_forest_mini_pack")
    assert product is not None

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, known_collections, asset_id=None
    )

    assert scope.outcome is ValidationScopeOutcome.SCOPED
    assert scope.member_asset_ids == ["purple_sea_urchin"]


def test_validation_scope_given_a_member_asset_id_scopes_to_just_that_one() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["ochre_sea_star", "giant_green_anemone"]),
        derivative_types=["cut_svg"],
    )

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, [], asset_id="ochre_sea_star"
    )

    assert scope.outcome is ValidationScopeOutcome.SCOPED
    assert scope.member_asset_ids == ["ochre_sea_star"]


def test_validation_scope_refuses_a_given_asset_that_is_not_a_member() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["ochre_sea_star"]), derivative_types=["cut_svg"]
    )

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, [], asset_id="giant_green_anemone"
    )

    assert scope.outcome is ValidationScopeOutcome.REFUSED_NOT_A_MEMBER
    assert scope.asset_id == "giant_green_anemone"


def test_validation_scope_reports_nothing_to_validate_without_cut_svg() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=Membership(asset_ids=["ochre_sea_star"]),
        derivative_types=["transparent_png"],
        formats=["png"],
    )

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, [], asset_id=None
    )

    assert scope.outcome is ValidationScopeOutcome.NOTHING_TO_VALIDATE
    assert scope.member_asset_ids is None


def test_validation_scope_refuses_on_unresolved_membership() -> None:
    config = load_catalog_config(FIXTURE_CATALOG_ROOT)
    known_assets = load_assets(FIXTURE_CATALOG_ROOT, config).assets
    product = _product(
        membership=None, collection_slug="not_a_real_collection", slug="unknown_ref_product"
    )

    scope = resolve_validation_scope(
        product, FIXTURE_CATALOG_ROOT, config, known_assets, [], asset_id=None
    )

    assert scope.outcome is ValidationScopeOutcome.REFUSED_REFERENCE_PROBLEMS
    assert scope.reference_problems is not None
    assert len(scope.reference_problems) == 1
    assert "not_a_real_collection" in scope.reference_problems[0].message
