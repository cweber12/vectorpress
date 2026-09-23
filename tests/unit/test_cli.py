from typer.testing import CliRunner

from vectorpress import __version__
from vectorpress.cli.app import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
