# v0.1 Architecture — Contract Diff

v0.1 ships `breakscope diff` only. Its job is to fix the **internal change model** that code analysis (v0.2 onward) will consume. If this model is right, the analyzers never need to touch OpenAPI.

## Pipeline

```text
old.yaml ─┐
          ├─► loader ─► resolver ($ref) ─► normalizer ─► Contract ─┐
new.yaml ─┘                                                        ├─► differ ─► list[APIChange] ─► reporter
                                                           Contract┘
```

Each stage is a pure function with no I/O except in the loader, so every stage can be tested on its own.

## Package layout (v0.1 only)

```text
breakscope/
├── __init__.py            # __version__
├── __main__.py            # python -m breakscope
├── cli/
│   └── main.py            # Typer app: diff (analyze/check are stubs that exit 2 with "coming in v0.4")
├── contracts/
│   ├── loader.py          # read file / git ref → dict; detect openapi version
│   ├── resolver.py        # $ref resolution, cycle-safe, records origin component name
│   ├── normalize.py       # dict → Contract (3.0 + 3.1 → one model)
│   ├── model.py           # Contract, Operation, Parameter, Schema
│   ├── diff.py            # Contract × Contract → list[APIChange]
│   └── rules.py           # rule catalog: id, default severity, description
├── changes.py             # APIChange, Severity, ChangeKind — the shared contract for everything downstream
├── reports/
│   ├── terminal.py        # rich
│   └── json.py
└── errors.py              # SpecLoadError, RefError, UnsupportedVersionError (human messages + hints)
```

`changes.py` sits at the top level on purpose. Analyzers and the impact engine depend on it, not on `contracts/`.

## Core models

```python
# changes.py
class Severity(StrEnum):
    BREAKING = "breaking"
    WARNING = "warning"        # e.g. enum value added to response (may break exhaustive switches)
    INFO = "info"              # non-breaking additions

class Direction(StrEnum):
    REQUEST = "request"        # client sends it; tightening breaks clients
    RESPONSE = "response"      # client reads it; loosening/removal breaks clients

class APIChange(BaseModel, frozen=True):
    rule: str                  # "response.property.removed"
    severity: Severity
    method: str | None         # "GET"; None for global/schema-only changes
    path: str | None           # "/users/{id}"
    direction: Direction | None
    status_code: str | None    # "200", "default"
    field_path: tuple[str, ...]  # ("items", "[]", "name"); "[]" = array element
    schema_name: str | None    # "User" if the field came from components/schemas/User
    old: Any | None
    new: Any | None
    message: str               # human-readable one-liner

    @property
    def key(self) -> str: ...  # stable id for snapshots/dedupe/ignore-lists

    @property
    def group_key(self) -> tuple[str, str | None, tuple[str, ...]]: ...  # (rule, schema_name, field_path)
```

`field_path` and `schema_name` are the two fields the impact engine will match code against (`user.name` ↔ `("name",)`, `User`). The resolver must keep `schema_name` when it inlines a `$ref`.

```python
# contracts/model.py
class Schema(BaseModel):
    types: frozenset[str]          # {"string"}, {"string","null"}; nullable folded in
    properties: dict[str, "Schema"]
    required: frozenset[str]
    items: "Schema | None"
    enum: tuple[Any, ...] | None
    format: str | None
    union: tuple["Schema", ...] | None   # oneOf/anyOf, compared opaquely in v0.1
    ref_name: str | None
    additional_properties: "bool | Schema"

class Parameter(BaseModel):
    name: str; location: Literal["path","query","header","cookie"]
    required: bool; schema: Schema

class Operation(BaseModel):
    method: str; path: str; operation_id: str | None
    parameters: dict[tuple[str, str], Parameter]   # (location, name)
    request_body: dict[str, Schema]                # media type → schema
    request_body_required: bool
    responses: dict[str, dict[str, Schema]]        # status → media type → schema

class Contract(BaseModel):
    version: str
    operations: dict[tuple[str, str], Operation]   # (METHOD, normalized_path)
```

**Path normalization:** `/users/{id}` and `/users/{userId}` are the same endpoint. The key replaces parameter names with `{}`, and the original path is kept for display.

