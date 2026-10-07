"""Redux Toolkit: follow API data from a thunk, through the store, to `useSelector`.

const fetchUser = createAsyncThunk("users/fetch", async () => (await api.get(...)).data)
builder.addCase(fetchUser.fulfilled, (state, action) => { state.current = action.payload })
const user = useSelector((state) => state.users.current)   <- traced from here
"""

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
    found = store.get((chain[0], chain[1]))
    if not found:
        return None
    rest = chain[2:]
    payloads = []
    for p in found:
        v: Value | None = p.value
        for prop in rest:
            v = v.member(prop) if v is not None else None
        if v is not None:
            payloads.append(Payload(p.key, v, p.origin))
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
