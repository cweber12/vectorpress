"""Tool-owned provenance records for generated derivatives (ADR 0004, ADR
0005, CONTEXT.md "Provenance").

Only ``catalog`` touches catalog files (ADR 0006): this module owns every
byte that crosses the boundary between disk and a generator -- reading a
source's bytes to hand to a generator, reading/writing provenance, and
deciding whether a derivative is current, stale (with a reason), or missing
by re-reading and re-hashing what is actually on disk (issue #26).
``pipeline.generate`` orchestrates (which recipe, which generator, in what
order) but never opens a catalog file itself (issue #23 review fix round 2).
"""

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from vectorpress.catalog.assets import SOURCES_DIRNAME
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.recipe import Recipe

#: Every asset's generated derivatives live under this folder, sibling to
#: ``sources/`` (ADR 0005's "Per-asset layout").
DERIVED_DIRNAME = "derived"

#: A provenance record for ``<name>`` is a plain-JSON file named
#: ``<name>.provenance.json`` beside it, so it never collides with a
#: derivative's own filename and is trivially findable from one.
_PROVENANCE_SUFFIX = ".provenance.json"


def sha256_bytes(data: bytes) -> str:
    """The SHA-256 hex digest of ``data`` (ADR 0004: "Hashes are SHA-256 of
    bytes")."""
    return hashlib.sha256(data).hexdigest()


