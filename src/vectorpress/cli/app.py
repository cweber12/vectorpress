"""Entry point for the ``vpress`` command.

The CLI is a thin layer: every command calls into ``vectorpress.build``,
``vectorpress.catalog`` and friends. No domain logic lives here.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import typer

from vectorpress import __version__
from vectorpress.catalog.assets import (
    AssetInventory,
    asset_dir,
    failed_asset_ids,
    load_assets,
    lookup_asset,
)
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.derivatives import DerivativeStateCounts
from vectorpress.catalog.errors import CatalogConfigError, CatalogNotFoundError
from vectorpress.catalog.findings import FindingsCurrencyState, findings_currency
from vectorpress.catalog.load import load_catalog, load_catalog_config
from vectorpress.catalog.locate import locate_catalog_root
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.overrides import (
    EffectiveDerivative,
    effective_derivative,
    effective_derivative_status,
    list_unrecognized_overrides,
)
from vectorpress.catalog.products import load_products, lookup_product
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes
from vectorpress.catalog.status import asset_derivative_status
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType, derivative_filename
from vectorpress.domain.finding import Finding, ValidationOutcome
from vectorpress.domain.numeric_format import format_number
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_reference_size_in
from vectorpress.domain.status import Status
from vectorpress.pipeline.generate import (
    DerivativeStatus,
    GenerationOutcome,
    asset_derivative_statuses,
    count_derivative_states,
    generate_asset,
)
from vectorpress.pipeline.review import (
    StatusCounts,
    TargetSelection,
    approve_derivative,
    count_derivative_statuses,
    regenerate_derivative,
    reject_derivative,
    select_review_targets,
)
from vectorpress.validate.cut_file import THRESHOLDS, validate_cut_file
from vectorpress.validate.validate_asset import AssetValidationOutcome, validate_asset_cut_file

app = typer.Typer(
    name="vpress",
    help="Turn master artwork into reusable vector products.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vpress {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    catalog: Path | None = typer.Option(
        None,
        "--catalog",
        help=(
            "Path to the catalog root (the directory holding catalog.toml). "
            "Defaults to walking up from the current directory."
        ),
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """vectorpress command line."""
    ctx.obj = {"catalog": catalog}


def _locate_root(ctx: typer.Context) -> Path:
    """Locate the catalog root, or exit with an actionable error."""
    explicit = ctx.obj.get("catalog") if ctx.obj else None
    try:
        return locate_catalog_root(Path.cwd(), explicit=explicit)
    except CatalogNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _locate_and_load_config(ctx: typer.Context) -> tuple[Path, CatalogConfig]:
    """Locate the catalog root and load its config, or exit with an actionable error."""
    root = _locate_root(ctx)
    try:
        config = load_catalog_config(root)
    except CatalogConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    return root, config


def _echo_problems(problems: list[MetadataProblem]) -> None:
    """Render metadata problems grouped by file. The catalog layer produces
    them; this only formats them."""
    if not problems:
        typer.echo("Metadata problems: none")
        return

    typer.echo(f"Metadata problems: {len(problems)}")
    by_file: dict[Path, list[MetadataProblem]] = {}
    for problem in problems:
        by_file.setdefault(problem.path, []).append(problem)

    for path in sorted(by_file, key=str):
        typer.echo(str(path))
        for problem in by_file[path]:
            if problem.field:
                typer.echo(f"  {problem.field}: {problem.message}")
            else:
                typer.echo(f"  {problem.message}")


def _lookup_asset_or_exit(inventory: AssetInventory, config: CatalogConfig, asset_id: str) -> Asset:
    """The asset named ``asset_id``, or exit 1. An ID whose ``asset.toml``
    failed to load prints that asset's problems; an ID naming no asset
    folder prints "Unknown asset"."""
    result = lookup_asset(inventory, config, asset_id)
    if result.asset is None:
        if result.problems:
            _echo_problems(result.problems)
        else:
            typer.echo(f"Unknown asset: {asset_id!r}", err=True)
        raise typer.Exit(code=1)
    return result.asset


def _lookup_product_or_exit(root: Path, config: CatalogConfig, slug: str) -> Product:
    """The product named ``slug``, or exit 1 -- the same two outcomes as
    :func:`_lookup_asset_or_exit`."""
    result = lookup_product(load_products(root, config), config, slug)
    if result.product is None:
        if result.problems:
            _echo_problems(result.problems)
        else:
            typer.echo(f"Unknown product: {slug!r}", err=True)
        raise typer.Exit(code=1)
    return result.product


@app.command()
def status(ctx: typer.Context) -> None:
    """Show the catalog's inventory and every metadata problem.

    Exits 1 when any metadata problem exists, so it works as a check in
    scripts.
    \f
    Aggregates problems from catalog config, assets, collections, products
    and brand. Missing, impossible and stale derivative counts are
    inventory, not problems, and never affect the exit code.
    """
    root = _locate_root(ctx)
    catalog = load_catalog(root)

    name = catalog.config.name if catalog.config is not None else root.name
    brand_name = catalog.brand.name if catalog.brand is not None else "none"
    typer.echo(f"{name}\n{root}")
    typer.echo(f"Brand: {brand_name}")
    typer.echo(f"Assets: {len(catalog.assets)}")
    typer.echo(f"Collections: {len(catalog.collections)}")
    typer.echo(f"Products: {len(catalog.products)}")
    if catalog.config is not None:
        counts = count_derivative_states(catalog.assets, root, catalog.config)
        status_counts = count_derivative_statuses(catalog.assets, root, catalog.config)
    else:
        counts = DerivativeStateCounts(missing=0, impossible=0, stale=0)
        status_counts = StatusCounts(needs_review=0, approved=0, rejected=0, regenerate=0)
    typer.echo(f"Missing derivatives: {counts.missing}")
    typer.echo(f"Impossible derivatives: {counts.impossible}")
    typer.echo(f"Stale derivatives: {counts.stale}")
    typer.echo(f"Needs review: {status_counts.needs_review}")
    typer.echo(f"Approved: {status_counts.approved}")
    typer.echo(f"Rejected: {status_counts.rejected}")
    typer.echo(f"Regenerate: {status_counts.regenerate}")
    _echo_problems(catalog.problems)

    if catalog.problems:
        raise typer.Exit(code=1)


@app.command()
def assets(ctx: typer.Context) -> None:
    """List every asset that loaded: ID, display name, rights status,
    accuracy status and number of sources.

    Assets that failed to load are reported by 'vpress status'.
    """
    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    for loaded in inventory.assets:
        typer.echo(
            f"{loaded.id}\t{loaded.display_name}\t"
            f"{loaded.rights_status.value}\t{loaded.accuracy_status.value}\t"
            f"{len(loaded.sources)}"
        )


def _findings_display(
    status: DerivativeStatus, root: Path, config: CatalogConfig, asset_id: str
) -> str:
    """The findings column on ``vpress asset``'s ``cut_svg`` line: ``pass`` /
    ``needs review`` for a current catalog-default findings report,
    ``findings stale`` when the report no longer matches the file, reference
    size or thresholds, else ``not validated``."""
    if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
        return "not validated"

    assert status.output_filename is not None  # CURRENT/STALE always carry a filename
    derived_dir = asset_dir(root, config, asset_id) / DERIVED_DIRNAME
    svg_bytes = read_derivative_bytes(derived_dir, status.output_filename)
    if svg_bytes is None:
        return "not validated"

    currency = findings_currency(
        derived_dir,
        status.output_filename,
        svg_bytes,
        config.reference_size_in,
        THRESHOLDS,
    )
    if currency.state is FindingsCurrencyState.NOT_VALIDATED:
        return "not validated"
    if currency.state is FindingsCurrencyState.STALE:
        return "findings stale"
    assert currency.result is not None  # set exactly when state is CURRENT
    return "pass" if currency.result is ValidationOutcome.PASS else "needs review"


def _status_display(
    status: DerivativeStatus, root: Path, config: CatalogConfig, asset_id: str
) -> str:
    """The status column on ``vpress asset``'s derivative line: ``needs
    review`` / ``approved`` / ``rejected`` / ``regenerate``, with its note
    in parentheses when one is present; empty for a derivative that does
    not exist yet (missing or impossible -- nothing to review)."""
    if status.state not in (DerivativeState.CURRENT, DerivativeState.STALE):
        return ""

    assert status.output_filename is not None  # CURRENT/STALE always carry a filename
    derived_dir = asset_dir(root, config, asset_id) / DERIVED_DIRNAME
    output_bytes = read_derivative_bytes(derived_dir, status.output_filename)
    if output_bytes is None:
        return ""

    record = asset_derivative_status(derived_dir, status.derivative_type, output_bytes)
    text = record.status.value.replace("_", " ")
    if record.note:
        text += f" ({record.note})"
    return text


def _override_status_display(
    effective: EffectiveDerivative,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
) -> str:
    """The status column on ``vpress asset``'s overridden derivative line:
    the override's own status (§6.8, CONTEXT.md "Effective derivative"),
    never the generated file's."""
    record = effective_derivative_status(asset_dir_path, derivative_type, effective)
    text = record.status.value.replace("_", " ")
    if record.note:
        text += f" ({record.note})"
    return text


