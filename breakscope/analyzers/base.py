"""Language-neutral pieces shared by the analyzers: call sites and URL templates."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from tree_sitter import Node

# A URL built from source code: literal text with holes where values are only known at
# runtime. `/users/${id}` is ("/users/", DYNAMIC).
DYNAMIC = None
UrlParts = list[str | None]

# A URL expression can evaluate to several URLs: `"/articles" + (feed ? "/feed" : "")`.
Alternatives = list[UrlParts]
MAX_ALTERNATIVES = 4

# Placeholder for a dynamic path segment, shared with the contract's path keys.
PARAM = "{}"


@dataclass(frozen=True)
class UrlTemplate:
    segments: tuple[str, ...]  # ("users", "{}")
    # The URL starts with a value we could not resolve (`${API_URL}/users`). The unknown
    # part is almost always scheme + host + base path, so matching ignores it.
    open_start: bool
    absolute: bool  # had an explicit http(s)://host
    relative: bool = False  # "users/1": no leading slash

    @property
    def path(self) -> str:
        return "/" + "/".join(self.segments)

    @property
    def has_literal(self) -> bool:
        return any(s != PARAM for s in self.segments)


@dataclass(frozen=True)
class CallSite:
    file: str  # repo-relative, forward slashes
    line: int  # 1-based
    column: int  # 1-based
    language: str
    client: str  # "fetch", "axios", "requests", "api", "self.client"
    method: str | None  # "GET"; None when the analyzer cannot tell
    url: UrlTemplate | None  # None when nothing about the URL is known statically
    url_source: str  # the URL expression as written
    code: str  # the source line, trimmed
    is_test: bool
    start_byte: int
    end_byte: int


class Analyzer(Protocol):
    language: str

    def scan(self, source: bytes, file: str, *, is_test: bool) -> list[CallSite]: ...


HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})


def build_template(parts: UrlParts) -> UrlTemplate | None:
    """Turn evaluated URL parts into path segments, dropping scheme, host and query."""
    # Join with a sentinel so we can split on "/" without losing where the holes are.
    hole = "\x00"
    text = "".join(hole if p is DYNAMIC else p for p in parts)
    for stop in ("?", "#"):
        text = text.split(stop, 1)[0]

    absolute = open_start = relative = False
    if text.lower().startswith(("http://", "https://", "//")):
        absolute = True
        rest = text.split("//", 1)[1]
        text = rest[rest.index("/") :] if "/" in rest else ""
    elif text.startswith(hole):
        open_start = True
        text = text.lstrip(hole)
    elif not text.startswith("/"):
        # "users/1" is a relative path; text without any slash is not a URL at all.
        if "/" not in text:
            return None
        relative = True

    segments = tuple(PARAM if hole in seg else seg for seg in text.split("/") if seg)
    if not segments and not absolute:
        return None
    return UrlTemplate(
        segments=segments, open_start=open_start, absolute=absolute, relative=relative
    )


def looks_like_url(t: UrlTemplate | None) -> bool:
    """For generic `x.get(...)` calls, which are often dict/Map/cache lookups: only treat
    them as HTTP when the first argument clearly looks like a URL path."""
    return t is not None and t.has_literal and not t.relative


def concat(a: Alternatives, b: Alternatives) -> Alternatives:
    return [x + y for x in a for y in b][:MAX_ALTERNATIVES]


def single(alts: Alternatives) -> str | None:
    """The literal string an expression evaluates to, if it is exactly one literal."""
    if len(alts) == 1 and all(p is not DYNAMIC for p in alts[0]):
        return "".join(p for p in alts[0] if p is not None)
    return None


def make_sites(
    node: Node,
    source: bytes,
    *,
    file: str,
    language: str,
    client: str,
    method: str | None,
    alternatives: Alternatives,
    url_node: Node,
    is_test: bool,
    known: bool,
) -> list[CallSite]:
    """One CallSite per distinct URL the call can target.

    Known clients are kept even when the URL is unresolvable (reported as unresolved).
    For generic `x.get(...)` the URL must look like one, or it is probably a Map lookup.
    """
    templates: dict[tuple[tuple[str, ...], bool], UrlTemplate] = {}
    for parts in alternatives:
        t = build_template(parts)
        if t is not None and t.has_literal and (known or looks_like_url(t)):
            templates.setdefault((t.segments, t.open_start), t)
    if not templates and not known:
        return []
    urls: list[UrlTemplate | None] = list(templates.values()) or [None]
    return [
        CallSite(
            file=file,
            line=node.start_point[0] + 1,
            column=node.start_point[1] + 1,
            language=language,
            client=client,
            method=method.upper() if method else None,
            url=url,
            url_source=text(url_node),
            code=line_of(source, node),
            is_test=is_test,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        )
        for url in urls
    ]


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def line_of(source: bytes, node: Node) -> str:
    start = source.rfind(b"\n", 0, node.start_byte) + 1
    end = source.find(b"\n", node.start_byte)
    line = source[start : end if end != -1 else len(source)].decode("utf-8", errors="replace")
    line = line.strip()
    return line if len(line) <= 120 else line[:117] + "..."
