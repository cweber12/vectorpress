"""Gathering one asset's publication-eligibility inputs from disk (§10,
§10.1, ADR 0004, ADR 0008).

Below :mod:`vectorpress.domain.eligibility`'s pure decision (CLAUDE.md's
layering guardrail): this module only resolves what each requested
derivative type's state and *effective* status currently are -- the same
disk-touching translation :func:`vectorpress.pipeline.review.
count_derivative_statuses` already does for the status tally, so an
override's own status counts here too (§6.8, CONTEXT.md "Effective
derivative"). Both ``cli`` and a future ``ui`` call this module and
:mod:`vectorpress.domain.eligibility` together, so "is this asset eligible"
is answered in exactly one place; a later PRD's product build calls the
same pair.
"""

from collections.abc import Iterable
from pathlib import Path

from vectorpress.catalog.overrides import effective_derivative, effective_derivative_status
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.eligibility import (
    EligibilityResult,
    IncludedDerivative,
    asset_eligibility,
    missing_optional_metadata_fields,
)
from vectorpress.pipeline.generate import asset_derivative_statuses


def possible_derivative_types(
    asset: Asset, asset_dir_path: Path, config: CatalogConfig | None = None
) -> list[DerivativeType]:
    """Every derivative type this asset can have at all -- every recipe-
    bearing type whose state is not ``impossible`` (§10.1) -- in the order
    :func:`~vectorpress.pipeline.generate.asset_derivative_statuses` returns
    them. Not itself an eligibility answer: this is only the default set
    ``vpress asset`` shows eligibility *for* when ``--types`` is not given,
    whether or not the asset is actually eligible to ship with them."""
    return [
        status.derivative_type
        for status in asset_derivative_statuses(asset, asset_dir_path, config)
        if status.state is not DerivativeState.IMPOSSIBLE
    ]


def included_derivatives(
    asset: Asset,
    asset_dir_path: Path,
    derivative_types: Iterable[DerivativeType],
    config: CatalogConfig | None = None,
) -> list[IncludedDerivative]:
    """One :class:`~vectorpress.domain.eligibility.IncludedDerivative` per
    requested ``derivative_types``: its current state, and its *effective*
    status (§6.8) when it has one -- a ``current`` or ``stale`` derivative,
    an override taking precedence over the generated file's own status the
    same way :func:`~vectorpress.catalog.overrides.effective_derivative_status`
    always does.

    A requested type with no recipe at all -- absent from
    :func:`~vectorpress.pipeline.generate.asset_derivative_statuses`'s
    output -- is reported ``impossible``: it can never have an output
    either way, the same dead end a genuinely impossible type reaches.
    """
    by_type = {
        status.derivative_type: status
        for status in asset_derivative_statuses(asset, asset_dir_path, config)
    }
    result: list[IncludedDerivative] = []
    for derivative_type in derivative_types:
        status = by_type.get(derivative_type)
        if status is None:
            result.append(IncludedDerivative(derivative_type, DerivativeState.IMPOSSIBLE, None))
            continue
        if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
            result.append(IncludedDerivative(derivative_type, status.state, None))
            continue

        assert status.output_filename is not None  # CURRENT/STALE always carry a filename
        effective = effective_derivative(asset_dir_path, status.output_filename)
        assert effective is not None  # CURRENT/STALE means the generated file exists on disk
        record = effective_derivative_status(asset_dir_path, derivative_type, effective)
        result.append(IncludedDerivative(derivative_type, status.state, record.status))
    return result


def asset_eligibility_for(
    asset: Asset,
    asset_dir_path: Path,
    derivative_types: Iterable[DerivativeType],
    config: CatalogConfig | None = None,
) -> EligibilityResult:
    """One asset's publication eligibility for ``derivative_types`` (§10,
    §10.1): gathers every input from disk and hands it to
    :func:`~vectorpress.domain.eligibility.asset_eligibility`, the one
    answer ``vpress asset`` and a later product build both call."""
    return asset_eligibility(
        asset.rights_status,
        asset.accuracy_status,
        missing_optional_metadata_fields(asset),
        included_derivatives(asset, asset_dir_path, derivative_types, config),
    )
