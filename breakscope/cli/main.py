import io
import sys
from contextlib import ExitStack
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from breakscope import __version__
from breakscope import fix as fix_plan
from breakscope.analyzers import scan_repo
from breakscope.changes import Severity
from breakscope.config import CONFIG_FILE, TEMPLATE, find_specs, load_config
from breakscope.contracts import diff_files, load_contract
from breakscope.errors import BreakScopeError
from breakscope.gitspec import open_spec, repo_root, spec_at_ref
from breakscope.impact import analyze as run_analysis
from breakscope.impact.models import Confidence, Impact, ImpactReport, Risk
from breakscope.reports import impact as impact_report
from breakscope.reports import json as json_report
from breakscope.reports import markdown as markdown_report
from breakscope.reports import sarif as sarif_report
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
    old: Annotated[str, typer.Argument(help="Old OpenAPI spec: a path or git:REF:PATH.")],
    new: Annotated[str, typer.Argument(help="New OpenAPI spec: a path or git:REF:PATH.")],
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
        with open_spec(old) as old_path, open_spec(new) as new_path:
            changes, a, b = diff_files(old_path, new_path)
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

    scan = scan_repo(repo, tuple(exclude or ()), contract)
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


class ReportFormat(StrEnum):
    terminal = "terminal"
    json = "json"
    markdown = "markdown"
    sarif = "sarif"


def _render(
    fmt: ReportFormat, report: ImpactReport, shown: list[Impact], link_base: str | None
) -> str:
    if fmt is ReportFormat.json:
        return impact_report.render_json(report, shown)
    if fmt is ReportFormat.markdown:
        return markdown_report.render(report, shown, link_base=link_base)
    if fmt is ReportFormat.sarif:
        return sarif_report.render(report, shown)
    buf = io.StringIO()
    impact_report.render_terminal(report, shown, Console(file=buf, width=120, no_color=True))
    return buf.getvalue()


def _emit(
    report: ImpactReport,
    shown: list[Impact],
    fmt: ReportFormat,
    output: Path | None,
    link_base: str | None = None,
) -> None:
    if output is not None:
        output.write_text(_render(fmt, report, shown, link_base), encoding="utf-8")
    elif fmt is ReportFormat.terminal:
        impact_report.render_terminal(report, shown, Console(highlight=False))
    else:
        typer.echo(_render(fmt, report, shown, link_base), nl=False)


def _exit_code(shown: list[Impact], fail_on: FailOn) -> int:
    if fail_on is FailOn.never:
        return EXIT_OK
    threshold = Risk(fail_on.value).rank
    return EXIT_BREAKING if any(i.risk.rank <= threshold for i in shown) else EXIT_OK


@app.command()
def analyze(
    old: Annotated[
        str,
        typer.Argument(help="Old spec (what the code was written for): a path or git:REF:PATH."),
    ],
    new: Annotated[str, typer.Argument(help="New spec: a path or git:REF:PATH.")],
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
    fmt: Annotated[
        ReportFormat, typer.Option("--format", "-f", help="Output format.")
    ] = ReportFormat.terminal,
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
        with open_spec(old) as old_path, open_spec(new) as new_path:
            report = run_analysis(
                load_contract(old_path),
                load_contract(new_path),
                repo,
                base_paths=base_url or (),
                exclude=tuple(exclude or ()),
            )
    except BreakScopeError as e:
        err.print(e.render(), markup=False, highlight=False)
        raise typer.Exit(EXIT_ERROR) from None

    shown = [i for i in report.impacts if i.confidence.rank <= min_confidence.rank]
    _emit(report, shown, fmt, output)
    raise typer.Exit(_exit_code(shown, fail_on))


@app.command()
def check(
    repo: Annotated[Path, typer.Option("--repo", help="Repository root.")] = Path("."),
    spec: Annotated[
        str | None, typer.Option("--spec", help="Spec path in the repo (default: from config).")
    ] = None,
    base: Annotated[
        str | None, typer.Option("--base", help="Git ref to compare against, e.g. origin/main.")
    ] = None,
    old: Annotated[
        str | None,
        typer.Option("--old", help="Compare against this spec file instead of the git base."),
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="Config file (default: .breakscope.yml).")
    ] = None,
    fail_on: Annotated[FailOn | None, typer.Option("--fail-on")] = None,
    min_confidence: Annotated[Confidence | None, typer.Option("--min-confidence")] = None,
    markdown: Annotated[
        Path | None, typer.Option("--markdown", help="Also write a Markdown report (PR comment).")
    ] = None,
    sarif: Annotated[
        Path | None, typer.Option("--sarif", help="Also write SARIF (GitHub code scanning).")
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Also write the JSON report.")
    ] = None,
    link_base: Annotated[
        str | None,
        typer.Option("--link-base", help="URL prefix for file links in Markdown, e.g. a blob URL."),
    ] = None,
) -> None:
    """CI mode: compare the spec with its version on the base branch, using .breakscope.yml.

    Exit code 0: nothing at or above fail-on. 1: affected code found. 2: error.
    """
    err = Console(stderr=True)
    try:
        root = repo.resolve() if old else repo_root(repo)
        cfg = load_config(config or root / CONFIG_FILE)
        spec_rel = spec or cfg.spec
        if not spec_rel:
            raise BreakScopeError(
                "no spec configured",
                hint="pass --spec path/to/openapi.yaml, or run `breakscope init`",
            )
        new_path = root / spec_rel
        if not new_path.is_file():
            raise BreakScopeError(f"spec not found: {spec_rel}", file=str(new_path))
        ref = base or cfg.base
        with ExitStack() as stack:
            old_path: Path | None
            if old:
                old_path = stack.enter_context(open_spec(old))
                label = old
            else:
                old_path = stack.enter_context(spec_at_ref(root, ref, spec_rel))
                label = f"{ref}:{spec_rel}"
            if old_path is None:
                err.print(f"{spec_rel} does not exist at {ref}: nothing to compare.", markup=False)
                report = ImpactReport(changes=[])
            else:
                report = run_analysis(
                    load_contract(old_path),
                    load_contract(new_path),
                    root,
                    base_paths=cfg.base_url,
                    exclude=tuple(cfg.exclude),
                )
    except BreakScopeError as e:
        err.print(e.render(), markup=False, highlight=False)
        raise typer.Exit(EXIT_ERROR) from None

    threshold = min_confidence or Confidence(cfg.min_confidence)
    shown = [i for i in report.impacts if i.confidence.rank <= threshold.rank]
    err.print(f"Comparing {label} -> {spec_rel}", markup=False, highlight=False)
    _emit(report, shown, ReportFormat.terminal, None)
    outputs = (
        (markdown, ReportFormat.markdown),
        (sarif, ReportFormat.sarif),
        (json_out, ReportFormat.json),
    )
    for path, fmt in outputs:
        if path is not None:
            _emit(report, shown, fmt, path, link_base)
    raise typer.Exit(_exit_code(shown, fail_on or FailOn(cfg.fail_on)))


