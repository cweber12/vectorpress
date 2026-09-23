"""Load every asset under a catalog's assets directory.

An asset is any folder under ``assets_dir`` that contains an ``asset.toml``
(CONTEXT.md); the folder name is its asset ID. Each file is validated
independently: one that fails becomes a ``MetadataProblem`` instead of
raising, so the rest of the catalog still loads (§35). Validation also
checks declared sources against the asset's ``sources/`` directory
(§4.1, §21, ADR 0003).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.asset import Asset, AssetId
from vectorpress.domain.catalog_config import CatalogConfig

ASSET_CONFIG_FILENAME = "asset.toml"
SOURCES_DIRNAME = "sources"


@dataclass(frozen=True)
class AssetInventory:
    """Every asset that loaded, plus every problem found along the way.

    ``assets`` excludes any folder whose ``asset.toml`` failed schema
    validation, or whose declared sources produced a problem (unknown
    role, missing or undeclared file, duplicate declaration, zero
    sources); ``assets`` is sorted by asset ID.
    """

    assets: list[Asset]
    problems: list[MetadataProblem]


def find_asset(inventory: AssetInventory, asset_id: AssetId) -> Asset | None:
    """Look up one loaded asset by ID, or ``None`` if it did not load.

    Kept here rather than duplicated in ``cli`` (and, later, ``ui``) per
    CLAUDE.md's "cli and ui are thin" guardrail.
    """
    return next((asset for asset in inventory.assets if asset.id == asset_id), None)


def load_assets(root: Path, config: CatalogConfig) -> AssetInventory:
    """Load and validate every ``asset.toml`` under the catalog's assets directory.

    A missing assets directory yields an empty inventory rather than an
    error: an asset-less catalog is valid, just empty.
    """
    assets_root = root / config.assets_dir
    if not assets_root.is_dir():
        return AssetInventory(assets=[], problems=[])

    assets: list[Asset] = []
    problems: list[MetadataProblem] = []

    for asset_dir in sorted(p for p in assets_root.iterdir() if p.is_dir()):
        toml_path = asset_dir / ASSET_CONFIG_FILENAME
        if not toml_path.is_file():
            continue  # a folder without asset.toml is not an asset

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
        return None, _problems_from_validation_error(rel_path, exc)

    source_problems = _validate_sources(root, asset_dir, rel_path, asset, config)
    if source_problems:
        return None, source_problems

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


def _problems_from_validation_error(path: Path, exc: ValidationError) -> list[MetadataProblem]:
    problems: list[MetadataProblem] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or None
        problems.append(MetadataProblem(path, field, error["msg"]))
    return problems
