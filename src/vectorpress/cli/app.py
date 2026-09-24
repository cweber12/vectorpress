"""Entry point for the ``vpress`` command.

The CLI is a thin layer: every command calls into ``vectorpress.build``,
``vectorpress.catalog`` and friends. No domain logic lives here.
"""

from pathlib import Path

import typer

from vectorpress import __version__
from vectorpress.catalog.assets import asset_dir, failed_asset_ids, load_assets, lookup_asset
from vectorpress.catalog.collections import load_collections
from vectorpress.catalog.derivatives import DerivativeStateCounts
from vectorpress.catalog.errors import CatalogConfigError, CatalogNotFoundError
from vectorpress.catalog.findings import FindingsCurrencyState, findings_currency
from vectorpress.catalog.load import load_catalog, load_catalog_config
from vectorpress.catalog.locate import locate_catalog_root
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.catalog.products import load_products
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.finding import ValidationOutcome
from vectorpress.pipeline.generate import (
    DerivativeStatus,
    GenerationOutcome,
    asset_derivative_statuses,
    count_derivative_states,
    generate_asset,
)
from vectorpress.validate.cut_file import THRESHOLDS
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
    """Render the problems section of ``vpress status``, grouped by file.

    The catalog layer produces ``problems``; this only formats it
    (CLAUDE.md's "cli and ui are thin").
    """
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


@app.command()
def status(ctx: typer.Context) -> None:
    """Report the catalog's inventory and every metadata problem found.

    The single place that answers "is my catalog metadata sound?" (issue
    #6): aggregates problems from catalog config, assets, collections,
    products and brand. ``Missing derivatives``, ``Impossible derivatives``
    (issue #22, ADR 0003, §34) and ``Stale derivatives`` (issue #26, ADR
    0004) are inventory counts, not problems, and never affect the exit
    code. Exit code is non-zero only when a metadata problem exists, so this
    works as a check in scripts.
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
    else:
        counts = DerivativeStateCounts(missing=0, impossible=0, stale=0)
    typer.echo(f"Missing derivatives: {counts.missing}")
    typer.echo(f"Impossible derivatives: {counts.impossible}")
    typer.echo(f"Stale derivatives: {counts.stale}")
    _echo_problems(catalog.problems)

    if catalog.problems:
        raise typer.Exit(code=1)


@app.command()
def assets(ctx: typer.Context) -> None:
    """List every loaded asset: ID, display name, statuses, and source count.

    Metadata problems are ``vpress status``'s report, not this command's; a
    catalog with a broken asset still lists every asset that did load.
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
    """The findings column ``vpress asset``'s ``cut_svg`` line adds (issue
    #37): ``pass`` / ``needs review`` when a current findings report exists,
    ``findings stale`` when one exists but no longer matches the file's
    content hash, reference size or thresholds, or ``not validated`` when
    there is no cut file to check yet (``impossible``/``missing``) or
    ``vpress validate`` has simply never run for it."""
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


