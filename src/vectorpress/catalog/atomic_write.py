"""Atomic file writes for tool-owned state under a catalog (§35).

Shared by every ``catalog`` module that persists a derivative or its JSON
state (:mod:`vectorpress.catalog.provenance`, :mod:`vectorpress.catalog.findings`),
so "never leave a half-written file observable" is implemented once.
"""

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` without ever leaving a half-written file
    observable: write to a temporary file in the same directory, then rename
    into place. ``Path.replace`` is atomic on both POSIX and Windows and,
    unlike a plain rename, always overwrites. A failure at any step removes
    the temporary file and re-raises."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
