"""Angular templates: reads of component fields in `{{ }}`, `[x]="..."`, `@if`, `@for`, `*ngIf`
and `*ngFor`. Template expressions are TypeScript expressions (minus pipes), so each one is
parsed and evaluated with the component's fields and the template's aliases in scope."""

import re

from tree_sitter import Parser

from breakscope.analyzers.javascript import _LANGS
from breakscope.impact.flow import Access, Value
from breakscope.impact.flow_js import JSFlow

_PARSER = Parser(_LANGS["typescript"])
_PAREN = r"\(((?:[^()]|\([^()]*\))*)\)"  # one level of nested parentheses: user()
_PATTERNS = [
    ("block", re.compile(r"@(?:if|else if|switch)\s*" + _PAREN)),
    ("for", re.compile(r"@for\s*" + _PAREN)),
    ("interp", re.compile(r"\{\{(.*?)\}\}", re.DOTALL)),
    ("attr", re.compile(r"(\[[\w.\-]+\]|\*ngIf|\*ngFor)\s*=\s*\"([^\"]*)\"")),
]
_PIPE = re.compile(r"(?<!\|)\|(?!\|)")


def _strip_pipes(expr: str) -> str:
    return _PIPE.split(expr, maxsplit=1)[0]


def template_accesses(
    file_text: str, start: int, end: int, fields: dict[str, Value]
) -> list[Access]:
    """Accesses in `file_text[start:end]` (a template), positioned in `file_text`."""
    env: dict[str, Value] = dict(fields)
    found: list[tuple[int, str, int, str]] = []  # (index, kind, expr start, expr)
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(file_text, start, end):
            group = 2 if kind == "attr" else 1
            label = m.group(1) if kind == "attr" else ""
            found.append(
                (m.start(), kind if kind != "attr" else label, m.start(group), m.group(group))
            )
    found.sort()

    accesses: list[Access] = []
    lines = file_text.splitlines()
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line) + 1)

    for _, kind, pos, expr in found:
        alias: str | None = None
        element = False
        if kind in ("block", "*ngIf"):
            # `@if (user(); as u)` or `*ngIf="user() as u"`: the alias names the value.
            head, _, rest = expr.partition(";")
            in_rest = re.search(r"\bas\s+(\w+)", rest)
            in_head = re.search(r"\s+as\s+(\w+)\s*$", head)
            if in_rest:
                alias = in_rest.group(1)
            elif in_head:
                alias = in_head.group(1)
                head = head[: in_head.start()]
            expr = head
        elif kind in ("for", "*ngFor"):
            # `@for (o of orders; track o.id)` or `*ngFor="let o of orders"`.
            loop = re.match(r"\s*(?:let\s+)?(\w+)\s+of\s+([^;]+)", expr)
            if not loop:
                continue
            alias, element = loop.group(1), True
            pos += loop.start(2)
            expr = loop.group(2)
        expr = _strip_pipes(expr)
        source = expr.encode("utf-8")
        root = _PARSER.parse(source).root_node
        flow = JSFlow(source, None, None, component=root, seed=dict(env))
        result = flow.run()
        if alias:
            stmt = root.named_children[0] if root.named_children else None
            node = stmt.named_children[0] if stmt is not None and stmt.named_children else None
            v = flow.value(node)
            if v is not None:
                env[alias] = v.element() if element else v
        for a in result.accesses:
            accesses.append(_place(a, pos, expr, file_text, line_starts, lines))
    return accesses


def _place(
    a: Access, pos: int, expr: str, file_text: str, line_starts: list[int], lines: list[str]
) -> Access:
    """Move an access from expression coordinates to file coordinates."""
    expr_lines = expr.split("\n")
    offset = sum(len(x) + 1 for x in expr_lines[: a.line - 1]) + a.column - 1
    index = pos + offset
    line_no = next(i for i in range(len(line_starts) - 1) if line_starts[i + 1] > index)
    raw = lines[line_no]
    code = raw.strip()
    col = index - line_starts[line_no]
    caret = None
    if a.caret is not None:
        at = col - (len(raw) - len(raw.lstrip()))
        if at >= 0 and at + a.caret[1] <= len(code):
            caret = (at, a.caret[1])
    if len(code) > 120:
        code, caret = code[:117] + "...", None
    return Access(path=a.path, line=line_no + 1, column=col + 1, code=code, caret=caret)
