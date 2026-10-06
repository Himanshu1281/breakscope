"""Trace a response value through JavaScript/TypeScript code within one function."""

from tree_sitter import Node

from breakscope.analyzers.base import text, walk
from breakscope.impact.flow import (
    ELEMENT,
    Access,
    FlowResult,
    Value,
    code_and_caret,
    outermost_function,
)

FUNCTIONS = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function_declaration",
        "function",
    }
)
_CLASS = frozenset({"class_body"})
_WRAPPERS = frozenset(
    {
        "await_expression",
        "parenthesized_expression",
        "as_expression",
        "non_null_expression",
        "satisfies_expression",
    }
)
# Array/Promise/Object members that are not response fields.
_NOT_FIELDS = frozenset(
    {
        "length",
        "map",
        "filter",
        "forEach",
        "find",
        "findIndex",
        "findLast",
        "some",
        "every",
        "reduce",
        "flatMap",
        "flat",
        "slice",
        "sort",
        "toSorted",
        "reverse",
        "concat",
        "includes",
        "indexOf",
        "join",
        "at",
        "push",
        "pop",
        "shift",
        "then",
        "catch",
        "finally",
        "pipe",
        "subscribe",
        "toString",
        "valueOf",
        "json",
        "keys",
        "values",
        "entries",
    }
)
_SAME_ARRAY = frozenset({"filter", "slice", "sort", "toSorted", "reverse", "concat"})
_ONE_ELEMENT = frozenset({"find", "findLast", "at", "pop", "shift"})
_ELEMENT_CALLBACK = frozenset(
    {
        "map",
        "forEach",
        "filter",
        "find",
        "findIndex",
        "findLast",
        "some",
        "every",
        "flatMap",
    }
)
_RX_MAP = frozenset({"map", "switchMap", "mergeMap", "concatMap", "exhaustMap"})
_PASSES = 4


