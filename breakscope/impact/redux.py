"""Redux Toolkit: follow API data from a thunk, through the store, to `useSelector`.

const fetchUser = createAsyncThunk("users/fetch", async () => (await api.get(...)).data)
builder.addCase(fetchUser.fulfilled, (state, action) => { state.current = action.payload })
const user = useSelector((state) => state.users.current)   <- traced from here
"""

import posixpath
from dataclasses import dataclass

from tree_sitter import Node

from breakscope.analyzers.base import text, walk
from breakscope.impact.flow import Value
from breakscope.impact.flow_js import FUNCTIONS, JSFlow

_SELECTOR_HOOKS = frozenset({"useSelector", "useAppSelector", "useTypedSelector"})


@dataclass(frozen=True)
class Payload:
    """A thunk's resolved value: which operation it came from."""

    key: tuple[str, str]
    value: Value
    origin: object  # the CallSite of the HTTP call, kept opaque here


Store = dict[tuple[str, str], list[Payload]]  # (slice, field) -> what may be stored there


def _string(node: Node | None) -> str | None:
    if node is not None and node.type == "string":
        return text(node)[1:-1]
    return None


def _pair(obj: Node, key: str) -> Node | None:
    for p in obj.named_children:
        if p.type == "pair" and text(p.child_by_field_name("key")).strip("\"'") == key:
            return p.child_by_field_name("value")
    return None


def _params(fn: Node) -> list[Node]:
    single = fn.child_by_field_name("parameter")
    if single is not None:
        return [single]
    params = fn.child_by_field_name("parameters")
    out = []
    for p in params.named_children if params is not None else []:
        inner = p.child_by_field_name("pattern") if p.type.endswith("_parameter") else p
        if inner is not None:
            out.append(inner)
    return out


def _reducer_seed(reducer: Node, payload: Value) -> tuple[str | None, dict[str, Value]]:
    """`(state, action)` -> ("state", {"action.payload": v}); `(state, { payload })` too."""
    params = _params(reducer)
    if len(params) < 2:
        return None, {}
    state = text(params[0]) if params[0].type == "identifier" else None
    action = params[1]
    if action.type == "identifier":
        return state, {f"{text(action)}.payload": payload}
    seed: dict[str, Value] = {}
    if action.type == "object_pattern":
        for c in action.named_children:
            if c.type == "shorthand_property_identifier_pattern" and text(c) == "payload":
                seed["payload"] = payload
            elif c.type == "pair_pattern" and text(c.child_by_field_name("key")) == "payload":
                alias = c.child_by_field_name("value")
                if alias is not None and alias.type == "identifier":
                    seed[text(alias)] = payload
    return state, seed


def slice_writes(root: Node, source: bytes, thunks: dict[str, list[Payload]]) -> Store:
    """Store slots written with thunk results, per `createSlice({ name })`."""
    store: Store = {}
    for call in walk(root):
        if call.type != "call_expression":
            continue
        if not text(call.child_by_field_name("function")).endswith("createSlice"):
            continue
        args = call.child_by_field_name("arguments")
        config = args.named_children[0] if args and args.named_children else None
        name = _string(_pair(config, "name")) if config is not None else None
        if config is None or name is None:
            continue
        for thunk, reducer in _fulfilled_reducers(config):
            for p in thunks.get(thunk, []):
                state, seed = _reducer_seed(reducer, p.value)
                if state is None or not seed:
                    continue
                flow = JSFlow(source, None, None, component=reducer, seed=seed, store_param=state)
                flow.run()
                for field, v in flow.store_writes.items():
                    store.setdefault((name, field), []).append(Payload(p.key, v, p.origin))
    return store


def _fulfilled_reducers(config: Node) -> list[tuple[str, Node]]:
    """(thunk name, reducer fn) for `addCase(thunk.fulfilled, fn)` and `[thunk.fulfilled]: fn`."""
    out: list[tuple[str, Node]] = []
    for n in walk(config):
        if n.type == "call_expression" and text(n.child_by_field_name("function")).endswith(
            "addCase"
        ):
            args = n.child_by_field_name("arguments")
            items = args.named_children if args else []
            if len(items) >= 2 and items[1].type in FUNCTIONS:
                out += _thunk_of(items[0], items[1])
        elif n.type == "pair":
            key = n.child_by_field_name("key")
            value = n.child_by_field_name("value")
            if key is not None and key.type == "computed_property_name" and value is not None:
                inner = key.named_children[0] if key.named_children else None
                if inner is not None and value.type in FUNCTIONS:
                    out += _thunk_of(inner, value)
    return out


def _thunk_of(ref: Node, reducer: Node) -> list[tuple[str, Node]]:
    if ref.type != "member_expression":
        return []
    if text(ref.child_by_field_name("property")) != "fulfilled":
        return []
    return [(text(ref.child_by_field_name("object")).rsplit(".", 1)[-1], reducer)]


