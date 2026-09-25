"""Override detection and the effective derivative (§6.8, §39.16, ADR 0003,
ADR 0004, ADR 0005, ADR 0007, CONTEXT.md "Override", "Effective derivative").

A hand-edited file under an asset's ``overrides/``, named exactly like the
generated derivative's filename for a type, is that type's override: the
**effective derivative** every other consumer (``vpress asset``,
``validate``, ``vpress status``) resolves through
:func:`effective_derivative` instead of reading ``derived/`` directly.
``overrides/`` is otherwise read-only to the tool (ADR 0003, ADR 0005,
§6.8): nothing in this module writes, moves or deletes anything under it,
except :func:`create_override_from_generated` -- ``vpress open --override``'s
create-only copy, made only on that explicit request, and never overwriting
a file already there -- and :func:`discard_override_file` -- ``vpress
override discard --yes``'s removal of the one file a human asked to remove
(CONTEXT.md "Override").

An override's own status and provenance are tool-owned state under
``derived/`` instead -- their own pair of files, distinct from the
generated derivative's own status record and provenance record (ADR 0006:
only ``catalog`` touches catalog files), so approving, rejecting or
hand-editing an override never touches the generated derivative's own
record, and regenerating never touches the override's.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from vectorpress.catalog.assets import SOURCES_DIRNAME
from vectorpress.catalog.atomic_write import atomic_write_bytes
from vectorpress.catalog.derivatives import select_source
from vectorpress.catalog.findings import findings_path
from vectorpress.catalog.provenance import (
    DERIVED_DIRNAME,
    SOURCE_CHANGED,
    read_derivative_bytes,
    read_provenance,
    read_source_bytes,
    sha256_bytes,
)
from vectorpress.catalog.status import asset_derivative_status
from vectorpress.domain.asset import Asset
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import Recipe
from vectorpress.domain.status import Status, StatusRecord, effective_status

#: Every asset's hand-edited derivatives live under this folder, sibling to
#: ``sources/`` and ``derived/`` (ADR 0005's per-asset layout). Read-only to
#: the tool: nothing in this module writes here.
OVERRIDES_DIRNAME = "overrides"


def override_path(asset_dir_path: Path, output_filename: str) -> Path:
    """Where one derivative type's override would live, if it exists --
    named exactly like the generated derivative's own filename (§6.8), just
    under ``overrides/`` instead of ``derived/``."""
    return asset_dir_path / OVERRIDES_DIRNAME / output_filename


def read_override_bytes(asset_dir_path: Path, output_filename: str) -> bytes | None:
    """One derivative type's override bytes, or ``None`` if no file named
    ``output_filename`` exists under ``overrides/``."""
    path = override_path(asset_dir_path, output_filename)
    if not path.is_file():
        return None
    return path.read_bytes()


@dataclass(frozen=True)
class EffectiveDerivative:
    """The file a product actually uses for one (asset, derivative type)
    (CONTEXT.md "Effective derivative"): the override's bytes when one
    exists, else the generated derivative's."""

    bytes: bytes
    is_override: bool


def effective_derivative(asset_dir_path: Path, output_filename: str) -> EffectiveDerivative | None:
    """The effective derivative for one (asset, derivative type) whose
    generated filename is ``output_filename`` -- the one catalog-level
    answer to "which file is effective" every consumer (``vpress asset``,
    ``validate``, ``vpress status``) goes through (§6.8): the override if
    one exists under ``overrides/``, else the generated file under
    ``derived/``. ``None`` when neither exists."""
    override_bytes = read_override_bytes(asset_dir_path, output_filename)
    if override_bytes is not None:
        return EffectiveDerivative(bytes=override_bytes, is_override=True)

    generated_bytes = read_derivative_bytes(asset_dir_path / DERIVED_DIRNAME, output_filename)
    if generated_bytes is not None:
        return EffectiveDerivative(bytes=generated_bytes, is_override=False)

    return None


