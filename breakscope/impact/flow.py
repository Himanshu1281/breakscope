"""Language-neutral pieces of response data-flow tracing."""

from dataclasses import dataclass, field
from typing import Literal

from tree_sitter import Node

# response: an HTTP response object; the body is behind `.data` (axios) or `.json()`.
# either:   a custom client's result; it may be the body itself or a response wrapper.
# body:     the parsed response body; `path` is the position inside it.
Kind = Literal["response", "either", "body"]
ELEMENT = "[]"


@dataclass(frozen=True)
class Value:
    kind: Kind
    path: tuple[str, ...] = ()

    def member(self, name: str) -> "Value | None":
        if self.kind == "response":
            return BODY if name == "data" else None
        if self.kind == "either":
            return BODY if name == "data" else Value("body", (name,))
        return Value("body", (*self.path, name))

    def element(self) -> "Value":
        base = () if self.kind != "body" else self.path
        return Value("body", (*base, ELEMENT))

    def parsed(self) -> "Value | None":
        """`.json()`: response -> body."""
        return BODY if self.kind in ("response", "either") else None


BODY = Value("body")


@dataclass(frozen=True)
class Access:
    """A read of `path` inside a response body."""

    path: tuple[str, ...]
    line: int
    column: int
    code: str
    caret: tuple[int, int] | None = None  # (offset in code, width) of the field name


@dataclass
class FlowResult:
    accesses: list[Access]
    # What the enclosing function returns, when it returns (part of) the response.
    returns: Value | None
    function_name: str | None
    # The class of a method, so `this.userService.get()` can be tied to UserService.get.
    class_name: str | None = None
    # Props passed to child components: (Component, {prop: value}).
    props: list[tuple[str, dict[str, Value]]] = field(default_factory=list)


def line_text(source: bytes, node: Node) -> str:
    start = source.rfind(b"\n", 0, node.start_byte) + 1
    end = source.find(b"\n", node.start_byte)
    line = source[start : end if end != -1 else len(source)].decode("utf-8", errors="replace")
    line = line.strip()
    return line if len(line) <= 120 else line[:117] + "..."


def code_and_caret(source: bytes, node: Node) -> tuple[str, tuple[int, int] | None]:
    """The trimmed source line of `node`, and where `node` sits within it."""
    start = source.rfind(b"\n", 0, node.start_byte) + 1
    end = source.find(b"\n", node.start_byte)
    raw = source[start : end if end != -1 else len(source)].decode("utf-8", errors="replace")
    stripped = raw.lstrip()
    code = stripped.rstrip()
    prefix = source[start : node.start_byte].decode("utf-8", errors="replace")
    offset = len(prefix) - (len(raw) - len(stripped))
    node_text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    width = len(node_text)
    if len(code) > 120:
        code = code[:117] + "..."
    if offset < 0 or "\n" in node_text or offset + width > len(code):
        return code, None
    return code, (offset, width)


def node_at(root: Node, start: int, end: int) -> Node | None:
    n = root.descendant_for_byte_range(start, end)
    while n is not None and (n.start_byte, n.end_byte) != (start, end):
        n = n.parent
    return n


def outermost_function(node: Node, function_types: frozenset[str], stop: frozenset[str]) -> Node:
    """The outermost enclosing function, not crossing a class body. React components keep
    state and effects together, so tracing must see the whole component, not just the
    callback that made the request."""
    best: Node | None = None
    n = node.parent
    while n is not None:
        if n.type in function_types:
            best = n
        elif n.type in stop and best is not None:
            break
        n = n.parent
    if best is not None:
        return best
    root = node
    while root.parent is not None:
        root = root.parent
    return root
