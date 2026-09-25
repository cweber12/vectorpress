"""Turning a membership's ``asset_ids`` into current members (§11, §34).

No I/O here: resolution is pure over already-loaded data -- the declared
asset IDs and the set of asset IDs that actually loaded. Finding which
collections and assets loaded, and turning an unknown asset ID into a
reference problem naming a file and field, is the ``catalog`` layer's job
(ADR 0011).

A member's way in is a set, not a single value: a membership can match the
same asset through more than one route (an explicit ID plus a metadata rule,
or several contributing collections in a union), and every route it matched
through stays visible rather than one overwriting another. ``WayInKind``
covers ``EXPLICIT`` (an asset ID named directly), ``RULE`` (a metadata rule
match), and ``VIA`` (a union member, naming the contributing collection);
this module currently only ever produces ``EXPLICIT``.
"""

from dataclasses import dataclass
from enum import StrEnum

from vectorpress.domain.asset import AssetId


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
class ExplicitResolution:
    """The result of resolving one membership's ``asset_ids`` against the
    set of asset IDs that actually loaded: current members, and unknown
    asset IDs for the catalog layer to turn into reference problems. Both
    are sorted and de-duplicated.
    """

    members: list[ResolvedMember]
    unknown_asset_ids: list[AssetId]


def resolve_explicit(asset_ids: list[AssetId], known_asset_ids: set[AssetId]) -> ExplicitResolution:
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
    return ExplicitResolution(members=members, unknown_asset_ids=sorted(unknown))