def recipe_identity_hash(recipe: Recipe, parameters: Mapping[str, object] | None = None) -> str:
    """The recipe identity hash: derivative type, generator name, and
    parameters (ADR 0004: "recipe identity including parameters, hashed so a
    parameter change changes the identity").

    ``parameters`` defaults to ``recipe.parameters`` -- every recipe but
    ``cut_svg`` (currently). ``cut_svg``'s cleanup thresholds are physical
    (§9.1), so its generator also needs the catalog's reference size, which
    is not part of ``recipe.parameters``' static declaration -- it is a
    catalog-wide setting, not something ``domain.recipe`` has any business
    knowing about (ADR 0006). ``pipeline.generate`` computes that *effective*
    parameter mapping (recipe parameters plus reference size) once and passes
    it here explicitly, so a ``reference_size_in`` change changes exactly
    this recipe's identity (issue #36) the same way any other parameter
    change would -- without ``domain.recipe`` or this function needing to
    know which recipes have catalog-level parameters and which don't.

    ``json.dumps(..., sort_keys=True)`` makes the encoding independent of
    ``parameters``' key order, so the hash depends only on the recipe's
    actual content -- not something incidental like dict insertion order.
    """
    effective_parameters = recipe.parameters if parameters is None else parameters
    payload = {
        "derivative_type": recipe.derivative_type.value,
        "generator": recipe.generator,
        "parameters": effective_parameters,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


@dataclass(frozen=True)
class Provenance:
    """One derivative's tool-owned provenance record (ADR 0004, issue #23).

    ``source_file`` and ``source_hash`` identify the source the derivative
    was built from; ``recipe_hash`` is :func:`recipe_identity_hash` of the
    recipe used, so a parameter or generator change is detectable without
    re-deriving it; ``generator_versions`` records vectorpress's own version
    plus every library the generator used (informational only -- ADR 0004:
    "No manually bumped version numbers in tool logic" means currency is
    never gated on these, only on the hashes).
    """

    source_file: str
    source_hash: str
    derivative_type: str
    generator: str
    parameters: dict[str, object]
    recipe_hash: str
    generator_versions: dict[str, str]
    output_file: str
    output_hash: str


def read_source_bytes(asset_dir: Path, source_file: str) -> bytes:
    """Read one asset's source file's bytes, to hand to a generator or hash
    against provenance (ADR 0003: ``sources/`` is read-only to the tool --
    this only ever reads it, never modifies it)."""
    return (asset_dir / SOURCES_DIRNAME / source_file).read_bytes()


#: The three ways a derivative can be stale (ADR 0004, CONTEXT.md "Stale",
#: issue #26), each a distinct, user-facing reason string. Checked in this
#: order by :func:`derivative_currency`; ``vpress asset`` shows the reason as
#: ``stale (<reason>)``.
SOURCE_CHANGED = "source changed"
RECIPE_CHANGED = "recipe changed"
OUTPUT_CHANGED_ON_DISK = "output changed on disk"


@dataclass(frozen=True)
class Currency:
    """The on-disk currency of one derivative that has already had a source
    selected for it (ADR 0004, issue #26): :attr:`DerivativeState.CURRENT`,
    :attr:`DerivativeState.STALE` with one of :data:`SOURCE_CHANGED`,
    :data:`RECIPE_CHANGED`, :data:`OUTPUT_CHANGED_ON_DISK`, or
    :attr:`DerivativeState.MISSING` (never generated, or its output file is
    gone -- CONTEXT.md's "Stale" reserves staleness for a derivative that
    still exists).

    ``reason`` is set exactly when ``state`` is ``STALE``.
    """

    state: DerivativeState
    reason: str | None


def derivative_currency(
    asset_dir: Path, output_filename: str, source_file: str, recipe_hash: str
) -> Currency:
    """Whether the derivative named ``output_filename`` is current, stale
    (with a reason), or was never generated (ADR 0004, §36, issue #26).

    ``MISSING``: no provenance record exists yet, or the output file itself
    is gone -- a derivative whose file was deleted is missing, not stale,
    even though its provenance record may still be sitting beside it.
    ``STALE``: provenance and the output file both exist, but the recorded
    source hash no longer matches ``source_file`` as it stands now
    (:data:`SOURCE_CHANGED`), the recorded recipe identity no longer matches
    ``recipe_hash`` (:data:`RECIPE_CHANGED`), or the output file's hash no
    longer matches the recorded output hash (:data:`OUTPUT_CHANGED_ON_DISK`
    -- hand-edited or replaced on disk; a hand edit belongs under
    ``overrides/``, PRD 4, not ``derived/``). ``CURRENT``: none of the above.

    Every catalog-file read this needs (source, provenance, output) happens
    here, not in ``pipeline`` (ADR 0006's "catalog... the only layer
    touching catalog files"): the caller passes in ``recipe_hash`` --
    :func:`recipe_identity_hash` of the current recipe -- rather than the
    recipe itself, since computing it is a pure function over domain data,
    not a file read, and stays the caller's job.
    """
    derived_dir = asset_dir / DERIVED_DIRNAME
    provenance = read_provenance(derived_dir, output_filename)
    if provenance is None:
        return Currency(DerivativeState.MISSING, None)

    output_path = derived_dir / output_filename
    if not output_path.is_file():
        return Currency(DerivativeState.MISSING, None)

    source_path = asset_dir / SOURCES_DIRNAME / source_file
    source_hash = sha256_bytes(source_path.read_bytes()) if source_path.is_file() else None
    if provenance.source_hash != source_hash:
        return Currency(DerivativeState.STALE, SOURCE_CHANGED)

    if provenance.recipe_hash != recipe_hash:
        return Currency(DerivativeState.STALE, RECIPE_CHANGED)

    if provenance.output_hash != sha256_bytes(output_path.read_bytes()):
        return Currency(DerivativeState.STALE, OUTPUT_CHANGED_ON_DISK)

    return Currency(DerivativeState.CURRENT, None)


def provenance_path(derived_dir: Path, output_filename: str) -> Path:
    """Where one derivative's provenance record lives, beside it."""
    return derived_dir / f"{output_filename}{_PROVENANCE_SUFFIX}"


def read_provenance(derived_dir: Path, output_filename: str) -> Provenance | None:
    """The provenance record for one derivative, or ``None`` if it does not
    exist (never generated, or an override with no generated counterpart)."""
    path = provenance_path(derived_dir, output_filename)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Provenance(**data)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` without ever leaving a half-written file
    observable (§35): write to a temporary file in the same directory, then
    rename into place -- a rename is atomic on both POSIX and Windows
    (``os.replace``, unlike a plain ``os.rename``, always overwrites)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        Path(tmp_name).replace(path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_derivative(
    derived_dir: Path, output_filename: str, output_bytes: bytes, provenance: Provenance
) -> None:
    """Persist one derivative's output and provenance (§35, §36, issue #23).

    Output is written first, provenance second, each as its own atomic
    write, so a crash between the two leaves, at worst, a derivative whose
    provenance has not caught up yet -- never a half-written file, and never
    provenance describing an output that was not actually written.

    When the output file already on disk hashes to ``provenance.output_hash``,
    its bytes are left untouched (no rewrite, no mtime change): this is what
    makes a second identical generation, and a parameter change that happens
    to produce identical output, non-destructive (§36 idempotence). The same
    idempotence applies to the provenance record itself (issue #26 review
    fix round 1, AC5's "no file is rewritten"): when the serialized payload
    about to be written is byte-identical to what is already on disk, it is
    left untouched too -- so ``--force`` on an unchanged derivative rewrites
    neither file. A payload that differs only in ``generator_versions``
    (e.g. a library upgrade) is still written, since that is part of the
    same serialized payload being compared.
    """
    output_path = derived_dir / output_filename
    if not (
        output_path.is_file() and sha256_bytes(output_path.read_bytes()) == provenance.output_hash
    ):
        _atomic_write_bytes(output_path, output_bytes)

    payload = json.dumps(asdict(provenance), sort_keys=True, indent=2).encode("utf-8")
    record_path = provenance_path(derived_dir, output_filename)
    if not (record_path.is_file() and record_path.read_bytes() == payload):
        _atomic_write_bytes(record_path, payload)
