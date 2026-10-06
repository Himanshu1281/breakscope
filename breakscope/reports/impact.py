import json
from typing import Any

from rich.console import Console
from rich.markup import escape

from breakscope import __version__
from breakscope.changes import APIChange, Severity
from breakscope.contracts.rules import RULES
from breakscope.impact.models import Confidence, Impact, ImpactReport, Risk
from breakscope.reports import group_changes

SCHEMA_VERSION = 1
# Icons and colours show risk (severity x confidence), not confidence alone.
_ICON = {Risk.HIGH: "🔴", Risk.MEDIUM: "🟡", Risk.LOW: "⚪"}
_ASCII = {Risk.HIGH: "[HIGH]", Risk.MEDIUM: "[MED] ", Risk.LOW: "[LOW] "}
_STYLE = {Risk.HIGH: "bold red", Risk.MEDIUM: "yellow", Risk.LOW: "dim"}
_SEV_STYLE = {Severity.BREAKING: "bold red", Severity.WARNING: "yellow", Severity.INFO: "dim"}


def overall_risk(impacts: list[Impact]) -> Risk | None:
    return min((i.risk for i in impacts), key=lambda r: r.rank, default=None)


def _impact_json(i: Impact) -> dict[str, Any]:
    return {
        "file": i.file,
        "line": i.line,
        "column": i.column,
        "code": i.code,
        "confidence": i.confidence.value,
        "risk": i.risk.value,
        "reason": i.reason,
        "is_test": i.is_test,
    }


def render_json(report: ImpactReport, impacts: list[Impact]) -> str:
    changes = []
    for g in group_changes(report.changes):
        group_impacts = [i for i in impacts if i.change in g.changes]
        changes.append(
            {
                "rule": g.rule,
                "severity": g.severity.value,
                "subject": g.first.subject,
                "message": g.first.message if len(g.changes) == 1 else RULES[g.rule].description,
                "operations": [
                    {"method": c.method, "path": c.path, "status_code": c.status_code}
                    for c in g.changes
                ],
                "call_sites": sum(report.call_counts.get(c.key, 0) for c in g.changes),
                "impacts": [_impact_json(i) for i in group_impacts],
            }
        )
    risk = overall_risk(impacts)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "breakscope_version": __version__,
        "summary": {
            "breaking_changes": sum(
                1 for g in group_changes(report.changes) if g.severity is Severity.BREAKING
            ),
            "locations": len({(i.file, i.line) for i in impacts}),
            "files": len({i.file for i in impacts}),
            "risk": risk.value if risk else "none",
            "files_scanned": report.files_scanned,
            "call_sites": report.call_sites,
        },
        "changes": changes,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def render_terminal(report: ImpactReport, impacts: list[Impact], console: Console) -> None:
    unicode = (console.encoding or "").lower().startswith("utf")
    icons = _ICON if unicode else _ASCII
    rule = "─" * 48 if unicode else "-" * 48
    console.print(f"[bold]API IMPACT ANALYSIS[/]\n{rule}")

    groups = group_changes(report.changes)
    if not groups:
        console.print("\nNo contract changes.")
    n = 0
    for sev in Severity:
        sev_groups = [g for g in groups if g.severity == sev]
        if not sev_groups:
            continue
        title = {"breaking": "BREAKING CHANGES", "warning": "WARNINGS", "info": "OTHER CHANGES"}
        console.print(f"\n[{_SEV_STYLE[sev]}]{title[sev.value]}: {len(sev_groups)}[/]")
        for g in sev_groups:
            n += 1
            group_impacts = [i for i in impacts if i.change in g.changes]
            _group(console, n, g.changes, group_impacts, report, icons)

    console.print(f"\n{rule}")
    files = len({i.file for i in impacts})
    risk = overall_risk(impacts)
    console.print(f"Files affected: {files}")
    console.print(f"Locations affected: {len({(i.file, i.line) for i in impacts})}")
    if risk is None:
        console.print("Risk: [green]NONE FOUND[/]")
    else:
        style = {"high": "bold red", "medium": "yellow", "low": "dim"}[risk.value]
        console.print(f"Risk: [{style}]{risk.value.upper()}[/]")


def _group(
    console: Console,
    n: int,
    changes: list[APIChange],
    impacts: list[Impact],
    report: ImpactReport,
    icons: dict[Risk, str],
) -> None:
    c = changes[0]
    console.print()
    if len(changes) == 1:
        head = f"{c.method} {c.path}" if c.method else c.subject
        console.print(f"{n}. [bold]{escape(head)}[/]")
        console.print(f"   {escape(c.message)}  [dim]({escape(c.rule)})[/]")
    else:
        console.print(f"{n}. [bold]{escape(c.subject)}[/]  [dim]({escape(c.rule)})[/]")
        ops = ", ".join(f"{x.method} {x.path}" for x in changes[:3])
        more = f" and {len(changes) - 3} more" if len(changes) > 3 else ""
        console.print(f"   {escape(RULES[c.rule].description)} In {escape(ops)}{more}.")

    calls = sum(report.call_counts.get(x.key, 0) for x in changes)
    hidden = sum(1 for i in report.impacts if i.change in changes and i not in impacts)
    hint = (
        f" [dim]{hidden} lower-confidence match{'es' if hidden != 1 else ''} hidden; "
        f"show with --min-confidence low.[/]"
        if hidden
        else ""
    )
    if not impacts:
        if calls:
            field = f" of `{c.subject}`" if c.field_path else ""
            console.print(
                f"   [dim]Called in {calls} place{'s' if calls != 1 else ''}, "
                f"but no traced reads{escape(field)}.[/]{hint}"
            )
        else:
            console.print(f"   [dim]No affected code found.[/]{hint}")
        return
    if hint:
        console.print(f"  {hint}")

    console.print("\n   Likely affected code:")
    for i in impacts:
        test = "  [dim](test)[/]" if i.is_test else ""
        style = _STYLE[i.risk]
        console.print(
            f"\n   {icons[i.risk]} [{style}]{escape(i.file)}:{i.line}[/]{test}", soft_wrap=True
        )
        console.print(f"      {escape(i.code)}", soft_wrap=True, highlight=False)
        if i.caret:
            console.print(f"      {' ' * i.caret[0]}[{style}]{'^' * i.caret[1]}[/]")
        if i.confidence is not Confidence.HIGH:
            console.print(
                f"      [dim]{i.confidence.value} confidence: {escape(i.reason)}[/]",
                soft_wrap=True,
            )
