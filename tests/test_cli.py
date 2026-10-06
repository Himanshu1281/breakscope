import json
from pathlib import Path

from typer.testing import CliRunner

from breakscope import __version__
from breakscope.cli.main import app

runner = CliRunner()
DEMO = Path(__file__).parents[1] / "examples" / "demo" / "api"
V1, V2 = str(DEMO / "openapi-v1.yaml"), str(DEMO / "openapi-v2.yaml")


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_analyze_demo() -> None:
    result = runner.invoke(app, ["analyze", V1, V2, str(DEMO.parents[1] / "demo")])
    assert result.exit_code == 1, result.output
    assert "frontend/src/components/UserProfile.tsx:18" in result.output
    assert "<h1>{user.name}</h1>" in result.output
    assert "backend/services/user_report.py:12" in result.output
    assert "Locations affected: 4" in result.output
    assert "Risk: HIGH" in result.output


def test_analyze_fail_on_never_exits_0() -> None:
    demo = str(DEMO.parents[1] / "demo")
    assert runner.invoke(app, ["analyze", V1, V2, demo, "--fail-on", "never"]).exit_code == 0


def test_analyze_no_changes_exits_0() -> None:
    result = runner.invoke(app, ["analyze", V1, V1, str(DEMO.parents[1] / "demo")])
    assert result.exit_code == 0
    assert "No contract changes" in result.output


def test_analyze_json() -> None:
    result = runner.invoke(app, ["analyze", V1, V2, str(DEMO.parents[1] / "demo"), "-f", "json"])
    doc = json.loads(result.output)
    assert doc["summary"]["risk"] == "high"
    removed = next(c for c in doc["changes"] if c["subject"] == "User.name")
    assert {(i["file"], i["confidence"]) for i in removed["impacts"]} == {
        ("frontend/src/components/UserProfile.tsx", "high"),
        ("backend/services/user_report.py", "high"),
    }


def test_analyze_bad_repo_exits_2() -> None:
    assert runner.invoke(app, ["analyze", V1, V2, "no-such-dir"]).exit_code == 2


def test_diff_breaking_exits_1() -> None:
    result = runner.invoke(app, ["diff", V1, V2])
    assert result.exit_code == 1
    assert "response.property.removed" in result.output
    assert "User.name" in result.output


def test_diff_identical_exits_0() -> None:
    result = runner.invoke(app, ["diff", V1, V1])
    assert result.exit_code == 0
    assert "No contract changes" in result.output


def test_diff_missing_file_exits_2() -> None:
    result = runner.invoke(app, ["diff", V1, "nope.yaml"])
    assert result.exit_code == 2
    assert "file not found" in result.output


def test_diff_json() -> None:
    result = runner.invoke(app, ["diff", V1, V2, "--format", "json"])
    assert result.exit_code == 1
    doc = json.loads(result.output)
    assert doc["schema_version"] == 1
    groups = {(g["rule"], g["subject"]): g for g in doc["groups"]}
    assert len(groups[("response.property.removed", "User.name")]["operations"]) == 3


def test_min_severity_filters_output_not_exit_code() -> None:
    hidden = runner.invoke(app, ["diff", V1, V2, "-f", "json"])
    shown = runner.invoke(app, ["diff", V1, V2, "-f", "json", "--min-severity", "info"])
    rules = {c["rule"] for c in json.loads(hidden.output)["changes"]}
    assert "response.enum.value_removed" not in rules
    assert "response.enum.value_removed" in {c["rule"] for c in json.loads(shown.output)["changes"]}
    assert hidden.exit_code == shown.exit_code == 1


def test_output_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = runner.invoke(app, ["diff", V1, V2, "-f", "json", "-o", str(out)])
    assert result.exit_code == 1
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["breaking"] > 0