def named_selectors(root: Node) -> dict[str, Node]:
    """`const selectUser = (state) => state.users.current` -> {"selectUser": <arrow>}."""
    out: dict[str, Node] = {}
    for n in walk(root):
        if n.type == "variable_declarator":
            value = n.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function_expression"):
                out[text(n.child_by_field_name("name"))] = value
    return out


def _selected(selector: Node, store: Store) -> tuple[list[Payload], str] | None:
    """What `(state) => state.users.current.profile` returns, from the store."""
    params = _params(selector)
    body = selector.child_by_field_name("body")
    if not params or body is None or params[0].type != "identifier":
        return None
    chain: list[str] = []
    node = body
    while node.type == "member_expression":
        chain.append(text(node.child_by_field_name("property")))
        obj = node.child_by_field_name("object")
        if obj is None:
            return None
        node = obj
    if node.type != "identifier" or text(node) != text(params[0]) or len(chain) < 2:
        return None
    chain.reverse()
    payloads = _lookup(store, chain)
    if not payloads:
        return None
    return payloads, "state." + ".".join(chain)


def selector_reads(
    root: Node, store: Store, selectors: dict[str, Node]
) -> list[tuple[Node, Payload, str]]:
    """(useSelector call, what it returns, "state.users.current") for each store read."""
    out: list[tuple[Node, Payload, str]] = []
    for n in walk(root):
        if n.type != "call_expression":
            continue
        fn = n.child_by_field_name("function")
        if fn is None or text(fn) not in _SELECTOR_HOOKS:
            continue
        args = n.child_by_field_name("arguments")
        arg = args.named_children[0] if args and args.named_children else None
        if arg is not None and arg.type == "identifier":
            arg = selectors.get(text(arg))
        if arg is None or arg.type not in ("arrow_function", "function_expression"):
            continue
        selected = _selected(arg, store)
        if selected is None:
            continue
        payloads, label = selected
        out += [(n, p, label) for p in payloads]
    return out


# -- classic Redux ---------------------------------------------------------------------
#
#   onLoad: (payload) => dispatch({ type: PROFILE_LOADED, payload })        mapDispatchToProps
#   case PROFILE_LOADED: return { ...state, user: action.payload[0] }      reducer
#   combineReducers({ profile: profileReducer })                           slice names
#   const mapStateToProps = (state) => ({ ...state.profile })              props
#   render() { this.props.user.name }                                      traced from here


def dispatch_props(root: Node) -> dict[str, str]:
    """`onLoad: (payload) => dispatch({ type: T, payload })` -> {"onLoad": "T"}."""
    out: dict[str, str] = {}
    for n in walk(root):
        if n.type != "pair":
            continue
        fn = n.child_by_field_name("value")
        if fn is None or fn.type not in FUNCTIONS:
            continue
        params = _params(fn)
        body = fn.child_by_field_name("body")
        if not params or body is None or params[0].type != "identifier":
            continue
        param = text(params[0])
        for call in walk(body):
            if call.type != "call_expression":
                continue
            if text(call.child_by_field_name("function")).rsplit(".", 1)[-1] != "dispatch":
                continue
            args = call.child_by_field_name("arguments")
            action = args.named_children[0] if args and args.named_children else None
            if action is None or action.type != "object":
                continue
            kind = _pair(action, "type")
            payload = _pair(action, "payload")
            shorthand = param == "payload" and any(
                c.type == "shorthand_property_identifier" and text(c) == "payload"
                for c in action.named_children
            )
            passes_param = payload is not None and text(payload) == param
            if kind is not None and (shorthand or passes_param):
                out[text(n.child_by_field_name("key"))] = _type_name(kind)
    return out


def _type_name(node: Node) -> str:
    return text(node).strip("\"'`").rsplit(".", 1)[-1]


def reducer_files(root: Node, rel: str) -> dict[str, str]:
    """`combineReducers({ profile: profileReducer })` plus its imports ->
    {reducer module path without extension: "profile"}."""
    imports: dict[str, str] = {}
    for n in walk(root):
        if n.type != "import_statement":
            continue
        src = n.child_by_field_name("source")
        clause = next((c for c in n.named_children if c.type == "import_clause"), None)
        if src is None or clause is None:
            continue
        default = next((c for c in clause.named_children if c.type == "identifier"), None)
        if default is not None:
            imports[text(default)] = text(src).strip("\"'`")
    out: dict[str, str] = {}
    for n in walk(root):
        if n.type != "call_expression":
            continue
        if not text(n.child_by_field_name("function")).endswith("combineReducers"):
            continue
        args = n.child_by_field_name("arguments")
        obj = args.named_children[0] if args and args.named_children else None
        if obj is None or obj.type != "object":
            continue
        for c in obj.named_children:
            if c.type == "shorthand_property_identifier":
                key, ident = text(c), text(c)
            elif c.type == "pair":
                key = text(c.child_by_field_name("key")).strip("\"'")
                ident = text(c.child_by_field_name("value"))
            else:
                continue
            module = imports.get(ident)
            if module and module.startswith("."):
                base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), module))
                out[base] = key
    return out


