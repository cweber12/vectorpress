"""Read and validate a catalog root's ``catalog.toml``, and the single load
entry point that aggregates every hand-authored file's metadata problems.

``catalog.toml`` is hand-authored and read-only to the tool (ADR 0005): this
module only ever reads it, through the standard-library ``tomllib``.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.brand import load_brand
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.errors import CatalogConfigError
from vectorpress.catalog.locate import CATALOG_CONFIG_FILENAME
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.products import load_products
from vectorpress.domain.asset import Asset
from vectorpress.domain.brand import Brand
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection
from vectorpress.domain.product import Product


@dataclass(frozen=True)
class LoadedCatalog:
    """Everything loaded from one catalog root: config, assets, collections,
    products, brand, and every metadata problem found across every
    hand-authored file (issue #6, issue #7).

    This is the catalog layer's single load entry point: ``cli`` (and later
    ``ui``) render ``problems``, never producing report text themselves
    (CLAUDE.md's "cli and ui are thin").

    ``config`` is ``None`` only when ``catalog.toml`` itself failed to load;
    in that case ``assets``, ``collections`` and ``products`` are empty and
    ``brand`` is ``None``, since nothing that depends on config (the assets,
    collections and products directories, accepted source roles) could be
    located, and loading stops there. ``brand`` is otherwise ``None`` when
    ``brand.toml`` is missing, malformed, or invalid (issue #3): a catalog
    can exist before its brand is written.
    """

    root: Path
    config: CatalogConfig | None
    assets: list[Asset]
    collections: list[Collection]
    products: list[Product]
    brand: Brand | None
    problems: list[MetadataProblem]


def load_catalog(root: Path) -> LoadedCatalog:
    """Load a catalog root end to end: config, assets, collections,
    products, brand, and every metadata problem found along the way.

    A broken ``catalog.toml`` does not raise here: the root was already
    located (its ``catalog.toml`` exists, or the caller would not have this
    path), so a broken config is a metadata problem, not a "no catalog
    found" error. It becomes one ``MetadataProblem`` naming ``catalog.toml``,
    and loading stops there, since ``assets_dir``, ``collections_dir`` and
    ``products_dir`` all come from config.
    """
    try:
        config = load_catalog_config(root)
    except CatalogConfigError as exc:
        problem = MetadataProblem(exc.path.relative_to(root), None, exc.detail)
        return LoadedCatalog(
            root=root,
            config=None,
            assets=[],
            collections=[],
            products=[],
            brand=None,
            problems=[problem],
        )

    inventory = load_assets(root, config)
    collection_inventory = load_collections(root, config)
    product_inventory = load_products(root, config)
    brand_result = load_brand(root)
    problems = [
        *inventory.problems,
        *collection_inventory.problems,
        *product_inventory.problems,
        *brand_result.problems,
    ]
    return LoadedCatalog(
        root=root,
        config=config,
        assets=inventory.assets,
        collections=collection_inventory.collections,
        products=product_inventory.products,
        brand=brand_result.brand,
        problems=problems,
    )


def load_catalog_config(root: Path) -> CatalogConfig:
    """Load and validate the ``catalog.toml`` at a catalog root.

    Raises ``CatalogConfigError`` naming the file, and where the problem
    traces to one, the offending field, for a TOML syntax error, an unknown
    key, or a wrongly typed value.
    """
    path = root / CATALOG_CONFIG_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogConfigError(path, str(exc)) from exc

    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogConfigError(path, f"TOML syntax error: {exc}") from exc

    try:
        return CatalogConfig.model_validate(data)
    except ValidationError as exc:
        raise CatalogConfigError(path, _format_validation_error(exc)) from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {field}: {error['msg']}")
    return "\n".join(lines)
