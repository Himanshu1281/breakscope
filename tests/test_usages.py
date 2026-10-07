import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from breakscope.analyzers import is_test_file, iter_source_files, scan_repo
from breakscope.analyzers.base import CallSite, UrlTemplate
from breakscope.cli.main import app
from breakscope.contracts import load_contract
from breakscope.contracts.model import Contract
from breakscope.usages import Matcher, Unmatched, Usage, index_usages

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "demo"
runner = CliRunner()


def contract(tmp_path: Path, paths: dict[str, list[str]], servers: str = "") -> Contract:
    lines = ["openapi: 3.0.3", "info: {title: t, version: '1'}", servers, "paths:"]
    for path, methods in paths.items():
        lines.append(f"  {path}:")
        lines += [f"    {m}: {{responses: {{'200': {{description: ok}}}}}}" for m in methods]
    p = tmp_path / "spec.yaml"
    p.write_text("\n".join(lines), encoding="utf-8")
    return load_contract(p)


def site(path: str, method: str | None = "GET", *, open_start: bool = False) -> CallSite:
    segs = tuple(s for s in path.split("/") if s)
    return CallSite(
        file="a.ts",
        line=1,
        column=1,
        language="typescript",
        client="fetch",
        method=method,
        url=UrlTemplate(segs, open_start=open_start, absolute=False),
        url_source="",
        code="",
        is_test=False,
        start_byte=0,
        end_byte=0,
    )


def keys(result: list[Usage] | Unmatched | None) -> list[tuple[str, str]]:
    assert isinstance(result, list), result
    return [u.key for u in result]


# -- matcher --------------------------------------------------------------------------


def test_literal_segment_beats_parameter(tmp_path: Path) -> None:
    m = Matcher(contract(tmp_path, {"/users/{id}": ["get"], "/users/me": ["get"]}))
    assert keys(m.match(site("/users/me"))) == [("GET", "/users/me")]
    assert keys(m.match(site("/users/{}"))) == [("GET", "/users/{}")]
    assert keys(m.match(site("/users/42"))) == [("GET", "/users/{}")]


def test_dynamic_segment_never_matches_literal(tmp_path: Path) -> None:
    m = Matcher(contract(tmp_path, {"/users/me": ["get"]}))
    assert isinstance(m.match(site("/users/{}")), Unmatched)


def test_server_base_path_is_stripped(tmp_path: Path) -> None:
    c = contract(tmp_path, {"/users": ["get"]}, "servers: [{url: 'https://api.x.com/v1'}]")
    assert c.base_paths == ("/v1",)
    usages = Matcher(c).match(site("/v1/users"))
    assert keys(usages) == [("GET", "/users")]
    assert isinstance(usages, list) and usages[0].match == "exact"


def test_user_base_url_is_stripped(tmp_path: Path) -> None:
    c = contract(tmp_path, {"/users": ["get"]})
    usages = Matcher(c, ["/api/v2"]).match(site("/api/v2/users"))
    assert isinstance(usages, list) and usages[0].match == "exact"


def test_unknown_prefix_is_guessed_with_lower_confidence(tmp_path: Path) -> None:
    usages = Matcher(contract(tmp_path, {"/users": ["get"]})).match(site("/api/users"))
    assert isinstance(usages, list) and usages[0].match == "prefix"


def test_method_mismatch_is_explained(tmp_path: Path) -> None:
    result = Matcher(contract(tmp_path, {"/users": ["get", "post"]})).match(site("/users", "PUT"))
    assert isinstance(result, Unmatched)
    assert result.reason == "/users has no PUT operation (has GET, POST)"


def test_unknown_method_matches_every_operation_on_the_path(tmp_path: Path) -> None:
    result = Matcher(contract(tmp_path, {"/users": ["get", "post"]})).match(site("/users", None))
    assert isinstance(result, list)
    assert sorted(u.key for u in result) == [("GET", "/users"), ("POST", "/users")]
    assert {u.match for u in result} == {"method_unknown"}