def _override_findings_display(
    effective: EffectiveDerivative,
    derived_dir: Path,
    output_filename: str,
    config: CatalogConfig,
) -> str:
    """The findings column on an overridden ``cut_svg`` line: the override's
    own findings currency (§6.8), mirroring :func:`_findings_display` but
    for the override's own coexisting report."""
    currency = findings_currency(
        derived_dir,
        output_filename,
        effective.bytes,
        config.reference_size_in,
        THRESHOLDS,
        is_override=True,
    )
    if currency.state is FindingsCurrencyState.NOT_VALIDATED:
        return "not validated"
    if currency.state is FindingsCurrencyState.STALE:
        return "findings stale"
    assert currency.result is not None  # set exactly when state is CURRENT
    return "pass" if currency.result is ValidationOutcome.PASS else "needs review"


@app.command()
def asset(
    ctx: typer.Context,
    asset_id: str = typer.Argument(help="The asset's ID (its folder name under assets/)."),
) -> None:
    """Show one asset: metadata, sources with their roles, and each
    derivative type's state (current, stale, missing or impossible).

    The cut_svg line also shows its findings result: pass, needs review,
    findings stale, or not validated. A type overridden under overrides/
    shows override (generated: <state>) instead, with the override's own
    status and findings. A file under overrides/ that matches no derivative
    type is reported, never an error. An asset that failed to load shows
    its metadata problems instead.
    """
    root, config = _locate_and_load_config(ctx)
    found = _lookup_asset_or_exit(load_assets(root, config), config, asset_id)
    asset_dir_path = asset_dir(root, config, found.id)
    typer.echo(f"{found.id}\t{found.display_name}")
    typer.echo(f"Rights status: {found.rights_status.value}")
    typer.echo(f"Accuracy status: {found.accuracy_status.value}")
    typer.echo("Sources:")
    for source in found.sources:
        typer.echo(f"  {source.file}\t{source.role}")

    typer.echo("Derivatives:")
    known_filenames: list[str] = []
    for status in asset_derivative_statuses(found, asset_dir_path, config):
        candidate_filename = derivative_filename(found.display_name, status.derivative_type)
        known_filenames.append(candidate_filename)
        effective = effective_derivative(asset_dir_path, candidate_filename)

        if effective is not None and effective.is_override:
            line = (
                f"  {status.derivative_type.value}\toverride (generated: {status.state.value})"
                f"\t{candidate_filename}"
            )
            line += (
                f"\t{_override_status_display(effective, asset_dir_path, status.derivative_type)}"
            )
            if status.derivative_type is DerivativeType.CUT_SVG:
                derived_dir = asset_dir_path / DERIVED_DIRNAME
                line += f"\t{_override_findings_display(effective, derived_dir, candidate_filename, config)}"
            typer.echo(line)
            continue

        if status.state is DerivativeState.IMPOSSIBLE:
            line = f"  {status.derivative_type.value}\t{status.state.value}\t{status.reason}"
        elif status.state is DerivativeState.CURRENT:
            line = (
                f"  {status.derivative_type.value}\t{status.state.value}\t{status.output_filename}"
            )
        elif status.state is DerivativeState.STALE:
            line = f"  {status.derivative_type.value}\tstale ({status.reason})\t{status.output_filename}"
        else:
            assert status.source is not None  # MISSING always carries a selected source
            line = (
                f"  {status.derivative_type.value}\t{status.state.value}\t"
                f"{status.source.file} ({status.source.role})"
            )
        status_text = _status_display(status, root, config, found.id)
        if status_text:
            line += f"\t{status_text}"
        # Only cut_svg is validated, so only its line carries a findings result.
        if status.derivative_type is DerivativeType.CUT_SVG:
            line += f"\t{_findings_display(status, root, config, found.id)}"
        typer.echo(line)

    unrecognized = list_unrecognized_overrides(asset_dir_path, known_filenames)
    if unrecognized:
        typer.echo("Unrecognized overrides:")
        for name in unrecognized:
            typer.echo(f"  {name}\tignored")


