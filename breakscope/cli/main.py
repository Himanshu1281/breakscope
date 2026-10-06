from pathlib import Path
from typing import Annotated

import typer

from breakscope import __version__

app = typer.Typer(
    name="breakscope",
    help="See what your API changes will break in your code.",
    no_args_is_help=True,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"breakscope {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    pass


@app.command()
def diff(
    old: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Old OpenAPI spec.")],
    new: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="New OpenAPI spec.")],
) -> None:
    """Show contract changes between two OpenAPI specs."""
    typer.echo("diff: coming in v0.1", err=True)
    raise typer.Exit(2)


@app.command()
def analyze() -> None:
    """Trace API changes into your codebase."""
    typer.echo("analyze: coming in v0.4", err=True)
    raise typer.Exit(2)
