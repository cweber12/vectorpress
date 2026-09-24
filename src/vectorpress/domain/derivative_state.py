"""Derivative state: per (asset, derivative type), whether a derivative can
exist at all and whether it does yet (ADR 0003, CONTEXT.md "Derivative
state").

Distinct from :class:`~vectorpress.domain.membership` and PRD 4's approval
**status** (``generated``, ``needs_review``, ``approved``, ``rejected``,
``regenerate``): status is about review of a derivative that exists; state
is about whether one can, and does, exist at all. No I/O here (ADR 0006).
"""

from enum import StrEnum


class DerivativeState(StrEnum):
    """Whether a derivative can be produced, and whether it has been.

    ``IMPOSSIBLE``: no source declared on the asset has a role its recipe
    accepts. ``MISSING``: a source is selectable but no derivative file
    exists yet. ``CURRENT`` (issue #23): the derivative exists on disk, its
    provenance's source hash matches the currently selected source, and its
    recipe identity matches the current recipe (ADR 0004) -- generation is
    idempotent, so a second ``vpress generate`` finds it and skips it. A
    later PRD slice adds ``STALE`` (CONTEXT.md).
    """

    IMPOSSIBLE = "impossible"
    MISSING = "missing"
    CURRENT = "current"
