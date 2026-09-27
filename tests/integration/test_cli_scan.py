from typer.testing import CliRunner

from unskein import __version__
from unskein.ai.models import AIReport, Problem
from unskein.cli import app, exit_code_for
from unskein.errors import ExitCode

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_scan_help_lists_exit_codes() -> None:
    result = runner.invoke(app, ["scan", "--help"])
    assert result.exit_code == 0
    assert "--no-ai" in result.output


def test_exit_code_high_severity() -> None:
    report = AIReport(
        summary="",
        architecture_health="concerning",
        problems=[
            Problem(
                severity="high",
                title="cycle",
                description="",
                affected_modules=["a", "b"],
                recommendation="",
            )
        ],
    )
    assert exit_code_for(report) is ExitCode.HIGH_SEVERITY_FOUND
    assert exit_code_for(None) is ExitCode.OK
