"""Turning a membership's declared asset IDs and rule into current members
(§11, §12, §34).

No I/O here: resolution is pure over already-loaded data -- the declared
asset IDs, the rule, and the assets that actually loaded. Finding which
collections and assets loaded, and turning an unknown asset ID into a
reference problem naming a file and field, is the ``catalog`` layer's job
(ADR 0011).

A member's way in is a set, not a single value: a membership can match the
same asset through more than one route (an explicit ID plus a metadata rule,
or several contributing collections in a union), and every route it matched
through stays visible rather than one overwriting another. ``WayInKind``
covers ``EXPLICIT`` (an asset ID named directly), ``RULE`` (a metadata rule
match), and ``VIA`` (a union member, naming the contributing collection);
this module does not yet produce ``VIA``.
"""

from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import Asset, AssetId
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
    """The result of resolving one membership -- its explicit list and its
    rule together -- against the assets that actually loaded: current
    members (a member matched through both gets both ways in), and unknown
    explicit asset IDs for the catalog layer to turn into reference
    problems. A rule matching nothing contributes no members and no
    problem (§11). Both lists are sorted and de-duplicated.
    """

    members: list[ResolvedMember]
    unknown_asset_ids: list[AssetId]


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
    return MembershipResolution(members=members, unknown_asset_ids=sorted(unknown))


def _asset_values_for_field(field: ClassificationField, asset: Asset) -> list[str]:
    """The asset's value(s) for one rule field -- the one place the field
    -> attribute mapping lives (§11, not in ``cli``): ``group`` and
    ``category`` stand for ``Asset.taxonomic_group`` and
    ``Asset.subject_category``, each wrapped in a one-element list so a
    single-valued field compares the same way as a multi-valued one
    (``tags``, ``regions``, ``ecosystems``, returned as-is)."""
    if field is ClassificationField.TAGS:
        return asset.tags
    if field is ClassificationField.REGIONS:
        return asset.regions
    if field is ClassificationField.ECOSYSTEMS:
        return asset.ecosystems
    if field is ClassificationField.GROUP:
        return [asset.taxonomic_group]
    return [asset.subject_category]


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


def resolve_membership(membership: Membership, assets: list[Asset]) -> MembershipResolution:
    """Resolve a membership's explicit list and rule together against the
    assets that actually loaded: the de-duplicated union of both forms as
    members, each carrying every way it matched (§11, §12). Only the
    explicit list can produce an unknown asset ID; a rule value that
    matches no asset is simply an empty match, never a reference problem.
    """
    known_asset_ids = {asset.id for asset in assets}
    explicit = resolve_explicit(membership.asset_ids, known_asset_ids)

    ways_in_by_id: dict[AssetId, set[WayIn]] = {
        member.asset_id: set(member.ways_in) for member in explicit.members
    }
    if membership.rule is not None:
        for member in resolve_rule(membership.rule, assets):
            ways_in_by_id.setdefault(member.asset_id, set()).update(member.ways_in)

    members = [
        ResolvedMember(asset_id, tuple(sorted(ways_in)))
        for asset_id, ways_in in sorted(ways_in_by_id.items())
    ]
    return MembershipResolution(members=members, unknown_asset_ids=explicit.unknown_asset_ids)
