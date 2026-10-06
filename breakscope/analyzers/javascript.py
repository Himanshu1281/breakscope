"""Find HTTP calls in JavaScript and TypeScript (including JSX/TSX)."""

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from breakscope.analyzers.base import (
    DYNAMIC,
    HTTP_VERBS,
    MAX_ALTERNATIVES,
    Alternatives,
    CallSite,
    concat,
    make_sites,
    single,
    text,
    walk,
)

_LANGS = {
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
    "javascript": Language(tree_sitter_javascript.language()),
}
# Objects whose .get/.post/... are HTTP calls whatever the URL looks like.
_KNOWN_CLIENTS = frozenset({"axios", "ky", "got", "superagent", "$http", "http", "httpClient"})
_MAX_DEPTH = 8
# Receivers that define server routes (Express, Fastify, Koa, Hono), not client calls.
_ROUTERS = frozenset({"app", "router", "server", "fastify", "api_router", "routes", "route"})
_FUNCTIONS = frozenset({"arrow_function", "function_expression", "function"})


class JavaScriptAnalyzer:
    def __init__(self, language: str) -> None:
        self.language = language
        self._parser = Parser(_LANGS[language])

    def scan(self, source: bytes, file: str, *, is_test: bool) -> list[CallSite]:
        root = self._parser.parse(source).root_node
        consts = _collect_consts(root)
        sites: list[CallSite] = []
        for node in walk(root):
            if node.type == "call_expression":
                sites += self._call(node, source, file, consts, is_test)
        return sites

    def _call(
        self, node: Node, source: bytes, file: str, consts: dict[str, Node | None], is_test: bool
    ) -> list[CallSite]:
        fn = node.child_by_field_name("function")
        args = _args(node)
        # tree-sitter-typescript parses `await api.get<T>(url)` as `(await api.get)<T>(url)`.
        while fn is not None and fn.type in ("await_expression", "parenthesized_expression"):
            fn = fn.named_children[0] if fn.named_children else None
        if fn is None:
            return []

        method: str | None
        url_node: Node | None
        known = True
        if fn.type == "identifier" and text(fn) == "fetch":
            client = "fetch"
            url_node = args[0] if args else None
            method = _option(args[1], "method", consts) if len(args) > 1 else None
            method = method or "GET"
        elif fn.type == "identifier" and text(fn) == "axios":
            client = "axios"
            if args and args[0].type == "object":
                url_node = _pair(args[0], "url")
                method = _option(args[0], "method", consts) or "GET"
            else:
                url_node = args[0] if args else None
                method = (_option(args[1], "method", consts) if len(args) > 1 else None) or "GET"
        elif fn.type == "member_expression":
            obj, prop = fn.child_by_field_name("object"), text(fn.child_by_field_name("property"))
            client = text(obj)
            last = client.rsplit(".", 1)[-1]
            known = last in _KNOWN_CLIENTS
            # app.get("/users", (req, res) => ...) defines a route; it does not call one.
            if last in _ROUTERS or any(a.type in _FUNCTIONS for a in args[1:]):
                return []
            if prop in HTTP_VERBS or prop == "del":  # superagent: .del() is DELETE
                method = "DELETE" if prop == "del" else prop.upper()
                url_node = args[0] if args else None
            elif prop == "request" and args and args[0].type == "object":
                url_node = _pair(args[0], "url")
                method = _option(args[0], "method", consts)
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


def _args(call: Node) -> list[Node]:
    a = call.child_by_field_name("arguments")
    return [c for c in a.named_children if c.type != "comment"] if a else []


def _pair(obj: Node, key: str) -> Node | None:
    for p in obj.named_children:
        if p.type == "pair" and text(p.child_by_field_name("key")).strip("\"'") == key:
            return p.child_by_field_name("value")
        if p.type == "shorthand_property_identifier" and text(p) == key:
            return p
    return None


def _option(obj: Node, key: str, consts: dict[str, Node | None]) -> str | None:
    if obj.type != "object":
        return None
    v = _pair(obj, key)
    if v is None:
        return None
    return single(_eval(v, consts, 0))


def _eval(node: Node, consts: dict[str, Node | None], depth: int) -> Alternatives:
    """Evaluate a string-ish expression to the URLs it can produce (literal parts with
    DYNAMIC holes). Ternaries yield one alternative per branch."""
    if depth > _MAX_DEPTH:
        return [[DYNAMIC]]
    t = node.type
    if t == "string":
        return [["".join(_fragment(c) for c in node.named_children)]]
    if t == "template_string":
        out: Alternatives = [[]]
        for c in node.named_children:
            if c.type == "template_substitution":
                inner = c.named_children[0] if c.named_children else None
                out = concat(out, _eval(inner, consts, depth + 1) if inner else [[DYNAMIC]])
            else:
                out = concat(out, [[_fragment(c)]])
        return out
    if t == "binary_expression" and text(node.child_by_field_name("operator")) == "+":
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if left is None or right is None:
            return [[DYNAMIC]]
        return concat(_eval(left, consts, depth + 1), _eval(right, consts, depth + 1))
    if t == "ternary_expression":
        a, b = node.child_by_field_name("consequence"), node.child_by_field_name("alternative")
        if a is None or b is None:
            return [[DYNAMIC]]
        return (_eval(a, consts, depth + 1) + _eval(b, consts, depth + 1))[:MAX_ALTERNATIVES]
    if t in (
        "parenthesized_expression",
        "as_expression",
        "non_null_expression",
        "satisfies_expression",
    ):
        return (
            _eval(node.named_children[0], consts, depth + 1) if node.named_children else [[DYNAMIC]]
        )
    if t == "identifier":
        value = consts.get(text(node))
        return _eval(value, consts, depth + 1) if value is not None else [[DYNAMIC]]
    return [[DYNAMIC]]


def _fragment(node: Node) -> str:
    if node.type == "escape_sequence":
        raw = text(node)
        return {"\\/": "/", "\\n": "\n", "\\t": "\t"}.get(raw, raw[1:])
    return text(node)


def _collect_consts(root: Node) -> dict[str, Node | None]:
    """`const NAME = <expr>` anywhere in the file. A name declared twice maps to None."""
    consts: dict[str, Node | None] = {}
    for node in walk(root):
        if node.type != "lexical_declaration" or not text(node).startswith("const"):
            continue
        for d in node.named_children:
            if d.type != "variable_declarator":
                continue
            name, value = d.child_by_field_name("name"), d.child_by_field_name("value")
            if name is None or name.type != "identifier" or value is None:
                continue
            key = text(name)
            consts[key] = None if key in consts else value
    return consts
