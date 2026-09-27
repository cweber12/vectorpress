"""A hand-authored file that failed validation.

Plain data, not an exception (issue #2): the catalog loaders collect these
instead of raising, so one bad file does not stop the rest of the catalog
from loading (§35). The ``cli`` layer renders them; #6 reuses this shape for
the catalog-wide attention report.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vectorpress.domain.metadata_field_error import MetadataFieldError, MetadataFieldsError


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
    ``collections``, ``products``) instead of each one duplicating this
    translation (deferred from issue #3).

    Pydantic prefixes a raised exception's own message with a wrapper
    string ("Value error, ...", "Assertion failed, ...") in ``msg``; the
    raised exception itself (``error["ctx"]["error"]``, present only when
    the error came from a raised exception rather than a built-in pydantic
    check) does not carry that prefix, so it is used for the message
    whenever present (issue #16). A cross-field ``model_validator`` check
    has an empty ``loc`` — pydantic has no single field to blame — so when
    the raised exception is a ``MetadataFieldError`` its ``field`` is used
    instead (issue #16). A ``MetadataFieldsError`` (plural) raise — one
    check that found several independent problems — expands into that many
    ``MetadataProblem``\\ s instead of one, since pydantic itself only ever
    raises the single exception a validator raised.
    """
    problems: list[MetadataProblem] = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or None
        message = error["msg"]

        raised = error.get("ctx", {}).get("error")
        if isinstance(raised, MetadataFieldsError):
            problems.extend(MetadataProblem(path, f, m) for f, m in raised.problems)
            continue
        if isinstance(raised, Exception):
            message = str(raised)
            if field is None and isinstance(raised, MetadataFieldError):
                field = raised.field

        problems.append(MetadataProblem(path, field, message))
    return problems


def duplicate_slug_problems(
    stems: list[tuple[Path, str]], *, field: str = "slug"
) -> list[MetadataProblem]:
    """Flag entries whose name collides with another's, comparing
    case-insensitively so the result is the same on Windows and Linux CI
    (issue #5's "normalise so CI on both agree") even though only a
    case-sensitive filesystem can actually hold both entries at once.

    ``stems`` pairs each entry's problem path with the name to compare —
    a file stem for a directory-of-``<slug>.toml``-files loader, a folder
    name for a directory-of-asset-folders loader. ``field`` names the
    offending field on the resulting problems, so a caller comparing
    something other than a slug (``assets``, on asset ID — issue #17) gets
    problems attributed correctly.

    Shared by every loader with this collide-on-name shape (``collections``,
    ``products``, issue #7's "reuse or generalise duplicate_slug_problems";
    ``assets``, issue #17) instead of each one duplicating this cross-file
    pass.
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
                    field,
                    f"duplicate {field} across files: {other_names}",
                )
            )
    return problems
