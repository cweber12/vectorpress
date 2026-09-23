"""Load every asset under a catalog's assets directory.

An asset is any folder under ``assets_dir`` that contains an ``asset.toml``
(CONTEXT.md); the folder name is its asset ID. Each file is validated
independently: one that fails becomes a ``MetadataProblem`` instead of
raising, so the rest of the catalog still loads (§35).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig

ASSET_CONFIG_FILENAME = "asset.toml"


@dataclass(frozen=True)
class AssetInventory:
    """Every asset that loaded, plus every problem found along the way.

    ``assets`` excludes any folder whose ``asset.toml`` produced a problem;
    ``assets`` is sorted by asset ID.
    """

    assets: list[Asset]
    problems: list[MetadataProblem]


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

        asset, file_problems = _load_one(root, asset_dir, toml_path)
        problems.extend(file_problems)
        if asset is not None:
            assets.append(asset)

    assets.sort(key=lambda asset: asset.id)
    return AssetInventory(assets=assets, problems=problems)


def _load_one(
    root: Path, asset_dir: Path, toml_path: Path
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

    return asset, []


def _problems_from_validation_error(path: Path, exc: ValidationError) -> list[MetadataProblem]:
    problems: list[MetadataProblem] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or None
        problems.append(MetadataProblem(path, field, error["msg"]))
    return problems