def _select_targets(
    inventory: AssetInventory, config: CatalogConfig, asset_id: str | None
) -> list[Asset]:
    """The assets a batch command acts on: the one named ``asset_id``, or
    every loaded asset when it is ``None`` -- naming each asset that failed
    to load as skipped, so one broken asset never stops the rest (§35)."""
    if asset_id is not None:
        return [_lookup_asset_or_exit(inventory, config, asset_id)]
    for failed_id in failed_asset_ids(inventory, config):
        typer.echo(f"{failed_id}\tskipped: failed to load")
    return inventory.assets


@app.command()
def generate(
    ctx: typer.Context,
    asset_id: str | None = typer.Argument(
        None, help="The asset's ID (its folder name under assets/)."
    ),
    all_assets: bool = typer.Option(
        False,
        "--all",
        help="Generate every recipe-bearing derivative type for every loaded asset.",
    ),
    stale: bool = typer.Option(
        False,
        "--stale",
        help="Regenerate only stale derivatives, across every loaded asset.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even current derivatives (combine with an asset ID or --all).",
    ),
) -> None:
    """Generate derivatives for one asset, every asset (--all), or only
    stale derivatives (--stale).

    Give exactly one of ASSET_ID, --all or --stale. Prints one line per
    derivative: generated, current, missing (--stale leaves never-generated
    derivatives alone), impossible, no generator, or failed. A current
    derivative is never rewritten unless --force asks, and even then
    unchanged bytes are left alone. Every asset is attempted; exits 1 if any
    derivative failed, with the cause of each failure on stderr.
    """
    selectors = [asset_id is not None, all_assets, stale]
    if sum(selectors) != 1:
        raise typer.BadParameter(
            "Provide exactly one of: an asset ID, --all, --stale.",
            param_hint="asset_id / --all / --stale",
        )
    if force and stale:
        raise typer.BadParameter(
            "--force combines with an asset ID or --all, not --stale.",
            param_hint="--force",
        )

    root, config = _locate_and_load_config(ctx)
    targets = _select_targets(load_assets(root, config), config, asset_id)

    failure_count = 0
    for target in targets:
        for result in generate_asset(
            target,
            asset_dir(root, config, target.id),
            stale_only=stale,
            force=force,
            config=config,
        ):
            typer.echo(
                f"{result.asset_id}\t{result.derivative_type.value}\t"
                f"{result.outcome.value}\t{result.detail}"
            )
            if result.outcome is GenerationOutcome.FAILED:
                failure_count += 1
                typer.echo(
                    f"generate: {result.asset_id} {result.derivative_type.value} failed "
                    f"(source: {result.source_file}): {result.detail}",
                    err=True,
                )

    if failure_count:
        typer.echo(f"generate: {failure_count} derivative(s) failed", err=True)
        raise typer.Exit(code=1)