class JSFlow:
    """Trace from an HTTP call (`call`, evaluating to `initial`), or from a component
    function whose props are already known (`component` + `props`)."""

    def __init__(
        self,
        source: bytes,
        call: Node | None,
        initial: Value | None,
        *,
        component: Node | None = None,
        props: dict[str, Value] | None = None,
    ) -> None:
        self.source = source
        self.call = call
        self.initial = initial
        if component is not None:
            self.scope = component
        else:
            assert call is not None
            self.scope = outermost_function(call, FUNCTIONS, _CLASS)
        self.env: dict[str, Value] = {}
        self.setters: dict[str, str] = {}  # setUser -> user (React useState)
        self.accesses: dict[tuple[int, int, tuple[str, ...]], Access] = {}
        # Props this code passes to child components: (Component, {prop: value}).
        self.props_out: list[tuple[str, dict[str, Value]]] = []
        if component is not None and props:
            self._seed_props(component, props)

    def run(self) -> FlowResult:
        nodes = list(walk(self.scope))
        self._fixpoint(nodes)
        for n in nodes:
            self._record(n)

        # Fields stored on `this` are read by other methods of the same class.
        fields = {k: v for k, v in self.env.items() if k.startswith("this.")}
        body = _enclosing(self.scope, "class_body")
        if fields and body is not None:
            inside = (self.scope.start_byte, self.scope.end_byte)
            rest = [
                n for n in walk(body) if not (inside[0] <= n.start_byte and n.end_byte <= inside[1])
            ]
            self.env = dict(fields)  # locals of other methods are unrelated
            self._fixpoint(rest)
            for n in rest:
                self._record(n)

        return FlowResult(
            accesses=list(self.accesses.values()),
            returns=self._returns(),
            function_name=_function_name(self.scope),
            class_name=_class_name(self.scope),
            props=self.props_out,
        )

    def _fixpoint(self, nodes: list[Node]) -> None:
        for _ in range(_PASSES):
            before = dict(self.env)
            for n in nodes:
                self._bind(n)
            if self.env == before:
                break

    def _seed_props(self, component: Node, props: dict[str, Value]) -> None:
        params = component.child_by_field_name("parameters")
        first = component.child_by_field_name("parameter")
        if first is None and params is not None and params.named_children:
            first = params.named_children[0]
        if first is not None and first.type in ("required_parameter", "optional_parameter"):
            first = first.child_by_field_name("pattern")
        if first is None:
            return
        if first.type == "identifier":  # props.user
            for name, v in props.items():
                self.env[f"{text(first)}.{name}"] = v
        elif first.type == "object_pattern":  # ({ user })
            for c in first.named_children:
                key = (
                    c
                    if c.type == "shorthand_property_identifier_pattern"
                    else (c.child_by_field_name("key") if c.type == "pair_pattern" else None)
                )
                if key is None or text(key) not in props:
                    continue
                if c.type == "pair_pattern":
                    self._bind_pattern(c.child_by_field_name("value") or key, props[text(key)])
                else:
                    self.env[text(key)] = props[text(key)]

    # -- evaluation -----------------------------------------------------------------

    def value(self, node: Node | None, depth: int = 0) -> Value | None:
        if node is None or depth > 40:
            return None
        if (
            self.call is not None
            and node.start_byte == self.call.start_byte
            and node.end_byte == self.call.end_byte
        ):
            return self.initial
        t = node.type
        if t in _WRAPPERS:
            return self.value(node.named_children[0], depth + 1) if node.named_children else None
        if t == "identifier":
            return self.env.get(text(node))
        if t == "member_expression":
            prop = text(node.child_by_field_name("property"))
            obj_node = node.child_by_field_name("object")
            # `this.user` and `props.user` are tracked as named slots.
            if obj_node is not None and obj_node.type in ("this", "identifier"):
                slot = self.env.get(f"{text(obj_node)}.{prop}")
                if slot is not None:
                    return slot
            v = self.value(obj_node, depth + 1)
            if v is None or prop in _NOT_FIELDS:
                return None
            return v.member(prop)
        if t == "subscript_expression":
            v = self.value(node.child_by_field_name("object"), depth + 1)
            idx = node.child_by_field_name("index")
            if v is None or idx is None:
                return None
            if idx.type == "string":
                return v.member(text(idx)[1:-1])
            if idx.type == "number":
                return v.element()
            return None
        if t == "call_expression":
            return self._call_value(node, depth)
        if t in ("ternary_expression",):
            return self.value(node.child_by_field_name("consequence"), depth + 1) or self.value(
                node.child_by_field_name("alternative"), depth + 1
            )
        if t == "binary_expression" and text(node.child_by_field_name("operator")) in (
            "??",
            "||",
            "&&",
        ):
            return self.value(node.child_by_field_name("left"), depth + 1) or self.value(
                node.child_by_field_name("right"), depth + 1
            )
        return None

    def _call_value(self, node: Node, depth: int) -> Value | None:
        fn = _callee(node)
        if fn is None or fn.type != "member_expression":
            return None
        method = text(fn.child_by_field_name("property"))
        obj = self.value(fn.child_by_field_name("object"), depth + 1)
        if obj is None:
            return None
        args = _args(node)
        if method == "json":
            return obj.parsed()
        if method == "then" and args:
            return self._callback_result(args[0], obj, depth)
        if method in _SAME_ARRAY:
            return obj
        if method in _ONE_ELEMENT:
            return obj.element()
        if method == "pipe":
            cur: Value | None = obj
            for op in args:
                if cur is None:
                    break
                if op.type == "call_expression" and text(_callee(op)) in _RX_MAP and _args(op):
                    cur = self._callback_result(_args(op)[0], cur, depth)
            return cur
        return None

    def _callback_result(self, cb: Node, param: Value, depth: int) -> Value | None:
        if cb.type not in FUNCTIONS:
            return None
        self._bind_params(cb, param)
        body = cb.child_by_field_name("body")
        if body is None:
            return None
        if body.type != "statement_block":
            return self.value(body, depth + 1)
        for n in walk(body):
            if n.type == "return_statement" and _own_function(n) == cb and n.named_children:
                return self.value(n.named_children[0], depth + 1)
        return None

    # -- bindings -------------------------------------------------------------------

    def _bind(self, n: Node) -> None:
        t = n.type
        if t == "variable_declarator":
            name, value = n.child_by_field_name("name"), n.child_by_field_name("value")
            if name is None or value is None:
                return
            if name.type == "array_pattern" and text(_callee(value)).endswith("useState"):
                items = [c for c in name.named_children if c.type == "identifier"]
                if len(items) == 2:
                    self.setters[text(items[1])] = text(items[0])
                return
            self._bind_pattern(name, self.value(value))
        elif t == "assignment_expression":
            left = n.child_by_field_name("left")
            v = self.value(n.child_by_field_name("right"))
            if left is None or v is None:
                return
            if left.type == "identifier":
                self.env[text(left)] = v
            elif left.type == "member_expression":
                obj = left.child_by_field_name("object")
                if obj is not None and obj.type == "this":
                    self.env[f"this.{text(left.child_by_field_name('property'))}"] = v
        elif t in ("jsx_self_closing_element", "jsx_opening_element"):
            self._jsx_props(n)
        elif t == "for_in_statement":
            if "of" not in [text(c) for c in n.children if not c.is_named]:
                return
            v = self.value(n.child_by_field_name("right"))
            left = n.child_by_field_name("left")
            if v is not None and left is not None:
                self._bind_pattern(left, v.element())
        elif t == "call_expression":
            self._bind_call(n)

    def _jsx_props(self, n: Node) -> None:
        name = n.child_by_field_name("name")
        component = text(name)
        if name is None or not component[:1].isupper():
            return  # <div>, <span>: DOM elements, not components
        props: dict[str, Value] = {}
        for attr in n.named_children:
            if attr.type != "jsx_attribute" or len(attr.named_children) < 2:
                continue
            key, value = attr.named_children[0], attr.named_children[1]
            if value.type == "jsx_expression" and value.named_children:
                v = self.value(value.named_children[0])
                if v is not None and v.kind == "body":
                    props[text(key)] = v
        if props and (component, props) not in self.props_out:
            self.props_out.append((component, props))

    def _bind_call(self, n: Node) -> None:
        fn = _callee(n)
        args = _args(n)
        if fn is None or not args:
            return
        if fn.type == "identifier" and text(fn) in self.setters:
            v = self.value(args[0])
            if v is not None:
                self.env[self.setters[text(fn)]] = v
            return
        if fn.type != "member_expression":
            return
        method = text(fn.child_by_field_name("property"))
        obj = self.value(fn.child_by_field_name("object"))
        if obj is None:
            return
        if method in _ELEMENT_CALLBACK:
            self._bind_params(args[0], obj.element())
        elif method in ("reduce", "reduceRight"):
            self._bind_params(args[0], obj.element(), position=1)  # (acc, item) => ...
        elif method in ("then", "subscribe"):
            cb = args[0]
            if cb.type == "object":  # subscribe({ next: (x) => ... })
                cb = _pair_value(cb, "next") or cb
            self._bind_params(cb, obj)
        elif method == "pipe":
            self._call_value(n, 0)
            cur = obj
            for op in args:
                callee = text(_callee(op)) if op.type == "call_expression" else ""
                if callee == "tap" and _args(op):
                    self._bind_params(_args(op)[0], cur)
                elif callee in _RX_MAP and _args(op):
                    nxt = self._callback_result(_args(op)[0], cur, 0)
                    if nxt is None:
                        break
                    cur = nxt

    def _bind_params(self, fn: Node, v: Value | None, position: int = 0) -> None:
        if v is None or fn.type not in FUNCTIONS:
            return
        single = fn.child_by_field_name("parameter")
        if single is not None:
            if position == 0:
                self._bind_pattern(single, v)
            return
        params = fn.child_by_field_name("parameters")
        if params is not None and len(params.named_children) > position:
            self._bind_pattern(params.named_children[position], v)

    def _bind_pattern(self, pat: Node, v: Value | None) -> None:
        if v is None:
            return
        t = pat.type
        if t == "identifier":
            self.env[text(pat)] = v
        elif t in ("required_parameter", "optional_parameter"):
            inner = pat.child_by_field_name("pattern")
            if inner is not None:
                self._bind_pattern(inner, v)
        elif t == "assignment_pattern":
            left = pat.child_by_field_name("left")
            if left is not None:
                self._bind_pattern(left, v)
        elif t == "object_pattern":
            for c in pat.named_children:
                if c.type == "shorthand_property_identifier_pattern":
                    m = v.member(text(c))
                    self._note(c, m)
                    if m is not None:
                        self.env[text(c)] = m
                elif c.type == "pair_pattern":
                    key, value = c.child_by_field_name("key"), c.child_by_field_name("value")
                    if key is not None and value is not None:
                        m = v.member(text(key).strip("\"'"))
                        self._note(key, m)
                        self._bind_pattern(value, m)
                elif c.type == "object_assignment_pattern":
                    left = c.child_by_field_name("left")
                    if left is not None and left.type == "shorthand_property_identifier_pattern":
                        m = v.member(text(left))
                        self._note(left, m)
                        if m is not None:
                            self.env[text(left)] = m
        elif t == "array_pattern":
            for c in pat.named_children:
                self._bind_pattern(c, v.element())

    # -- accesses -------------------------------------------------------------------

    def _record(self, n: Node) -> None:
        if n.type not in ("member_expression", "subscript_expression"):
            return
        parent = n.parent
        if parent is not None and parent.type == "call_expression" and _callee(parent) == n:
            return  # a method call such as data.map(...) is not a field read
        self._note(
            n,
            self.value(n),
            anchor=n.child_by_field_name("property" if n.type == "member_expression" else "index"),
        )

    def _note(self, node: Node, v: Value | None, anchor: Node | None = None) -> None:
        if v is None or v.kind != "body" or not v.path or v.path[-1] == ELEMENT:
            return
        a = anchor or node
        key = (a.start_point[0], a.start_point[1], v.path)
        code, caret = code_and_caret(self.source, a)
        self.accesses.setdefault(
            key,
            Access(
                path=v.path,
                line=a.start_point[0] + 1,
                column=a.start_point[1] + 1,
                code=code,
                caret=caret,
            ),
        )

    def _returns(self) -> Value | None:
        scope = self.scope
        if scope.type not in FUNCTIONS:
            return None
        body = scope.child_by_field_name("body")
        if body is not None and body.type != "statement_block":
            return self.value(body)
        for n in walk(scope):
            if n.type == "return_statement" and _own_function(n) == scope and n.named_children:
                v = self.value(n.named_children[0])
                if v is not None:
                    return v
        return None


