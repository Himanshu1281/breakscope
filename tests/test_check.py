import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from breakscope.cli.main import app
from breakscope.config import Config, find_specs, load_config
from breakscope.errors import BreakScopeError
from breakscope.gitspec import parse_spec_arg, spec_at_ref
from breakscope.reports.markdown import MARKER, _code

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "demo"
runner = CliRunner()

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The demo app on `main` with the v1 spec, then a `feature` branch with v2."""
    shutil.copytree(DEMO / "frontend", tmp_path / "frontend")
    shutil.copytree(DEMO / "backend", tmp_path / "backend")
    (tmp_path / "api").mkdir()
    # A split spec: the schema lives in a sibling file reached by relative $ref.
    v1 = (DEMO / "api" / "openapi-v1.yaml").read_text(encoding="utf-8")
    (tmp_path / "api" / "openapi.yaml").write_text(v1, encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "feature")
    v2 = (DEMO / "api" / "openapi-v2.yaml").read_text(encoding="utf-8")
    (tmp_path / "api" / "openapi.yaml").write_text(v2, encoding="utf-8")
    git(tmp_path, "commit", "-qam", "change")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_check_against_git_base(repo: Path) -> None:
    md, sarif, js = repo / "r.md", repo / "r.sarif", repo / "r.json"
    result = runner.invoke(
        app,
        [
            "check",
            "--spec",
            "api/openapi.yaml",
            "--base",
            "main",
            "--markdown",
            str(md),
            "--sarif",
            str(sarif),
            "--json",
            str(js),
            "--link-base",
            "https://github.com/o/r/blob/abc",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "Comparing main:api/openapi.yaml -> api/openapi.yaml" in result.output
    report = md.read_text(encoding="utf-8")
    assert report.startswith(MARKER)
    assert "4 breaking API changes, 4 affected locations" in report
    assert "(https://github.com/o/r/blob/abc/frontend/src/components/UserProfile.tsx#L18)" in report
    assert "`` const res = await fetch(`${API_URL}/users`, { ``" in report
    run = json.loads(sarif.read_text(encoding="utf-8"))["runs"][0]
    assert run["tool"]["driver"]["name"] == "BreakScope"
    levels = {r["level"] for r in run["results"]}
    assert levels <= {"error", "warning", "note"} and "error" in levels
    assert json.loads(js.read_text(encoding="utf-8"))["summary"]["locations"] == 4


def test_check_uses_config_file(repo: Path) -> None:
    (repo / ".breakscope.yml").write_text(
        "spec: api/openapi.yaml\nbase: main\nfail-on: never\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert "Risk: HIGH" in result.output


def test_check_new_spec_has_nothing_to_compare(repo: Path) -> None:
    (repo / "api" / "new.yaml").write_text(
        (DEMO / "api" / "openapi-v2.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    md = repo / "r.md"
    result = runner.invoke(
        app, ["check", "--spec", "api/new.yaml", "--base", "main", "--markdown", str(md)]
    )
    assert result.exit_code == 0, result.output
    assert "does not exist at main" in result.output
    assert "no API contract changes" in md.read_text(encoding="utf-8")


def test_check_unknown_ref_explains_fetch(repo: Path) -> None:
    result = runner.invoke(app, ["check", "--spec", "api/openapi.yaml", "--base", "origin/x"])
    assert result.exit_code == 2
    assert "git ref not found: origin/x" in result.output
    assert "fetch-depth: 0" in result.output


def test_check_without_spec_points_to_init(repo: Path) -> None:
    result = runner.invoke(app, ["check", "--base", "main"])
    assert result.exit_code == 2
    assert "breakscope init" in result.output


def test_check_with_old_file_needs_no_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    result = runner.invoke(
        app,
        [
            "check",
            "--repo",
            str(DEMO),
            "--spec",
            "api/openapi-v2.yaml",
            "--old",
            str(DEMO / "api" / "openapi-v1.yaml"),
            "--fail-on",
            "never",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Locations affected: 4" in result.output


def test_git_spec_arg_in_diff(repo: Path) -> None:
    result = runner.invoke(app, ["diff", "git:main:api/openapi.yaml", "api/openapi.yaml"])
    assert result.exit_code == 1
    assert "User.name" in result.output


def test_spec_at_ref_keeps_sibling_files_for_relative_refs(repo: Path) -> None:
    (repo / "api" / "schemas").mkdir()
    (repo / "api" / "schemas" / "user.yaml").write_text("type: object\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "split")
    with spec_at_ref(repo, "HEAD", "api/openapi.yaml") as local:
        assert local is not None
        assert (local.parent / "schemas" / "user.yaml").read_text() == "type: object\n"


@pytest.mark.parametrize(
    ("arg", "expected"),
    [
        ("git:origin/main:api/openapi.yaml", ("origin/main", "api/openapi.yaml")),
        ("git:HEAD~1:openapi.json", ("HEAD~1", "openapi.json")),
        ("api/openapi.yaml", None),
    ],
)
def test_parse_spec_arg(arg: str, expected: tuple[str, str] | None) -> None:
    assert parse_spec_arg(arg) == expected


def test_parse_spec_arg_rejects_garbage() -> None:
    with pytest.raises(BreakScopeError) as e:
        parse_spec_arg("git:nocolon")
    assert "git:<ref>:<path>" in e.value.render()


# -- init and config ------------------------------------------------------------------


def test_init_detects_spec_and_writes_workflow(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--repo", str(tmp_path), "--workflow"])
    assert result.exit_code == 0, result.output
    cfg = load_config(tmp_path / ".breakscope.yml")
    assert cfg.spec == "docs/openapi.yaml"
    wf = (tmp_path / ".github" / "workflows" / "breakscope.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in wf and "Himanshu1281/breakscope@v" in wf
    # A second run must not overwrite.
    assert runner.invoke(app, ["init", "--repo", str(tmp_path)]).exit_code == 2


def test_find_specs_prefers_openapi_names(tmp_path: Path) -> None:
    for rel in ["api/openapi.yaml", "a/b/openapi.json", "my-api.yaml", "other.yaml"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('openapi: "3.1.0"\n', encoding="utf-8")
    assert find_specs(tmp_path) == ["api/openapi.yaml", "a/b/openapi.json", "my-api.yaml"]


def test_config_accepts_kebab_and_snake_case(tmp_path: Path) -> None:
    p = tmp_path / "c.yml"
    p.write_text("spec: a.yaml\nfail-on: medium\nmin_confidence: low\n", encoding="utf-8")
    assert load_config(p) == Config(spec="a.yaml", fail_on="medium", min_confidence="low")


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("fail-on: sometimes\n", "fail-on"),
        ("speck: a.yaml\n", "speck"),
        ("- a\n", "must be a mapping"),
    ],
)
def test_config_errors_name_the_key(tmp_path: Path, text: str, needle: str) -> None:
    p = tmp_path / ".breakscope.yml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(BreakScopeError) as e:
        load_config(p)
    assert needle in e.value.render()


def test_missing_config_gives_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.yml") == Config()


# -- markdown details -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("user.name", "`user.name`"),
        ("fetch(`/users/${id}`)", "`` fetch(`/users/${id}`) ``"),
        ("a || b", "`a \\|\\| b`"),
    ],
)
def test_markdown_code_spans(code: str, expected: str) -> None:
    assert _code(code) == expected
