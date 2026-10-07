"""RTK Query: `createApi({ endpoints })` defines the calls; generated hooks make them.

getUserById: build.query({ query: (id) => `/users/${id}` })
...
const { data } = useGetUserByIdQuery(id)   <- the call site, GET /users/{}
"""

from dataclasses import dataclass

from tree_sitter import Node

from breakscope.analyzers.base import Alternatives, CallSite, make_sites, text, walk
from breakscope.analyzers.javascript import _collect_consts, _eval, _option, _pair


@dataclass(frozen=True)
class Endpoint:
    name: str
    kind: str  # "query" or "mutation"
    method: str
    alternatives: Alternatives
    url_node: Node


def _object_of(fn: Node) -> Node | None:
    """The object an arrow function returns: `(build) => ({ ... })` or `{ return {...} }`."""
    body = fn.child_by_field_name("body")
    while body is not None and body.type == "parenthesized_expression" and body.named_children:
        body = body.named_children[0]
    if body is not None and body.type == "object":
        return body
    if body is not None and body.type == "statement_block":
        for n in walk(body):
            if n.type == "return_statement" and n.named_children:
                ret = n.named_children[0]
                while ret.type == "parenthesized_expression" and ret.named_children:
                    ret = ret.named_children[0]
                return ret if ret.type == "object" else None
    return None


def endpoints(root: Node) -> list[Endpoint]:
    consts = _collect_consts(root)
    found: list[Endpoint] = []
    for call in walk(root):
        if call.type != "call_expression":
            continue
        callee = text(call.child_by_field_name("function"))
        if not callee.endswith(("createApi", "injectEndpoints")):
            continue
        args = call.child_by_field_name("arguments")
        config = args.named_children[0] if args and args.named_children else None
        if config is None or config.type != "object":
            continue
        builder = _pair(config, "endpoints")
        defs = (
            _object_of(builder)
            if builder is not None and builder.type == "arrow_function"
            else None
        )
        if defs is None:
            continue
        for pair in defs.named_children:
            if pair.type != "pair":
                continue
            name = text(pair.child_by_field_name("key")).strip("\"'")
            build = pair.child_by_field_name("value")
            if build is None or build.type != "call_expression":
                continue
            kind = text(build.child_by_field_name("function")).rsplit(".", 1)[-1]
            bargs = build.child_by_field_name("arguments")
            opts = bargs.named_children[0] if bargs and bargs.named_children else None
            query = _pair(opts, "query") if opts is not None and opts.type == "object" else None
            if kind not in ("query", "mutation") or query is None:
                continue
            body: Node | None = query
            if query.type == "arrow_function":
                body = query.child_by_field_name("body")
                while body is not None and body.type == "parenthesized_expression":
                    body = body.named_children[0] if body.named_children else None
            if body is None:
                continue
            method = "GET"
            url_node: Node | None = body
            if body.type == "object":  # ({ url, method, body })
                url_node = _pair(body, "url")
                method = (_option(body, "method", consts) or "GET").upper()
            if url_node is None:
                continue
            found.append(Endpoint(name, kind, method, _eval(url_node, consts, 0), url_node))
    return found


def hook_names(ep: Endpoint) -> list[str]:
    cap = ep.name[:1].upper() + ep.name[1:]
    if ep.kind == "query":
        return [f"use{cap}Query", f"useLazy{cap}Query"]
    return [f"use{cap}Mutation"]


def hook_calls(
    root: Node, source: bytes, file: str, language: str, eps: list[Endpoint], *, is_test: bool
) -> list[CallSite]:
    by_hook = {h: ep for ep in eps for h in hook_names(ep)}
    sites: list[CallSite] = []
    for n in walk(root):
        if n.type != "call_expression":
            continue
        fn = n.child_by_field_name("function")
        if fn is None:
            continue
        name = text(fn) if fn.type == "identifier" else text(fn.child_by_field_name("property"))
        ep = by_hook.get(name)
        if ep is None:
            continue
        sites += make_sites(
            n,
            source,
            file=file,
            language=language,
            client=f"rtk-query:{name}",
            method=ep.method,
            alternatives=ep.alternatives,
            url_node=ep.url_node,
            is_test=is_test,
            known=True,
        )
    return sites
