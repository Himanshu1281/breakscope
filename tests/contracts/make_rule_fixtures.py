"""Regenerate tests/contracts/rules/<rule>/{old,new}.yaml.

Each fixture is the same small base spec with one mutation applied, so every fixture
isolates exactly one rule. Run: python tests/contracts/make_rule_fixtures.py
"""

import copy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

D = dict[str, Any]
OUT = Path(__file__).parent / "rules"


def ref(name: str) -> D:
    return {"$ref": f"#/components/schemas/{name}"}


def json_body(schema: D) -> D:
    return {"application/json": {"schema": schema}}


BASE: D = {
    "openapi": "3.0.3",
    "info": {"title": "Fixture", "version": "1"},
    "paths": {
        "/items/{id}": {
            "get": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    {"name": "q", "in": "query", "schema": {"type": "string", "enum": ["a", "b"]}},
                ],
                "responses": {"200": {"description": "ok", "content": json_body(ref("Item"))}},
            },
            "put": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
                "requestBody": {"content": json_body(ref("ItemInput"))},
                "responses": {"200": {"description": "ok", "content": json_body(ref("Item"))}},
            },
        }
    },
    "components": {
        "schemas": {
            "Item": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "status": {"type": "string", "enum": ["on", "off"]},
                    "created": {"type": "string", "format": "date-time"},
                    "shape": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                },
            },
            "ItemInput": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["x", "y"]},
                    "count": {"type": "integer"},
                },
            },
        }
    },
}


def get(s: D) -> D:
    return s["paths"]["/items/{id}"]["get"]


def put(s: D) -> D:
    return s["paths"]["/items/{id}"]["put"]


def item(s: D) -> D:
    return s["components"]["schemas"]["Item"]


def item_input(s: D) -> D:
    return s["components"]["schemas"]["ItemInput"]


def q(s: D) -> D:
    return get(s)["parameters"][1]


def _remove_body(s: D) -> None:
    del put(s)["requestBody"]


def _add_required_body(s: D) -> None:
    put(s)["requestBody"] = {"required": True, "content": json_body(ref("ItemInput"))}


# rule -> (mutate old, mutate new)
Mut = Callable[[D], None]
FIXTURES: dict[str, tuple[Mut | None, Mut]] = {
    "endpoint.removed": (None, lambda s: s["paths"]["/items/{id}"].pop("put")),
    "endpoint.added": (
        None,
        lambda s: s["paths"]["/items/{id}"].update(
            delete={"responses": {"204": {"description": "gone"}}}
        ),
    ),
    "parameter.removed": (None, lambda s: get(s)["parameters"].pop(1)),
    "parameter.added.required": (
        None,
        lambda s: get(s)["parameters"].append(
            {"name": "r", "in": "query", "required": True, "schema": {"type": "string"}}
        ),
    ),
    "parameter.added.optional": (
        None,
        lambda s: get(s)["parameters"].append(
            {"name": "o", "in": "query", "schema": {"type": "string"}}
        ),
    ),
    "parameter.became_required": (None, lambda s: q(s).update(required=True)),
    "parameter.type.changed": (None, lambda s: q(s).update(schema={"type": "integer"})),
    "parameter.enum.value_removed": (None, lambda s: q(s)["schema"].update(enum=["a"])),
    "request.body.added.required": (_remove_body, _add_required_body),
    "request.body.became_required": (None, lambda s: put(s)["requestBody"].update(required=True)),
    "request.media_type.removed": (
        None,
        lambda s: put(s)["requestBody"].update(
            content={"application/xml": {"schema": ref("ItemInput")}}
        ),
    ),
    "request.property.added.required": (
        None,
        lambda s: item_input(s).update(
            required=["owner"],
            properties={**item_input(s)["properties"], "owner": {"type": "string"}},
        ),
    ),
    "request.property.became_required": (None, lambda s: item_input(s).update(required=["name"])),
    "request.property.type.changed": (
        None,
        lambda s: item_input(s)["properties"].update(count={"type": "string"}),
    ),
    "request.property.enum.value_removed": (
        None,
        lambda s: item_input(s)["properties"]["kind"].update(enum=["x"]),
    ),
    "request.property.removed": (None, lambda s: item_input(s)["properties"].pop("count")),
    "response.status.removed": (
        None,
        lambda s: get(s).update(responses={"201": get(s)["responses"]["200"]}),
    ),
    "response.media_type.removed": (
        None,
        lambda s: get(s)["responses"]["200"].update(
            content={"application/xml": {"schema": ref("Item")}}
        ),
    ),
    "response.property.removed": (None, lambda s: item(s)["properties"].pop("name")),
    "response.property.became_optional": (None, lambda s: item(s).update(required=["id"])),
    "response.property.became_nullable": (
        None,
        lambda s: item(s)["properties"]["name"].update(nullable=True),
    ),
    "response.property.type.changed": (
        None,
        lambda s: item(s)["properties"].update(id={"type": "string"}),
    ),
    "response.property.format.changed": (
        None,
        lambda s: item(s)["properties"]["created"].update(format="date"),
    ),
    "response.enum.value_added": (
        None,
        lambda s: item(s)["properties"]["status"].update(enum=["on", "off", "paused"]),
    ),
    "response.enum.value_removed": (
        None,
        lambda s: item(s)["properties"]["status"].update(enum=["on"]),
    ),
    "response.property.added": (
        None,
        lambda s: item(s)["properties"].update(color={"type": "string"}),
    ),
    "schema.union.changed": (
        None,
        lambda s: item(s)["properties"].update(
            shape={"oneOf": [{"type": "string"}, {"type": "boolean"}]}
        ),
    ),
}


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    for rule, (mut_old, mut_new) in FIXTURES.items():
        old, new = copy.deepcopy(BASE), copy.deepcopy(BASE)
        if mut_old:
            mut_old(old)
            mut_old(new)
        mut_new(new)
        d = OUT / rule
        d.mkdir(parents=True)
        for name, spec in (("old", old), ("new", new)):
            text = yaml.safe_dump(spec, sort_keys=False, width=100)
            (d / f"{name}.yaml").write_text(text, encoding="utf-8")
    print(f"wrote {len(FIXTURES)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
