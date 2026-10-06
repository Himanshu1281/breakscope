from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from breakscope import __version__
from breakscope.analyzers import scan_repo
from breakscope.changes import Severity
from breakscope.contracts import diff_files, load_contract
from breakscope.errors import BreakScopeError
from breakscope.impact import analyze as run_analysis
from breakscope.impact.models import Confidence, Risk
from breakscope.reports import impact as impact_report
from breakscope.reports import json as json_report
from breakscope.reports import terminal
from breakscope.reports import usages as usages_report
from breakscope.usages import index_usages

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
def usages(
    spec: Annotated[Path, typer.Argument(help="OpenAPI spec (YAML or JSON).")],
    repo: Annotated[Path, typer.Argument(help="Repository to scan.")] = Path("."),
    base_url: Annotated[
        list[str] | None,
        typer.Option("--base-url", help="Path prefix your code adds to every URL, e.g. /api/v1."),
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Glob of files to skip (repeatable).")
    ] = None,
    fmt: Annotated[Format, typer.Option("--format", "-f", help="Output format.")] = Format.terminal,
    show_unused: Annotated[
        bool, typer.Option("--show-unused", help="List operations with no call sites.")
    ] = False,
    show_unresolved: Annotated[
        bool, typer.Option("--show-unresolved", help="List calls whose URL is not static.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the report to a file.")
    ] = None,
) -> None:
    """List where your code calls each API operation (Python, TypeScript, JavaScript)."""
    err = Console(stderr=True)
    if not repo.is_dir():
        err.print(f"error: repository directory not found: {repo}", markup=False)
        raise typer.Exit(EXIT_ERROR)
    try:
        contract = load_contract(spec)
    except BreakScopeError as e:
        err.print(e.render(), markup=False, highlight=False)
        raise typer.Exit(EXIT_ERROR) from None

    scan = scan_repo(repo, tuple(exclude or ()))
    index = index_usages(contract, scan.sites, base_url or ())

    if fmt is Format.json:
        text = usages_report.render_json(contract, index, scan)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text, nl=False)
        return
    kwargs = {"show_unused": show_unused, "show_unresolved": show_unresolved}
    if output:
        with output.open("w", encoding="utf-8") as fh:
            console = Console(file=fh, width=120, no_color=True)
            usages_report.render_terminal(contract, index, scan, console, **kwargs)
    else:
        usages_report.render_terminal(contract, index, scan, Console(highlight=False), **kwargs)


class FailOn(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    never = "never"


@app.command()
def analyze(
    old: Annotated[Path, typer.Argument(help="Old OpenAPI spec (what the code was written for).")],
    new: Annotated[Path, typer.Argument(help="New OpenAPI spec.")],
    repo: Annotated[Path, typer.Argument(help="Repository to scan.")] = Path("."),
    min_confidence: Annotated[
        Confidence, typer.Option("--min-confidence", help="Hide less certain locations.")
    ] = Confidence.MEDIUM,
    fail_on: Annotated[
        FailOn, typer.Option("--fail-on", help="Exit 1 when a location has this risk or higher.")
    ] = FailOn.high,
    base_url: Annotated[
        list[str] | None,
        typer.Option("--base-url", help="Path prefix your code adds to every URL, e.g. /api/v1."),
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Glob of files to skip (repeatable).")
    ] = None,
    fmt: Annotated[Format, typer.Option("--format", "-f", help="Output format.")] = Format.terminal,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the report to a file.")
    ] = None,
) -> None:
    """Find the code that is likely to break when the API changes from OLD to NEW.

    Exit code 0: nothing at or above --fail-on. 1: affected code found. 2: error.
    """
    err = Console(stderr=True)
    if not repo.is_dir():
        err.print(f"error: repository directory not found: {repo}", markup=False)
        raise typer.Exit(EXIT_ERROR)
    try:
        report = run_analysis(
            load_contract(old),
            load_contract(new),
            repo,
            base_paths=base_url or (),
            exclude=tuple(exclude or ()),
        )
    except BreakScopeError as e:
        err.print(e.render(), markup=False, highlight=False)
        raise typer.Exit(EXIT_ERROR) from None

    shown = [i for i in report.impacts if i.confidence.rank <= min_confidence.rank]
    if fmt is Format.json:
        text = impact_report.render_json(report, shown)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text, nl=False)
    elif output:
        with output.open("w", encoding="utf-8") as fh:
            impact_report.render_terminal(report, shown, Console(file=fh, width=120, no_color=True))
    else:
        impact_report.render_terminal(report, shown, Console(highlight=False))

    if fail_on is not FailOn.never:
        threshold = Risk(fail_on.value).rank
        if any(i.risk.rank <= threshold for i in shown):
            raise typer.Exit(EXIT_BREAKING)