@app.command()
def asset(
    ctx: typer.Context,
    asset_id: str = typer.Argument(help="The asset's ID (its folder name under assets/)."),
) -> None:
    """Show one asset in full: metadata, statuses, every source with its
    role, and every recipe-bearing derivative type's selected source,
    impossibility reason, or (once generated) current or stale output
    filename (issue #22, issue #23, issue #26, ADR 0003, ADR 0004).

    An ID naming a folder whose ``asset.toml`` failed to load is not the
    same as an ID naming no folder at all (issue #15): the former prints
    that asset's problems (same rendering as ``vpress status``), the latter
    prints "Unknown asset". ``catalog.assets.lookup_asset`` tells the two
    apart; this only formats whichever it returns.
    """
    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    result = lookup_asset(inventory, config, asset_id)
    if result.asset is None:
        if result.problems:
            _echo_problems(result.problems)
        else:
            typer.echo(f"Unknown asset: {asset_id!r}", err=True)
        raise typer.Exit(code=1)

    found = result.asset
    typer.echo(f"{found.id}\t{found.display_name}")
    typer.echo(f"Rights status: {found.rights_status.value}")
    typer.echo(f"Accuracy status: {found.accuracy_status.value}")
    typer.echo("Sources:")
    for source in found.sources:
        typer.echo(f"  {source.file}\t{source.role}")

    typer.echo("Derivatives:")
    for status in asset_derivative_statuses(found, asset_dir(root, config, found.id), config):
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
        # cut_svg's line alone also carries its findings result (issue #37):
        # no other derivative type is validated yet.
        if status.derivative_type is DerivativeType.CUT_SVG:
            line += f"\t{_findings_display(status, root, config, found.id)}"
        typer.echo(line)


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
    """Generate every recipe-bearing derivative type for one asset, every
    loaded asset with ``--all``, or only stale derivatives across every
    loaded asset with ``--stale`` (§6.1, §20, §22, §35, §36, issue #23,
    issue #24 review fix round 1, issue #26).

    Exactly one of ``asset_id``, ``--all``, ``--stale`` selects which
    derivatives are considered; ``--force`` combines with ``asset_id`` or
    ``--all`` only (not ``--stale``) to regenerate current derivatives too.
    Any other combination is a usage error.

    Each derivative is reported on its own line: asset, type, and outcome
    (``generated``, ``current``, ``missing`` -- ``--stale`` only, for a
    derivative it left untouched because it was never generated --
    ``impossible``, ``no generator`` for a recipe-bearing type whose
    generator has not landed yet, or ``failed`` when reading its source,
    running the generator, or writing its result raised (issue #27,
    widened from just the generator itself)). Regenerating is a no-op: a
    current derivative is reported ``current`` and never rewritten (§36)
    unless ``--force`` asks for it anyway, and even then unchanged bytes
    are not rewritten. An asset that failed to load is skipped and named
    rather than stopping the rest of ``--all``/``--stale`` (§35); an
    unknown asset ID is the same actionable error ``vpress asset`` gives.

    Each ``failed`` derivative also gets its own stderr line naming the
    asset, type, source file and cause (§35: failures must be visible and
    understandable), on top of its place in the stdout report above; a run
    with at least one failure ends with a stderr summary of how many.
    Exits non-zero if any derivative failed, even though every asset was
    still attempted.
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
    inventory = load_assets(root, config)

    if all_assets or stale:
        for failed_id in failed_asset_ids(inventory, config):
            typer.echo(f"{failed_id}\tskipped: failed to load")
        targets = inventory.assets
    else:
        assert asset_id is not None  # usage-error branch above covers the None case
        result = lookup_asset(inventory, config, asset_id)
        if result.asset is None:
            if result.problems:
                _echo_problems(result.problems)
            else:
                typer.echo(f"Unknown asset: {asset_id!r}", err=True)
            raise typer.Exit(code=1)
        targets = [result.asset]

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
) -> None:
    """Validate one asset's ``cut_svg``, or every loaded asset's with
    ``--all``, against every landed §9 detector (§9, §9.1, §9.2, ADR 0007,
    issue #37), writing a findings report beside the file (through
    ``catalog.findings``) and printing pass / needs review with each
    finding's kind and location.

    Exactly one of ``asset_id`` or ``--all`` selects which assets are
    checked; providing both, or neither, is a usage error. An asset whose
    cut file is ``missing`` or ``impossible`` is reported as such and not
    validated (there is no file to check yet); an asset that failed to load
    is skipped and named (§35), the same as ``vpress generate --all``.
    ``vpress generate`` itself never calls this -- a findings report only
    ever exists because ``validate`` was run.

    A validation failure (an unparseable SVG -- most plausibly a hand-edited
    override, since a generated cut file always parses) is reported on
    stderr naming the asset, file and cause, and the run still tries every
    other asset before exiting 1. A needs-review result is not a failure:
    the command exits 0 as long as every asset it attempted to validate
    parsed successfully.
    """
    selectors = [asset_id is not None, all_assets]
    if sum(selectors) != 1:
        raise typer.BadParameter(
            "Provide exactly one of: an asset ID, --all.",
            param_hint="asset_id / --all",
        )

    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    if all_assets:
        for failed_id in failed_asset_ids(inventory, config):
            typer.echo(f"{failed_id}\tskipped: failed to load")
        targets = inventory.assets
    else:
        assert asset_id is not None  # usage-error branch above covers the None case
        result = lookup_asset(inventory, config, asset_id)
        if result.asset is None:
            if result.problems:
                _echo_problems(result.problems)
            else:
                typer.echo(f"Unknown asset: {asset_id!r}", err=True)
            raise typer.Exit(code=1)
        targets = [result.asset]

    failure_count = 0
    for target in targets:
        # The whole read-validate-persist cycle lives in the ``validate``
        # layer (issue #37 fix round 1): this command only decides *which*
        # assets to check and formats the result -- it never opens a
        # catalog file itself (ADR 0006, CLAUDE.md's "cli stays thin").
        outcome = validate_asset_cut_file(root, config, target, config.reference_size_in)

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
        typer.echo(f"{target.id}\tcut_svg\t{outcome.filename}\t{result_text}")
        for finding in outcome.validation.findings:
            location = finding.location
            typer.echo(
                f"  {finding.kind.value}\t"
                f"({location.min_x},{location.min_y})-({location.max_x},{location.max_y})\t"
                f"{finding.message}"
            )

    if failure_count:
        typer.echo(f"validate: {failure_count} asset(s) failed", err=True)
        raise typer.Exit(code=1)


@app.command()
def collections(ctx: typer.Context) -> None:
    """List every loaded collection: slug, name, and membership form.

    Membership resolution (which assets actually match) is PRD 5's job;
    this only reports the declared shape (issue #5). Metadata problems are
    ``vpress status``'s report, not this command's; a catalog with a broken
    collection still lists every collection that did load.
    """
    root, config = _locate_and_load_config(ctx)
    inventory = load_collections(root, config)

    for loaded in inventory.collections:
        typer.echo(f"{loaded.slug}\t{loaded.name}\t{loaded.membership.form.value}")


@app.command()
def products(ctx: typer.Context) -> None:
    """List every loaded product: slug, listing title, tier, and collection
    reference.

    The listing title falls back to the slug when the product has no
    ``[listing]`` yet (issue #7: a product can exist before PRD 7 drafts
    one). Metadata problems are ``vpress status``'s report, not this
    command's; a catalog with a broken product still lists every product
    that did load.
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
