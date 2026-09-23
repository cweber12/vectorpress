"""Entry point for the ``vpress`` command.

The CLI is a thin layer: every command calls into ``vectorpress.build``,
``vectorpress.catalog`` and friends. No domain logic lives here.
"""

from pathlib import Path

import typer

from vectorpress import __version__
from vectorpress.catalog.assets import load_assets
from vectorpress.catalog.errors import CatalogConfigError, CatalogNotFoundError
from vectorpress.catalog.load import load_catalog_config
from vectorpress.catalog.locate import locate_catalog_root
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


def _locate_and_load_config(ctx: typer.Context) -> tuple[Path, CatalogConfig]:
    """Locate the catalog root and load its config, or exit with an actionable error."""
    explicit = ctx.obj.get("catalog") if ctx.obj else None
    try:
        root = locate_catalog_root(Path.cwd(), explicit=explicit)
    except CatalogNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        config = load_catalog_config(root)
    except CatalogConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    return root, config


@app.command()
def status(ctx: typer.Context) -> None:
    """Locate the catalog, load its config and assets, and report an inventory."""
    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)
    problem_files = {problem.path for problem in inventory.problems}

    typer.echo(f"{config.name}\n{root}")
    typer.echo(f"Assets: {len(inventory.assets)}")
    typer.echo(f"Metadata problems: {len(problem_files)}")


@app.command()
def assets(ctx: typer.Context) -> None:
    """List every loaded asset: ID, display name, rights status, accuracy status."""
    root, config = _locate_and_load_config(ctx)
    inventory = load_assets(root, config)

    for asset in inventory.assets:
        typer.echo(
            f"{asset.id}\t{asset.display_name}\t"
            f"{asset.rights_status.value}\t{asset.accuracy_status.value}"
        )

    for problem in inventory.problems:
        typer.echo(str(problem), err=True)
