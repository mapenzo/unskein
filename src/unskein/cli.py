"""Typer command-line interface: the ``scan`` command and its orchestration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from unskein import __version__
from unskein.ai.models import AIReport, Severity
from unskein.errors import ExitCode
from unskein.graph.metrics import AnalysisResult

EXIT_CODES_EPILOG = (
    "Exit codes: 0=OK, 1=usage error, 2=high-severity problems found, 3=internal error."
)

app = typer.Typer(add_completion=False, no_args_is_help=True, epilog=EXIT_CODES_EPILOG)


@dataclass
class ScanOptions:
    """Options of one ``scan`` run, decoupled from typer so it can be tested directly.

    Attributes:
        path: Directory to analyze.
        no_ai: Whether to skip the AI interpretation.
        exclude: Extra exclude patterns (gitignore syntax).
        min_severity: Lowest AI problem severity to report.
        verbose: Whether to show progress and performance stats.
        output: File to also write the Markdown report to.
        log_file: File to also write DEBUG logs to.
        api_key: Key from the insecure ``--api-key`` flag.
        lang: Requested output language.
        follow_symlinks: Whether discovery follows symlinked directories.
        encoding: Fallback encoding for files whose encoding cannot be detected.
        include_tests: Whether test code is analyzed.
    """

    path: Path
    no_ai: bool = False
    exclude: tuple[str, ...] = ()
    min_severity: Severity = "low"
    verbose: bool = False
    output: Path | None = None
    log_file: Path | None = None
    api_key: str | None = None
    lang: str | None = None
    follow_symlinks: bool = False
    encoding: str | None = None
    include_tests: bool = False


def run_scan(options: ScanOptions) -> tuple[AnalysisResult, AIReport | None]:
    """Run the pipeline: discover -> parse -> resolve -> analyze -> AI (optional).

    Kept apart from the typer command so it is testable and reusable as a library.

    Args:
        options: Options of this scan.

    Returns:
        The deterministic analysis and the AI report, or None when AI is
        disabled, not configured or failed.

    Raises:
        UnskeinError: On usage errors such as an invalid path or no Python files.
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def exit_code_for(ai_report: AIReport | None) -> ExitCode:
    """Map an AI report to the process exit code.

    Args:
        ai_report: The AI report, or None when there is none.

    Returns:
        HIGH_SEVERITY_FOUND if any problem is high severity, otherwise OK.
    """
    if ai_report and any(p.severity == "high" for p in ai_report.problems):
        return ExitCode.HIGH_SEVERITY_FOUND
    return ExitCode.OK


def _version_callback(value: bool) -> None:
    """Print the version and stop when ``--version`` is passed.

    Args:
        value: Whether the ``--version`` flag was given.

    Raises:
        typer.Exit: After printing the version, to end the command.
    """
    if value:
        typer.echo(f"unskein {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """AI-assisted static analysis of module dependencies and coupling."""


@app.command(epilog=EXIT_CODES_EPILOG)
def scan(
    path: Annotated[Path, typer.Argument(help="Directory to analyze.")] = Path("."),
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Skip AI interpretation.")] = False,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Extra exclude pattern (repeatable).")
    ] = None,
    min_severity: Annotated[
        str, typer.Option("--min-severity", help="low | medium | high")
    ] = "low",
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    log_file: Annotated[Path | None, typer.Option("--log-file")] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="INSECURE (shell history). Prefer UNSKEIN_API_KEY."),
    ] = None,
    lang: Annotated[str | None, typer.Option("--lang", help="es | en")] = None,
    follow_symlinks: Annotated[bool, typer.Option("--follow-symlinks")] = False,
    include_tests: Annotated[
        bool, typer.Option("--include-tests", help="Also analyze test code (excluded by default).")
    ] = False,
    encoding: Annotated[
        str | None, typer.Option("--encoding", help="Fallback encoding when undetectable.")
    ] = None,
) -> None:
    """Analyze a Python project and print a dependency/coupling report."""
    raise NotImplementedError
