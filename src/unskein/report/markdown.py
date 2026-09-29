"""Markdown report combining the deterministic analysis and the optional AI report."""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from unskein.ai.models import AIFailure, AIReport, Problem, Severity
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang, t, translate_warning
from unskein.parsers.models import ParseWarning, WarningCode

SEVERITY_ORDER: dict[Severity, int] = {"low": 0, "medium": 1, "high": 2}
MAX_MODULES_IN_TABLE = 15
MAX_WARNING_EXAMPLES = 5
MAX_TANGLE_MEMBERS_SHOWN = 10


class AIStatus(StrEnum):
    """Why the AI section looks the way it does; the section is never left blank.

    Attributes:
        PRESENT: An AI report is available.
        DISABLED: The user passed ``--no-ai``.
        NOT_CONFIGURED: No AI model is configured in any layer.
        FAILED: AI is configured but produced no report; see ``ReportContext.ai_failure``.
    """

    PRESENT = "present"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


@dataclass(frozen=True)
class ReportContext:
    """Everything a report is rendered from.

    Attributes:
        root: Project root; names the report and makes warning paths relative.
        result: The deterministic analysis.
        ai_report: The AI interpretation, or None.
        ai_status: Why the AI section has, or lacks, content.
        min_severity: Lowest AI problem severity to show.
        ai_failure: Why the AI produced no report, when ai_status is FAILED.
        ai_error_type: Exception class name behind a call error.
    """

    root: Path
    result: AnalysisResult
    ai_report: AIReport | None
    ai_status: AIStatus
    min_severity: Severity = "low"
    ai_failure: AIFailure | None = None
    ai_error_type: str | None = None


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


def render_report(context: ReportContext, lang: Lang) -> str:
    """Render the full report as Markdown.

    Formatting only, no business logic: every number and judgment comes from
    the analysis or the AI report. The warnings section appears only when
    there are warnings; every other section is always present.

    Args:
        context: Analysis, AI report and presentation settings.
        lang: Language of the report text.

    Returns:
        The report as a Markdown string.
    """
    sections = [
        [f"# {t('report.title', lang, project=context.root.resolve().name)}"],
        _summary(context, lang),
        _metrics(context.result, lang),
        _cycles(context.result, lang),
        _coupled(context.result, lang),
        _ai(context, lang),
    ]
    if context.result.parse_warnings:
        sections.append(_warnings(context.result.parse_warnings, context.root, lang))
    return "\n\n".join("\n".join(lines) for lines in sections) + "\n"


def _cycle_count(result: AnalysisResult) -> str:
    """Return the number of cycles, marked with ``+`` when the search was truncated.

    Args:
        result: The deterministic analysis.

    Returns:
        The count as text, e.g. ``"100+"``.
    """
    return f"{len(result.cycles)}{'+' if result.cycles_truncated else ''}"


def _summary(context: ReportContext, lang: Lang) -> list[str]:
    """Build the summary: always the key numbers, plus the AI summary when present.

    Args:
        context: Report context.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    result = context.result
    counts = t(
        "report.summary_counts",
        lang,
        modules=result.graph.number_of_nodes(),
        dependencies=result.graph.number_of_edges(),
        cycles=_cycle_count(result),
    )
    lines = [f"## {t('report.summary', lang)}", "", counts]
    if result.high_coupling_modules:
        top = result.coupling_metrics[result.high_coupling_modules[0]]
        top_line = t(
            "report.summary_top_module", lang, module=top.module, ca=top.afferent, ce=top.efferent
        )
        lines.append(top_line)
    if result.tangles:
        lines.append(_tangle_summary(result.tangles, lang))
    if context.ai_report:
        health = t(f"report.health.{context.ai_report.architecture_health}", lang)
        lines += ["", context.ai_report.summary, "", t("report.health", lang, health=health)]
    return lines


def _tangle_summary(tangles: list[list[str]], lang: Lang) -> str:
    """Summarize how many tangles there are and how big the largest one is.

    Args:
        tangles: Tangles of the analysis, largest first.
        lang: Report language.

    Returns:
        One sentence, singular or plural.
    """
    largest = len(tangles[0])
    if len(tangles) == 1:
        return t("report.summary_tangles.one", lang, size=largest)
    return t("report.summary_tangles.other", lang, count=len(tangles), size=largest)


def _metrics(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the general metrics table.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    rows = [
        ("report.metric.modules", result.graph.number_of_nodes()),
        ("report.metric.dependencies", result.graph.number_of_edges()),
        ("report.metric.cycles", _cycle_count(result)),
        ("report.metric.tangles", len(result.tangles)),
        ("report.metric.warnings", len(result.parse_warnings)),
    ]
    lines = [
        f"## {t('report.metrics', lang)}",
        "",
        f"| {t('report.metric', lang)} | {t('report.value', lang)} |",
        "|---|---|",
    ]
    lines += [f"| {t(key, lang)} | {value} |" for key, value in rows]
    return lines


def _cycles(result: AnalysisResult, lang: Lang) -> list[str]:
    """List the tangles first, then every cycle found as an example loop.

    Tangles give the true extent of the problem (never truncated); cycles,
    which can be truncated, illustrate concrete dependency paths inside them.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.cycles', lang)}", ""]
    if not result.cycles:
        return [*lines, t("report.no_cycles", lang)]
    lines += [f"### {t('report.tangles_heading', lang)}", ""]
    lines += [_tangle_line(tangle, lang) for tangle in result.tangles]
    lines += ["", f"### {t('report.cycles_heading', lang)}", ""]
    for cycle in result.cycles:
        loop = [*cycle, cycle[0]]
        lines.append("- " + " → ".join(f"`{module}`" for module in loop))
    if result.cycles_truncated:
        lines += ["", t("report.cycles_truncated", lang, shown=len(result.cycles))]
    return lines


