"""Entry point for the ``vpress`` command.

The CLI is a thin layer: every command calls into ``vectorpress.build``,
``vectorpress.catalog`` and friends. No domain logic lives here.
"""

from pathlib import Path

import typer

from vectorpress import __version__
from vectorpress.catalog.assets import find_asset, load_assets
from vectorpress.catalog.errors import CatalogConfigError, CatalogNotFoundError
from vectorpress.catalog.load import load_catalog, load_catalog_config
from vectorpress.catalog.locate import locate_catalog_root
from vectorpress.catalog.metadata_problem import MetadataProblem
from vectorpress.domain.catalog_config import CatalogConfig

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
    #6): aggregates problems from catalog config, assets and (once their
    slices land) collections, products and brand. Exit code is non-zero
    when any problem exists, so this works as a check in scripts.
    """
    root = _locate_root(ctx)
    catalog = load_catalog(root)

    name = catalog.config.name if catalog.config is not None else root.name
    typer.echo(f"{name}\n{root}")
    typer.echo(f"Assets: {len(catalog.assets)}")
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


@app.command()
def asset(
    ctx: typer.Context,
    asset_id: str = typer.Argument(help="The asset's ID (its folder name under assets/)."),
) -> None:
    """Show one asset in full: metadata, statuses, and every source with its role."""
    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    found = find_asset(inventory, asset_id)
    if found is None:
        typer.echo(f"Unknown asset: {asset_id!r}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{found.id}\t{found.display_name}")
    typer.echo(f"Rights status: {found.rights_status.value}")
    typer.echo(f"Accuracy status: {found.accuracy_status.value}")
    typer.echo("Sources:")
    for source in found.sources:
        typer.echo(f"  {source.file}\t{source.role}")