def list_unrecognized_overrides(asset_dir_path: Path, known_filenames: Iterable[str]) -> list[str]:
    """Every file under ``overrides/`` that does not match any of
    ``known_filenames`` (every recipe-bearing derivative type's filename for
    this asset), sorted. Reported by ``vpress asset`` as ignored, never an
    error (§6.8's own file, never a source or generated derivative, is the
    only thing a name match here can mean)."""
    overrides_dir = asset_dir_path / OVERRIDES_DIRNAME
    if not overrides_dir.is_dir():
        return []
    known = set(known_filenames)
    return sorted(
        entry.name
        for entry in overrides_dir.iterdir()
        if entry.is_file() and entry.name not in known
    )


def create_override_from_generated(
    asset: Asset,
    asset_dir_path: Path,
    recipe: Recipe,
    output_filename: str,
    generated_bytes: bytes,
) -> Path:
    """Start an override for one (asset, ``recipe``'s type) by copying the
    current generated file into ``overrides/`` byte-for-byte (``vpress open
    --override``, §6.8, §24) -- the one sanctioned write under
    ``overrides/`` this module otherwise never makes, on the user's explicit
    request only. Create-only: a file already there is returned untouched,
    never rewritten, so a second call is a no-op.

    Records the override's provenance immediately
    (:func:`ensure_override_provenance`) the moment it is created, rather
    than waiting for a later ``validate`` or ``approve``, so a source change
    afterward is detectable as staleness right away.

    Also clears any provenance, status or findings left behind by a
    *previous* override at this path that was deleted by hand instead of
    through ``vpress override discard`` (§22.2): that leftover state is
    orphaned, since nothing here removed it when the file disappeared, and
    the fresh override must not inherit it -- a stale flag, an approval or a
    findings result that describe bytes nobody wrote.
    """
    path = override_path(asset_dir_path, output_filename)
    if path.is_file():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(generated_bytes)
    except FileExistsError:
        # Created by someone else between the check above and here: the
        # file that won is what matters, not which call wrote it.
        return path

    _clear_orphaned_override_state(asset_dir_path, recipe.derivative_type, output_filename)
    ensure_override_provenance(asset, asset_dir_path, recipe, output_filename, generated_bytes)
    return path


# --- override provenance: the source hash it was edited against (§6.8, ADR 0004) ----

_OVERRIDE_PROVENANCE_SUFFIX = ".override_provenance.json"


@dataclass(frozen=True)
class OverrideProvenance:
    """One override's tool-owned provenance record (ADR 0004, ADR 0007).

    Stripped to what an override needs, unlike
    :class:`~vectorpress.catalog.provenance.Provenance`: no recipe or
    generator, since a human, not a recipe, produced it. ``source_hash`` is
    the hash of the source the override was edited against -- recorded once,
    when the override is first seen, and never updated afterward: a later
    source change is what makes the override *stale* (§22.2, a later PRD
    slice), which needs a fixed point of comparison, not a moving one.
    ``output_hash`` is the override file's own current bytes hash.
    """

    source_hash: str
    output_hash: str


def override_provenance_path(derived_dir: Path, output_filename: str) -> Path:
    """Where one override's provenance record lives, under ``derived/`` --
    never colliding with the generated derivative's own
    ``<name>.provenance.json`` and never written under ``overrides/``."""
    return derived_dir / f"{output_filename}{_OVERRIDE_PROVENANCE_SUFFIX}"


def read_override_provenance(derived_dir: Path, output_filename: str) -> OverrideProvenance | None:
    """One override's provenance record, or ``None`` if it has never been
    seen by :func:`ensure_override_provenance`."""
    path = override_provenance_path(derived_dir, output_filename)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return OverrideProvenance(source_hash=data["source_hash"], output_hash=data["output_hash"])


