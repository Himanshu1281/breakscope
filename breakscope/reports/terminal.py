from rich.console import Console
from rich.markup import escape

from breakscope.changes import APIChange, Severity
from breakscope.contracts.rules import RULES
from breakscope.reports import ChangeGroup, group_changes, rename_hint

_STYLE = {Severity.BREAKING: "bold red", Severity.WARNING: "yellow", Severity.INFO: "dim"}
_ICON = {Severity.BREAKING: "🔴", Severity.WARNING: "🟡", Severity.INFO: "⚪"}
_ASCII = {Severity.BREAKING: "[x]", Severity.WARNING: "[!]", Severity.INFO: "[i]"}
_TITLE = {
    Severity.BREAKING: "BREAKING CHANGES",
    Severity.WARNING: "WARNINGS",
    Severity.INFO: "NON-BREAKING CHANGES",
}
_MAX_OPS = 5


def render(changes: list[APIChange], console: Console, *, skipped: dict[str, str]) -> None:
    unicode = (console.encoding or "").lower().startswith("utf")
    icons = _ICON if unicode else _ASCII
    rule_line = "─" * 48 if unicode else "-" * 48

    console.print(f"[bold]API CONTRACT DIFF[/]\n{rule_line}")
    for key, reason in skipped.items():
        console.print(f"[yellow]skipped[/] {escape(key)}: {escape(reason)}")

    groups = group_changes(changes)
    for sev in Severity:
        sev_groups = [g for g in groups if g.severity == sev]
        if not sev_groups:
            continue
        console.print(f"\n[{_STYLE[sev]}]{_TITLE[sev]}: {len(sev_groups)}[/]")
        for g in sev_groups:
            _group(console, g, icons[sev], _STYLE[sev])

    console.print(f"\n{rule_line}")
    if not changes:
        console.print("No contract changes.")
        return
    n = {sev: sum(1 for g in groups if g.severity == sev) for sev in Severity}
    console.print(
        f"[bold red]{_plural(n[Severity.BREAKING], 'breaking change')}[/], "
        f"[yellow]{_plural(n[Severity.WARNING], 'warning')}[/], "
        f"{n[Severity.INFO]} non-breaking"
    )


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _group(console: Console, g: ChangeGroup, icon: str, style: str) -> None:
    c = g.first
    if len(g.changes) == 1:
        head = f"{c.method} {c.path}" if c.method else ""
        console.print(f"\n{icon} [{style}]{escape(c.rule)}[/]  {escape(head)}")
        console.print(f"   {escape(_where(c))}{escape(c.message)}")
        return
    console.print(f"\n{icon} [{style}]{escape(c.rule)}[/]  [bold]{escape(c.subject)}[/]")
    console.print(f"   {escape(RULES[c.rule].description)}")
    hint = rename_hint(c)
    if hint:
        console.print(f"   [green]hint:[/] {escape(hint)}")
    console.print(f"   affects {len(g.changes)} operations:")
    for x in g.changes[:_MAX_OPS]:
        console.print(f"     {escape(f'{x.method} {x.path}')}{escape(_status(x))}")
    if len(g.changes) > _MAX_OPS:
        console.print(f"     ... and {len(g.changes) - _MAX_OPS} more")


def _status(c: APIChange) -> str:
    return f" -> {c.status_code}" if c.status_code else ""


def _where(c: APIChange) -> str:
    if c.status_code:
        return f"[{c.status_code}] "
    if c.direction:
        return f"[{c.direction.value}] "
    return ""