class _ReviewResult(Protocol):
    """What :func:`approve_derivative`, :func:`reject_derivative` and
    :func:`regenerate_derivative` have in common: ``error`` is ``None`` on
    success, the reason nothing was written otherwise. The three commands
    below act through this shape so their CLI plumbing does not care which
    one it is calling. A read-only property, not a plain field: each
    concrete result is a frozen dataclass, and a plain Protocol field would
    demand a settable ``error`` too."""

    @property
    def error(self) -> str | None: ...


_ReviewAction = Callable[[Asset, Path, DerivativeType, str | None, CatalogConfig], _ReviewResult]


def _parse_derivative_type_or_exit(value: str) -> DerivativeType:
    try:
        return DerivativeType(value)
    except ValueError:
        typer.echo(f"Unknown derivative type: {value!r}", err=True)
        raise typer.Exit(code=1) from None


def _parse_status_or_exit(value: str) -> Status:
    try:
        return Status(value)
    except ValueError:
        typer.echo(f"Unknown status: {value!r}", err=True)
        raise typer.Exit(code=1) from None


def _echo_review_line(
    asset_id: str, derivative_type: str, status_text: str, note: str | None
) -> None:
    note_suffix = f"\t{note}" if note else ""
    typer.echo(f"{asset_id}\t{derivative_type}\t{status_text}{note_suffix}")


