"""Turning a membership's declared asset IDs, rule and collection union into
current members (§11, §12, §13, §34).

No I/O here: resolution is pure over already-loaded data -- the declared
asset IDs, the rule, the declared collection slugs, and the assets and
sibling memberships that actually loaded. Finding which collections and
assets loaded, and turning an unknown asset ID or collection slug (or a
cycle) into a reference problem naming a file and field, is the ``catalog``
layer's job (ADR 0011).

A member's way in is a set, not a single value: a membership can match the
same asset through more than one route (an explicit ID plus a metadata rule,
or several contributing collections in a union), and every route it matched
through stays visible rather than one overwriting another. ``WayInKind``
covers ``EXPLICIT`` (an asset ID named directly), ``RULE`` (a metadata rule
match), and ``VIA`` (a union member, naming the collection it was referenced
*through directly* -- not a deeper collection a nested union pulled it from).

Resolving a union walks its ``collection_slugs`` recursively against the
other loaded memberships passed in as ``collections_by_slug``, tracking the
path of slugs visited so far. A slug not in that map is unknown; a slug
already on the path is a cycle (a self-reference, ``own_slug`` naming itself,
is the one-element case) -- either way resolution of that branch stops
there, without raising, and every other branch still resolves.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.collection import CollectionSlug
from vectorpress.domain.membership import ClassificationField, Membership, MembershipRule


class WayInKind(StrEnum):
    """How one asset ended up a collection's member."""

    EXPLICIT = "explicit"
    RULE = "rule"
    VIA = "via"


@dataclass(frozen=True, order=True)
class WayIn:
    """One route by which a member got into a collection.

    ``via_slug`` is set only for :attr:`WayInKind.VIA`, naming the
    contributing collection.
    """

    kind: WayInKind
    via_slug: str | None = None

    def __str__(self) -> str:
        if self.kind is WayInKind.VIA:
            assert self.via_slug is not None  # VIA always carries the contributing slug
            return f"via {self.via_slug}"
        return self.kind.value


@dataclass(frozen=True)
class ResolvedMember:
    """One asset currently in a collection, and every way it got there.

    ``ways_in`` is sorted and de-duplicated so display is deterministic
    even when the same asset matched through more than one route.
    """

    asset_id: AssetId
    ways_in: tuple[WayIn, ...]


@dataclass(frozen=True)
class MembershipResolution:
    """The result of resolving one membership -- its explicit list, its
    rule, and its collection union together -- against the assets and
    sibling memberships that actually loaded: current members (a member
    matched through several routes gets every way in), and everything the
    catalog layer turns into a reference problem: unknown explicit asset
    IDs, unknown collection slugs, and cycles (each the path of slugs that
    closes it, e.g. ``("a", "b", "a")``). A rule matching nothing, or a
    union contributing no members, is not a problem (§11, §13). All four
    lists are sorted and de-duplicated.
    """

    members: list[ResolvedMember]
    unknown_asset_ids: list[AssetId]
    unknown_collection_slugs: list[CollectionSlug]
    cycles: list[tuple[CollectionSlug, ...]]


def resolve_explicit(
    asset_ids: list[AssetId], known_asset_ids: set[AssetId]
) -> MembershipResolution:
    """Resolve an explicit asset ID list against the asset IDs that
    actually loaded.

    An ID in ``known_asset_ids`` becomes a member with way in
    :attr:`WayInKind.EXPLICIT`; any other ID -- including one whose own
    ``asset.toml`` failed to load, since it is then absent from
    ``known_asset_ids`` too -- becomes an unknown ID instead. A repeated ID
    contributes one member or one unknown ID, not several.
    """
    known: set[AssetId] = set()
    unknown: set[AssetId] = set()
    for asset_id in asset_ids:
        (known if asset_id in known_asset_ids else unknown).add(asset_id)

    members = [ResolvedMember(asset_id, (WayIn(WayInKind.EXPLICIT),)) for asset_id in sorted(known)]
    return MembershipResolution(
        members=members,
        unknown_asset_ids=sorted(unknown),
        unknown_collection_slugs=[],
        cycles=[],
    )


def _asset_values_for_field(field: ClassificationField, asset: Asset) -> list[str]:
    """The asset's value(s) for one rule field -- the one place the field
    -> attribute mapping lives (§11, not in ``cli``): ``group`` and
    ``category`` stand for ``Asset.taxonomic_group`` and
    ``Asset.subject_category``, each wrapped in a one-element list so a
    single-valued field compares the same way as a multi-valued one
    (``tags``, ``regions``, ``ecosystems``, returned as-is). Exhaustive over
    ``ClassificationField`` so a new field is a type error here, not a
    silent fall-through."""
    match field:
        case ClassificationField.TAGS:
            return asset.tags
        case ClassificationField.REGIONS:
            return asset.regions
        case ClassificationField.ECOSYSTEMS:
            return asset.ecosystems
        case ClassificationField.GROUP:
            return [asset.taxonomic_group]
        case ClassificationField.CATEGORY:
            return [asset.subject_category]
        case _:
            assert_never(field)


