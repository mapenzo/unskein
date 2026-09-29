"""Scan orchestration: configuration, then discover -> parse -> resolve -> analyze.

Independent of the CLI so it can be tested directly and reused as a library.
"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from unskein import config as config_module
from unskein.ai.client import AIClient
from unskein.ai.models import AIOutcome, AIReport, Severity
from unskein.ai.prompts import build_context, build_messages, ground_report
from unskein.config import (
    AIConfig,
    AnalysisConfig,
    AnalysisFlags,
    load_toml_config,
    resolve_ai_config,
    resolve_analysis_config,
)
from unskein.errors import ErrorKey, UnskeinError
from unskein.graph.metrics import AnalysisResult, analyze
from unskein.i18n import Lang, detect_lang
from unskein.parsers.discovery import load_exclude_spec
from unskein.parsers.python_parser import PythonAdapter
from unskein.report.markdown import AIStatus

logger = logging.getLogger("unskein")


@dataclass(frozen=True)
class ScanOptions:
    """What the user asked for in one scan, before configuration is resolved.

    Attributes:
        path: Directory to analyze.
        no_ai: Whether to skip the AI interpretation.
        exclude: Extra exclude patterns (gitignore syntax).
        min_severity: Lowest AI problem severity to report.
        api_key: Key from the insecure ``--api-key`` flag.
        lang: Requested output language.
        follow_symlinks: Whether discovery follows symlinked directories; None
            when not given, so ``.unskein.toml`` decides.
        include_tests: Whether test code is analyzed; None when not given.
        encoding: Fallback encoding for files whose encoding cannot be detected.
    """

    path: Path
    no_ai: bool = False
    exclude: tuple[str, ...] = ()
    min_severity: Severity = "low"
    api_key: str | None = None
    lang: str | None = None
    follow_symlinks: bool | None = None
    include_tests: bool | None = None
    encoding: str | None = None


@dataclass(frozen=True)
class ScanContext:
    """A scan with its configuration resolved, ready to run.

    Attributes:
        root: Directory to analyze.
        lang: Output language.
        analysis: Resolved analysis settings.
        ai_config: Model settings, or None when the AI cannot or must not run.
        ai_disabled: Whether the user passed ``--no-ai``.
        min_severity: Lowest AI problem severity to report.
    """

    root: Path
    lang: Lang
    analysis: AnalysisConfig
    ai_config: AIConfig | None
    ai_disabled: bool
    min_severity: Severity


@dataclass(frozen=True)
class ScanOutcome:
    """Result of running a scan.

    Attributes:
        result: The deterministic analysis.
        ai_status: Whether and why the AI section has content.
        ai_outcome: What the AI call produced; None when no call was made.
    """

    result: AnalysisResult
    ai_status: AIStatus
    ai_outcome: AIOutcome | None = None

    @property
    def ai_report(self) -> AIReport | None:
        """Return the grounded AI report, or None when there is none."""
        return self.ai_outcome.report if self.ai_outcome else None


def prepare_scan(
    options: ScanOptions,
    env: Mapping[str, str] | None = None,
    user_config: Path | None = None,
) -> ScanContext:
    """Load ``.unskein.toml`` and resolve language, analysis and AI settings.

    Separate from ``execute_scan`` so that, once this succeeds, every later
    error can be reported in the configured language.

    Args:
        options: What the user asked for.
        env: Environment variables; None means ``os.environ`` at call time.
        user_config: User-wide config file; None means
            ``~/.config/unskein/config.toml``, looked up at call time.

    Returns:
        The scan context.

    Raises:
        ConfigError: If a configuration file is invalid.
    """
    env = os.environ if env is None else env
    toml = load_toml_config(options.path, user_config or config_module.USER_CONFIG_PATH)
    flags = AnalysisFlags(
        exclude=options.exclude,
        include_tests=options.include_tests,
        follow_symlinks=options.follow_symlinks,
        encoding=options.encoding,
    )
    ai_config = None if options.no_ai else resolve_ai_config(toml, env, options.api_key)
    return ScanContext(
        root=options.path,
        lang=detect_lang(options.lang, toml.general.lang, env),
        analysis=resolve_analysis_config(toml, flags),
        ai_config=ai_config,
        ai_disabled=options.no_ai,
        min_severity=options.min_severity,
    )


def analyze_project(context: ScanContext) -> AnalysisResult:
    """Run discovery, parsing, re-export resolution and analysis.

    Parsing is sequential for now: ``pipeline.parse_all`` would route projects
    above ``parallel_threshold`` to the not-yet-implemented parallel parser.

    Args:
        context: A prepared scan.

    Returns:
        The deterministic analysis.

    Raises:
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    root = context.root
    if not root.is_dir():
        raise UnskeinError(ErrorKey.PATH_NOT_FOUND, {"path": str(root)})
    config = context.analysis
    adapter = PythonAdapter(config)
    spec = load_exclude_spec(root, config.exclude, config.include_tests)
    files = sorted(adapter.discover_files(root, spec, config.follow_symlinks))
    if not files:
        raise UnskeinError(ErrorKey.NO_FILES_FOUND, {"path": str(root)})
    logger.debug("Discovered %d Python files under %s", len(files), root)
    parsed = adapter.parse(files, root)
    result = analyze(adapter.resolve_indirection(parsed))
    logger.debug(
        "Analyzed %d modules, %d dependencies",
        result.graph.number_of_nodes(),
        result.graph.number_of_edges(),
    )
    return result


def interpret(result: AnalysisResult, context: ScanContext) -> ScanOutcome:
    """Add the AI interpretation to an analysis when it is enabled and configured.

    The client, and with it LiteLLM, is only built here and only when needed.
    An AI failure never raises: it becomes a ``FAILED`` status.

    Args:
        result: The deterministic analysis.
        context: The prepared scan.

    Returns:
        The analysis with the AI status and, on success, the grounded report.
    """
    if context.ai_disabled:
        return ScanOutcome(result, AIStatus.DISABLED)
    if context.ai_config is None:
        return ScanOutcome(result, AIStatus.NOT_CONFIGURED)
    client = AIClient(context.ai_config)
    outcome = client.generate_report(build_messages(build_context(result), context.lang))
    if outcome.report is None:
        return ScanOutcome(result, AIStatus.FAILED, outcome)
    grounded = replace(outcome, report=ground_report(outcome.report, result.graph))
    return ScanOutcome(result, AIStatus.PRESENT, grounded)


def execute_scan(context: ScanContext) -> ScanOutcome:
    """Analyze the project, then interpret it with the AI when enabled.

    Args:
        context: A prepared scan.

    Returns:
        The analysis and the AI outcome.

    Raises:
        UnskeinError: If the path is not a directory or holds no Python files.
    """
    return interpret(analyze_project(context), context)
