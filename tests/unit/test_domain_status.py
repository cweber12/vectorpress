"""domain.status: the pure review-status transition rules (§10, §22.1, ADR
0004).

No I/O anywhere here: every case is built from bare hash strings and
:class:`~vectorpress.domain.status.StatusRecord` values, never a real file.
"""

import pytest

from vectorpress.domain.status import (
    Status,
    StatusRecord,
    effective_status,
    status_after_generation,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


# --- status_after_generation (§22.1) -----------------------------------------------


def test_a_new_derivative_gets_needs_review() -> None:
    record = status_after_generation(None, HASH_A)

    assert record == StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=HASH_A)


@pytest.mark.parametrize("previous_status", list(Status))
def test_a_changed_output_hash_returns_to_needs_review_from_every_prior_status(
    previous_status: Status,
) -> None:
    """ADR 0004: "output changed = output hash changed -> needs_review" --
    from any prior status, including one already needs_review, and clears
    whatever note described the old bytes."""
    previous = StatusRecord(status=previous_status, note="an old note", output_hash=HASH_A)

    record = status_after_generation(previous, HASH_B)

    assert record == StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=HASH_B)


@pytest.mark.parametrize("previous_status", list(Status))
def test_an_unchanged_output_hash_preserves_status_and_note(previous_status: Status) -> None:
    """ADR 0004: "unchanged keeps status" -- the whole prior record, note
    included, is returned untouched."""
    previous = StatusRecord(status=previous_status, note="clean", output_hash=HASH_A)

    record = status_after_generation(previous, HASH_A)

    assert record == previous


# --- effective_status (ADR 0004's "status follows the bytes") ----------------------


def test_no_record_at_all_is_legacy_needs_review() -> None:
    record = effective_status(None, HASH_A)

    assert record == StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=HASH_A)


def test_a_record_matching_the_current_hash_is_returned_as_is() -> None:
    stored = StatusRecord(status=Status.APPROVED, note="clean", output_hash=HASH_A)

    record = effective_status(stored, HASH_A)

    assert record == stored


def test_a_record_whose_hash_no_longer_matches_the_disk_bytes_reports_needs_review() -> None:
    """An approval never carries over to bytes nobody approved -- the note
    describing the old, approved bytes is cleared too."""
    stored = StatusRecord(status=Status.APPROVED, note="clean", output_hash=HASH_A)

    record = effective_status(stored, HASH_B)

    assert record == StatusRecord(status=Status.NEEDS_REVIEW, note=None, output_hash=HASH_B)