def _callee(call: Node | None) -> Node | None:
    if call is None or call.type != "call_expression":
        return None
    fn = call.child_by_field_name("function")
    while fn is not None and fn.type in ("await_expression", "parenthesized_expression"):
        fn = fn.named_children[0] if fn.named_children else None
    return fn


def _args(call: Node) -> list[Node]:
    a = call.child_by_field_name("arguments")
    return [c for c in a.named_children if c.type != "comment"] if a else []


def _pair_value(obj: Node, key: str) -> Node | None:
    for p in obj.named_children:
        if p.type == "pair" and text(p.child_by_field_name("key")).strip("\"'") == key:
            return p.child_by_field_name("value")
    return None


def _own_function(n: Node) -> Node | None:
    p = n.parent
    while p is not None and p.type not in FUNCTIONS:
        p = p.parent
    return p


def _function_name(fn: Node) -> str | None:
    if fn.type in ("function_declaration", "generator_function_declaration", "method_definition"):
        return text(fn.child_by_field_name("name")) or None
    parent = fn.parent
    if parent is not None and parent.type == "variable_declarator":
        return text(parent.child_by_field_name("name")) or None
    if parent is not None and parent.type == "pair":
        return text(parent.child_by_field_name("key")) or None
    return None


def _enclosing(n: Node, node_type: str) -> Node | None:
    p = n.parent
    while p is not None and p.type != node_type:
        p = p.parent
    return p


def _class_name(fn: Node) -> str | None:
    body = fn.parent
    if fn.type != "method_definition" or body is None or body.type != "class_body":
        return None
    cls = body.parent
    return text(cls.child_by_field_name("name")) or None if cls is not None else None