def slice_for(rel: str, reducer_map: dict[str, str]) -> str | None:
    stem = rel.rsplit(".", 1)[0]
    return reducer_map.get(stem) or reducer_map.get(stem.removesuffix("/index"))


def switch_reducer_writes(
    root: Node, source: bytes, slice_name: str, actions: dict[str, list[Payload]]
) -> Store:
    """Slots written by `switch (action.type) { case T: return {...} }` reducers."""
    store: Store = {}
    for sw in walk(root):
        if sw.type != "switch_statement":
            continue
        fn = sw.parent
        while fn is not None and fn.type not in FUNCTIONS:
            fn = fn.parent
        body = sw.child_by_field_name("body")
        if fn is None or body is None:
            continue
        for case in body.named_children:
            value = case.child_by_field_name("value")
            if case.type != "switch_case" or value is None:
                continue
            for p in actions.get(_type_name(value), []):
                state, seed = _reducer_seed(fn, p.value)
                if not seed:
                    continue
                flow = JSFlow(source, None, None, component=fn, seed=seed, store_param=state)
                flow.run()
                for ret in walk(case):
                    if ret.type != "return_statement" or not ret.named_children:
                        continue
                    for field, v in _returned_fields(flow, ret.named_children[0]).items():
                        slot = store.setdefault((slice_name, field), [])
                        slot.append(Payload(p.key, v, p.origin))
    return store


def _returned_fields(flow: JSFlow, expr: Node) -> dict[str, Value]:
    """`{ ...state, user: x }` -> {"user": x}; `{ ...x }` or `x` -> {"": x} (whole slice)."""
    while expr.type == "parenthesized_expression" and expr.named_children:
        expr = expr.named_children[0]
    if expr.type != "object":
        v = flow.value(expr)
        return {"": v} if v is not None else {}
    out: dict[str, Value] = {}
    for c in expr.named_children:
        if c.type == "pair":
            v = flow.value(c.child_by_field_name("value"))
            if v is not None:
                out[text(c.child_by_field_name("key")).strip("\"'")] = v
        elif c.type == "spread_element" and c.named_children:
            v = flow.value(c.named_children[0])
            if v is not None:
                out[""] = v
    return out


def _lookup(store: Store, chain: list[str]) -> list[Payload]:
    """state.<slice>.<field>.<rest> -> payloads, from a field slot or the slice root."""
    if not chain:
        return []
    candidates: list[tuple[str, list[str]]] = []
    if len(chain) > 1:
        candidates.append((chain[1], chain[2:]))
    candidates.append(("", chain[1:]))
    for field, rest in candidates:
        found = store.get((chain[0], field))
        if not found:
            continue
        out = []
        for p in found:
            v: Value | None = p.value
            for prop in rest:
                v = v.member(prop) if v is not None else None
            if v is not None:
                out.append(Payload(p.key, v, p.origin))
        return out
    return []


def connected_props(root: Node, store: Store) -> dict[str, list[Payload]]:
    """Props that `mapStateToProps` fills from the store, by prop name."""
    from breakscope.analyzers.rtk import _object_of

    out: dict[str, list[Payload]] = {}
    for n in walk(root):
        if n.type != "variable_declarator":
            continue
        if text(n.child_by_field_name("name")) != "mapStateToProps":
            continue
        fn = n.child_by_field_name("value")
        if fn is None or fn.type not in FUNCTIONS:
            continue
        params = _params(fn)
        obj = _object_of(fn)
        if not params or obj is None:
            continue
        state = text(params[0])
        for c in obj.named_children:
            if c.type == "pair":
                chain = _chain(c.child_by_field_name("value"), state)
                if chain:
                    key = text(c.child_by_field_name("key"))
                    out.setdefault(key, []).extend(_lookup(store, chain))
            elif c.type == "spread_element" and c.named_children:
                chain = _chain(c.named_children[0], state)
                if chain and len(chain) == 1:
                    for (sl, field), payloads in store.items():
                        if sl == chain[0] and field:
                            out.setdefault(field, []).extend(payloads)
    return {k: v for k, v in out.items() if v}


def _chain(node: Node | None, root_name: str) -> list[str] | None:
    chain: list[str] = []
    while node is not None and node.type == "member_expression":
        chain.append(text(node.child_by_field_name("property")))
        node = node.child_by_field_name("object")
    if node is None or node.type != "identifier" or text(node) != root_name or not chain:
        return None
    chain.reverse()
    return chain


def components(root: Node) -> list[Node]:
    """Class components and capitalized function components in a file."""
    out: list[Node] = []
    for n in walk(root):
        if n.type == "class_declaration":
            out.append(n)
        elif n.type == "function_declaration":
            if text(n.child_by_field_name("name"))[:1].isupper():
                out.append(n)
        elif n.type in ("arrow_function", "function_expression"):
            decl = n.parent
            if (
                decl is not None
                and decl.type == "variable_declarator"
                and text(decl.child_by_field_name("name"))[:1].isupper()
            ):
                out.append(n)
    return out
