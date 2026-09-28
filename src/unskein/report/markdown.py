"""Markdown report combining the deterministic analysis and the optional AI report."""

from unskein.ai.models import AIReport, Problem, Severity
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang

SEVERITY_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2}
MAX_MODULES_IN_TABLE = 15


def filter_by_severity(problems: list[Problem], min_severity: Severity) -> list[Problem]:
    """Keep problems at or above a severity threshold.

    Applied at presentation time so the LLM is never asked to filter.

    Args:
        problems: Problems flagged by the LLM.
        min_severity: Lowest severity to keep.

    Returns:
        Problems whose severity is at least ``min_severity``, in original order.
    """
    threshold = SEVERITY_ORDER[min_severity]
    return [p for p in problems if SEVERITY_ORDER[p.severity] >= threshold]


def render_report(
    project_name: str,
    result: AnalysisResult,
    ai_report: AIReport | None,
    lang: Lang,
) -> str:
    """Render the full report as Markdown.

    Formatting only, no business logic. Sections: summary, general metrics,
    cycles, top coupled modules, AI problems (or a notice when absent) and
    analysis warnings.

    Args:
        project_name: Name shown in the report title.
        result: The deterministic analysis.
        ai_report: The AI interpretation, or None when unavailable or disabled.
        lang: Language of the report text.

    Returns:
        The report as a Markdown string.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