def _validate_review_targeting(
    asset_id: str | None,
    derivative_type: str | None,
    all_types: bool,
    all_assets: bool,
    type_filter: str | None,
    status_filter: str | None,
) -> None:
    """The one targeting shape ``approve``, ``reject`` and ``regenerate``
    share (§10, §24): ``ASSET_ID DERIVATIVE_TYPE``, ``ASSET_ID --all-types``,
    or ``--all`` (optionally narrowed by ``--type`` and/or ``--status``,
    which only mean anything alongside ``--all``). Anything else -- no
    targeting at all included -- is a usage error, exit 2, before anything
    is loaded or written.
    """
    has_asset = asset_id is not None
    has_type_arg = derivative_type is not None
    modes = [
        has_asset and has_type_arg and not all_types and not all_assets,
        has_asset and not has_type_arg and all_types and not all_assets,
        not has_asset and not has_type_arg and not all_types and all_assets,
    ]
    if sum(modes) != 1:
        raise typer.BadParameter(
            "Give exactly one of: ASSET_ID DERIVATIVE_TYPE, ASSET_ID --all-types, or --all.",
            param_hint="asset_id / derivative_type / --all-types / --all",
        )
    if type_filter is not None and not all_assets:
        raise typer.BadParameter("--type only narrows --all.", param_hint="--type")
    if status_filter is not None and not all_assets:
        raise typer.BadParameter("--status only narrows --all.", param_hint="--status")


def _run_bulk_review(
    command: str,
    status_text: str,
    act: _ReviewAction,
    selection: TargetSelection,
    root: Path,
    config: CatalogConfig,
    note: str | None,
) -> None:
    """Run ``act`` over every target ``select_review_targets`` picked,
    printing a line per derivative it skips (named, never failed on) or
    changes, then a summary (§10, §24's "many at once")."""
    for skip in selection.skipped:
        typer.echo(f"{skip.asset_id}\t{skip.derivative_type.value}\tskipped: {skip.reason}")

    changed = 0
    for target in selection.targets:
        result = act(
            target.asset,
            asset_dir(root, config, target.asset.id),
            target.derivative_type,
            note,
            config,
        )
        if result.error is None:
            _echo_review_line(target.asset.id, target.derivative_type.value, status_text, note)
            changed += 1
        else:
            typer.echo(
                f"{target.asset.id}\t{target.derivative_type.value}\tskipped: {result.error}"
            )

    typer.echo(f"{command}: {changed} changed, {len(selection.skipped)} skipped")


def _run_review(
    ctx: typer.Context,
    command: str,
    status_text: str,
    act: _ReviewAction,
    asset_id: str | None,
    derivative_type: str | None,
    all_types: bool,
    all_assets: bool,
    type_filter: str | None,
    status_filter: str | None,
    note: str | None,
) -> None:
    """Shared body of ``approve``, ``reject`` and ``regenerate``: validate
    targeting, then either act on the one named (asset, type) directly --
    an unknown asset/type or a missing/impossible derivative errors, exit 1
    -- or resolve the bulk targets (``--all-types``/``--all``) and run
    ``act`` over each, which never fails the command (§10, §24)."""
    _validate_review_targeting(
        asset_id, derivative_type, all_types, all_assets, type_filter, status_filter
    )
    root, config = _locate_and_load_config(ctx)

    if derivative_type is not None:
        assert asset_id is not None  # single-target mode requires both, enforced above
        found = _lookup_asset_or_exit(load_assets(root, config), config, asset_id)
        parsed_type = _parse_derivative_type_or_exit(derivative_type)
        result = act(found, asset_dir(root, config, found.id), parsed_type, note, config)
        if result.error is not None:
            typer.echo(f"{command}: {asset_id} {derivative_type} failed: {result.error}", err=True)
            raise typer.Exit(code=1)
        _echo_review_line(asset_id, derivative_type, status_text, note)
        return

    inventory = load_assets(root, config)
    scoped_assets = _select_targets(inventory, config, asset_id)
    parsed_type_filter = (
        _parse_derivative_type_or_exit(type_filter) if type_filter is not None else None
    )
    parsed_status_filter = (
        _parse_status_or_exit(status_filter) if status_filter is not None else None
    )

    selection = select_review_targets(
        scoped_assets, root, config, derivative_type=parsed_type_filter, status=parsed_status_filter
    )
    _run_bulk_review(command, status_text, act, selection, root, config, note)


