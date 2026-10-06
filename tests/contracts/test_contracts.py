from pathlib import Path
from textwrap import dedent

import pytest

from breakscope.contracts import diff_files, load_contract
from breakscope.errors import RefError, SpecLoadError, UnsupportedVersionError

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "examples" / "demo" / "api"
CORPUS = sorted((Path(__file__).parent / "corpus").glob("*.yaml"))


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(text), encoding="utf-8")
    return p


def spec(version: str, user_schema: str, extra: str = "") -> str:
    return f"""\
openapi: {version}
info: {{title: t, version: "1"}}
paths:
  /users/{{id}}:
    get:
      parameters: [{{name: id, in: path, required: true, schema: {{type: integer}}}}]
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {{$ref: "#/components/schemas/User"}}
components:
  schemas:
    User:
{user_schema}
{extra}"""


# -- the M1 demo gate ----------------------------------------------------------------


def test_demo_gate() -> None:
    changes, _, _ = diff_files(DEMO / "openapi-v1.yaml", DEMO / "openapi-v2.yaml")
    removed = [c for c in changes if c.rule == "response.property.removed"]
    assert ("GET", "/users/{userId}", ("name",)) in {
        (c.method, c.path, c.field_path) for c in removed
    }
    assert {c.subject for c in removed} == {"User.name"}
    # The path parameter was renamed {id} -> {userId}; that is not a removal.
    assert not any(c.rule == "endpoint.removed" and c.method == "GET" for c in changes)


# -- normalization: 3.0 and 3.1 forms are equivalent ----------------------------------


NULLABLE_30 = """\
      type: object
      properties:
        name: {type: string, nullable: true}
        role: {type: string, enum: [admin, user]}"""
NULLABLE_31 = """\
      type: object
      properties:
        name: {type: [string, "null"]}
        role: {type: string, enum: [admin, user]}"""
NULLABLE_ANYOF = """\
      type: object
      properties:
        name: {anyOf: [{type: string}, {type: "null"}]}
        role: {type: string, enum: [admin, user]}"""
ALLOF = """\
      allOf:
        - type: object
          properties:
            name: {type: string, nullable: true}
        - type: object
          properties:
            role: {type: string, enum: [admin, user]}"""


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (("3.0.3", NULLABLE_30), ("3.1.0", NULLABLE_31)),
        (("3.0.3", NULLABLE_30), ("3.1.0", NULLABLE_ANYOF)),
        (("3.0.3", NULLABLE_30), ("3.0.3", ALLOF)),
    ],
    ids=["type-list", "anyOf-null", "allOf"],
)
def test_equivalent_forms_produce_no_changes(
    tmp_path: Path, old: tuple[str, str], new: tuple[str, str]
) -> None:
    a = write(tmp_path, "a.yaml", spec(*old))
    b = write(tmp_path, "b.yaml", spec(*new))
    assert diff_files(a, b)[0] == []


def test_nullable_detected_across_versions(tmp_path: Path) -> None:
    a = write(tmp_path, "a.yaml", spec("3.0.3", NULLABLE_30.replace(", nullable: true", "")))
    b = write(tmp_path, "b.yaml", spec("3.1.0", NULLABLE_31))
    changes, _, _ = diff_files(a, b)
    assert [(c.rule, c.subject) for c in changes] == [
        ("response.property.became_nullable", "User.name")
    ]


# -- $ref resolution ------------------------------------------------------------------


RECURSIVE = """\
      type: object
      properties:
        name: {type: string}
        manager: {$ref: "#/components/schemas/User"}
        reports: {type: array, items: {$ref: "#/components/schemas/User"}}"""


def test_recursive_schema_terminates(tmp_path: Path) -> None:
    a = write(tmp_path, "a.yaml", spec("3.0.3", RECURSIVE))
    b = write(tmp_path, "b.yaml", spec("3.0.3", RECURSIVE.replace("name", "full_name")))
    changes, _, _ = diff_files(a, b)
    removed = [c for c in changes if c.rule == "response.property.removed"]
    assert [(c.field_path, c.subject) for c in removed] == [(("name",), "User.name")]


