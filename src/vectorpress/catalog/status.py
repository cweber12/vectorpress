"""Tool-owned per-derivative status, persisted per asset (ADR 0004, ADR
0005, CONTEXT.md "Status", §10, §22.1).

Unlike :mod:`vectorpress.catalog.provenance` and :mod:`vectorpress.catalog.findings`
(one JSON file per derivative file), every derivative type's status for one
asset lives together in a single ``derived/_state.json``, keyed by
derivative type -- the "asset's tool-owned ``derived/_state.json``" ADR
0005's per-asset layout names. Only ``catalog`` touches catalog files (ADR
0006): this module owns every byte crossing the boundary between disk and a
status record.
"""

import json
from pathlib import Path

from vectorpress.catalog.atomic_write import atomic_write_bytes
from vectorpress.catalog.provenance import sha256_bytes
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.status import Status, StatusRecord, effective_status

#: One asset's whole status record lives in this file, sibling to its
#: generated derivatives and provenance/findings records under ``derived/``
#: (ADR 0005's per-asset layout).
STATE_FILENAME = "_state.json"


def state_path(derived_dir: Path) -> Path:
    """Where one asset's status record lives."""
    return derived_dir / STATE_FILENAME


def read_all_statuses(derived_dir: Path) -> dict[DerivativeType, StatusRecord]:
    """Every derivative type this asset has a stored status record for, or
    an empty mapping when ``derived/_state.json`` does not exist yet (no
    derivative of this asset has ever been (re)generated since status
    tracking began)."""
    path = state_path(derived_dir)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    statuses: dict[DerivativeType, StatusRecord] = {}
    for type_name, record in data.items():
        statuses[DerivativeType(type_name)] = StatusRecord(
            status=Status(record["status"]),
            note=record["note"],
            output_hash=record["output_hash"],
        )
    return statuses


def read_status(derived_dir: Path, derivative_type: DerivativeType) -> StatusRecord | None:
    """One derivative type's stored status record, or ``None`` if it has
    never been (re)generated since status tracking began -- a legacy
    derivative, treated as ``needs_review`` by
    :func:`~vectorpress.domain.status.effective_status`."""
    return read_all_statuses(derived_dir).get(derivative_type)


def _state_payload(statuses: dict[DerivativeType, StatusRecord]) -> bytes:
    """``statuses`` serialized deterministically: sorted object keys, so
    byte equality (the idempotence check below, and cross-OS snapshot
    tests) does not depend on incidental dict insertion order -- the same
    rule :func:`vectorpress.catalog.provenance.write_derivative`'s
    provenance payload follows."""
    payload = {
        derivative_type.value: {
            "status": record.status.value,
            "note": record.note,
            "output_hash": record.output_hash,
        }
        for derivative_type, record in statuses.items()
    }
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def write_status(derived_dir: Path, derivative_type: DerivativeType, record: StatusRecord) -> None:
    """Persist one derivative type's status record: read-modify-write
    against the asset's single ``_state.json`` (§35, §36).

    Idempotent like :func:`vectorpress.catalog.provenance.write_derivative`:
    when the payload about to be written already matches what is on disk
    byte-for-byte, the file is left untouched -- an unchanged status after
    regeneration, or a repeated identical approve, rewrites nothing.
    """
    statuses = read_all_statuses(derived_dir)
    statuses[derivative_type] = record
    payload = _state_payload(statuses)
    path = state_path(derived_dir)
    if not (path.is_file() and path.read_bytes() == payload):
        atomic_write_bytes(path, payload)


def asset_derivative_status(
    derived_dir: Path, derivative_type: DerivativeType, output_bytes: bytes
) -> StatusRecord:
    """The status to show for one derivative that exists on disk right now:
    the persisted record if it still matches ``output_bytes``, else
    ``needs_review`` (ADR 0004's "status follows the bytes" -- covers both a
    legacy derivative with no record at all and one hand-edited since its
    last approval)."""
    record = read_status(derived_dir, derivative_type)
    return effective_status(record, sha256_bytes(output_bytes))
