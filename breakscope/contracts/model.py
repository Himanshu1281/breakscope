"""Version-agnostic contract model. OpenAPI 3.0 and 3.1 both normalize to this."""

from dataclasses import dataclass, field
from typing import Any, Literal

ParamLocation = Literal["path", "query", "header", "cookie"]


@dataclass(frozen=True, eq=False)
class Schema:
    # JSON types; empty means "any". "null" is folded in from 3.0 `nullable: true`.
    types: frozenset[str] = frozenset()
    properties: dict[str, "Schema"] = field(default_factory=dict)
    required: frozenset[str] = frozenset()
    items: "Schema | None" = None
    enum: tuple[Any, ...] | None = None
    format: str | None = None
    # oneOf/anyOf, compared opaquely in v0.1.
    union: tuple["Schema", ...] | None = None
    # components/schemas/<ref_name> this schema came from, if any.
    ref_name: str | None = None
    # A reference back to a schema that is already being expanded (Node.children: [Node]).
    # Only ref_name is meaningful on such a placeholder.
    recursive: bool = False

    @property
    def nullable(self) -> bool:
        return "null" in self.types

    @property
    def value_types(self) -> frozenset[str]:
        return self.types - {"null"}


@dataclass(frozen=True)
class Parameter:
    name: str
    location: ParamLocation
    required: bool
    schema: Schema


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    operation_id: str | None
    # Keyed by (location, name). Path parameters are keyed by position ("#0", "#1") so
    # renaming {id} to {userId} is not reported as a removal.
    parameters: dict[tuple[str, str], Parameter]
    request_body: dict[str, Schema]  # media type -> schema
    request_body_required: bool
    responses: dict[str, dict[str, Schema]]  # status -> media type -> schema


OperationKey = tuple[str, str]  # (METHOD, path with parameter names replaced by "{}")


@dataclass
class Contract:
    version: str
    source: str
    operations: dict[OperationKey, Operation] = field(default_factory=dict)
    # Operations that failed to normalize. The differ ignores these keys on both sides
    # so a broken operation is never reported as removed.
    skipped: dict[OperationKey, str] = field(default_factory=dict)
