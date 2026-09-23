"""Load every collection under a catalog's collections directory.

A collection is any ``*.toml`` file directly under ``collections_dir``
(CONTEXT.md); the file's stem is its slug. Each file is validated
independently: one that fails becomes a ``MetadataProblem`` instead of
raising, so the rest of the catalog still loads (§35). Resolving a
collection's members (checking that asset IDs and other collection slugs
exist, evaluating a rule) is PRD 5's job; this module only validates shape
(issue #5).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.catalog.metadata_problem import MetadataProblem, problems_from_validation_error
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.collection import Collection, CollectionSlug

COLLECTION_CONFIG_SUFFIX = ".toml"


@dataclass(frozen=True)
class CollectionInventory:
    """Every collection that loaded, plus every problem found along the way.

    ``collections`` excludes any file that failed schema validation, or
    whose ``slug`` key disagreed with its own file stem, or that shares a
    slug with another file (case-insensitively — Windows and Linux
    filesystems disagree on whether ``Foo.toml`` and ``foo.toml`` can
    coexist, so this check normalises rather than comparing exact case);
    ``collections`` is sorted by slug.
    """

    collections: list[Collection]
    problems: list[MetadataProblem]


def find_collection(inventory: CollectionInventory, slug: CollectionSlug) -> Collection | None:
    """Look up one loaded collection by slug, or ``None`` if it did not load.

    Kept here rather than duplicated in ``cli`` (and, later, ``ui``) per
    CLAUDE.md's "cli and ui are thin" guardrail.
    """
    return next((c for c in inventory.collections if c.slug == slug), None)


def load_collections(root: Path, config: CatalogConfig) -> CollectionInventory:
    """Load and validate every collection file under the catalog's
    collections directory.

    A missing collections directory yields an empty inventory rather than
    an error: a collection-less catalog is valid, just empty.
    """
    collections_root = root / config.collections_dir
    if not collections_root.is_dir():
        return CollectionInventory(collections=[], problems=[])

    toml_paths = sorted(
        p
        for p in collections_root.iterdir()
        if p.is_file() and p.suffix == COLLECTION_CONFIG_SUFFIX
    )

    problems = duplicate_slug_problems([(p.relative_to(root), p.stem) for p in toml_paths])

    collections: list[Collection] = []
    for toml_path in toml_paths:
        collection, file_problems = _load_one(root, toml_path)
        problems.extend(file_problems)
        if collection is not None:
            collections.append(collection)

    collections.sort(key=lambda c: c.slug)
    return CollectionInventory(collections=collections, problems=problems)


def duplicate_slug_problems(stems: list[tuple[Path, str]]) -> list[MetadataProblem]:
    """Flag files whose slug (file stem) collides with another file's,
    comparing case-insensitively so the result is the same on Windows and
    Linux CI (issue #5's "normalise so CI on both agree") even though only
    a case-sensitive filesystem can actually hold both files at once.

    Public (not the directory-scanning loader's private detail) so the
    normalising comparison itself can be unit tested directly against
    fabricated paths, independent of what a given OS's filesystem allows
    two real files on disk to do.
    """
    by_normalized: dict[str, list[Path]] = {}
    for rel_path, stem in stems:
        by_normalized.setdefault(stem.casefold(), []).append(rel_path)

    problems: list[MetadataProblem] = []
    for paths in by_normalized.values():
        if len(paths) < 2:
            continue
        other_names = ", ".join(str(p) for p in paths)
        for rel_path in paths:
            problems.append(
                MetadataProblem(
                    rel_path,
                    "slug",
                    f"duplicate slug across files: {other_names}",
                )
            )
    return problems


def _load_one(root: Path, toml_path: Path) -> tuple[Collection | None, list[MetadataProblem]]:
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
        collection = Collection.model_validate({**data, "slug": slug})
    except ValidationError as exc:
        return None, problems_from_validation_error(rel_path, exc)

    return collection, []