def test_parameter_names_do_not_matter(tmp_path: Path) -> None:
    m = Matcher(contract(tmp_path, {"/orgs/{org}/repos/{repo}": ["get"]}))
    assert keys(m.match(site("/orgs/{}/repos/{}"))) == [("GET", "/orgs/{}/repos/{}")]


# -- scanner --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/api.py", True),
        ("src/__tests__/a.ts", True),
        ("src/user.test.tsx", True),
        ("src/user.spec.ts", True),
        ("test_users.py", True),
        ("users_test.py", True),
        ("src/latest/users.ts", False),
        ("src/contest.py", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    from pathlib import PurePosixPath

    assert is_test_file(PurePosixPath(path)) is expected


def test_scanner_skips_vendored_generated_and_excluded(tmp_path: Path) -> None:
    for rel in [
        "src/a.ts",
        "src/types.d.ts",
        "src/b.min.js",
        "node_modules/x/index.js",
        ".venv/lib/x.py",
        "src/gen/client.ts",
        "README.md",
    ]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('fetch("/x")', encoding="utf-8")
    files = iter_source_files(tmp_path, ("src/gen/*",))
    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["src/a.ts"]


def test_scan_survives_syntax_errors_and_bad_encoding(tmp_path: Path) -> None:
    (tmp_path / "broken.ts").write_text('fetch("/users");\nconst = = ;', encoding="utf-8")
    (tmp_path / "latin1.py").write_bytes(b'# caf\xe9\nrequests.get("/users")\n')
    result = scan_repo(tmp_path)
    assert result.files_scanned == 2
    assert {s.file for s in result.sites} == {"broken.ts", "latin1.py"}


# -- M2 gate and CLI ------------------------------------------------------------------


def test_demo_gate() -> None:
    c = load_contract(DEMO / "api" / "openapi-v1.yaml")
    index = index_usages(c, scan_repo(DEMO).sites)
    files = {u.site.file for u in index.by_operation[("GET", "/users/{}")]}
    assert files == {
        "frontend/src/components/UserProfile.tsx",
        "backend/services/user_report.py",
    }
    assert index.unmatched == [] and index.unresolved == []
    assert all(c in index.by_operation for c in c.operations)


def test_cli_usages() -> None:
    result = runner.invoke(app, ["usages", str(DEMO / "api" / "openapi-v1.yaml"), str(DEMO)])
    assert result.exit_code == 0, result.output
    assert "GET /users/{id}" in result.output
    assert "frontend/src/components/UserProfile.tsx:9" in result.output
    assert "4 of 4 operations used" in result.output


def test_cli_usages_json_against_v2_reports_the_removed_endpoint() -> None:
    result = runner.invoke(
        app, ["usages", str(DEMO / "api" / "openapi-v2.yaml"), str(DEMO), "-f", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.output)
    assert doc["summary"]["call_sites"] == 6
    # DELETE /users/{id} no longer exists in v2, so that call has nowhere to go.
    (unmatched,) = doc["unmatched"]
    assert unmatched["method"] == "DELETE"
    assert unmatched["reason"] == "/users/{} has no DELETE operation (has GET)"


def test_cli_usages_missing_repo() -> None:
    result = runner.invoke(app, ["usages", str(DEMO / "api" / "openapi-v1.yaml"), "nope-dir"])
    assert result.exit_code == 2


def test_cli_usages_bad_spec(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(dedent("swagger: '2.0'\n"), encoding="utf-8")
    result = runner.invoke(app, ["usages", str(bad), str(tmp_path)])
    assert result.exit_code == 2
    assert "swagger2openapi" in result.output


def test_receiver_matches_class_name() -> None:
    from breakscope.impact.resolver import _receiver_matches

    assert _receiver_matches("this.userService", "UserService")
    assert _receiver_matches("self.user_service", "UserService")
    assert _receiver_matches("userService", "UserService")
    assert not _receiver_matches("this.http", "UserService")
    assert not _receiver_matches(None, "UserService")


def test_receiver_matches_singular_and_plural() -> None:
    from breakscope.impact.resolver import _receiver_matches

    assert _receiver_matches("this.articleService", "ArticlesService")
    assert _receiver_matches("this.articlesService", "ArticleService")
    assert not _receiver_matches("this.commentService", "ArticlesService")
