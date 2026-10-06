"""Join contract changes, call sites and response data flow into impacts."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tree_sitter import Node, Parser

from breakscope.analyzers import is_test_file, iter_source_files, scan_repo
from breakscope.analyzers.base import CallSite, text, walk
from breakscope.analyzers.javascript import _LANGS as _JS_LANGS
from breakscope.analyzers.python import _LANG as _PY_LANG
from breakscope.changes import APIChange, Direction, Severity
from breakscope.contracts.diff import diff_contracts
from breakscope.contracts.model import Contract, OperationKey
from breakscope.contracts.normalize import operation_key
from breakscope.impact.flow import (
    Access,
    FlowResult,
    Value,
    code_and_caret,
    line_text,
    node_at,
)
from breakscope.impact.flow_js import JSFlow
from breakscope.impact.flow_py import PyFlow
from breakscope.impact.models import Confidence, Impact, ImpactReport
from breakscope.usages import Usage, index_usages

_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
}
_RESPONSE_CLIENTS_JS = frozenset({"fetch", "axios", "ky", "got"})
_BODY_CLIENTS_JS = frozenset({"http", "httpClient", "HttpClient"})  # Angular HttpClient
_RESPONSE_CLIENTS_PY = frozenset({"requests", "httpx", "session", "urllib", "aiohttp"})
# Too generic to follow across files by name.
_GENERIC_NAMES = frozenset(
    {
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "del",
        "head",
        "options",
        "request",
        "fetch",
        "then",
        "json",
        "call",
        "send",
        "run",
        "handler",
        "default",
        "load",
        "main",
    }
)


@dataclass(frozen=True)
class _Trace:
    key: OperationKey
    site: CallSite
    confidence: Confidence
    accesses: list[Access]
    via: str  # "" for direct flow, or "via getUser()" for a one-hop return


@dataclass(frozen=True)
class _Return:
    """A function that returns (part of) a response: callers continue the trace."""

    key: OperationKey
    value: Value
    origin: CallSite
    class_name: str | None
    needs_receiver: bool  # generic name: only follow `x.userService.get()` for UserService


class _Sources:
    """Parsed files, cached: every phase needs the same trees."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._parsers = {
            "python": Parser(_PY_LANG),
            **{name: Parser(lang) for name, lang in _JS_LANGS.items()},
        }
        self._cache: dict[str, tuple[bytes, Node, str] | None] = {}

    def get(self, rel: str) -> tuple[bytes, Node, str] | None:
        if rel not in self._cache:
            path = self.root / rel
            lang = _LANGUAGE_BY_EXT.get(path.suffix)
            try:
                source = path.read_bytes() if lang else None
            except OSError:
                source = None
            if source is None or lang is None:
                self._cache[rel] = None
            else:
                tree = self._parsers[lang].parse(source)
                self._cache[rel] = (source, tree.root_node, lang)
        return self._cache[rel]


def initial_value(site: CallSite) -> Value:
    last = site.client.rsplit(".", 1)[-1]
    if site.language == "python":
        is_response = last in _RESPONSE_CLIENTS_PY or last.endswith("session")
        return Value("response") if is_response else Value("either")
    if last in _RESPONSE_CLIENTS_JS:
        return Value("response")
    if last in _BODY_CLIENTS_JS:
        return Value("body")
    return Value("either")


def _flow(source: bytes, node: Node, language: str, initial: Value) -> FlowResult:
    if language == "python":
        return PyFlow(source, node, initial).run()
    return JSFlow(source, node, initial).run()


def _base_confidence(u: Usage) -> Confidence:
    return Confidence.HIGH if u.match == "exact" and not u.ambiguous else Confidence.MEDIUM


