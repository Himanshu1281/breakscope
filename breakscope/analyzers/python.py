"""Find HTTP calls in Python: requests, httpx, aiohttp-style sessions and custom clients."""

import re

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from breakscope.analyzers.base import (
    DYNAMIC,
    HTTP_VERBS,
    MAX_ALTERNATIVES,
    Alternatives,
    CallSite,
    UrlParts,
    concat,
    make_sites,
    single,
    text,
    walk,
)

_LANG = Language(tree_sitter_python.language())
# Receivers whose .get/.post/... are HTTP calls whatever the URL looks like.
_KNOWN_CLIENTS = frozenset({"requests", "httpx", "session", "http", "http_client", "httpx_client"})
_MAX_DEPTH = 8
_PERCENT = re.compile(r"%(?:\([^)]*\))?[sdirf]")


class PythonAnalyzer:
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(_LANG)

    def parse(self, source: bytes) -> Node:
        return self._parser.parse(source).root_node

    def scan(self, source: bytes, file: str, *, is_test: bool) -> list[CallSite]:
        root = self.parse(source)
        consts = _collect_consts(root)
        sites: list[CallSite] = []
        for node in walk(root):
            if node.type == "call":
                sites += self._call(node, source, file, consts, is_test)
        return sites

    def _call(
        self, node: Node, source: bytes, file: str, consts: dict[str, Node | None], is_test: bool
    ) -> list[CallSite]:
        fn = node.child_by_field_name("function")
        if fn is None:
            return []
        # @app.get("/users") / @router.post(...) define routes (FastAPI, Flask); not calls.
        if node.parent is not None and node.parent.type == "decorator":
            return []
        positional, keywords = _args(node)

        method: str | None
        url_node: Node | None
        if fn.type == "identifier" and text(fn) == "urlopen":
            client, known, method = "urllib", True, "GET"
            url_node = positional[0] if positional else keywords.get("url")
        elif fn.type == "attribute":
            obj = fn.child_by_field_name("object")
            attr = text(fn.child_by_field_name("attribute"))
            client = text(obj)
            last = client.rsplit(".", 1)[-1]
            known = last in _KNOWN_CLIENTS or last.endswith(("_session", "_client"))
            if attr in HTTP_VERBS:
                method = attr.upper()
                url_node = positional[0] if positional else keywords.get("url")
            elif attr == "request":
                m = positional[0] if positional else keywords.get("method")
                method = _literal(m, consts)
                url_node = positional[1] if len(positional) > 1 else keywords.get("url")
            elif attr == "urlopen":
                method, known = "GET", True
                url_node = positional[0] if positional else keywords.get("url")
            else:
                return []
        else:
            return []

        if url_node is None:
            return []
        return make_sites(
            node,
            source,
            file=file,
            language=self.language,
            client=client,
            method=method,
            alternatives=_eval(url_node, consts, 0),
            url_node=url_node,
            is_test=is_test,
            known=known,
        )


def _args(call: Node) -> tuple[list[Node], dict[str, Node]]:
    a = call.child_by_field_name("arguments")
    positional: list[Node] = []
    keywords: dict[str, Node] = {}
    for c in a.named_children if a else []:
        if c.type == "keyword_argument":
            name, value = c.child_by_field_name("name"), c.child_by_field_name("value")
            if name is not None and value is not None:
                keywords[text(name)] = value
        elif c.type not in ("comment", "list_splat", "dictionary_splat"):
            positional.append(c)
    return positional, keywords


def _literal(node: Node | None, consts: dict[str, Node | None]) -> str | None:
    if node is None:
        return None
    return single(_eval(node, consts, 0))


def _eval(node: Node, consts: dict[str, Node | None], depth: int) -> Alternatives:
    """Evaluate a string-ish expression to the URLs it can produce (literal parts with
    DYNAMIC holes). Conditional expressions yield one alternative per branch."""
    if depth > _MAX_DEPTH:
        return [[DYNAMIC]]
    t = node.type
    if t == "string":
        out: Alternatives = [[]]
        for c in node.named_children:
            if c.type == "string_content":
                out = concat(out, [[text(c)]])
            elif c.type == "escape_sequence":
                out = concat(out, [[text(c)[1:]]])
            elif c.type == "interpolation":
                inner = c.child_by_field_name("expression")
                out = concat(out, _eval(inner, consts, depth + 1) if inner else [[DYNAMIC]])
        return [o or [""] for o in out]
    if t == "concatenated_string":
        out = [[]]
        for c in node.named_children:
            out = concat(out, _eval(c, consts, depth + 1))
        return out
    if t == "binary_operator":
        op = text(node.child_by_field_name("operator"))
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None:
            return [[DYNAMIC]]
        if op == "+":
            return concat(_eval(left, consts, depth + 1), _eval(right, consts, depth + 1))
        if op == "%":
            return [_percent_holes(a) for a in _eval(left, consts, depth + 1)]
        return [[DYNAMIC]]
    if t == "conditional_expression" and len(node.named_children) == 3:
        yes, _, no = node.named_children
        return (_eval(yes, consts, depth + 1) + _eval(no, consts, depth + 1))[:MAX_ALTERNATIVES]
    if t == "parenthesized_expression" and node.named_children:
        return _eval(node.named_children[0], consts, depth + 1)
    if t == "identifier":
        value = consts.get(text(node))
        return _eval(value, consts, depth + 1) if value is not None else [[DYNAMIC]]
    if t == "call":
        # "/users/{}".format(x): keep the template, holes dynamic.
        fn = node.child_by_field_name("function")
        if (
            fn is not None
            and fn.type == "attribute"
            and text(fn.child_by_field_name("attribute")) == "format"
        ):
            obj = fn.child_by_field_name("object")
            if obj is not None:
                return [_format_holes(a, "{", "}") for a in _eval(obj, consts, depth + 1)]
    return [[DYNAMIC]]


def _format_holes(parts: UrlParts, open_: str, close: str) -> UrlParts:
    out: UrlParts = []
    for p in parts:
        if p is DYNAMIC:
            out.append(DYNAMIC)
            continue
        while open_ in p and close in p.split(open_, 1)[1]:
            before, rest = p.split(open_, 1)
            out += [before, DYNAMIC]
            p = rest.split(close, 1)[1]
        out.append(p)
    return out


def _percent_holes(parts: UrlParts) -> UrlParts:
    out: UrlParts = []
    for p in parts:
        if p is DYNAMIC:
            out.append(DYNAMIC)
            continue
        for i, chunk in enumerate(_PERCENT.split(p)):
            if i:
                out.append(DYNAMIC)
            out.append(chunk)
    return out


def _collect_consts(root: Node) -> dict[str, Node | None]:
    """Module-level `NAME = <expr>` assignments. A name assigned twice maps to None."""
    consts: dict[str, Node | None] = {}
    for stmt in root.named_children:
        if stmt.type != "expression_statement" or not stmt.named_children:
            continue
        a = stmt.named_children[0]
        if a.type != "assignment":
            continue
        name, value = a.child_by_field_name("left"), a.child_by_field_name("right")
        if name is None or name.type != "identifier" or value is None:
            continue
        key = text(name)
        consts[key] = None if key in consts else value
    return consts