@app.command()
def approve(
    ctx: typer.Context,
    asset_id: str | None = typer.Argument(
        None, help="The asset's ID (its folder name under assets/)."
    ),
    derivative_type: str | None = typer.Argument(
        None, help="The derivative type to approve, e.g. cut_svg."
    ),
    all_types: bool = typer.Option(
        False, "--all-types", help="Approve every existing derivative of ASSET_ID."
    ),
    all_assets: bool = typer.Option(
        False, "--all", help="Approve every existing derivative across the catalog."
    ),
    type_filter: str | None = typer.Option(
        None, "--type", help="With --all, narrow to one derivative type."
    ),
    status_filter: str | None = typer.Option(
        None, "--status", help="With --all, narrow to derivatives currently at this status."
    ),
    note: str | None = typer.Option(
        None, "--note", help="An optional note to record with the approval."
    ),
) -> None:
    """Approve a derivative, every derivative of one asset, or every
    matching derivative across the catalog, recording each approved with an
    optional note.

    Give exactly one of: ASSET_ID DERIVATIVE_TYPE, ASSET_ID --all-types, or
    --all (optionally narrowed by --type and/or --status). Any other
    combination is a usage error, exit 2.
    \f
    ASSET_ID DERIVATIVE_TYPE errors with exit 1 and writes nothing for an
    unknown asset, an unknown derivative type, or a derivative that is
    missing or impossible. --all-types and --all never fail that way: a
    missing/impossible derivative, a --type naming a type with no recipe
    yet, or an asset that failed to load, is skipped and named instead, and
    the run still exits 0.
    """
    _run_review(
        ctx,
        "approve",
        Status.APPROVED.value,
        approve_derivative,
        asset_id,
        derivative_type,
        all_types,
        all_assets,
        type_filter,
        status_filter,
        note,
    )


@app.command()
def reject(
    ctx: typer.Context,
    asset_id: str | None = typer.Argument(
        None, help="The asset's ID (its folder name under assets/)."
    ),
    derivative_type: str | None = typer.Argument(
        None, help="The derivative type to reject, e.g. cut_svg."
    ),
    all_types: bool = typer.Option(
        False, "--all-types", help="Reject every existing derivative of ASSET_ID."
    ),
    all_assets: bool = typer.Option(
        False, "--all", help="Reject every existing derivative across the catalog."
    ),
    type_filter: str | None = typer.Option(
        None, "--type", help="With --all, narrow to one derivative type."
    ),
    status_filter: str | None = typer.Option(
        None, "--status", help="With --all, narrow to derivatives currently at this status."
    ),
    note: str | None = typer.Option(
        None, "--note", help="An optional note to record with the rejection."
    ),
) -> None:
    """Reject a derivative, every derivative of one asset, or every
    matching derivative across the catalog, recording each rejected with an
    optional note.

    Give exactly one of: ASSET_ID DERIVATIVE_TYPE, ASSET_ID --all-types, or
    --all (optionally narrowed by --type and/or --status). Any other
    combination is a usage error, exit 2.
    \f
    Same shape and error handling as ``approve``: ASSET_ID DERIVATIVE_TYPE
    errors with exit 1 and writes nothing for an unknown asset, an unknown
    derivative type, or a derivative that is missing or impossible;
    --all-types and --all skip and name those instead of failing.
    """
    _run_review(
        ctx,
        "reject",
        Status.REJECTED.value,
        reject_derivative,
        asset_id,
        derivative_type,
        all_types,
        all_assets,
        type_filter,
        status_filter,
        note,
    )


@app.command()
def regenerate(
    ctx: typer.Context,
    asset_id: str | None = typer.Argument(
        None, help="The asset's ID (its folder name under assets/)."
    ),
    derivative_type: str | None = typer.Argument(
        None, help="The derivative type to mark for regeneration, e.g. cut_svg."
    ),
    all_types: bool = typer.Option(
        False, "--all-types", help="Mark every existing derivative of ASSET_ID for regeneration."
    ),
    all_assets: bool = typer.Option(
        False, "--all", help="Mark every existing derivative across the catalog for regeneration."
    ),
    type_filter: str | None = typer.Option(
        None, "--type", help="With --all, narrow to one derivative type."
    ),
    status_filter: str | None = typer.Option(
        None, "--status", help="With --all, narrow to derivatives currently at this status."
    ),
    note: str | None = typer.Option(
        None, "--note", help="An optional note to record with the mark."
    ),
) -> None:
    """Mark a derivative, every derivative of one asset, or every matching
    derivative across the catalog for regeneration, with an optional note.

    Give exactly one of: ASSET_ID DERIVATIVE_TYPE, ASSET_ID --all-types, or
    --all (optionally narrowed by --type and/or --status). Any other
    combination is a usage error, exit 2.
    \f
    Marking does not regenerate anything itself: the next ``vpress
    generate`` for a marked asset regenerates every derivative marked
    regenerate even when it is current, as if --force applied to that
    derivative alone, and each ends up needs_review afterward whether or
    not its output changed. Same error handling as ``approve``: ASSET_ID
    DERIVATIVE_TYPE errors with exit 1 and writes nothing for an unknown
    asset, an unknown derivative type, or a derivative that is missing or
    impossible; --all-types and --all skip and name those instead of
    failing.
    """
    _run_review(
        ctx,
        "regenerate",
        Status.REGENERATE.value,
        regenerate_derivative,
        asset_id,
        derivative_type,
        all_types,
        all_assets,
        type_filter,
        status_filter,
        note,
    )