def analyze(
    old: Contract,
    new: Contract,
    repo: Path,
    *,
    base_paths: Iterable[str] = (),
    exclude: tuple[str, ...] = (),
    min_severity: Severity = Severity.WARNING,
) -> ImpactReport:
    changes = [c for c in diff_contracts(old, new) if c.severity.rank <= min_severity.rank]
    scan = scan_repo(repo, exclude)
    # Code is written against the old contract, so match call sites to it.
    index = index_usages(old, scan.sites, base_paths)
    sources = _Sources(repo)
    report = ImpactReport(
        changes=changes, files_scanned=scan.files_scanned, call_sites=len(scan.sites)
    )

    traces: dict[OperationKey, list[_Trace]] = defaultdict(list)
    returns: dict[str, list[_Return]] = defaultdict(list)
    props: list[tuple[OperationKey, CallSite, str, dict[str, Value]]] = []

    def keep(key: OperationKey, site: CallSite, conf: Confidence, r: FlowResult, via: str) -> None:
        traces[key].append(_Trace(key, site, conf, r.accesses, via))
        props.extend((key, site, component, p) for component, p in r.props)

    # 1. Direct flow from every call site.
    for key, usages in index.by_operation.items():
        for u in usages:
            parsed = sources.get(u.site.file)
            node = node_at(parsed[1], u.site.start_byte, u.site.end_byte) if parsed else None
            if parsed is None or node is None:
                continue
            result = _flow(parsed[0], node, parsed[2], initial_value(u.site))
            keep(key, u.site, _base_confidence(u), result, "")
            name = result.function_name
            # Generic method names (`get`) are only followed when the receiver names the
            # class: `this.userService.get()` -> UserService.get.
            if (
                result.returns is not None
                and name
                and (name not in _GENERIC_NAMES or result.class_name)
            ):
                returns[name].append(
                    _Return(key, result.returns, u.site, result.class_name, name in _GENERIC_NAMES)
                )

    # 2. One hop: callers of functions that return the response, in any file.
    if returns:
        for path in iter_source_files(repo, exclude):
            rel = path.relative_to(repo).as_posix()
            parsed = sources.get(rel)
            if parsed is None:
                continue
            source, root, lang = parsed
            for call, name, receiver in _calls_by_name(root, lang, returns.keys()):
                for ret in returns[name]:
                    origin = ret.origin
                    if origin.file == rel and call.start_byte <= origin.start_byte < call.end_byte:
                        continue
                    if ret.needs_receiver and not _receiver_matches(receiver, ret.class_name):
                        continue
                    result = _flow(source, call, lang, ret.value)
                    site = _site_for(call, rel, lang, source, origin)
                    label = f"{ret.class_name}.{name}()" if ret.class_name else f"{name}()"
                    keep(ret.key, site, Confidence.MEDIUM, result, f"via {label}")

    # 2b. One hop into child components: <UserCard user={user} />.
    if props:
        components = _component_index(repo, exclude, sources)
        for key, site, component, values in props:
            for rel, fn in components.get(component, []):
                parsed = sources.get(rel)
                if parsed is None:
                    continue
                result = JSFlow(parsed[0], None, None, component=fn, props=values).run()
                via = f"via <{component} {' '.join(f'{k}=...' for k in values)}>"
                traces[key].append(_Trace(key, site, Confidence.MEDIUM, result.accesses, via))

    # 3. Map each change to locations.
    for change in changes:
        if change.method is None or change.path is None:
            continue
        key = operation_key(change.method, change.path)
        usages = index.by_operation.get(key, [])
        report.call_counts[change.key] = len(usages)
        if _is_response_field_change(change):
            report.impacts += _field_impacts(change, traces.get(key, []))
        else:
            report.impacts += [
                Impact(
                    change=change,
                    file=u.site.file,
                    line=u.site.line,
                    column=u.site.column,
                    code=u.site.code,
                    confidence=_base_confidence(u),
                    reason=f"calls {change.method} {change.path}",
                    is_test=u.site.is_test,
                )
                for u in usages
            ]

    # 4. Name-only matches (LOW): `user.name` where the schema is User, no traced flow.
    report.impacts += _name_matches(changes, report.impacts, repo, exclude, sources)
    report.impacts = _dedupe(report.impacts)
    return report


def _is_response_field_change(c: APIChange) -> bool:
    return (
        c.direction is Direction.RESPONSE
        and bool(c.field_path)
        and (c.status_code or "").startswith(("2", "default"))
    )


def _hits(access: tuple[str, ...], field: tuple[str, ...]) -> bool:
    return access[: len(field)] == field


def _field_impacts(change: APIChange, traces: list[_Trace]) -> list[Impact]:
    out: list[Impact] = []
    for t in traces:
        for a in t.accesses:
            if _hits(a.path, change.field_path):
                via = f" {t.via}" if t.via else ""
                out.append(
                    Impact(
                        change=change,
                        file=t.site.file,
                        line=a.line,
                        column=a.column,
                        code=a.code,
                        confidence=t.confidence,
                        caret=a.caret,
                        reason=f"reads `{change.subject}` from {change.method} {change.path}"
                        f" ({t.site.file}:{t.site.line}){via}",
                        is_test=t.site.is_test,
                    )
                )
    return out


def _calls_by_name(
    root: Node, lang: str, names: Iterable[str]
) -> list[tuple[Node, str, str | None]]:
    """Calls to any of `names`, with the receiver text for method calls (`this.userService`)."""
    wanted = set(names)
    call_type = "call" if lang == "python" else "call_expression"
    out: list[tuple[Node, str, str | None]] = []
    for n in walk(root):
        if n.type != call_type:
            continue
        fn = n.child_by_field_name("function")
        while fn is not None and fn.type in ("await_expression", "parenthesized_expression"):
            fn = fn.named_children[0] if fn.named_children else None
        if fn is None:
            continue
        receiver: str | None = None
        if fn.type == "identifier":
            name = text(fn)
        elif fn.type == "member_expression":
            name = text(fn.child_by_field_name("property"))
            receiver = text(fn.child_by_field_name("object"))
        elif fn.type == "attribute":
            name = text(fn.child_by_field_name("attribute"))
            receiver = text(fn.child_by_field_name("object"))
        else:
            continue
        if name in wanted:
            out.append((n, name, receiver))
    return out


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _receiver_matches(receiver: str | None, class_name: str | None) -> bool:
    """`this.userService` / `self.user_service` / `userService` name the UserService class."""
    if not receiver or not class_name:
        return False
    return _norm(receiver.rsplit(".", 1)[-1]) == _norm(class_name)