def _tangle_line(members: list[str], lang: Lang) -> str:
    """Render one tangle as its size and up to ``MAX_TANGLE_MEMBERS_SHOWN`` members.

    Args:
        members: Modules of the tangle, sorted.
        lang: Report language.

    Returns:
        One Markdown list item.
    """
    shown = ", ".join(f"`{m}`" for m in members[:MAX_TANGLE_MEMBERS_SHOWN])
    hidden = len(members) - MAX_TANGLE_MEMBERS_SHOWN
    more = f" {t('report.more', lang, count=hidden)}" if hidden > 0 else ""
    return f"- **{t('report.tangle_size', lang, size=len(members))}**: {shown}{more}"


def _coupled(result: AnalysisResult, lang: Lang) -> list[str]:
    """Build the table of the most coupled modules, capped at ``MAX_MODULES_IN_TABLE``.

    Args:
        result: The deterministic analysis.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.coupled', lang)}", ""]
    modules = result.high_coupling_modules
    if not modules:
        return [*lines, t("report.no_coupled", lang)]
    lines += [
        f"| {t('report.module', lang)} | Ca | Ce | {t('report.instability', lang)} |",
        "|---|---:|---:|---:|",
    ]
    for name in modules[:MAX_MODULES_IN_TABLE]:
        m = result.coupling_metrics[name]
        lines.append(f"| `{name}` | {m.afferent} | {m.efferent} | {m.instability:.2f} |")
    if len(modules) > MAX_MODULES_IN_TABLE:
        lines += ["", t("report.showing", lang, shown=MAX_MODULES_IN_TABLE, total=len(modules))]
    return lines


def _ai(context: ReportContext, lang: Lang) -> list[str]:
    """Build the AI problems section, or the notice explaining its absence.

    Args:
        context: Report context.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    lines = [f"## {t('report.ai', lang)}", ""]
    if context.ai_report is None:
        if context.ai_status is AIStatus.FAILED:
            notice = t(
                f"report.ai.failed.{context.ai_failure}",
                lang,
                error_type=context.ai_error_type or "",
            )
        else:
            notice = t(f"report.ai.{context.ai_status}", lang)
        return [*lines, notice]
    problems = filter_by_severity(context.ai_report.problems, context.min_severity)
    if not problems:
        return [*lines, t("report.ai.no_problems", lang)]
    for problem in problems:
        modules = ", ".join(f"`{m}`" for m in problem.affected_modules)
        lines += [
            f"- **[{problem.severity}] {problem.title}** — {modules}",
            f"  {problem.description}",
            f"  *{t('report.recommendation', lang)}:* {problem.recommendation}",
        ]
    return lines


def _location(warning: ParseWarning, root: Path) -> str:
    """Return ``path:line`` relative to the project root, or empty for project-level warnings.

    Args:
        warning: The warning to locate.
        root: Project root.

    Returns:
        The location as Markdown code, followed by a separator, or an empty string.
    """
    if warning.path is None:
        return ""
    path = warning.path
    if path.is_relative_to(root):
        path = path.relative_to(root)
    location = path.as_posix() + (f":{warning.line}" if warning.line else "")
    return f"`{location}` — "


def _warnings(warnings: list[ParseWarning], root: Path, lang: Lang) -> list[str]:
    """Group warnings by kind, showing a few examples of each.

    Grouping keeps huge projects readable: 264 star imports read as one
    heading with ``MAX_WARNING_EXAMPLES`` examples, not 264 lines.

    Args:
        warnings: Warnings collected during the analysis.
        root: Project root, to show paths relative to it.
        lang: Report language.

    Returns:
        Markdown lines of the section.
    """
    groups: dict[WarningCode, list[ParseWarning]] = defaultdict(list)
    for warning in warnings:
        groups[warning.code].append(warning)
    lines = [f"## {t('report.warnings', lang)}"]
    for code, group in groups.items():
        lines += ["", f"### {t(f'warning_title.{code}', lang)} ({len(group)})", ""]
        for warning in group[:MAX_WARNING_EXAMPLES]:
            lines.append(f"- {_location(warning, root)}{translate_warning(warning, lang)}")
        hidden = len(group) - MAX_WARNING_EXAMPLES
        if hidden > 0:
            lines.append(f"- {t('report.more', lang, count=hidden)}")
    return lines
