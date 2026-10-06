from typer.testing import CliRunner

from breakscope import __version__
from breakscope.cli.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_analyze_stub_exits_2() -> None:
    assert runner.invoke(app, ["analyze"]).exit_code == 2
