"""Contract x Contract -> list[APIChange]."""

from dataclasses import dataclass
from typing import Any, Literal

from breakscope.changes import APIChange, Direction
from breakscope.contracts.model import Contract, Operation, Schema
from breakscope.contracts.renames import guess_renames
from breakscope.contracts.rules import RULES

Kind = Literal["parameter", "request", "response"]
# (schema name, path relative to it) for the field currently being compared.
Owner = tuple[str | None, tuple[str, ...]]


@dataclass(frozen=True)
class _Ctx:
    method: str
    path: str
    kind: Kind
    status_code: str | None = None

    @property
    def direction(self) -> Direction:
        return Direction.RESPONSE if self.kind == "response" else Direction.REQUEST


def diff_contracts(old: Contract, new: Contract) -> list[APIChange]:
    d = _Differ()
    ignored = old.skipped.keys() | new.skipped.keys()
    for key, op in old.operations.items():
        if key in ignored:
            continue
        if key not in new.operations:
            d.emit(
                "endpoint.removed", op.method, op.path, message=f"{op.method} {op.path} was removed"
            )
        else:
            d.operation(op, new.operations[key])
    for key, op in new.operations.items():
        if key not in old.operations and key not in ignored:
            d.emit("endpoint.added", op.method, op.path, message=f"{op.method} {op.path} was added")
    return sorted(d.out, key=APIChange.sort_key)


def _show(v: Any) -> str:
    if isinstance(v, (set, frozenset, list, tuple)):
        return " | ".join(sorted(str(x) for x in v)) or "any"
    return repr(v) if isinstance(v, str) else str(v)


def _types(s: Schema) -> list[str]:
    return sorted(s.types)


def _covers(big: frozenset[str], small: frozenset[str]) -> bool:
    return all(t in big or (t == "integer" and "number" in big) for t in small)