def write_override_provenance(
    derived_dir: Path, output_filename: str, record: OverrideProvenance
) -> None:
    """Persist one override's provenance record. Idempotent like every other
    tool-owned JSON write in ``catalog`` (:mod:`vectorpress.catalog.provenance`,
    :mod:`vectorpress.catalog.status`, :mod:`vectorpress.catalog.findings`):
    when the payload already matches what is on disk byte-for-byte, the file
    is left untouched."""
    payload = json.dumps(
        {"source_hash": record.source_hash, "output_hash": record.output_hash},
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    path = override_provenance_path(derived_dir, output_filename)
    if not (path.is_file() and path.read_bytes() == payload):
        atomic_write_bytes(path, payload)


def _current_selected_source_hash(asset: Asset, asset_dir_path: Path, recipe: Recipe) -> str:
    """The hash of the source currently selected for ``recipe`` (§6.8,
    §22.2): what an override edited right now, or re-baselined against, is
    taken to be edited against. An override for an impossible type names no
    source to edit against, so callers only reach here once one exists."""
    selection = select_source(asset, recipe)
    assert selection.source is not None
    return sha256_bytes(read_source_bytes(asset_dir_path, selection.source.file))


def _initial_override_source_hash(
    asset: Asset, asset_dir_path: Path, recipe: Recipe, output_filename: str
) -> str:
    """The source hash a newly-seen override was edited against (§6.8): the
    generated derivative's own recorded source hash if one exists, else the
    hash of the source currently selected for this recipe (an override
    dropped in before the type was ever generated)."""
    generated_provenance = read_provenance(asset_dir_path / DERIVED_DIRNAME, output_filename)
    if generated_provenance is not None:
        return generated_provenance.source_hash
    return _current_selected_source_hash(asset, asset_dir_path, recipe)


def ensure_override_provenance(
    asset: Asset,
    asset_dir_path: Path,
    recipe: Recipe,
    output_filename: str,
    override_bytes: bytes,
) -> OverrideProvenance:
    """The override's provenance record for (``asset``, ``recipe``'s type),
    writing one the first time this override is seen (§6.8).

    Unchanged bytes since the last call: the existing record, untouched (no
    rewrite). Changed bytes (a re-edit, §22.2's re-edit rule): the edit is
    taken as made against the source as it stands right now, so
    ``source_hash`` re-baselines to :func:`_current_selected_source_hash`
    -- this is what clears a stale flag the moment a human edits the file,
    without any extra command. Never seen before: :func:`_initial_override_source_hash`.
    """
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    output_hash = sha256_bytes(override_bytes)
    existing = read_override_provenance(derived_dir, output_filename)

    if existing is not None:
        if existing.output_hash == output_hash:
            return existing
        updated = OverrideProvenance(
            source_hash=_current_selected_source_hash(asset, asset_dir_path, recipe),
            output_hash=output_hash,
        )
        write_override_provenance(derived_dir, output_filename, updated)
        return updated

    source_hash = _initial_override_source_hash(asset, asset_dir_path, recipe, output_filename)
    record = OverrideProvenance(source_hash=source_hash, output_hash=output_hash)
    write_override_provenance(derived_dir, output_filename, record)
    return record


def rebaseline_override_source(
    asset: Asset,
    asset_dir_path: Path,
    recipe: Recipe,
    output_filename: str,
    override_bytes: bytes,
) -> OverrideProvenance:
    """Re-baseline one override's edited-against hash to the source
    currently selected for ``recipe`` (§22.2's "keep": the override stays
    as-is against the new source, only the baseline moves). ``output_hash``
    is refreshed too, from ``override_bytes``, so the record always
    describes the bytes actually on disk."""
    record = OverrideProvenance(
        source_hash=_current_selected_source_hash(asset, asset_dir_path, recipe),
        output_hash=sha256_bytes(override_bytes),
    )
    write_override_provenance(asset_dir_path / DERIVED_DIRNAME, output_filename, record)
    return record


# --- override status: separate from the generated file's own (§6.8, §10, ADR 0004) --

_OVERRIDE_STATE_FILENAME = "_overrides_state.json"


def override_state_path(derived_dir: Path) -> Path:
    """Where every derivative type's override status for one asset lives --
    its own file, sibling to :data:`~vectorpress.catalog.status.STATE_FILENAME`,
    so an override's status can never collide with the generated file's own."""
    return derived_dir / _OVERRIDE_STATE_FILENAME


def read_all_override_statuses(derived_dir: Path) -> dict[DerivativeType, StatusRecord]:
    """Every derivative type this asset has a stored override status record
    for, or an empty mapping when no override has ever been reviewed."""
    path = override_state_path(derived_dir)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        DerivativeType(type_name): StatusRecord(
            status=Status(record["status"]),
            note=record["note"],
            output_hash=record["output_hash"],
        )
        for type_name, record in data.items()
    }


