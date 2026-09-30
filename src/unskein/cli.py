"""Typer command-line interface: argument parsing, output and exit codes only.

The pipeline itself lives in ``unskein.scan`` so it stays usable without typer.
"""

import io
import sys
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.markdown import Markdown

from unskein import __version__
from unskein.ai.models import AIReport, Severity
from unskein.errors import ExitCode, UnskeinError
from unskein.i18n import Lang, detect_lang, t, translate_error
from unskein.logging_setup import setup_logging
from unskein.perf import PerformanceStats, measure
from unskein.report.markdown import ReportContext, render_report
from unskein.scan import (
    ScanContext,
    ScanOptions,
    ScanOutcome,
    analyze_project,
    interpret,
    prepare_scan,
)

EXIT_CODES_EPILOG = (
    "Exit codes: 0=OK, 1=usage error, 2=high-severity problems found, 3=internal error."
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    epilog=EXIT_CODES_EPILOG,
    # Plain click help: rich tables squeeze the --x/--no-x columns unreadably at 80 columns.
    rich_markup_mode=None,
)


def run() -> None:
    """Console entry point: run the app, mapping click usage errors to exit code 1.

    Click exits with 2 on usage errors, but unskein reserves 2 for
    "high-severity problems found"; a script must be able to tell them apart.
    Typer vendors its own click, so only typer's public exception types are
    caught here (never ``click``'s).

    Raises:
        SystemExit: Always, with the process exit code.
    """
    _tolerate_legacy_console_encodings()
    try:
        code = app(standalone_mode=False)
    except typer.TyperException as e:
        # Usage errors carry show(), which prints the usage line and the hint.
        show = getattr(e, "show", None)
        if show:
            show()
        else:
            _print_to_stderr(str(e), style="red")
        sys.exit(ExitCode.USAGE_ERROR)
    except typer.Abort:
        sys.exit(ExitCode.USAGE_ERROR)
    sys.exit(code or ExitCode.OK)