class _Differ:
    def __init__(self) -> None:
        self.out: list[APIChange] = []

    def emit(
        self,
        rule: str,
        method: str | None,
        path: str | None,
        *,
        message: str,
        ctx: _Ctx | None = None,
        field_path: tuple[str, ...] = (),
        owner: Owner = (None, ()),
        old: Any = None,
        new: Any = None,
        renamed_to: str | None = None,
        renamed_from: str | None = None,
    ) -> None:
        name, rel = owner
        self.out.append(
            APIChange(
                rule=rule,
                severity=RULES[rule].severity,
                method=method,
                path=path,
                direction=ctx.direction if ctx else None,
                status_code=ctx.status_code if ctx else None,
                field_path=field_path,
                schema_name=name if rel else None,
                schema_path=rel if name else (),
                old=old,
                new=new,
                message=message,
                renamed_to=renamed_to,
                renamed_from=renamed_from,
            )
        )

    def _at(
        self,
        rule: str,
        ctx: _Ctx,
        fp: tuple[str, ...],
        owner: Owner,
        message: str,
        old: Any = None,
        new: Any = None,
        **hints: str | None,
    ) -> None:
        self.emit(
            rule,
            ctx.method,
            ctx.path,
            message=message,
            ctx=ctx,
            field_path=fp,
            owner=owner,
            old=old,
            new=new,
            **hints,
        )

    # -- operations ---------------------------------------------------------------

    def operation(self, old: Operation, new: Operation) -> None:
        m, p = new.method, new.path
        pctx = _Ctx(m, p, "parameter")
        for key, op_param in old.parameters.items():
            label = f"{op_param.location} parameter `{op_param.name}`"
            fp = (op_param.name,)
            np = new.parameters.get(key)
            if np is None:
                self._at("parameter.removed", pctx, fp, (None, ()), f"{label} was removed")
                continue
            if np.required and not op_param.required:
                self._at(
                    "parameter.became_required",
                    pctx,
                    fp,
                    (None, ()),
                    f"{label} is now required",
                    False,
                    True,
                )
            self.schema(op_param.schema, np.schema, pctx, fp, (None, ()))
        for key, np in new.parameters.items():
            if key not in old.parameters:
                label = f"{np.location} parameter `{np.name}`"
                if np.required:
                    self._at(
                        "parameter.added.required",
                        pctx,
                        (np.name,),
                        (None, ()),
                        f"new required {label}",
                    )
                else:
                    self._at(
                        "parameter.added.optional",
                        pctx,
                        (np.name,),
                        (None, ()),
                        f"new optional {label}",
                    )

        rctx = _Ctx(m, p, "request")
        if not old.request_body and new.request_body:
            if new.request_body_required:
                self._at(
                    "request.body.added.required",
                    rctx,
                    (),
                    (None, ()),
                    "a request body is now required",
                )
        elif old.request_body and new.request_body:
            if new.request_body_required and not old.request_body_required:
                self._at(
                    "request.body.became_required",
                    rctx,
                    (),
                    (None, ()),
                    "the request body is now required",
                    False,
                    True,
                )
            for media, schema in old.request_body.items():
                if media not in new.request_body:
                    self._at(
                        "request.media_type.removed",
                        rctx,
                        (),
                        (None, ()),
                        f"request media type {media} is no longer accepted",
                        media,
                    )
                else:
                    self.schema(schema, new.request_body[media], rctx, (), (None, ()))

        for status, contents in old.responses.items():
            sctx = _Ctx(m, p, "response", status)
            if status not in new.responses:
                if status.startswith("2"):
                    self._at(
                        "response.status.removed",
                        sctx,
                        (),
                        (None, ()),
                        f"status {status} is no longer returned",
                        status,
                    )
                continue
            for media, schema in contents.items():
                if media not in new.responses[status]:
                    self._at(
                        "response.media_type.removed",
                        sctx,
                        (),
                        (None, ()),
                        f"{status} response no longer returns {media}",
                        media,
                    )
                else:
                    self.schema(schema, new.responses[status][media], sctx, (), (None, ()))

    # -- schemas ------------------------------------------------------------------

    def schema(
        self, old: Schema, new: Schema, ctx: _Ctx, fp: tuple[str, ...], owner: Owner
    ) -> None:
        if old.recursive or new.recursive:
            return
        k = ctx.kind
        what = "parameter" if k == "parameter" else f"{k}.property"
        where = ".".join(fp).replace(".[]", "[]") or "body"

        ov, nv = old.value_types, new.value_types
        if ov and nv and ov != nv:
            ok = _covers(ov, nv) if k == "response" else _covers(nv, ov)
            if not ok:
                self._at(
                    f"{what}.type.changed",
                    ctx,
                    fp,
                    owner,
                    f"`{where}` type changed from {_show(ov)} to {_show(nv)}",
                    _types(old),
                    _types(new),
                )
                return

        if k == "response" and new.nullable and not old.nullable:
            self._at(
                "response.property.became_nullable",
                ctx,
                fp,
                owner,
                f"`{where}` can now be null",
                False,
                True,
            )
        elif k != "response" and old.nullable and not new.nullable:
            self._at(
                f"{what}.type.changed",
                ctx,
                fp,
                owner,
                f"`{where}` no longer accepts null",
                _types(old),
                _types(new),
            )

        if k == "response" and old.format and old.format != new.format:
            self._at(
                "response.property.format.changed",
                ctx,
                fp,
                owner,
                f"`{where}` format changed from {old.format} to {new.format or 'none'}",
                old.format,
                new.format,
            )

        self._enum(old, new, ctx, fp, owner, what, where)

        if _union_sig(old) != _union_sig(new):
            self._at("schema.union.changed", ctx, fp, owner, f"`{where}` oneOf/anyOf changed")

        if k == "parameter":
            return

        child_owner: Owner = (old.ref_name, ()) if old.ref_name else owner
        cname, crel = child_owner
        renames = guess_renames(
            {n: s for n, s in old.properties.items() if n not in new.properties},
            {n: s for n, s in new.properties.items() if n not in old.properties},
        )
        renamed_from = {to: frm for frm, to in renames.items()}
        for name, op in old.properties.items():
            cfp, cown = fp + (name,), (cname, crel + (name,))
            label = ".".join(cfp).replace(".[]", "[]")
            npr = new.properties.get(name)
            if npr is None:
                to = renames.get(name)
                hint = f" (probably renamed to `{to}`)" if to else ""
                self._at(
                    f"{k}.property.removed",
                    ctx,
                    cfp,
                    cown,
                    f"`{label}` was removed{hint}",
                    _types(op),
                    renamed_to=to,
                )
                continue
            if k == "response" and name in old.required and name not in new.required:
                self._at(
                    "response.property.became_optional",
                    ctx,
                    cfp,
                    cown,
                    f"`{label}` is no longer always present",
                    True,
                    False,
                )
            if k == "request" and name in new.required and name not in old.required:
                self._at(
                    "request.property.became_required",
                    ctx,
                    cfp,
                    cown,
                    f"`{label}` is now required",
                    False,
                    True,
                )
            self.schema(op, npr, ctx, cfp, cown)
        for name, npr in new.properties.items():
            if name in old.properties:
                continue
            cfp, cown = fp + (name,), (cname, crel + (name,))
            label = ".".join(cfp).replace(".[]", "[]")
            if k == "response":
                self._at(
                    "response.property.added",
                    ctx,
                    cfp,
                    cown,
                    f"`{label}` was added",
                    None,
                    _types(npr),
                    renamed_from=renamed_from.get(name),
                )
            elif name in new.required:
                self._at(
                    "request.property.added.required",
                    ctx,
                    cfp,
                    cown,
                    f"new required property `{label}`"
                    + (
                        f" (probably replaces `{renamed_from[name]}`)"
                        if name in renamed_from
                        else ""
                    ),
                    None,
                    _types(npr),
                    renamed_from=renamed_from.get(name),
                )

        if old.items is not None and new.items is not None:
            self.schema(old.items, new.items, ctx, fp + ("[]",), (cname, crel + ("[]",)))

    def _enum(
        self,
        old: Schema,
        new: Schema,
        ctx: _Ctx,
        fp: tuple[str, ...],
        owner: Owner,
        what: str,
        where: str,
    ) -> None:
        oe, ne = old.enum, new.enum
        if oe == ne or (oe is None and ne is None):
            return
        if ctx.kind == "response":
            if oe is not None and ne is None:
                self._at(
                    "response.enum.value_added",
                    ctx,
                    fp,
                    owner,
                    f"`{where}` is no longer restricted to an enum",
                    list(oe),
                    None,
                )
                return
            if oe is None:
                return
            added = [v for v in ne or () if v not in oe]
            removed = [v for v in oe if v not in (ne or ())]
            if added:
                self._at(
                    "response.enum.value_added",
                    ctx,
                    fp,
                    owner,
                    f"`{where}` can now be {', '.join(map(_show, added))}",
                    list(oe),
                    list(ne or ()),
                )
            if removed:
                self._at(
                    "response.enum.value_removed",
                    ctx,
                    fp,
                    owner,
                    f"`{where}` is no longer {', '.join(map(_show, removed))}",
                    list(oe),
                    list(ne or ()),
                )
            return
        if ne is None:
            return
        removed = [v for v in oe or () if v not in ne]
        if oe is None:
            self._at(
                f"{what}.enum.value_removed",
                ctx,
                fp,
                owner,
                f"`{where}` is now restricted to {', '.join(map(_show, ne))}",
                None,
                list(ne),
            )
        elif removed:
            self._at(
                f"{what}.enum.value_removed",
                ctx,
                fp,
                owner,
                f"`{where}` no longer accepts {', '.join(map(_show, removed))}",
                list(oe),
                list(ne),
            )


def _union_sig(s: Schema) -> tuple[str, ...] | None:
    if s.union is None:
        return None
    return tuple(sorted(m.ref_name or "|".join(sorted(m.types)) or "any" for m in s.union))
