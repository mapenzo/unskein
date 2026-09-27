from unskein.ai.models import AIReport, Problem, Severity
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang

SEVERITY_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2}
MAX_MODULES_IN_TABLE = 15


def filter_by_severity(problems: list[Problem], min_severity: Severity) -> list[Problem]:
    threshold = SEVERITY_ORDER[min_severity]
    return [p for p in problems if SEVERITY_ORDER[p.severity] >= threshold]


def render_report(
    project_name: str,
    result: AnalysisResult,
    ai_report: AIReport | None,
    lang: Lang,
) -> str:
    """Formatting only, no business logic. Sections: summary, metrics, cycles,
    top coupled modules, AI problems (or notice), analysis warnings."""
    raise NotImplementedError