## Direction-aware rule catalog (v0.1)

Breaking-ness depends on direction. Making a *response* field optional breaks readers. Making a *request* field required breaks writers.

| Rule | Severity |
|---|---|
| `endpoint.removed` | breaking |
| `endpoint.added` | info |
| `parameter.removed` (path/query/header) | breaking |
| `parameter.added.required` | breaking |
| `parameter.added.optional` | info |
| `parameter.became_required` | breaking |
| `parameter.type.changed` | breaking |
| `parameter.enum.value_removed` | breaking |
| `request.body.added.required` | breaking |
| `request.property.added.required` | breaking |
| `request.property.became_required` | breaking |
| `request.property.type.changed` | breaking |
| `request.property.enum.value_removed` | breaking |
| `request.property.removed` | warning (server may now reject or ignore it) |
| `response.status.removed` (2xx) | breaking |
| `response.media_type.removed` | breaking |
| `response.property.removed` | breaking |
| `response.property.became_optional` | warning |
| `response.property.became_nullable` | breaking |
| `response.property.type.changed` | breaking |
| `response.property.format.changed` | warning |
| `response.enum.value_added` | warning |
| `response.enum.value_removed` | info |
| `response.property.added` | info |
| `schema.union.changed` | warning (opaque in v0.1) |

The differ recurses through `properties` and `items` and builds up `field_path`. Each rule is a small function `(old, new, ctx) -> Iterable[APIChange]` registered in `rules.py`, so adding a rule never touches the walker.

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Spec parsing | PyYAML (`CSafeLoader`) + own resolver | We need `ref_name` provenance, which most resolvers throw away. `openapi-spec-validator` is only an optional `--validate` step. |
| Models | Pydantic v2, frozen | Free JSON serialization for the JSON reporter, and hashable keys |
| Recursive schemas | Resolver keeps a visited set and emits a `RecursiveRef(name)` sentinel. The differ compares sentinels by name. | Avoids infinite recursion on `Node.children: [Node]` |
| Determinism | Changes are sorted by `(path, method, direction, field_path, rule)` | Stable snapshots and stable PR comments |
| Errors | Each error has a message, a file and JSON pointer, and a hint | Developer tools live or die by their error messages |
| Partial failure | One broken operation logs a warning and is skipped; the diff of the rest continues | Real specs are messy |
| 3.2 | `UnsupportedVersionError`, with a hint that it is planned | Explicit beats silently wrong |

## Shared schemas: one change, many endpoints

Removing `User.name` when `User` is used by 8 operations must not print 8 unrelated changes. The differ still emits one `APIChange` per operation, because the impact engine needs the `(method, path)` of each one. Reporters then group changes by `(rule, schema_name, field_path)`:

```text
🔴 response.property.removed  User.name
   affects 8 operations: GET /users/{id}, GET /users, GET /teams/{id}/members, …
```

`APIChange.group_key` makes this grouping explicit. JSON output contains both the flat list and the groups.

## CLI surface (v0.1)

```text
breakscope diff OLD NEW [--format terminal|json] [--min-severity breaking|warning|info] [--output FILE]
```

- `OLD`/`NEW` accept paths now. `git:<ref>:<path>` comes in v0.5.
- Exit codes: `0` no breaking changes, `1` breaking changes present, `2` error.

## Testing strategy

- `tests/contracts/rules/<rule_id>/{old,new}.yaml` holds one fixture per rule, auto-discovered by a parametrized test and snapshot-asserted
- `tests/contracts/test_normalize.py` checks that equivalent 3.0 and 3.1 forms normalize to equal `Schema`s
- `tests/contracts/corpus/` holds real-world specs, used only to assert "no crash, deterministic output"
- Target ≥90% coverage on `contracts/` and `changes.py`

## Dependencies

Runtime: `typer`, `rich`, `pydantic>=2`, `pyyaml`.
Dev: `pytest`, `syrupy`, `ruff`, `mypy`.
`tree-sitter` is **not** a v0.1 dependency.

## What v0.1 explicitly does not do

Code scanning, git refs, config files, remote `$ref`, deep `oneOf`/`anyOf` comparison, OpenAPI 3.2, Swagger 2.0.
