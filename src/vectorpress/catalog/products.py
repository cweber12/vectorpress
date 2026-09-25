"""Load every product under a catalog's products directory.

A product is any ``*.toml`` file directly under ``products_dir``
(CONTEXT.md); the file's stem is its slug. Each file is validated
independently: one that fails becomes a ``MetadataProblem`` instead of
raising, so the rest of the catalog still loads (§35). Whether a product's
referenced collection slug, or an inline membership's asset IDs and
collection slugs, actually exist is PRD 5's job; this module only
validates shape (issue #7).
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
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.product import Product, ProductSlug

PRODUCT_CONFIG_SUFFIX = ".toml"


@dataclass(frozen=True)
class ProductInventory:
    """Every product that loaded, plus every problem found along the way.

    ``products`` excludes any file that failed schema validation, or whose
    ``slug`` key disagreed with its own file stem, or that shares a slug
    with another file (case-insensitively, the same rule collections
    follow — issue #5); ``products`` is sorted by slug.
    """

    products: list[Product]
    problems: list[MetadataProblem]


def find_product(inventory: ProductInventory, slug: ProductSlug) -> Product | None:
    """Look up one loaded product by slug, or ``None`` if it did not load.

    Kept here rather than duplicated in ``cli`` (and, later, ``ui``) per
    CLAUDE.md's "cli and ui are thin" guardrail.
    """
    return next((p for p in inventory.products if p.slug == slug), None)


def product_toml_path(config: CatalogConfig, slug: ProductSlug) -> Path:
    """The on-disk path (relative to the catalog root) a product's slug
    would have loaded from, whether or not it did -- used to attribute a
    failed-to-load lookup, or a reference problem on this product's own
    file (``build.product_resolution``'s inline-membership path, and
    ``catalog.collection_resolution.product_collection_slug_reference_problem``),
    to the right file. Mirrors ``catalog.collection_resolution.collection_toml_path``.
    """
    return Path(config.products_dir) / f"{slug}{PRODUCT_CONFIG_SUFFIX}"


@dataclass(frozen=True)
class ProductLookup:
    """The result of resolving one product slug against a loaded inventory
    (issue #38), mirroring :class:`~vectorpress.catalog.assets.AssetLookup`.

    Three outcomes, told apart here rather than in ``cli`` (ADR 0006): the
    product loaded (``product`` set, ``problems`` empty); no ``<slug>.toml``
    exists at all (both empty -- genuinely unknown slug); or that file exists
    but failed to load (``product`` is ``None``, ``problems`` non-empty).
    """

    product: Product | None
    problems: list[MetadataProblem]


def lookup_product(
    inventory: ProductInventory, config: CatalogConfig, slug: ProductSlug
) -> ProductLookup:
    """Resolve one product slug, distinguishing "no such file" from "file
    exists but failed to load" (issue #38's "An unknown product slug is an
    actionable error, and so is a product that failed to load"), the same
    two-outcome split :func:`vectorpress.catalog.assets.lookup_asset` already
    makes for asset IDs.

    A problem is attributed to this slug when its ``path`` (relative to the
    catalog root) is exactly ``<products_dir>/<slug>.toml`` -- the file
    ``load_products`` would have read this product from, whether the failure
    was a TOML syntax error, a schema problem, or a duplicate-slug collision.
    """
    product = find_product(inventory, slug)
    if product is not None:
        return ProductLookup(product=product, problems=[])

    toml_path = product_toml_path(config, slug)
    problems = [problem for problem in inventory.problems if problem.path == toml_path]
    return ProductLookup(product=None, problems=problems)


def load_products(root: Path, config: CatalogConfig) -> ProductInventory:
    """Load and validate every product file under the catalog's products
    directory.

    A missing products directory yields an empty inventory rather than an
    error: a product-less catalog is valid, just empty.
    """
    products_root = root / config.products_dir
    if not products_root.is_dir():
        return ProductInventory(products=[], problems=[])

    toml_paths = sorted(
        p for p in products_root.iterdir() if p.is_file() and p.suffix == PRODUCT_CONFIG_SUFFIX
    )

    problems = duplicate_slug_problems([(p.relative_to(root), p.stem) for p in toml_paths])
    # A file flagged above is a problem file; problem files are not "loaded"
    # (the same rule assets and collections follow), so skip parsing it
    # rather than let a duplicate slug quietly end up in ``products``
    # alongside its twin.
    duplicate_paths = {problem.path for problem in problems}

    products: list[Product] = []
    for toml_path in toml_paths:
        if toml_path.relative_to(root) in duplicate_paths:
            continue
        product, file_problems = _load_one(root, toml_path)
        problems.extend(file_problems)
        if product is not None:
            products.append(product)

    products.sort(key=lambda p: p.slug)
    return ProductInventory(products=products, problems=problems)


def _load_one(root: Path, toml_path: Path) -> tuple[Product | None, list[MetadataProblem]]:
    rel_path = toml_path.relative_to(root)
    slug = toml_path.stem

    try:
        raw_text = toml_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [MetadataProblem(rel_path, None, str(exc))]

    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        return None, [MetadataProblem(rel_path, None, f"TOML syntax error: {exc}")]

    raw_slug = data.pop("slug", None)
    if raw_slug is not None and raw_slug != slug:
        return None, [
            MetadataProblem(
                rel_path,
                "slug",
                f"slug {raw_slug!r} does not match file name {slug!r}",
            )
        ]

    try:
        product = Product.model_validate({**data, "slug": slug})
    except ValidationError as exc:
        return None, problems_from_validation_error(rel_path, exc)

    return product, []
