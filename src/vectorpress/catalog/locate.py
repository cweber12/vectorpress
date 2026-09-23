"""Locate a catalog root: an explicit ``--catalog`` path, or walk up from cwd.

The only thing this module does is find the directory that holds
``catalog.toml``; reading and validating that file is ``catalog.load``'s job
(ADR 0006 keeps the ``catalog`` layer as the only one that touches catalog
files).
"""

from pathlib import Path

from vectorpress.catalog.errors import CatalogNotFoundError

CATALOG_CONFIG_FILENAME = "catalog.toml"


def locate_catalog_root(start: Path, *, explicit: Path | None = None) -> Path:
    """Return the catalog root directory (the one containing ``catalog.toml``).

    - If ``explicit`` is given (from ``--catalog``), that directory must
      itself contain ``catalog.toml``; no walking is done.
    - Otherwise, walk up from ``start`` until a directory containing
      ``catalog.toml`` is found.

    Raises ``CatalogNotFoundError`` naming every directory searched.
    """
    if explicit is not None:
        root = explicit.resolve()
        if not (root / CATALOG_CONFIG_FILENAME).is_file():
            raise CatalogNotFoundError([root])
        return root

    searched: list[Path] = []
    current = start.resolve()
    while True:
        searched.append(current)
        if (current / CATALOG_CONFIG_FILENAME).is_file():
            return current
        parent = current.parent
        if parent == current:
            raise CatalogNotFoundError(searched)
        current = parent