def test_external_file_ref_keeps_schema_name(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    write(tmp_path, "schemas/user.yaml", "type: object\nproperties:\n  name: {type: string}\n")
    write(tmp_path, "schemas/user2.yaml", "type: object\nproperties:\n  nick: {type: string}\n")
    a = write(tmp_path, "a.yaml", spec("3.0.3", '      $ref: "schemas/user.yaml"'))
    b = write(tmp_path, "b.yaml", spec("3.0.3", '      $ref: "schemas/user2.yaml"'))
    removed = [c for c in diff_files(a, b)[0] if c.rule == "response.property.removed"]
    assert [c.subject for c in removed] == ["User.name"]


@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ("https://example.com/user.yaml", "remote $ref is not supported"),
        ("#/components/schemas/Nope", "$ref target not found"),
        ("missing.yaml", "missing file"),
    ],
)
def test_bad_ref_skips_operation_instead_of_failing(tmp_path: Path, ref: str, reason: str) -> None:
    good = write(tmp_path, "a.yaml", spec("3.0.3", "      type: object"))
    bad = write(
        tmp_path,
        "b.yaml",
        spec("3.0.3", "      type: object").replace("#/components/schemas/User", ref),
    )
    contract = load_contract(bad)
    assert list(contract.skipped) == [("GET", "/users/{}")]
    assert reason in contract.skipped[("GET", "/users/{}")]
    # A broken operation must never show up as "endpoint.removed".
    assert diff_files(good, bad)[0] == []


def test_ref_chain_loop_is_reported(tmp_path: Path) -> None:
    p = write(
        tmp_path,
        "a.yaml",
        spec(
            "3.0.3",
            '      $ref: "#/components/schemas/Other"',
            '    Other: {$ref: "#/components/schemas/User"}',
        ),
    )
    reason = load_contract(p).skipped[("GET", "/users/{}")]
    assert "loops" in reason


def test_ref_error_carries_location(tmp_path: Path) -> None:
    from breakscope.contracts.resolver import Resolver

    with pytest.raises(RefError) as e:
        Resolver(tmp_path / "x.yaml", {}).resolve("#/components/schemas/X", tmp_path / "x.yaml")
    assert "x.yaml#/components/schemas/X" in e.value.render()


# -- loader errors --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "error", "needle"),
    [
        (
            "openapi: 3.2.0\ninfo: {}\npaths: {}\n",
            UnsupportedVersionError,
            "3.2 support is planned",
        ),
        ("swagger: '2.0'\n", UnsupportedVersionError, "swagger2openapi"),
        ("info: {}\n", SpecLoadError, "missing `openapi`"),
        ("- a\n- b\n", SpecLoadError, "not a mapping"),
        ("openapi: 3.0.0\npaths: {a: [\n", SpecLoadError, "invalid YAML"),
    ],
)
def test_loader_errors(tmp_path: Path, text: str, error: type[Exception], needle: str) -> None:
    p = write(tmp_path, "s.yaml", text)
    with pytest.raises(error) as e:
        load_contract(p)
    assert needle in e.value.render()  # type: ignore[attr-defined]


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SpecLoadError, match="file not found"):
        load_contract(tmp_path / "nope.yaml")


def test_json_spec(tmp_path: Path) -> None:
    p = write(tmp_path, "s.json", '{"openapi": "3.1.0", "info": {}, "paths": {"/a": {"get": {}}}}')
    assert list(load_contract(p).operations) == [("GET", "/a")]


# -- real-world corpus ----------------------------------------------------------------


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_corpus_loads_and_diffs_deterministically(path: Path) -> None:
    contract = load_contract(path)
    assert contract.skipped == {}
    assert diff_files(path, path)[0] == []
    other = CORPUS[(CORPUS.index(path) + 1) % len(CORPUS)]
    first = diff_files(path, other)[0]
    assert first == diff_files(path, other)[0]
