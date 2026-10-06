from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from breakscope import __version__
from breakscope.changes import Severity
from breakscope.contracts import diff_files
from breakscope.errors import BreakScopeError
from breakscope.reports import json as json_report
from breakscope.reports import terminal

app = typer.Typer(
    name="breakscope",
    help="See what your API changes will break in your code.",
    no_args_is_help=True,
)

EXIT_OK, EXIT_BREAKING, EXIT_ERROR = 0, 1, 2


class Format(StrEnum):
    terminal = "terminal"
    json = "json"


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
    old: Annotated[Path, typer.Argument(help="Old OpenAPI spec (YAML or JSON).")],
    new: Annotated[Path, typer.Argument(help="New OpenAPI spec (YAML or JSON).")],
    fmt: Annotated[Format, typer.Option("--format", "-f", help="Output format.")] = Format.terminal,
    min_severity: Annotated[
        Severity, typer.Option("--min-severity", help="Hide changes below this severity.")
    ] = Severity.WARNING,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the report to a file.")
    ] = None,
) -> None:
    """Show contract changes between two OpenAPI specs.

    Exit code 0: no breaking changes. 1: breaking changes found. 2: error.
    """
    err = Console(stderr=True)
    try:
        changes, a, b = diff_files(old, new)
    except BreakScopeError as e:
        err.print(e.render(), markup=False, highlight=False)
        raise typer.Exit(EXIT_ERROR) from None

    skipped = {
        f"{m} {p} ({src})": reason
        for contract, src in ((a, "old"), (b, "new"))
        for (m, p), reason in contract.skipped.items()
    }
    shown = [c for c in changes if c.severity.rank <= min_severity.rank]

    if fmt is Format.json:
        text = json_report.render(shown, skipped=skipped)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text, nl=False)
    elif output:
        with output.open("w", encoding="utf-8") as fh:
            terminal.render(shown, Console(file=fh, width=100, no_color=True), skipped=skipped)
    else:
        terminal.render(shown, Console(highlight=False), skipped=skipped)

    breaking = any(c.severity is Severity.BREAKING for c in changes)
    raise typer.Exit(EXIT_BREAKING if breaking else EXIT_OK)


@app.command()
def analyze() -> None:
    """Trace API changes into your codebase."""
    typer.echo("analyze: coming in v0.4", err=True)
    raise typer.Exit(EXIT_ERROR)
