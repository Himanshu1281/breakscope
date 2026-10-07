"""The change model shared by the diff engine, reporters and (later) the impact engine.

Nothing in here knows about OpenAPI. Downstream code depends on this module only.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Severity(StrEnum):
    BREAKING = "breaking"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"breaking": 0, "warning": 1, "info": 2}[self.value]


class Direction(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"


class APIChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    severity: Severity
    method: str | None = None
    path: str | None = None
    direction: Direction | None = None
    status_code: str | None = None
    # Location of the field from the root of the request/response body (or parameter).
    # "[]" marks an array element: ("items", "[]", "name").
    field_path: tuple[str, ...] = ()
    # Nearest named schema (components/schemas/<name>) that owns the field, and the
    # field's path relative to it. User.name is ("name",) whether it was reached
    # through GET /users/{id} or through GET /users -> "[]".
    schema_name: str | None = None
    schema_path: tuple[str, ...] = ()
    old: Any = None
    new: Any = None
    message: str
    # A removed property that was probably renamed, and the reverse on the added one.
    renamed_to: str | None = None
    renamed_from: str | None = None

    @property
    def key(self) -> str:
        """Stable identifier for snapshots, dedupe and ignore lists."""
        parts = [
            self.rule,
            self.method or "",
            self.path or "",
            self.status_code or "",
            ".".join(self.field_path),
        ]
        return " ".join(p for p in parts if p)

    @property
    def group_key(self) -> tuple[str, ...]:
        """Changes to one shared schema field group together across operations."""
        if self.schema_name and self.schema_path:
            return (self.rule, self.schema_name, *self.schema_path)
        return (self.key,)

    @property
    def subject(self) -> str:
        """Short human label for the changed thing: `User.name`, `email`, `items[].id`."""
        if self.schema_name and self.schema_path:
            return format_field_path((self.schema_name, *self.schema_path))
        return format_field_path(self.field_path)

    def sort_key(self) -> tuple[Any, ...]:
        return (
            self.severity.rank,
            self.path or "",
            self.method or "",
            self.direction or "",
            self.status_code or "",
            self.field_path,
            self.rule,
        )


def format_field_path(path: tuple[str, ...]) -> str:
    out = ""
    for part in path:
        if part == "[]":
            out += "[]"
        else:
            out += f".{part}" if out else part
    return out
