"""Trace a response value through Python code within one function."""

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

FUNCTIONS = frozenset({"function_definition", "lambda"})
_CLASS = frozenset({"class_definition"})
# Attributes of dicts, lists and response objects that are not response fields.
_NOT_FIELDS = frozenset(
    {
        "json",
        "get",
        "items",
        "keys",
        "values",
        "copy",
        "pop",
        "update",
        "setdefault",
        "append",
        "extend",
        "index",
        "count",
        "sort",
        "status_code",
        "status",
        "text",
        "content",
        "headers",
        "ok",
        "raise_for_status",
        "url",
        "reason",
        "elapsed",
        "cookies",
        "encoding",
        "request",
        "is_success",
        "is_error",
        "read",
        "close",
    }
)
_PASSES = 4


class PyFlow:
    def __init__(self, source: bytes, call: Node, initial: Value) -> None:
        self.source = source
        self.call = call
        self.initial = initial
        self.scope = outermost_function(call, frozenset({"function_definition"}), _CLASS)
        self.env: dict[str, Value] = {}
        self.accesses: dict[tuple[int, int, tuple[str, ...]], Access] = {}

    def run(self) -> FlowResult:
        nodes = list(walk(self.scope))
        self._fixpoint(nodes)
        for n in nodes:
            self._record(n)

        # Attributes stored on `self` are read by other methods of the same class.
        fields = {k: v for k, v in self.env.items() if k.startswith("self.")}
        cls = self._class()
        if fields and cls is not None:
            inside = (self.scope.start_byte, self.scope.end_byte)
            rest = [
                n for n in walk(cls) if not (inside[0] <= n.start_byte and n.end_byte <= inside[1])
            ]
            self.env = dict(fields)  # locals of other methods are unrelated
            self._fixpoint(rest)
            for n in rest:
                self._record(n)

        name = self.scope.child_by_field_name("name") if self.scope.type in FUNCTIONS else None
        cls_name = cls.child_by_field_name("name") if cls is not None else None
        return FlowResult(
            accesses=list(self.accesses.values()),
            returns=self._returns(),
            function_name=text(name) or None,
            class_name=text(cls_name) or None,
        )

    def _fixpoint(self, nodes: list[Node]) -> None:
        for _ in range(_PASSES):
            before = dict(self.env)
            for n in nodes:
                self._bind(n)
            if self.env == before:
                break

    def _class(self) -> Node | None:
        """The class whose method is being traced, if any."""
        if self.scope.type != "function_definition":
            return None
        p = self.scope.parent
        while p is not None and p.type in ("block", "decorated_definition"):
            p = p.parent
        return p if p is not None and p.type == "class_definition" else None

    def value(self, node: Node | None, depth: int = 0) -> Value | None:
        if node is None or depth > 40:
            return None
        if node.start_byte == self.call.start_byte and node.end_byte == self.call.end_byte:
            return self.initial
        t = node.type
        if t in ("await", "parenthesized_expression") and node.named_children:
            return self.value(node.named_children[0], depth + 1)
        if t == "identifier":
            return self.env.get(text(node))
        if t == "subscript":
            v = self.value(node.child_by_field_name("value"), depth + 1)
            key = node.child_by_field_name("subscript")
            if v is None or key is None:
                return None
            if key.type == "string":
                return v.member(_string(key))
            if key.type in ("integer", "unary_operator"):
                return v.element()
            return None
        if t == "attribute":
            obj_node = node.child_by_field_name("object")
            attr = text(node.child_by_field_name("attribute"))
            if obj_node is not None and text(obj_node) == "self":
                return self.env.get(f"self.{attr}")
            v = self.value(obj_node, depth + 1)
            if v is None or attr in _NOT_FIELDS:
                return None
            if v.kind == "response":
                return None  # resp.status_code and friends; the body is behind .json()
            return v.member(attr)
        if t == "call":
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                return None
            obj = self.value(fn.child_by_field_name("object"), depth + 1)
            method = text(fn.child_by_field_name("attribute"))
            if obj is None:
                return None
            if method == "json":
                return obj.parsed()
            if method == "get":
                key = _first_arg(node)
                if key is not None and key.type == "string" and obj.kind == "body":
                    return obj.member(_string(key))
            return None
        if t == "boolean_operator":
            return self.value(node.child_by_field_name("left"), depth + 1) or self.value(
                node.child_by_field_name("right"), depth + 1
            )
        return None

    def _bind(self, n: Node) -> None:
        t = n.type
        if t == "assignment":
            left = n.child_by_field_name("left")
            v = self.value(n.child_by_field_name("right"))
            if left is None or v is None:
                return
            if left.type == "identifier":
                self.env[text(left)] = v
            elif left.type == "attribute" and text(left.child_by_field_name("object")) == "self":
                self.env[f"self.{text(left.child_by_field_name('attribute'))}"] = v
        elif t in ("for_statement", "for_in_clause"):
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            v = self.value(right)
            if v is not None and left is not None and left.type == "identifier":
                self.env[text(left)] = v.element()
        elif t == "as_pattern":  # async with session.get(url) as resp:
            alias = n.child_by_field_name("alias")
            v = self.value(n.named_children[0]) if n.named_children else None
            target = (
                alias.named_children[0] if alias is not None and alias.named_children else alias
            )
            if v is not None and target is not None and target.type == "identifier":
                self.env[text(target)] = v

    def _record(self, n: Node) -> None:
        if n.type == "subscript":
            anchor = n.child_by_field_name("subscript")
        elif n.type == "attribute":
            parent = n.parent
            if (
                parent is not None
                and parent.type == "call"
                and parent.child_by_field_name("function") == n
            ):
                return  # data.items() etc.
            anchor = n.child_by_field_name("attribute")
        elif n.type == "call":
            fn = n.child_by_field_name("function")
            if (
                fn is None
                or fn.type != "attribute"
                or text(fn.child_by_field_name("attribute")) != "get"
            ):
                return
            anchor = _first_arg(n)
        else:
            return
        v = self.value(n)
        if v is None or v.kind != "body" or not v.path or v.path[-1] == ELEMENT or anchor is None:
            return
        key = (anchor.start_point[0], anchor.start_point[1], v.path)
        code, caret = code_and_caret(self.source, anchor)
        self.accesses.setdefault(
            key,
            Access(
                path=v.path,
                line=anchor.start_point[0] + 1,
                column=anchor.start_point[1] + 1,
                code=code,
                caret=caret,
            ),
        )

    def _returns(self) -> Value | None:
        if self.scope.type != "function_definition":
            return None
        for n in walk(self.scope):
            if n.type != "return_statement" or not n.named_children:
                continue
            owner = n.parent
            while owner is not None and owner.type not in FUNCTIONS:
                owner = owner.parent
            if owner == self.scope:
                v = self.value(n.named_children[0])
                if v is not None:
                    return v
        return None


def _first_arg(call: Node) -> Node | None:
    a = call.child_by_field_name("arguments")
    args = [c for c in a.named_children if c.type != "comment"] if a else []
    return args[0] if args else None


def _string(node: Node) -> str:
    return "".join(text(c) for c in node.named_children if c.type == "string_content")