def read_override_status(derived_dir: Path, derivative_type: DerivativeType) -> StatusRecord | None:
    """One derivative type's stored override status record, or ``None`` if
    its override has never been reviewed."""
    return read_all_override_statuses(derived_dir).get(derivative_type)


def _override_state_payload(statuses: dict[DerivativeType, StatusRecord]) -> bytes:
    payload = {
        derivative_type.value: {
            "status": record.status.value,
            "note": record.note,
            "output_hash": record.output_hash,
        }
        for derivative_type, record in statuses.items()
    }
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def write_override_status(
    derived_dir: Path, derivative_type: DerivativeType, record: StatusRecord
) -> None:
    """Persist one derivative type's override status record: read-modify-write
    against the asset's own override state file. Idempotent, mirroring
    :func:`vectorpress.catalog.status.write_status`."""
    statuses = read_all_override_statuses(derived_dir)
    statuses[derivative_type] = record
    payload = _override_state_payload(statuses)
    path = override_state_path(derived_dir)
    if not (path.is_file() and path.read_bytes() == payload):
        atomic_write_bytes(path, payload)


def delete_override_status(derived_dir: Path, derivative_type: DerivativeType) -> None:
    """Remove one derivative type's stored override status record, leaving
    every other type's untouched -- ``vpress override discard``'s status
    cleanup, and re-used to drop orphaned state ahead of a fresh override
    (:func:`_clear_orphaned_override_state`). A no-op when no record exists
    for this type."""
    statuses = read_all_override_statuses(derived_dir)
    if derivative_type not in statuses:
        return
    del statuses[derivative_type]
    path = override_state_path(derived_dir)
    if not statuses:
        path.unlink(missing_ok=True)
        return
    payload = _override_state_payload(statuses)
    if not (path.is_file() and path.read_bytes() == payload):
        atomic_write_bytes(path, payload)


def asset_override_status(
    derived_dir: Path, derivative_type: DerivativeType, override_bytes: bytes
) -> StatusRecord:
    """The status to show for one override that exists on disk right now:
    the persisted record if it still matches ``override_bytes``, else
    ``needs_review`` (ADR 0004's "status follows the bytes") -- covers both a
    newly-seen override with no record at all and one hand-edited again
    since its last review, exactly the rule
    :func:`vectorpress.catalog.status.asset_derivative_status` applies to a
    generated derivative."""
    record = read_override_status(derived_dir, derivative_type)
    return effective_status(record, sha256_bytes(override_bytes))


def effective_derivative_status(
    asset_dir_path: Path, derivative_type: DerivativeType, effective: EffectiveDerivative
) -> StatusRecord:
    """The status to show for the *effective* derivative (§6.8): the
    override's own record when ``effective.is_override``, else the generated
    derivative's -- the one answer every status-showing consumer
    (``vpress asset``, ``vpress status``, ``pipeline.review``) goes through."""
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    if effective.is_override:
        return asset_override_status(derived_dir, derivative_type, effective.bytes)
    return asset_derivative_status(derived_dir, derivative_type, effective.bytes)


# --- stale overrides: the source hash an override was edited against, versus now (§22.2) --


def override_is_stale(edited_against_source_hash: str, current_source_hash: str | None) -> bool:
    """Whether an override is stale (§22.2, ADR 0004, CONTEXT.md "Stale"):
    its edited-against source hash no longer equals the currently selected
    source's hash. Covers a source's content changing and a pin selecting a
    different source alike -- both land here as the same mismatch, since
    neither this function nor its caller cares which one happened.
    ``current_source_hash`` is ``None`` when the currently selected source
    file is gone from disk -- always a mismatch, the override's baseline
    describes a source that no longer exists to compare it against.

    Pure: both hashes are already-computed values, so this is testable
    without touching a filesystem -- the check :func:`override_currency`
    performs once it has read them."""
    return edited_against_source_hash != current_source_hash