def _component_index(
    repo: Path, exclude: tuple[str, ...], sources: "_Sources"
) -> dict[str, list[tuple[str, Node]]]:
    """Capitalized function components by name: `function UserCard(...)`,
    `const UserCard = (...) => ...`."""
    index: dict[str, list[tuple[str, Node]]] = defaultdict(list)
    for path in iter_source_files(repo, exclude):
        rel = path.relative_to(repo).as_posix()
        parsed = sources.get(rel)
        if parsed is None or parsed[2] == "python":
            continue
        for n in walk(parsed[1]):
            name: Node | None = None
            if n.type == "function_declaration":
                name = n.child_by_field_name("name")
            elif (
                n.type in ("arrow_function", "function_expression")
                and n.parent is not None
                and n.parent.type == "variable_declarator"
            ):
                name = n.parent.child_by_field_name("name")
            if name is not None and text(name)[:1].isupper():
                index[text(name)].append((rel, n))
    return index


def _site_for(call: Node, rel: str, lang: str, source: bytes, origin: CallSite) -> CallSite:
    return CallSite(
        file=rel,
        line=call.start_point[0] + 1,
        column=call.start_point[1] + 1,
        language=lang,
        client=origin.client,
        method=origin.method,
        url=origin.url,
        url_source=origin.url_source,
        code=line_text(source, call),
        is_test=is_test_file(PurePosixPath(rel)),
        start_byte=call.start_byte,
        end_byte=call.end_byte,
    )


def _schema_var_names(schema: str) -> set[str]:
    s = re.sub(r"[^a-z0-9]", "", schema.lower())
    return {s, s + "s", s + "data", "current" + s, "my" + s, s + "info"}


def _name_matches(
    changes: list[APIChange],
    existing: list[Impact],
    repo: Path,
    exclude: tuple[str, ...],
    sources: _Sources,
) -> list[Impact]:
    wanted: dict[tuple[str, str], list[APIChange]] = defaultdict(list)
    for c in changes:
        if _is_response_field_change(c) and c.schema_name and len(c.schema_path) == 1:
            for var in _schema_var_names(c.schema_name):
                wanted[(var, c.schema_path[0])].append(c)
    if not wanted:
        return []
    seen = {(i.change.group_key, i.file, i.line) for i in existing}
    out: list[Impact] = []
    for path in iter_source_files(repo, exclude):
        rel = path.relative_to(repo).as_posix()
        parsed = sources.get(rel)
        if parsed is None:
            continue
        source, root, _ = parsed
        for n in walk(root):
            obj, field, anchor = _simple_access(n)
            if obj is None or field is None or anchor is None:
                continue
            var = re.sub(r"[^a-z0-9]", "", obj.lower())
            for c in wanted.get((var, field), []):
                line = anchor.start_point[0] + 1
                if (c.group_key, rel, line) in seen:
                    continue
                seen.add((c.group_key, rel, line))
                code, caret = code_and_caret(source, anchor)
                out.append(
                    Impact(
                        change=c,
                        file=rel,
                        line=line,
                        column=anchor.start_point[1] + 1,
                        code=code,
                        caret=caret,
                        confidence=Confidence.LOW,
                        reason=f"`{obj}.{field}` looks like `{c.subject}`; no data flow traced",
                        is_test=is_test_file(PurePosixPath(rel)),
                    )
                )
    return out


def _simple_access(n: Node) -> tuple[str | None, str | None, Node | None]:
    """`x.field`, `x["field"]` or `x?.field` where x is a plain identifier."""
    if n.type in ("member_expression", "attribute"):
        obj = n.child_by_field_name("object")
        prop = n.child_by_field_name("property" if n.type == "member_expression" else "attribute")
        if obj is not None and obj.type == "identifier" and prop is not None:
            return text(obj), text(prop), prop
    if n.type in ("subscript_expression", "subscript"):
        obj = n.child_by_field_name("object" if n.type == "subscript_expression" else "value")
        idx = n.child_by_field_name("index" if n.type == "subscript_expression" else "subscript")
        if (
            obj is not None
            and obj.type == "identifier"
            and idx is not None
            and idx.type == "string"
        ):
            raw = text(idx)
            return text(obj), raw.strip("\"'`").lstrip("bfrBFR").strip("\"'"), idx
    return None, None, None


def _dedupe(impacts: list[Impact]) -> list[Impact]:
    """One impact per (change, file, line), keeping the most confident."""
    best: dict[tuple[str, str, int], Impact] = {}
    for i in impacts:
        k = (i.change.key, i.file, i.line)
        if k not in best or i.confidence.rank < best[k].confidence.rank:
            best[k] = i
    return sorted(best.values(), key=lambda i: (i.confidence.rank, i.is_test, i.file, i.line))
