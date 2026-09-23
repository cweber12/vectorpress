"""Errors raised while locating or loading a catalog."""

from pathlib import Path


class CatalogNotFoundError(Exception):
    """Raised when no ``catalog.toml`` was found.

    Carries every directory that was searched so the message can name them,
    per issue #1's "no catalog found is an actionable error naming the
    directories searched".
    """

    def __init__(self, searched: list[Path]) -> None:
        self.searched = searched
        dirs = "\n".join(f"  - {d}" for d in searched)
        super().__init__(f"No catalog.toml found. Searched:\n{dirs}")


class CatalogConfigError(Exception):
    """Raised when ``catalog.toml`` cannot be read or fails validation.

    Names the file and, where the problem traces to a specific field, that
    field too.
    """

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid catalog config at {path}:\n{detail}")