def _normalized(value: str) -> str:
    """Fold case and surrounding whitespace for a rule comparison (§11)."""
    return value.strip().casefold()


def _asset_matches_rule(rule: MembershipRule, asset: Asset) -> bool:
    """Any of the asset's values for the rule's field equals any of the
    rule's values, case- and whitespace-insensitively -- an exact match,
    not a substring match (§11)."""
    rule_values = {_normalized(value) for value in rule.values}
    asset_values = {_normalized(value) for value in _asset_values_for_field(rule.field, asset)}
    return not rule_values.isdisjoint(asset_values)


def resolve_rule(rule: MembershipRule, assets: list[Asset]) -> list[ResolvedMember]:
    """Resolve a metadata rule against every loaded asset: each match
    becomes a member with way in :attr:`WayInKind.RULE`. Matching nothing
    is not a problem -- an empty list (§11)."""
    matched_ids = {asset.id for asset in assets if _asset_matches_rule(rule, asset)}
    return [ResolvedMember(asset_id, (WayIn(WayInKind.RULE),)) for asset_id in sorted(matched_ids)]


def resolve_membership(
    membership: Membership,
    assets: list[Asset],
    collections_by_slug: Mapping[CollectionSlug, Membership] | None = None,
    *,
    own_slug: CollectionSlug | None = None,
) -> MembershipResolution:
    """Resolve a membership's explicit list, rule and collection union
    together against the assets and sibling memberships that actually
    loaded: the de-duplicated union of all three forms as members, each
    carrying every way it matched (§11, §12, §13).

    ``collections_by_slug`` supplies every other loaded collection's
    membership, keyed by slug, for resolving ``collection_slugs`` --
    omit it (or pass an empty mapping) when the membership declares no
    union, the same as every call site before this recursed. ``own_slug``
    is this membership's own slug, if it has one (a real collection does; an
    inline product membership does not, per ``vectorpress.domain.
    membership``'s own docstring) -- it seeds the cycle-tracking path so a
    collection unioning itself is caught on the first hop, not just a
    longer cycle back to it.

    Only the explicit list can produce an unknown asset ID; a rule value
    that matches no asset is simply an empty match, never a reference
    problem, and neither is an empty union.
    """
    path = (own_slug,) if own_slug is not None else ()
    return _resolve_membership(membership, assets, collections_by_slug or {}, path)


def _resolve_membership(
    membership: Membership,
    assets: list[Asset],
    collections_by_slug: Mapping[CollectionSlug, Membership],
    path: tuple[CollectionSlug, ...],
) -> MembershipResolution:
    """The recursive worker behind :func:`resolve_membership`: ``path`` is
    every collection slug visited so far, from the outermost membership
    being resolved down to this one, so a repeat means a cycle."""
    known_asset_ids = {asset.id for asset in assets}
    explicit = resolve_explicit(membership.asset_ids, known_asset_ids)

    ways_in_by_id: dict[AssetId, set[WayIn]] = {
        member.asset_id: set(member.ways_in) for member in explicit.members
    }
    if membership.rule is not None:
        for member in resolve_rule(membership.rule, assets):
            ways_in_by_id.setdefault(member.asset_id, set()).update(member.ways_in)

    unknown_collection_slugs: set[CollectionSlug] = set()
    cycles: set[tuple[CollectionSlug, ...]] = set()
    # dict.fromkeys: de-duplicate declared slugs while keeping first-seen
    # order, so a repeated slug in one union list is resolved once.
    for slug in dict.fromkeys(membership.collection_slugs):
        if slug in path:
            cycles.add((*path[path.index(slug) :], slug))
            continue
        sub_membership = collections_by_slug.get(slug)
        if sub_membership is None:
            unknown_collection_slugs.add(slug)
            continue
        sub_resolution = _resolve_membership(
            sub_membership, assets, collections_by_slug, (*path, slug)
        )
        for member in sub_resolution.members:
            # The way in names the collection referenced directly -- this
            # union's own slug -- never the deeper collection a nested
            # union pulled the member from.
            ways_in_by_id.setdefault(member.asset_id, set()).add(WayIn(WayInKind.VIA, slug))
        unknown_collection_slugs.update(sub_resolution.unknown_collection_slugs)
        cycles.update(sub_resolution.cycles)

    members = [
        ResolvedMember(asset_id, tuple(sorted(ways_in)))
        for asset_id, ways_in in sorted(ways_in_by_id.items())
    ]
    return MembershipResolution(
        members=members,
        unknown_asset_ids=explicit.unknown_asset_ids,
        unknown_collection_slugs=sorted(unknown_collection_slugs),
        cycles=sorted(cycles),
    )
