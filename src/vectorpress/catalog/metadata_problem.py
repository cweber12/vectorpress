"""A hand-authored file that failed validation.

Plain data, not an exception (issue #2): the catalog loaders collect these
instead of raising, so one bad file does not stop the rest of the catalog
from loading (§35). The ``cli`` layer renders them; #6 reuses this shape for
the catalog-wide attention report.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError


@dataclass(frozen=True)
class MetadataProblem:
    """One hand-authored file's validation failure.

    ``path`` is relative to the catalog root. ``field`` is the offending
    field name where the problem traces to one field, else ``None``.
    """

    path: Path
    field: str | None
    message: str

    def __str__(self) -> str:
        location = f"{self.path} ({self.field})" if self.field else str(self.path)
        return f"{location}: {self.message}"


def problems_from_validation_error(path: Path, exc: ValidationError) -> list[MetadataProblem]:
    """Turn a pydantic ``ValidationError`` into one ``MetadataProblem`` per error.

    Shared by every hand-authored-file loader (``assets``, ``brand``,
    ``collections``) instead of each one duplicating this translation
    (deferred from issue #3).
    """
    problems: list[MetadataProblem] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or None
        problems.append(MetadataProblem(path, field, error["msg"]))
    return problems