def _tolerate_legacy_console_encodings() -> None:
    """Replace characters the console cannot encode instead of crashing.

    Windows pipes use the ANSI code page (e.g. cp1252), which lacks symbols
    the report uses such as "→"; without this, printing a cycle ends the run
    with an internal error. ``-o`` files are always written as full UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


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
def main(  # pylint: disable=unused-argument  # typer needs the eager param
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """AI-assisted static analysis of module dependencies and coupling."""


@app.command(epilog=EXIT_CODES_EPILOG)
def scan(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    path: Annotated[Path, typer.Argument(help="Directory to analyze.")] = Path("."),
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Skip AI interpretation.")] = False,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Extra exclude pattern (repeatable).")
    ] = None,
    min_severity: Annotated[
        Severity, typer.Option("--min-severity", help="Lowest AI problem severity to report.")
    ] = "low",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show progress and performance stats.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Also save the Markdown report here.")
    ] = None,
    log_file: Annotated[
        Path | None, typer.Option("--log-file", help="Also write debug logs to this file.")
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="INSECURE (shell history). Prefer UNSKEIN_API_KEY."),
    ] = None,
    lang: Annotated[
        Literal["es", "en"] | None, typer.Option("--lang", help="Output language.")
    ] = None,
    follow_symlinks: Annotated[
        bool | None,
        typer.Option(
            "--follow-symlinks/--no-follow-symlinks",
            help="Follow symlinked directories (default: no, or .unskein.toml).",
            show_default=False,
        ),
    ] = None,
    include_tests: Annotated[
        bool | None,
        typer.Option(
            "--include-tests/--no-include-tests",
            help="Also analyze test code (default: no, or .unskein.toml).",
            show_default=False,
        ),
    ] = None,
    encoding: Annotated[
        str | None, typer.Option("--encoding", help="Fallback encoding when undetectable.")
    ] = None,
) -> None:
    """Analyze a Python project and print a dependency/coupling report."""
    setup_logging(verbose, log_file)
    options = ScanOptions(
        path=path,
        no_ai=no_ai,
        exclude=tuple(exclude or ()),
        min_severity=min_severity,
        api_key=api_key,
        lang=lang,
        follow_symlinks=follow_symlinks,
        include_tests=include_tests,
        encoding=encoding,
    )
    try:
        code = _run_scan(options, output, verbose)
    except Exception:  # pylint: disable=broad-exception-caught  # any bug -> exit 3
        Console(stderr=True).print_exception()
        code = ExitCode.INTERNAL_ERROR
    raise typer.Exit(code)


def _run_scan(options: ScanOptions, output: Path | None, verbose: bool) -> ExitCode:
    """Prepare and execute the scan, print the report and pick the exit code.

    Expected errors become translated messages (exit code 1); anything else
    propagates to ``scan``, which shows the full traceback (exit code 3).

    Args:
        options: What the user asked for.
        output: File to also write the raw Markdown report to.
        verbose: Whether to print performance stats.

    Returns:
        The process exit code.
    """
    try:
        context = prepare_scan(options)
    except UnskeinError as e:
        # The TOML could not be read, so the language comes from flag, env and locale only.
        _print_to_stderr(translate_error(e, detect_lang(options.lang)), style="red")
        return ExitCode.USAGE_ERROR
    try:
        outcome, stats = measure(lambda: _run_pipeline(context))
    except UnskeinError as e:
        _print_to_stderr(translate_error(e, context.lang), style="red")
        return ExitCode.USAGE_ERROR
    ai_outcome = outcome.ai_outcome
    report = render_report(
        ReportContext(
            root=context.root,
            result=outcome.result,
            ai_report=outcome.ai_report,
            ai_status=outcome.ai_status,
            min_severity=context.min_severity,
            ai_failure=ai_outcome.failure if ai_outcome else None,
            ai_error_type=ai_outcome.error_type if ai_outcome else None,
            ai_dropped_problems=ai_outcome.dropped_problems if ai_outcome else 0,
        ),
        context.lang,
    )
    if output:
        output.write_text(report, encoding="utf-8")
    Console().print(Markdown(report))
    if verbose:
        _print_stats(stats, context)
    return exit_code_for(outcome.ai_report)


def _run_pipeline(context: ScanContext) -> ScanOutcome:
    """Analyze the project and interpret it, showing progress while the model answers.

    Args:
        context: A prepared scan.

    Returns:
        The analysis and the AI outcome.
    """
    result = analyze_project(context)
    with _ai_waiting_indicator(context):
        return interpret(result, context)


def _ai_waiting_indicator(context: ScanContext) -> AbstractContextManager[object]:
    """Return a stderr spinner for the model call, or a no-op when not useful.

    Only shown on a terminal, so pipes, files and CI logs stay clean.

    Args:
        context: The scan, for its language and model.

    Returns:
        A context manager to wrap the AI call in.
    """
    console = Console(stderr=True)
    if context.ai_disabled or context.ai_config is None or not console.is_terminal:
        return nullcontext()
    message = t("cli.ai_waiting", context.lang, model=context.ai_config.model)
    return console.status(message, spinner="dots")


def _print_stats(stats: PerformanceStats, context: ScanContext) -> None:
    """Print the local, informational performance stats.

    Args:
        stats: Duration and memory of the analysis.
        context: The scan, for its output language.
    """
    lang: Lang = context.lang
    _print_to_stderr(
        t(
            "cli.stats",
            lang,
            seconds=f"{stats.duration_seconds:.2f}",
            memory=f"{stats.peak_memory_mb:.1f}",
        )
    )


def _print_to_stderr(message: str, style: str | None = None) -> None:
    """Print a message to stderr exactly as given.

    Messages embed user paths: rich markup is off so ``[v2]`` in a path is not
    read as a style tag, and soft wrapping leaves line breaks to the terminal
    so paths stay intact for copy and paste.

    Args:
        message: Text to print.
        style: Optional rich style for the whole message, e.g. ``"red"``.
    """
    Console(stderr=True, soft_wrap=True).print(message, style=style, markup=False, highlight=False)
