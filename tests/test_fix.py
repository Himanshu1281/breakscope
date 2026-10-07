import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from breakscope.cli.main import app
from breakscope.fix import _edit_at

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "demo"
runner = CliRunner()


def apply(line: str, column: int) -> str | None:
    edit = _edit_at("f", 1, line, column, "name", "full_name")
    if edit is None:
        return None
    return line[: edit.start] + edit.replacement + line[edit.end :]


@pytest.mark.parametrize(
    ("line", "token_at", "expected"),
    [
        ("<h1>{user.name}</h1>", "name}", "<h1>{user.full_name}</h1>"),
        ("x = user?.name ?? ''", "name ", "x = user?.full_name ?? ''"),
        ('return data["name"]', '"name"', 'return data["full_name"]'),
        ("return data.get('name')", "'name'", "return data.get('full_name')"),
        ("const { name } = user;", "name }", "const { full_name: name } = user;"),
        ("const { id, name: n } = user;", "name:", "const { id, full_name: n } = user;"),
        # Only the traced read changes, not a look-alike on the same line.
        (
            "<h2 className={theme.name}>{user.name}</h2>",
            "name}</h2>",
            "<h2 className={theme.name}>{user.full_name}</h2>",
        ),
        # Reported deeper in the chain: fix the nearest `.name` before it.
        ("user.name.first", "first", "user.full_name.first"),
    ],
)
def test_edit_forms(line: str, token_at: str, expected: str) -> None:
    column = line.rindex(token_at) + 1
    assert apply(line, column) == expected


def test_refuses_when_text_does_not_match() -> None:
    assert apply("const label = title;", 7) is None


def test_fix_demo_patch_applies(tmp_path: Path) -> None:
    patch = tmp_path / "fix.patch"
    result = runner.invoke(
        app,
        [
            "fix",
            str(DEMO / "api" / "openapi-v1.yaml"),
            str(DEMO / "api" / "openapi-v2.yaml"),
            str(DEMO),
            "-o",
            str(patch),
        ],
    )
    assert result.exit_code == 0, result.output
    text = patch.read_text(encoding="utf-8")
    assert '+    return resp.json()["full_name"]' in text
    assert "+      <h1>{user.full_name}</h1>" in text
    assert "rename: User.name -> full_name" in result.output
    check = subprocess.run(
        ["git", "apply", "--check", "--directory=examples/demo", str(patch)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_fix_never_writes_files() -> None:
    result = runner.invoke(app, ["fix", "a.yaml", "b.yaml", "--no-dry-run"])
    assert result.exit_code == 2
    assert "only prints patches" in result.output
