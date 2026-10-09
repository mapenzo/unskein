import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import Result
from typer.testing import CliRunner

from unskein import __version__
from unskein.ai.models import AIReport, Problem
from unskein.cli import app, exit_code_for, run
from unskein.errors import ExitCode

runner = CliRunner()

# Rich forces color on CI (GITHUB_ACTIONS, FORCE_COLOR) and splits option names with ANSI codes.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI color codes from CLI output.

    Args:
        text: Output that may contain ANSI escapes.

    Returns:
        The text without them.
    """
    return ANSI_ESCAPE.sub("", text)


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_scan_help_lists_exit_codes() -> None:
    result = runner.invoke(app, ["scan", "--help"])
    assert result.exit_code == 0
    output = plain(result.output)
    assert "--no-ai" in output
    assert "--include-tests" in output
    assert "--no-include-tests" in output
    assert "--no-follow-symlinks" in output
    assert "--star-fixes" in output
    assert "--no-star-fixes" in output
    assert "Exit codes" in output


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


def scan_cli(*args: str) -> Result:
    """Invoke ``unskein scan`` in-process with the given arguments.

    Args:
        *args: Arguments after ``scan``.

    Returns:
        The CliRunner result, with plain (ANSI-free) output in ``result.output``.
    """
    return runner.invoke(app, ["scan", *args])


def run_entry_point(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    """Run the real ``unskein`` console entry point and return its exit code.

    Args:
        monkeypatch: Pytest monkeypatch fixture, to set ``sys.argv``.
        *argv: Arguments after the program name.

    Returns:
        The process exit code.
    """
    monkeypatch.setattr(sys, "argv", ["unskein", *argv])
    with pytest.raises(SystemExit) as exc:
        run()
    return exc.value.code


def test_scan_fixture_prints_report_and_exits_ok(circular_imports: Path) -> None:
    result = scan_cli(str(circular_imports), "--no-ai", "--lang", "en")
    assert result.exit_code == ExitCode.OK
    output = plain(result.output)
    assert "Analysis of circular_imports" in output
    assert "app.a" in output
    assert "--no-ai" in output


def test_report_language_follows_flag(circular_imports: Path) -> None:
    output = plain(scan_cli(str(circular_imports), "--no-ai", "--lang", "es").output)
    assert "Análisis de circular_imports" in output


def test_output_file_gets_raw_markdown(circular_imports: Path, tmp_path: Path) -> None:
    target = tmp_path / "report.md"
    result = scan_cli(str(circular_imports), "--no-ai", "--lang", "en", "-o", str(target))
    assert result.exit_code == ExitCode.OK
    assert target.read_text(encoding="utf-8").startswith("# Analysis of circular_imports")


def test_missing_path_exits_1_with_translated_message(tmp_path: Path) -> None:
    # A long path must not be hard-wrapped: users copy paths out of error messages.
    missing = tmp_path / ("very_long_directory_name_" * 4) / "nope"
    result = scan_cli(str(missing), "--lang", "es")
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert f"La ruta '{missing}' no existe" in plain(result.output)
    assert "Traceback" not in result.output


def test_invalid_config_exits_1_with_translated_message(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / ".unskein.toml").write_text("[analysis]\nbogus = 1\n")
    result = scan_cli(str(tmp_path), "--lang", "en")
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "Unknown setting 'analysis.bogus'" in plain(result.output)


def test_unexpected_error_exits_3_with_traceback(
    circular_imports: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(context: object) -> None:
        """Simulate a bug deep in the pipeline.

        Args:
            context: Ignored scan context.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError("simulated bug")

    monkeypatch.setattr("unskein.cli.analyze_project", boom)
    result = scan_cli(str(circular_imports), "--no-ai")
    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "simulated bug" in plain(result.output)
    assert "Traceback" in plain(result.output)


def test_verbose_shows_performance_stats(circular_imports: Path) -> None:
    output = plain(scan_cli(str(circular_imports), "--no-ai", "--lang", "en", "-v").output)
    assert "Duration" in output
    assert "peak memory" in output


def test_invalid_choice_is_rejected(circular_imports: Path) -> None:
    assert scan_cli(str(circular_imports), "--lang", "fr").exit_code != ExitCode.OK


def test_usage_error_exits_1_not_2(monkeypatch: pytest.MonkeyPatch) -> None:
    assert run_entry_point(monkeypatch, "scan", "--bogus-flag") == ExitCode.USAGE_ERROR


def test_entry_point_propagates_scan_exit_code(
    monkeypatch: pytest.MonkeyPatch, circular_imports: Path
) -> None:
    assert run_entry_point(monkeypatch, "scan", str(circular_imports), "--no-ai") == ExitCode.OK


def test_python_dash_m_uses_the_same_exit_codes() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "unskein", "scan", "--bogus-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == ExitCode.USAGE_ERROR


def test_legacy_console_encoding_does_not_crash(circular_imports: Path) -> None:
    # Windows pipes use the ANSI code page (cp1252), which has no "→" for cycles.
    completed = subprocess.run(
        [sys.executable, "-m", "unskein", "scan", str(circular_imports), "--no-ai"],
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert completed.returncode == ExitCode.OK


def test_error_message_shows_brackets_in_paths_literally(tmp_path: Path) -> None:
    missing = tmp_path / "proj[v2]" / "[bold]x"
    result = scan_cli(str(missing), "--lang", "en")
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert f"Path '{missing}' does not exist" in plain(result.output)


def test_ai_waiting_indicator_stays_silent_off_a_terminal(
    circular_imports: Path, monkeypatch: pytest.MonkeyPatch, fake_llm: Any
) -> None:
    fake_llm.content = AIReport(
        summary="s", architecture_health="fair", problems=[]
    ).model_dump_json()
    monkeypatch.setenv("UNSKEIN_AI_MODEL", "ollama/x")
    result = scan_cli(str(circular_imports), "--lang", "en")
    assert result.exit_code == ExitCode.OK
    assert "Asking the model" not in plain(result.output)
    assert len(fake_llm.calls) == 1


def test_no_findings_flag_is_accepted(circular_imports: Path) -> None:
    result = scan_cli(str(circular_imports), "--no-ai", "--lang", "en", "--no-findings")

    assert result.exit_code == 0
    assert "Findings" not in plain(result.output)


def test_findings_section_is_shown_by_default(circular_imports: Path) -> None:
    result = scan_cli(str(circular_imports), "--no-ai", "--lang", "en")

    assert result.exit_code == 0
    assert "Findings" in plain(result.output)


def test_scan_of_a_workspace_counts_member_imports_as_internal() -> None:
    root = Path(__file__).parent.parent / "fixtures" / "workspace_monorepo"
    result = runner.invoke(app, ["scan", str(root), "--no-ai", "--lang", "en"])
    assert result.exit_code == 0
    assert "core_enterprise" in result.output
    assert ".circleci.scripts" not in result.output