def _optional_catalog_config(ctx: typer.Context) -> CatalogConfig | None:
    """The config of the catalog containing the current directory, or
    ``None`` when there is none or it fails to load. Only ``validate
    --file`` uses this: it works on any SVG, inside a catalog or not."""
    explicit = ctx.obj.get("catalog") if ctx.obj else None
    try:
        root = locate_catalog_root(Path.cwd(), explicit=explicit)
    except CatalogNotFoundError:
        return None
    try:
        return load_catalog_config(root)
    except CatalogConfigError:
        return None


def _format_location(finding: Finding) -> str:
    """A finding's bbox as CLI text, or a marker when it has none (e.g. an
    empty group, located by element reference alone)."""
    location = finding.location
    if location is None:
        return "(no bbox)"
    return f"({location.min_x},{location.min_y})-({location.max_x},{location.max_y})"


def _echo_finding(finding: Finding) -> None:
    typer.echo(f"  {finding.kind.value}\t{_format_location(finding)}\t{finding.message}")


def _validate_file(file: Path, reference_size_in: float, catalog_reference_size_in: float) -> None:
    """Validate any SVG on disk with the same ``validate_cut_file`` asset
    validation uses, print the report, and write nothing."""
    if not file.is_file():
        typer.echo(f"validate: {file} failed: no such file", err=True)
        raise typer.Exit(code=1)

    svg_bytes = file.read_bytes()
    try:
        validation = validate_cut_file(
            svg_bytes, reference_size_in, catalog_reference_size_in=catalog_reference_size_in
        )
    except Exception as exc:  # any parse failure is a reported validation failure (§35)
        typer.echo(f"validate: {file} failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    result_text = "pass" if validation.outcome is ValidationOutcome.PASS else "needs review"
    typer.echo(f"{file}\tcut_svg\t{result_text}")
    for finding in validation.findings:
        _echo_finding(finding)


@app.command()
def validate(
    ctx: typer.Context,
    asset_id: str | None = typer.Argument(
        None, help="The asset's ID (its folder name under assets/)."
    ),
    all_assets: bool = typer.Option(
        False,
        "--all",
        help="Validate every loaded asset's cut file.",
    ),
    file: Path | None = typer.Option(
        None,
        "--file",
        help=(
            "Validate this SVG file on disk instead of a catalog asset. "
            "Prints the same report and result; writes nothing."
        ),
    ),
    reference_size: float | None = typer.Option(
        None,
        "--reference-size",
        help=(
            "Physical reference size in inches, for --file only. "
            "Defaults to the catalog default when run inside a catalog; "
            "required otherwise."
        ),
    ),
    product: str | None = typer.Option(
        None,
        "--product",
        help=(
            "Validate at this product's resolved reference size (its own "
            "override if it has one, else the catalog default) instead of "
            "the catalog default alone. Only resolves the size -- it does "
            "not check that an asset belongs to the product. Not supported "
            "with --file."
        ),
    ),
) -> None:
    """Validate cut files and print pass / needs review with each finding's
    kind and location.

    Give exactly one of ASSET_ID, --all or --file. Validating an asset
    writes a findings report beside its cut file; an asset whose cut file
    is missing or impossible is reported and skipped. --file checks any SVG
    on disk and writes nothing. Exits 0 for pass or needs review, 1 if any
    file could not be read or parsed.
    \f
    Validation runs in the ``validate`` layer; this command only picks the
    assets and reference size and formats the result. A ``--product``
    report is saved at its own size-keyed path and never replaces the
    catalog-default report, which is the one ``vpress asset`` shows.
    ``vpress generate`` never validates: a findings report exists only
    because this command ran.
    """
    selectors = [asset_id is not None, all_assets, file is not None]
    if sum(selectors) != 1:
        raise typer.BadParameter(
            "Provide exactly one of: an asset ID, --all, --file.",
            param_hint="asset_id / --all / --file",
        )

    if file is not None:
        if product is not None:
            raise typer.BadParameter(
                "--product is not supported with --file.", param_hint="--product"
            )
        file_config = _optional_catalog_config(ctx)
        if file_config is not None:
            # excessive_complexity is judged at the catalog size (ADR 0010).
            catalog_reference_size_in = file_config.reference_size_in
        elif reference_size is not None:
            # Outside a catalog, the given size is the only one there is.
            catalog_reference_size_in = reference_size
        else:
            raise typer.BadParameter(
                "No catalog found here; --reference-size is required for --file outside a catalog.",
                param_hint="--reference-size",
            )
        file_reference_size_in = (
            reference_size if reference_size is not None else catalog_reference_size_in
        )
        _validate_file(file, file_reference_size_in, catalog_reference_size_in)
        return

    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    # Resolve the product first: an unknown one stops the run before any
    # asset is validated.
    resolved_product = (
        _lookup_product_or_exit(root, config, product) if product is not None else None
    )
    reference_size_in = resolve_reference_size_in(config, resolved_product)

    targets = _select_targets(inventory, config, asset_id)

    if reference_size_in != config.reference_size_in:
        # Said once per run, not per asset: excessive_complexity alone is
        # judged at the catalog size (ADR 0010).
        typer.echo(
            f"excessive_complexity is measured at the "
            f"{format_number(config.reference_size_in)}in catalog size"
        )

    failure_count = 0
    for target in targets:
        outcome = validate_asset_cut_file(root, config, target, reference_size_in)

        if outcome.outcome is AssetValidationOutcome.IMPOSSIBLE:
            typer.echo(f"{target.id}\tcut_svg\timpossible\t{outcome.reason}")
            continue
        if outcome.outcome is AssetValidationOutcome.MISSING:
            typer.echo(f"{target.id}\tcut_svg\tmissing")
            continue
        if outcome.outcome is AssetValidationOutcome.FAILED:
            failure_count += 1
            typer.echo(
                f"validate: {target.id} cut_svg failed ({outcome.filename}): {outcome.reason}",
                err=True,
            )
            continue

        assert outcome.validation is not None  # set exactly when outcome is VALIDATED
        result_text = (
            "pass" if outcome.validation.outcome is ValidationOutcome.PASS else "needs review"
        )
        size_note = (
            f"\t(at {format_number(reference_size_in)}in, product {resolved_product.slug})"
            if resolved_product is not None
            else ""
        )
        override_note = "\t(override)" if outcome.is_override else ""
        typer.echo(
            f"{target.id}\tcut_svg\t{outcome.filename}\t{result_text}{size_note}{override_note}"
        )
        for finding in outcome.validation.findings:
            _echo_finding(finding)

    if failure_count:
        typer.echo(f"validate: {failure_count} asset(s) failed", err=True)
        raise typer.Exit(code=1)


@app.command()
def collections(ctx: typer.Context) -> None:
    """List every collection that loaded: slug, name, and membership form.

    Membership is shown as declared; which assets match is not resolved
    yet. Collections that failed to load are reported by 'vpress status'.
    """
    root, config = _locate_and_load_config(ctx)
    inventory = load_collections(root, config)

    for loaded in inventory.collections:
        typer.echo(f"{loaded.slug}\t{loaded.name}\t{loaded.membership.form.value}")


@app.command()
def products(ctx: typer.Context) -> None:
    """List every product that loaded: slug, listing title, tier, and
    collection.

    The title falls back to the slug for a product with no listing yet.
    Products that failed to load are reported by 'vpress status'.
    """
    root, config = _locate_and_load_config(ctx)
    inventory = load_products(root, config)

    for loaded in inventory.products:
        title = loaded.listing.title if loaded.listing is not None else loaded.slug
        if loaded.collection_slug is not None:
            collection_ref = loaded.collection_slug
        else:
            assert loaded.membership is not None  # enforced by Product's own validation
            collection_ref = f"inline ({loaded.membership.form.value})"
        typer.echo(f"{loaded.slug}\t{title}\t{loaded.tier.value}\t{collection_ref}")
