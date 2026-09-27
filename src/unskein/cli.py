from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from unskein import __version__
from unskein.ai.models import AIReport, Severity
from unskein.errors import ExitCode
from unskein.graph.metrics import AnalysisResult

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    epilog="Exit codes: 0=OK, 1=usage error, 2=high-severity problems found, 3=internal error.",
)


@dataclass
class ScanOptions:
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


def run_scan(options: ScanOptions) -> tuple[AnalysisResult, AIReport | None]:
    """discover -> parse -> resolve -> analyze -> AI (optional).

    Raises UnskeinError on usage errors.
    """
    raise NotImplementedError


def exit_code_for(ai_report: AIReport | None) -> ExitCode:
    if ai_report and any(p.severity == "high" for p in ai_report.problems):
        return ExitCode.HIGH_SEVERITY_FOUND
    return ExitCode.OK


def _version_callback(value: bool) -> None:
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


@app.command()
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
    encoding: Annotated[
        str | None, typer.Option("--encoding", help="Fallback encoding when undetectable.")
    ] = None,
) -> None:
    """Analyze a Python project and print a dependency/coupling report."""
    raise NotImplementedError
