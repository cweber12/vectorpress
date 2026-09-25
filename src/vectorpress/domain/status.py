"""Per-derivative review status: the CONTEXT.md "Status" lifecycle (§10,
§22.1, ADR 0004).

No I/O here (ADR 0006): a status is a value plus two pure decisions -- what
a derivative's status becomes right after (re)generation, and what to show
for a derivative given the bytes currently on disk. Persisting a status
under an asset's ``derived/_state.json`` is :mod:`vectorpress.catalog.status`'s
job.

Distinct from :class:`~vectorpress.domain.derivative_state.DerivativeState`
(whether a derivative can exist, and does) and
:class:`~vectorpress.domain.finding.ValidationOutcome` (a mechanical
pass/needs-review roll-up from cut-file checks, CONTEXT.md "Findings"):
status is the human review decision, and only it is set here.
"""

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    """One derivative's review status (CONTEXT.md "Status", §10).

    ``GENERATED`` is a pass-through: a freshly (re)generated derivative with
    a changed output is recorded directly as ``NEEDS_REVIEW`` (§22.1), so
    ``GENERATED`` is never itself persisted -- it exists only to complete
    the lifecycle CONTEXT.md documents (``generated -> needs_review ->
    approved``).
    """

    GENERATED = "generated"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REGENERATE = "regenerate"


@dataclass(frozen=True)
class StatusRecord:
    """One derivative's stored status: the status itself, an optional
    human note, and the output hash the status was given against (ADR
    0004) -- "status follows the bytes": a record only describes the
    derivative as-is when its current output hash still matches this one
    (see :func:`effective_status`)."""

    status: Status
    note: str | None
    output_hash: str


def status_after_generation(previous: StatusRecord | None, output_hash: str) -> StatusRecord:
    """The status record a derivative gets right after (re)generation
    writes ``output_hash`` (§22.1, ADR 0004: "output changed = output hash
    changed -> needs_review; unchanged keeps status").

    No prior record at all (a new derivative): ``NEEDS_REVIEW``, no note.
    A prior record whose output hash differs (the (re)generation actually
    changed the bytes): ``NEEDS_REVIEW`` again, whatever the previous
    status was, note cleared -- a note about the old bytes does not
    describe the new ones. A prior record whose output hash is unchanged:
    returned as-is, status and note both preserved -- this is what makes
    ``generate --force`` non-destructive to an already-approved derivative.
    """
    if previous is None or previous.output_hash != output_hash:
        return StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=output_hash)
    return previous


def effective_status(record: StatusRecord | None, current_output_hash: str) -> StatusRecord:
    """The status to show for a derivative that exists on disk right now
    (ADR 0004's "status follows the bytes").

    No record at all (a derivative generated before status tracking
    existed): legacy, reported ``NEEDS_REVIEW``. A record whose output hash
    no longer matches ``current_output_hash`` (the file was hand-edited or
    replaced outside generation, CONTEXT.md's "output changed on disk"):
    also ``NEEDS_REVIEW``, note cleared -- an approval never carries over
    to bytes nobody approved. Otherwise: the record itself, unchanged.
    """
    if record is None or record.output_hash != current_output_hash:
        return StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=current_output_hash)
    return record