@dataclass(frozen=True)
class OverrideCurrency:
    """One override's on-disk currency against the source it was edited
    against (§22.2, ADR 0004): :attr:`DerivativeState.CURRENT` or
    :attr:`DerivativeState.STALE` with :data:`~vectorpress.catalog.provenance.SOURCE_CHANGED`
    -- the only reason an override can be stale (CONTEXT.md "Stale": unlike
    a generated derivative, an override has no recipe to change and is never
    rewritten on disk by the tool, so ``recipe changed`` and ``output
    changed on disk`` do not apply to it)."""

    state: DerivativeState
    reason: str | None


def override_currency(
    asset: Asset, asset_dir_path: Path, recipe: Recipe, output_filename: str
) -> OverrideCurrency | None:
    """Whether the override at (``asset``, ``recipe``'s type) is stale
    against the source currently selected for it, or ``None`` when there is
    nothing yet to compare: no override provenance has ever been recorded
    (:func:`ensure_override_provenance` has not run for this override), the
    override file itself is gone, or no source is currently selectable at
    all (an impossible type).

    A read-only check: it never re-baselines anything, even when it finds
    the bytes on disk have moved past the last recorded baseline. When they
    have -- the override was edited since :func:`ensure_override_provenance`
    last ran -- the edit is taken as made against the current source
    already (§22.2's re-edit rule), reported ``CURRENT`` without waiting for
    some other command to persist that baseline first: ``vpress asset``
    would otherwise keep showing a since-fixed stale flag until the human
    happens to run one of the handful of commands that write provenance.
    """
    provenance = read_override_provenance(asset_dir_path / DERIVED_DIRNAME, output_filename)
    if provenance is None:
        return None

    override_bytes = read_override_bytes(asset_dir_path, output_filename)
    if override_bytes is None:
        return None
    if sha256_bytes(override_bytes) != provenance.output_hash:
        return OverrideCurrency(DerivativeState.CURRENT, None)

    selection = select_source(asset, recipe)
    if selection.source is None:
        return None

    source_path = asset_dir_path / SOURCES_DIRNAME / selection.source.file
    current_source_hash = sha256_bytes(source_path.read_bytes()) if source_path.is_file() else None
    if override_is_stale(provenance.source_hash, current_source_hash):
        return OverrideCurrency(DerivativeState.STALE, SOURCE_CHANGED)
    return OverrideCurrency(DerivativeState.CURRENT, None)


# --- override discard: the one deletion the tool ever makes under overrides/ (§22.2) ------


def discard_override_file(asset_dir_path: Path, output_filename: str) -> None:
    """Remove one override file (``vpress override discard --yes``): the
    only deletion this module ever makes under ``overrides/``, made only on
    that explicit, confirmed request. A no-op if the file is already gone."""
    override_path(asset_dir_path, output_filename).unlink(missing_ok=True)


def delete_override_provenance(derived_dir: Path, output_filename: str) -> None:
    """Remove one override's provenance record, if it exists. A no-op
    otherwise."""
    override_provenance_path(derived_dir, output_filename).unlink(missing_ok=True)


def delete_override_findings(derived_dir: Path, output_filename: str) -> None:
    """Remove one override's own findings report, if it exists. A no-op
    otherwise. Only the catalog-default report -- the one ``vpress asset``
    shows -- a product-sized override report (a non-default ``at_size``) is
    not this discard's concern."""
    findings_path(derived_dir, output_filename, is_override=True).unlink(missing_ok=True)


def _clear_orphaned_override_state(
    asset_dir_path: Path, derivative_type: DerivativeType, output_filename: str
) -> None:
    """Remove provenance, status and findings left behind by a previous
    override at this path that no longer exists (§22.2's "a newly appearing
    override... must start fresh, not inherit it"): only
    :func:`create_override_from_generated` calls this, and only once it has
    confirmed it is writing a file that was not there a moment ago -- a
    hand-deleted override's leftover state never gets attributed to the one
    replacing it."""
    derived_dir = asset_dir_path / DERIVED_DIRNAME
    delete_override_provenance(derived_dir, output_filename)
    delete_override_status(derived_dir, derivative_type)
    delete_override_findings(derived_dir, output_filename)
