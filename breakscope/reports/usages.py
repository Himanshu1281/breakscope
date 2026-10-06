import json
from typing import Any

from rich.console import Console
from rich.markup import escape

from breakscope import __version__
from breakscope.analyzers import ScanResult
from breakscope.analyzers.base import CallSite
from breakscope.contracts.model import Contract
from breakscope.usages import Usage, UsageIndex

SCHEMA_VERSION = 1


def _site(s: CallSite) -> dict[str, Any]:
    return {
        "file": s.file,
        "line": s.line,
        "column": s.column,
        "language": s.language,
        "client": s.client,
        "method": s.method,
        "url": s.url.path if s.url else None,
        "url_source": s.url_source,
        "code": s.code,
        "is_test": s.is_test,
    }


def render_json(contract: Contract, index: UsageIndex, scan: ScanResult) -> str:
    ops = []
    for key, op in contract.operations.items():
        usages = index.by_operation.get(key, [])
        ops.append(
            {
                "method": op.method,
                "path": op.path,
                "operation_id": op.operation_id,
                "usages": [
                    _site(u.site) | {"match": u.match, "ambiguous": u.ambiguous} for u in usages
                ],
            }
        )
    doc = {
        "schema_version": SCHEMA_VERSION,
        "breakscope_version": __version__,
        "summary": {
            "files_scanned": scan.files_scanned,
            "call_sites": len(scan.sites),
            "operations": len(contract.operations),
            "operations_used": sum(1 for k in contract.operations if index.by_operation.get(k)),
            "unmatched": len(index.unmatched),
            "unresolved": len(index.unresolved),
        },
        "operations": ops,
        "unmatched": [_site(u.site) | {"reason": u.reason} for u in index.unmatched],
        "unresolved": [_site(s) for s in index.unresolved],
        "unreadable_files": scan.errors,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def render_terminal(
    contract: Contract,
    index: UsageIndex,
    scan: ScanResult,
    console: Console,
    *,
    show_unused: bool,
    show_unresolved: bool,
) -> None:
    unicode = (console.encoding or "").lower().startswith("utf")
    rule = "─" * 48 if unicode else "-" * 48
    console.print(f"[bold]API USAGES[/]\n{rule}")

    used = [(k, op) for k, op in contract.operations.items() if index.by_operation.get(k)]
    unused = [(k, op) for k, op in contract.operations.items() if not index.by_operation.get(k)]
    for key, op in sorted(used, key=lambda x: (x[1].path, x[1].method)):
        usages = index.by_operation[key]
        n = len(usages)
        oid = f"  [dim]({escape(op.operation_id)})[/]" if op.operation_id else ""
        console.print(
            f"\n[bold]{escape(op.method)} {escape(op.path)}[/]{oid}  "
            f"{n} call site{'s' if n != 1 else ''}"
        )
        width = max(len(_loc(u.site)) for u in usages)
        for u in sorted(usages, key=lambda u: (u.site.is_test, u.site.file, u.site.line)):
            console.print(
                f"  {escape(_loc(u.site).ljust(width))}  {escape(u.site.code)}{_tags(u)}",
                soft_wrap=True,
            )

    if index.unmatched:
        console.print(f"\n[yellow]Calls that match no operation: {len(index.unmatched)}[/]")
        for m in index.unmatched:
            console.print(f"  {escape(_loc(m.site))}  {escape(m.site.code)}", soft_wrap=True)
            console.print(f"    [dim]{escape(m.reason)}[/]")

    if show_unresolved and index.unresolved:
        console.print(f"\n[dim]Calls with a URL we could not resolve: {len(index.unresolved)}[/]")
        for s in index.unresolved:
            console.print(f"  {escape(_loc(s))}  {escape(s.code)}", soft_wrap=True)

    if show_unused and unused:
        console.print(f"\n[dim]Operations with no call sites: {len(unused)}[/]")
        for _, op in sorted(unused, key=lambda x: (x[1].path, x[1].method)):
            console.print(f"  [dim]{escape(op.method)} {escape(op.path)}[/]")

    console.print(f"\n{rule}")
    console.print(
        f"{len(scan.sites)} call sites in {scan.files_scanned} files scanned. "
        f"{len(used)} of {len(contract.operations)} operations used, "
        f"{len(index.unmatched)} unmatched, {len(index.unresolved)} unresolved."
    )
    hints = []
    if unused and not show_unused:
        hints.append("--show-unused")
    if index.unresolved and not show_unresolved:
        hints.append("--show-unresolved")
    if hints:
        console.print(f"[dim]More detail: {' '.join(hints)}[/]")


def _loc(s: CallSite) -> str:
    return f"{s.file}:{s.line}"


def _tags(u: Usage) -> str:
    tags = []
    if u.site.is_test:
        tags.append("test")
    if u.match == "prefix":
        tags.append("path prefix guessed")
    elif u.match == "method_unknown":
        tags.append("method unknown")
    if u.ambiguous:
        tags.append("ambiguous")
    return f"  [dim]({escape(', '.join(tags))})[/]" if tags else ""
