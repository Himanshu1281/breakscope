"""Generated API clients: recognise their files, and find calls to them by operationId.

Generators name client methods after the spec's operationId (`getUser`, `get_user`,
`UsersService.getUser`, `get_user.sync(...)`), so a call to such a name *is* a call to that
operation even though no URL appears in your code.
"""

import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from tree_sitter import Node

from breakscope.analyzers.base import PARAM, CallSite, UrlTemplate, line_of, text, walk
from breakscope.contracts.model import Contract

# Header markers used by openapi-generator, openapi-typescript-codegen, orval,
# openapi-python-client, swagger-codegen and many others.
_GENERATED = re.compile(
    rb"(auto-?generated|generated (by|using|with)|do not (edit|modify)|@generated"
    rb"|this file (is|was) (auto-?)?generated|openapi-generator|swagger-codegen)",
    re.IGNORECASE,
)
_HEADER_BYTES = 1500
# Python clients from openapi-python-client: `get_user.sync(client=..., id=1)`.
_PY_ENTRYPOINTS = frozenset({"sync", "asyncio", "sync_detailed", "asyncio_detailed"})
# operationIds too generic to match by name alone.
_TOO_GENERIC = frozenset({"get", "list", "create", "update", "delete", "search", "find", "query"})


def is_generated(source: bytes) -> bool:
    return bool(_GENERATED.search(source[:_HEADER_BYTES]))


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class OperationIndex:
    """operationId (normalized) -> (METHOD, path), for ids your generated code defines."""

    def __init__(self, contract: Contract, generated_sources: Iterable[bytes]) -> None:
        by_id: dict[str, tuple[str, str]] = {}
        for op in contract.operations.values():
            key = norm(op.operation_id or "")
            if len(key) >= 4 and key not in _TOO_GENERIC:
                by_id[key] = (op.method, op.path)
        # Only ids that some generated file actually spells out (in any naming style).
        corpus = b"\n".join(generated_sources)
        words = {norm(w.decode("ascii", "ignore")) for w in re.findall(rb"[A-Za-z_]\w+", corpus)}
        self.ops = {k: v for k, v in by_id.items() if k in words}

    def __bool__(self) -> bool:
        return bool(self.ops)

    def lookup(self, name: str) -> tuple[str, str] | None:
        return self.ops.get(norm(name))


def _callee_name(call: Node, language: str) -> tuple[str, Node] | None:
    fn = call.child_by_field_name("function")
    while fn is not None and fn.type in ("await_expression", "await", "parenthesized_expression"):
        fn = fn.named_children[0] if fn.named_children else None
    if fn is None:
        return None
    if fn.type == "identifier":
        return text(fn), fn
    if fn.type in ("member_expression", "attribute"):
        prop = fn.child_by_field_name("property" if fn.type == "member_expression" else "attribute")
        obj = fn.child_by_field_name("object")
        if language == "python" and obj is not None and text(prop) in _PY_ENTRYPOINTS:
            # get_user.sync(...) -> the module name carries the operationId.
            return text(obj).rsplit(".", 1)[-1], fn
        return text(prop), fn
    return None


def client_calls(
    root: Node, source: bytes, file: str, language: str, index: OperationIndex, *, is_test: bool
) -> list[CallSite]:
    call_type = "call" if language == "python" else "call_expression"
    sites: list[CallSite] = []
    for n in walk(root):
        if n.type != call_type:
            continue
        found = _callee_name(n, language)
        if found is None:
            continue
        name, fn = found
        op = index.lookup(name)
        if op is None:
            continue
        method, path = op
        segments = tuple(
            PARAM if s.startswith("{") else s for s in PurePosixPath(path).parts if s != "/"
        )
        sites.append(
            CallSite(
                file=file,
                line=n.start_point[0] + 1,
                column=n.start_point[1] + 1,
                language=language,
                client=f"generated:{text(fn)}",
                method=method,
                url=UrlTemplate(segments=segments, open_start=False, absolute=False),
                url_source=text(fn),
                code=line_of(source, n),
                is_test=is_test,
                start_byte=n.start_byte,
                end_byte=n.end_byte,
            )
        )
    return sites


def read_header(path: Path) -> bytes:
    try:
        with path.open("rb") as fh:
            return fh.read(_HEADER_BYTES)
    except OSError:
        return b""