@app.command()
def fix(
    old: Annotated[str, typer.Argument(help="Old spec: a path or git:REF:PATH.")],
    new: Annotated[str, typer.Argument(help="New spec: a path or git:REF:PATH.")],
    repo: Annotated[Path, typer.Argument(help="Repository to fix.")] = Path("."),
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Print the patch (always on).")
    ] = True,
    base_url: Annotated[
        list[str] | None,
        typer.Option("--base-url", help="Path prefix your code adds to every URL, e.g. /api/v1."),
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Glob of files to skip (repeatable).")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the patch to a file.")
    ] = None,
) -> None:
    """Print a patch for renamed fields (`.name` -> `.full_name`), for review and `git apply`.

    Only fields with a rename hint are fixed, only at reads traced with high or medium
    confidence. Files are never modified.
    """
    err = Console(stderr=True, highlight=False)
    if not dry_run:
        err.print("BreakScope only prints patches; apply them with `git apply`.", markup=False)
        raise typer.Exit(EXIT_ERROR)
    if not repo.is_dir():
        err.print(f"error: repository directory not found: {repo}", markup=False)
        raise typer.Exit(EXIT_ERROR)
    try:
        with open_spec(old) as old_path, open_spec(new) as new_path:
            report = run_analysis(
                load_contract(old_path),
                load_contract(new_path),
                repo,
                base_paths=base_url or (),
                exclude=tuple(exclude or ()),
            )
    except BreakScopeError as e:
        err.print(e.render(), markup=False)
        raise typer.Exit(EXIT_ERROR) from None

    planned = fix_plan.plan(report, report.impacts, repo)
    patch = fix_plan.render(planned, repo)
    if output is not None:
        # Bytes, not text mode: the patch carries each file's own line endings.
        output.write_bytes(patch.encode("utf-8"))
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(patch.encode("utf-8"))
        sys.stdout.buffer.flush()

    files = len({e.file for e in planned.edits})
    for subject, to in sorted(planned.renames.items()):
        err.print(f"rename: {subject} -> {to}", markup=False)
    err.print(f"{len(planned.edits)} edits in {files} files.", markup=False)
    for impact, reason in planned.skipped:
        err.print(f"skipped {impact.file}:{impact.line}: {reason}", markup=False)
    if planned.renames:
        err.print(
            "Also update type definitions and fixtures that mention the old names.", markup=False
        )


_WORKFLOW = """\
name: BreakScope

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  api-impact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: Himanshu1281/breakscope@v{major}
"""


@app.command()
def init(
    repo: Annotated[Path, typer.Option("--repo", help="Repository root.")] = Path("."),
    spec: Annotated[str | None, typer.Option("--spec", help="Spec path in the repo.")] = None,
    workflow: Annotated[
        bool, typer.Option("--workflow", help="Also write .github/workflows/breakscope.yml.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Create .breakscope.yml (and optionally a GitHub Actions workflow)."""
    console = Console(highlight=False)
    target = repo / CONFIG_FILE
    if target.exists() and not force:
        console.print(f"{CONFIG_FILE} already exists (use --force to overwrite).", markup=False)
        raise typer.Exit(EXIT_ERROR)
    found = find_specs(repo)
    chosen = spec or (found[0] if found else None)
    if chosen is None:
        console.print("No OpenAPI spec found; edit `spec:` in the config.", markup=False)
    elif not spec and len(found) > 1:
        others = ", ".join(found[1:4])
        console.print(f"Found {len(found)} specs, using {chosen} (others: {others})", markup=False)
    target.write_text(TEMPLATE.format(spec=chosen or "openapi.yaml"), encoding="utf-8")
    console.print(f"Wrote {target}", markup=False)

    if workflow:
        wf = repo / ".github" / "workflows" / "breakscope.yml"
        if wf.exists() and not force:
            console.print(f"{wf} already exists (use --force to overwrite).", markup=False)
        else:
            wf.parent.mkdir(parents=True, exist_ok=True)
            major = __version__.split(".")[0]
            wf.write_text(_WORKFLOW.format(major=major), encoding="utf-8")
            console.print(f"Wrote {wf}", markup=False)
    console.print(
        "Next: run `breakscope check` to compare your spec with the base branch.", markup=False
    )
