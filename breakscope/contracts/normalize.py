"""Turn a loaded OpenAPI 3.0/3.1 document into a version-agnostic Contract."""

import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from breakscope.contracts.loader import LoadedSpec
from breakscope.contracts.model import (
    Contract,
    Operation,
    OperationKey,
    Parameter,
    ParamLocation,
    Schema,
)
from breakscope.contracts.resolver import Resolver
from breakscope.errors import BreakScopeError

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_PARAM_LOCATIONS = ("path", "query", "header", "cookie")
_PATH_PARAM = re.compile(r"\{([^}]*)\}")
_ANY = Schema()


def operation_key(method: str, path: str) -> OperationKey:
    return (method.upper(), _PATH_PARAM.sub("{}", path))


def normalize(spec: LoadedSpec) -> Contract:
    return _Normalizer(spec).contract()


class _Normalizer:
    def __init__(self, spec: LoadedSpec) -> None:
        self.spec = spec
        self.root = spec.path.resolve()
        self.resolver = Resolver(spec.path, spec.document)
        self._cache: dict[tuple[str, str], Schema] = {}
        self._expanding: set[tuple[str, str]] = set()

    def contract(self) -> Contract:
        c = Contract(version=self.spec.version, source=str(self.spec.path))
        paths = self.spec.document.get("paths") or {}
        if not isinstance(paths, dict):
            raise BreakScopeError(
                "`paths` must be a mapping", file=str(self.spec.path), pointer="/paths"
            )
        for path, item in paths.items():
            path = str(path)
            base = self.root
            if isinstance(item, dict) and "$ref" in item:
                t = self.resolver.resolve(str(item["$ref"]), base)
                item, base = t.node, t.file
            if not isinstance(item, dict):
                continue
            for method in HTTP_METHODS:
                if method not in item:
                    continue
                key = operation_key(method, path)
                try:
                    c.operations[key] = self._operation(method, path, item, base)
                except (BreakScopeError, AttributeError, TypeError, KeyError, ValueError) as e:
                    msg = e.message if isinstance(e, BreakScopeError) else f"malformed: {e!r}"
                    c.skipped[key] = msg
        return c

    # -- operations ---------------------------------------------------------------

    def _deref(self, node: Any, base: Path) -> tuple[Any, Path]:
        if isinstance(node, dict) and "$ref" in node:
            t = self.resolver.resolve(str(node["$ref"]), base)
            return t.node, t.file
        return node, base

    def _operation(self, method: str, path: str, item: dict[str, Any], base: Path) -> Operation:
        op, op_base = self._deref(item[method], base)
        path_params = _PATH_PARAM.findall(path)

        params: dict[tuple[str, str], Parameter] = {}
        # Path-item parameters first; operation parameters override by (in, name).
        for raw, raw_base in [(p, base) for p in item.get("parameters") or []] + [
            (p, op_base) for p in op.get("parameters") or []
        ]:
            p, p_base = self._deref(raw, raw_base)
            loc = p.get("in")
            if loc not in _PARAM_LOCATIONS:
                continue
            location: ParamLocation = loc
            name = str(p["name"])
            if location == "path" and name in path_params:
                key = ("path", f"#{path_params.index(name)}")
            elif location == "header":
                key = ("header", name.lower())
            else:
                key = (location, name)
            params[key] = Parameter(
                name=name,
                location=location,
                required=bool(p.get("required", location == "path")),
                schema=self._param_schema(p, p_base),
            )

        body: dict[str, Schema] = {}
        body_required = False
        if "requestBody" in op:
            rb, rb_base = self._deref(op["requestBody"], op_base)
            body = self._content(rb.get("content"), rb_base)
            body_required = bool(rb.get("required", False))

        responses: dict[str, dict[str, Schema]] = {}
        for status, resp in (op.get("responses") or {}).items():
            r, r_base = self._deref(resp, op_base)
            responses[str(status)] = self._content(r.get("content"), r_base) if r else {}

        return Operation(
            method=method.upper(),
            path=path,
            operation_id=op.get("operationId"),
            parameters=params,
            request_body=body,
            request_body_required=body_required,
            responses=responses,
        )

    def _param_schema(self, p: dict[str, Any], base: Path) -> Schema:
        if "schema" in p:
            return self.schema(p["schema"], base)
        content = self._content(p.get("content"), base)
        return next(iter(content.values()), _ANY)

    def _content(self, content: Any, base: Path) -> dict[str, Schema]:
        if not isinstance(content, dict):
            return {}
        return {
            str(media): self.schema((m or {}).get("schema", {}), base)
            for media, m in content.items()
        }

    # -- schemas ------------------------------------------------------------------

    def schema(self, node: Any, base: Path) -> Schema:
        if not isinstance(node, dict):
            return _ANY  # 3.1 boolean schemas, or garbage we choose not to crash on
        if "$ref" in node:
            t = self.resolver.resolve(str(node["$ref"]), base)
            if t.id in self._expanding:
                return Schema(ref_name=t.name or t.pointer, recursive=True)
            if t.id in self._cache:
                s = self._cache[t.id]
            else:
                self._expanding.add(t.id)
                try:
                    s = self._inline(t.node, t.file)
                finally:
                    self._expanding.discard(t.id)
                if t.name:
                    s = replace(s, ref_name=t.name)
                self._cache[t.id] = s
            # 3.0 allows `nullable` next to $ref in practice; honour it.
            if node.get("nullable") is True and not s.nullable:
                s = replace(s, types=s.types | {"null"})
            return s
        return self._inline(node, base)

    def _inline(self, node: Any, base: Path) -> Schema:
        if not isinstance(node, dict):
            return _ANY
        if "allOf" in node:
            own = {k: v for k, v in node.items() if k != "allOf"}
            parts = [self.schema(s, base) for s in node["allOf"] or []]
            own_schema = self._inline(own, base) if own else None
            merged = _merge_all_of(parts + ([own_schema] if own_schema else []))
            named = [p.ref_name for p in parts if p.ref_name]
            if len(parts) == 1 and named and not (own_schema and own_schema.properties):
                merged = replace(merged, ref_name=named[0])
            return merged

        types = _types(node)
        union: tuple[Schema, ...] | None = None
        for kw in ("oneOf", "anyOf"):
            if kw not in node:
                continue
            members = [self.schema(s, base) for s in node[kw] or []]
            non_null = [m for m in members if m.types != frozenset({"null"})]
            if len(non_null) < len(members):
                types = types | {"null"}
            if len(non_null) == 1:
                # `anyOf: [User, {type: null}]` is just a nullable User.
                m = non_null[0]
                return replace(m, types=m.types | types)
            union = tuple(non_null)

        properties = {
            str(k): self.schema(v, base) for k, v in (node.get("properties") or {}).items()
        }
        items = self.schema(node["items"], base) if "items" in node else None
        if not types - {"null"}:
            if properties:
                types = types | {"object"}
            elif items is not None:
                types = types | {"array"}

        enum: tuple[Any, ...] | None = None
        if isinstance(node.get("enum"), list):
            enum = tuple(node["enum"])
        elif "const" in node:
            enum = (node["const"],)

        return Schema(
            types=types,
            properties=properties,
            required=frozenset(str(r) for r in node.get("required") or []),
            items=items,
            enum=enum,
            format=node.get("format"),
            union=union,
        )


def _types(node: dict[str, Any]) -> frozenset[str]:
    t = node.get("type")
    if isinstance(t, str):
        types = {t}
    elif isinstance(t, list):
        types = {str(x) for x in t}
    else:
        types = set()
    if node.get("nullable") is True:
        types.add("null")
    return frozenset(types)


def _merge_all_of(parts: list[Schema]) -> Schema:
    properties: dict[str, Schema] = {}
    required: set[str] = set()
    types: frozenset[str] | None = None
    enum = items = fmt = None
    nullable = True
    for p in parts:
        properties.update(p.properties)
        required |= p.required
        if p.value_types:
            types = p.value_types if types is None else types & p.value_types
        nullable = nullable and (p.nullable or not p.types)
        enum = enum if enum is not None else p.enum
        items = items if items is not None else p.items
        fmt = fmt or p.format
    final = types or frozenset()
    if nullable and any(p.nullable for p in parts):
        final = final | {"null"}
    if properties and not final - {"null"}:
        final = final | {"object"}
    return Schema(
        types=final,
        properties=properties,
        required=frozenset(required),
        items=items,
        enum=enum,
        format=fmt,
    )
