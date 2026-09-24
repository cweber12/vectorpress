"""Entry point for the ``vpress`` command.

The CLI is a thin layer: every command calls into ``vectorpress.build``,
``vectorpress.catalog`` and friends. No domain logic lives here.
"""

from pathlib import Path

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
from vectorpress.catalog.products import load_products, lookup_product
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_state import DerivativeState
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.finding import Finding, ValidationOutcome
from vectorpress.domain.numeric_format import format_number
from vectorpress.domain.product import Product
from vectorpress.domain.reference_size import resolve_reference_size_in
from vectorpress.pipeline.generate import (
    DerivativeStatus,
    GenerationOutcome,
    asset_derivative_statuses,
    count_derivative_states,
    generate_asset,
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


@app.command()
def asset(
    ctx: typer.Context,
    asset_id: str = typer.Argument(help="The asset's ID (its folder name under assets/)."),
) -> None:
    """Show one asset: metadata, sources with their roles, and each
    derivative type's state (current, stale, missing or impossible).

    The cut_svg line also shows its findings result: pass, needs review,
    findings stale, or not validated. An asset that failed to load shows
    its metadata problems instead.
    """
    root, config = _locate_and_load_config(ctx)
    found = _lookup_asset_or_exit(load_assets(root, config), config, asset_id)
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
        # Only cut_svg is validated, so only its line carries a findings result.
        if status.derivative_type is DerivativeType.CUT_SVG:
            line += f"\t{_findings_display(status, root, config, found.id)}"
        typer.echo(line)


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


def _validate_file(file: Path, reference_size_in: float) -> None:
    """Validate any SVG on disk with the same ``validate_cut_file`` asset
    validation uses, print the report, and write nothing."""
    if not file.is_file():
        typer.echo(f"validate: {file} failed: no such file", err=True)
        raise typer.Exit(code=1)

    svg_bytes = file.read_bytes()
    try:
        validation = validate_cut_file(svg_bytes, reference_size_in)
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
        if reference_size is not None:
            file_reference_size_in = reference_size
        else:
            file_config = _optional_catalog_config(ctx)
            if file_config is None:
                raise typer.BadParameter(
                    "No catalog found here; --reference-size is required for "
                    "--file outside a catalog.",
                    param_hint="--reference-size",
                )
            file_reference_size_in = file_config.reference_size_in
        _validate_file(file, file_reference_size_in)
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
        typer.echo(f"{target.id}\tcut_svg\t{outcome.filename}\t{result_text}{size_note}")
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
