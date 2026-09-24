"""Load every asset under a catalog's assets directory.

An asset is any folder under ``assets_dir`` that contains an ``asset.toml``
(CONTEXT.md); the folder name is its asset ID. Each file is validated
independently: one that fails becomes a ``MetadataProblem`` instead of
raising, so the rest of the catalog still loads (§35). Validation also
checks declared sources against the asset's ``sources/`` directory, and any
``[derivatives.<type>]`` pin against those sources and the domain's recipes
(§4.1, §21, ADR 0003).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.metadata_problem import (
    MetadataProblem,
    duplicate_slug_problems,
    problems_from_validation_error,
)
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.recipe import recipe_for

ASSET_CONFIG_FILENAME = "asset.toml"
SOURCES_DIRNAME = "sources"


@dataclass(frozen=True)
class AssetInventory:
    """Every asset that loaded, plus every problem found along the way.

    ``assets`` excludes any folder whose ``asset.toml`` failed schema
    validation, or whose declared sources produced a problem (unknown
    role, missing or undeclared file, duplicate declaration, zero
    sources), or whose ``[derivatives.<type>]`` pin produced a problem
    (undeclared file, unaccepted role, or a type with no recipe), or whose
    folder name shares an asset ID with another folder
    (case-insensitively — Windows and macOS filesystems disagree with
    Linux on whether ``Sea_Otter/`` and ``sea_otter/`` can coexist, so
    this check normalises rather than comparing exact case, same as
    collections and products, issue #17); ``assets`` is sorted by asset ID.
    """

    assets: list[Asset]
    problems: list[MetadataProblem]


def asset_dir(root: Path, config: CatalogConfig, asset_id: AssetId) -> Path:
    """The on-disk folder for one asset ID, whether or not it loaded.

    Kept here rather than duplicated in ``pipeline`` or ``cli`` (CLAUDE.md's
    "cli and ui are thin"): only ``catalog`` computes on-disk layout, and
    generation (issue #23) needs this same join of ``config.assets_dir`` and
    ``asset_id`` that ``load_assets`` already does internally.
    """
    return root / config.assets_dir / asset_id


def failed_asset_ids(inventory: AssetInventory, config: CatalogConfig) -> list[str]:
    """Every asset ID whose folder exists under ``config.assets_dir`` but
    failed to load, sorted and de-duplicated (issue #23's ``vpress generate
    --all``: "assets that failed to load are skipped and named").

    Derived from ``inventory.problems``' paths rather than re-walking the
    filesystem: a problem's path always falls under
    ``<assets_dir>/<asset_id>/...`` (``lookup_asset``'s same assumption).
    """
    assets_dir_parts = Path(config.assets_dir).parts
    depth = len(assets_dir_parts)
    ids: set[str] = set()
    for problem in inventory.problems:
        parts = problem.path.parts
        if len(parts) > depth and parts[:depth] == assets_dir_parts:
            ids.add(parts[depth])
    return sorted(ids)


def find_asset(inventory: AssetInventory, asset_id: AssetId) -> Asset | None:
    """Look up one loaded asset by ID, or ``None`` if it did not load.

    Kept here rather than duplicated in ``cli`` (and, later, ``ui``) per
    CLAUDE.md's "cli and ui are thin" guardrail.
    """
    return next((asset for asset in inventory.assets if asset.id == asset_id), None)


@dataclass(frozen=True)
class AssetLookup:
    """The result of resolving one asset ID against a loaded inventory.

    Three outcomes, told apart here rather than in ``cli`` (ADR 0006):
    the asset loaded (``asset`` set, ``problems`` empty); no folder with
    that ID exists at all (both empty — genuinely unknown); or a folder
    with that ID exists but its ``asset.toml`` failed to load (``asset``
    is ``None``, ``problems`` non-empty; issue #15).
    """

    asset: Asset | None
    problems: list[MetadataProblem]


def lookup_asset(
    inventory: AssetInventory, config: CatalogConfig, asset_id: AssetId
) -> AssetLookup:
    """Resolve one asset ID, distinguishing "no such folder" from "folder
    exists but failed to load" (issue #15).

    A problem is attributed to this asset's folder when its ``path``
    (relative to the catalog root, per ``MetadataProblem``) falls under
    ``<assets_dir>/<asset_id>/`` — the folder ``load_assets`` would have
    read this asset from, whether the failure was a TOML syntax error, a
    schema problem, a source problem, or a duplicate-ID collision. That is
    enough to attribute correctly without touching the filesystem again.
    """
    asset = find_asset(inventory, asset_id)
    if asset is not None:
        return AssetLookup(asset=asset, problems=[])

    folder = Path(config.assets_dir) / asset_id
    problems = [
        problem
        for problem in inventory.problems
        if problem.path == folder or folder in problem.path.parents
    ]
    return AssetLookup(asset=None, problems=problems)


def load_assets(root: Path, config: CatalogConfig) -> AssetInventory:
    """Load and validate every ``asset.toml`` under the catalog's assets directory.

    A missing assets directory yields an empty inventory rather than an
    error: an asset-less catalog is valid, just empty.
    """
    assets_root = root / config.assets_dir
    if not assets_root.is_dir():
        return AssetInventory(assets=[], problems=[])

    # A folder without asset.toml is not an asset, so it is excluded here,
    # before the duplicate-ID pass, rather than being mistaken for one that
    # collides with a real asset folder of the same (case-folded) name.
    candidate_dirs = [
        asset_dir
        for asset_dir in sorted(p for p in assets_root.iterdir() if p.is_dir())
        if (asset_dir / ASSET_CONFIG_FILENAME).is_file()
    ]

    problems = duplicate_slug_problems(
        [
            ((asset_dir / ASSET_CONFIG_FILENAME).relative_to(root), asset_dir.name)
            for asset_dir in candidate_dirs
        ],
        field="id",
    )
    # A folder flagged above is a problem folder; problem folders are not
    # "loaded" (the same rule collections and products follow), so skip
    # parsing it rather than let a duplicate ID quietly end up in ``assets``
    # alongside its twin.
    duplicate_paths = {problem.path for problem in problems}

    assets: list[Asset] = []
    for asset_dir in candidate_dirs:
        toml_path = asset_dir / ASSET_CONFIG_FILENAME
        if toml_path.relative_to(root) in duplicate_paths:
            continue

        asset, file_problems = _load_one(root, asset_dir, toml_path, config)
        problems.extend(file_problems)
        if asset is not None:
            assets.append(asset)

    assets.sort(key=lambda asset: asset.id)
    return AssetInventory(assets=assets, problems=problems)


def _load_one(
    root: Path, asset_dir: Path, toml_path: Path, config: CatalogConfig
) -> tuple[Asset | None, list[MetadataProblem]]:
    rel_path = toml_path.relative_to(root)
    asset_id = asset_dir.name

    try:
        raw_text = toml_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [MetadataProblem(rel_path, None, str(exc))]

    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        return None, [MetadataProblem(rel_path, None, f"TOML syntax error: {exc}")]

    raw_id = data.pop("id", None)
    if raw_id is not None and raw_id != asset_id:
        return None, [
            MetadataProblem(
                rel_path,
                "id",
                f"id {raw_id!r} does not match folder name {asset_id!r}",
            )
        ]

    try:
        asset = Asset.model_validate({**data, "id": asset_id})
    except ValidationError as exc:
        return None, problems_from_validation_error(rel_path, exc)

    problems = [
        *_validate_sources(root, asset_dir, rel_path, asset, config),
        *_validate_derivatives(rel_path, asset),
    ]
    if problems:
        return None, problems

    return asset, []


def _validate_sources(
    root: Path,
    asset_dir: Path,
    toml_rel_path: Path,
    asset: Asset,
    config: CatalogConfig,
) -> list[MetadataProblem]:
    """Check one asset's declared sources against its ``sources/`` directory.

    Produces a problem for: a role outside the catalog's accepted roles
    (built-in plus ``catalog.toml``'s ``extra_roles``), a declared file
    that does not exist, a file under ``sources/`` that no declaration
    covers, the same file declared twice, and an asset with zero sources
    declared (§4.1, §21, ADR 0003).
    """
    problems: list[MetadataProblem] = []
    sources_dir = asset_dir / SOURCES_DIRNAME

    declared: dict[str, list[int]] = {}
    for index, source in enumerate(asset.sources):
        declared.setdefault(source.file, []).append(index)

        if source.role not in config.source_roles:
            problems.append(
                MetadataProblem(
                    toml_rel_path,
                    f"sources[{index}].role",
                    f"unknown role {source.role!r} for source {source.file!r}",
                )
            )
        if not (sources_dir / source.file).is_file():
            problems.append(
                MetadataProblem(
                    toml_rel_path,
                    f"sources[{index}].file",
                    f"declared source file not found: {source.file}",
                )
            )

    for file, indices in declared.items():
        if len(indices) > 1:
            problems.append(
                MetadataProblem(
                    toml_rel_path,
                    "sources",
                    f"{file!r} is declared {len(indices)} times",
                )
            )

    if sources_dir.is_dir():
        for entry in sorted(sources_dir.iterdir()):
            if entry.is_file() and entry.name not in declared:
                problems.append(
                    MetadataProblem(
                        entry.relative_to(root),
                        None,
                        "file in sources/ is not declared by any [[sources]] entry in asset.toml",
                    )
                )

    if not asset.sources:
        problems.append(MetadataProblem(toml_rel_path, "sources", "asset has no source images"))

    return problems


def _validate_derivatives(toml_rel_path: Path, asset: Asset) -> list[MetadataProblem]:
    """Check every ``[derivatives.<type>]`` pin against the asset's declared
    sources and the domain's recipes (ADR 0003, issue #22).

    A pin naming a file not declared under ``[[sources]]``, a file whose
    role the type's recipe does not accept, or a type with no recipe at all
    (not yet one of the three this PRD slice covers, or not a real
    derivative type) each produce one problem naming ``asset.toml`` and the
    offending field -- the same rule declared-source problems follow (the
    asset does not load).
    """
    problems: list[MetadataProblem] = []
    sources_by_file = {source.file: source for source in asset.sources}

    for type_name, pin in asset.derivatives.items():
        field = f"derivatives.{type_name}.source"

        recipe = recipe_for(type_name)
        if recipe is None:
            problems.append(
                MetadataProblem(toml_rel_path, field, f"{type_name!r} has no recipe to pin")
            )
            continue

        source = sources_by_file.get(pin.source)
        if source is None:
            problems.append(
                MetadataProblem(toml_rel_path, field, f"pinned source not declared: {pin.source!r}")
            )
            continue

        if source.role not in recipe.accepted_roles:
            accepted = ", ".join(recipe.accepted_roles)
            problems.append(
                MetadataProblem(
                    toml_rel_path,
                    field,
                    f"pinned source {pin.source!r} has role {source.role!r}, "
                    f"not accepted by {type_name} ({accepted})",
                )
            )

    return problems
