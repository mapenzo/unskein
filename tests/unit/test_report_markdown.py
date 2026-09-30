from dataclasses import replace
from pathlib import Path

import networkx as nx
import pathspec

from unskein.ai.models import AIFailure, AIReport, Problem
from unskein.graph.metrics import AnalysisResult, CouplingMetrics, analyze
from unskein.i18n import Lang
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ParseWarning, WarningCode
from unskein.parsers.python_parser import PythonAdapter
from unskein.report.markdown import (
    MAX_MODULES_IN_TABLE,
    MAX_TANGLE_MEMBERS_SHOWN,
    MAX_WARNING_EXAMPLES,
    AIStatus,
    ReportContext,
    filter_by_severity,
    render_report,
)


def _problem(severity: str) -> Problem:
    """Build a minimal AI problem of the given severity.

    Args:
        severity: Problem severity.

    Returns:
        The problem, titled after its severity.
    """
    return Problem(
        severity=severity,
        title=f"{severity} problem",
        description="why it matters",
        affected_modules=["app.a"],
        recommendation="what to do",
    )


def analyzed(root: Path) -> AnalysisResult:
    """Discover, parse, resolve and analyze a fixture project.

    Args:
        root: Fixture project directory.

    Returns:
        The analysis of the fixture.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)))


def render(
    root: Path,
    result: AnalysisResult,
    lang: Lang = Lang.EN,
    **context: object,
) -> str:
    """Render a report with sensible defaults for the fields a test does not care about.

    Args:
        root: Project root shown in the title and used for relative paths.
        result: Analysis to render.
        lang: Report language.
        **context: Overrides for other ``ReportContext`` fields.

    Returns:
        The Markdown report.
    """
    defaults = {"ai_report": None, "ai_status": AIStatus.DISABLED}
    return render_report(ReportContext(root=root, result=result, **(defaults | context)), lang)


def headings(report: str) -> list[str]:
    """Return the level-1 and level-2 headings of a Markdown report, in order.

    Args:
        report: Markdown text.

    Returns:
        Heading lines.
    """
    return [line for line in report.splitlines() if line.startswith(("# ", "## "))]


def test_filter_by_severity_keeps_threshold_and_above() -> None:
    problems = [_problem("low"), _problem("medium"), _problem("high")]
    kept = [p.severity for p in filter_by_severity(problems, "medium")]
    assert kept == ["medium", "high"]


def test_sections_in_order_english(circular_imports: Path) -> None:
    assert headings(render(circular_imports, analyzed(circular_imports))) == [
        "# Analysis of circular_imports",
        "## Summary",
        "## General metrics",
        "## Dependency cycles",
        "## Most coupled modules",
        "## Problems flagged (AI)",
    ]


def test_sections_in_spanish(circular_imports: Path) -> None:
    report = render(circular_imports, analyzed(circular_imports), Lang.ES)
    assert headings(report)[:3] == [
        "# Análisis de circular_imports",
        "## Resumen",
        "## Métricas generales",
    ]


def test_summary_is_never_empty_without_ai(simple_project: Path) -> None:
    report = render(simple_project, analyzed(simple_project))
    summary = report.split("## Summary")[1].split("## ")[0]
    assert "5 modules" in summary
    assert "0 dependency cycles" in summary


def test_cycles_are_listed_as_loops(circular_imports: Path) -> None:
    assert "`app.a` → `app.b` → `app.a`" in render(circular_imports, analyzed(circular_imports))


def test_no_cycles_message(simple_project: Path) -> None:
    assert "No dependency cycles found." in render(simple_project, analyzed(simple_project))


def test_truncated_cycles_are_announced(circular_imports: Path) -> None:
    result = replace(analyzed(circular_imports), cycles_truncated=True)
    assert "search stopped" in render(circular_imports, result)


def test_coupled_table_is_truncated_with_a_note(tmp_path: Path) -> None:
    names = [f"m{i:02d}" for i in range(MAX_MODULES_IN_TABLE + 3)]
    result = AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={n: CouplingMetrics(n, 2, 1) for n in names},
        cycles=[],
        high_coupling_modules=names,
    )
    report = render(tmp_path, result)
    assert "| `m00` | 2 | 1 | 0.33 |" in report
    assert f"`m{MAX_MODULES_IN_TABLE:02d}`" not in report
    assert (
        f"Showing the {MAX_MODULES_IN_TABLE} most coupled of the {len(names)} modules "
        "in the top 10% by Ca + Ce." in report
    )


def test_coupled_table_explains_which_modules_it_lists(tmp_path: Path) -> None:
    result = AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={"a": CouplingMetrics("a", 2, 1)},
        cycles=[],
        high_coupling_modules=["a"],
    )
    report = render(tmp_path, result, lang=Lang.ES)
    assert "El 10 % de los módulos con mayor Ca + Ce" in report
    assert "Se muestran" not in report


def test_ai_status_messages(simple_project: Path) -> None:
    result = analyzed(simple_project)
    assert "--no-ai" in render(simple_project, result, ai_status=AIStatus.DISABLED)
    assert "UNSKEIN_AI_MODEL" in render(simple_project, result, ai_status=AIStatus.NOT_CONFIGURED)


def test_ai_problems_are_rendered_and_filtered(simple_project: Path) -> None:
    ai_report = AIReport(
        summary="The core is healthy.",
        architecture_health="fair",
        problems=[_problem("low"), _problem("high")],
    )
    report = render(
        simple_project,
        analyzed(simple_project),
        ai_report=ai_report,
        ai_status=AIStatus.PRESENT,
        min_severity="medium",
    )
    assert "The core is healthy." in report
    assert "high problem" in report
    assert "low problem" not in report


def test_warnings_are_grouped_by_kind_with_relative_paths(tmp_path: Path) -> None:
    count = MAX_WARNING_EXAMPLES + 2
    star = [
        ParseWarning(WarningCode.STAR_IMPORT, tmp_path / "pkg" / f"m{i}.py", i + 1, "pkg.base")
        for i in range(count)
    ]
    cycle = [ParseWarning(WarningCode.REEXPORT_CYCLE, None, None, "Thing: app.a, app.b")]
    result = replace(analyzed(tmp_path), parse_warnings=star + cycle)
    report = render(tmp_path, result)
    assert "## Analysis warnings" in report
    assert f"### Star imports ({count})" in report
    assert "`pkg/m0.py:1`" in report
    assert str(tmp_path) not in report
    assert "…and 2 more" in report
    assert "### Re-export cycles (1)" in report


def test_no_warnings_section_when_clean(simple_project: Path) -> None:
    assert "## Analysis warnings" not in render(simple_project, analyzed(simple_project))


def test_tangles_come_before_cycles(circular_imports: Path) -> None:
    report = render(circular_imports, analyzed(circular_imports))
    assert "### Tangles" in report
    assert "- **2 modules**: `app.a`, `app.b`" in report
    assert report.index("### Tangles") < report.index("### Cycles")


def test_tangle_members_are_truncated(tmp_path: Path) -> None:
    members = [f"m{i:02d}" for i in range(MAX_TANGLE_MEMBERS_SHOWN + 2)]
    result = AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={},
        cycles=[members[:2]],
        high_coupling_modules=[],
        tangles=[members],
    )
    report = render(tmp_path, result)
    assert f"`m{MAX_TANGLE_MEMBERS_SHOWN - 1:02d}`" in report
    assert f"`m{MAX_TANGLE_MEMBERS_SHOWN:02d}`" not in report
    assert "…and 2 more" in report


def test_summary_and_metrics_mention_tangles_only_when_present(
    circular_imports: Path, simple_project: Path
) -> None:
    tangled = render(circular_imports, analyzed(circular_imports))
    assert "1 tangle" in tangled.split("## General metrics", maxsplit=1)[0]
    assert "| Tangles | 1 |" in tangled
    clean = render(simple_project, analyzed(simple_project))
    assert "tangle" not in clean.split("## General metrics", maxsplit=1)[0].lower()
    assert "| Tangles | 0 |" in clean


def test_tangles_in_spanish(circular_imports: Path) -> None:
    report = render(circular_imports, analyzed(circular_imports), Lang.ES)
    assert "### Marañas" in report
    assert "- **2 módulos**: `app.a`, `app.b`" in report


def test_ai_failure_notices_explain_why_there_is_no_ai_section(simple_project: Path) -> None:
    result = analyzed(simple_project)

    def failed(failure: AIFailure, error_type: str | None = None) -> str:
        return render(
            simple_project,
            result,
            ai_status=AIStatus.FAILED,
            ai_failure=failure,
            ai_error_type=error_type,
        )

    assert "did not answer in time" in failed(AIFailure.TIMEOUT)
    call_error = failed(AIFailure.CALL_ERROR, "AuthenticationError")
    assert "AuthenticationError" in call_error
    assert "expected format" in failed(AIFailure.INVALID_RESPONSE)
    assert "deterministic analysis is complete" in call_error


def test_a_failed_ai_without_a_failure_reason_falls_back_to_the_call_error_notice(
    simple_project: Path,
) -> None:
    report = render(
        simple_project, analyzed(simple_project), ai_status=AIStatus.FAILED, ai_failure=None
    )
    assert "deterministic analysis is complete" in report


def test_dropped_ai_problems_are_reported(simple_project: Path) -> None:
    ai_report = AIReport(summary="s", architecture_health="fair", problems=[_problem("high")])
    report = render(
        simple_project,
        analyzed(simple_project),
        lang=Lang.ES,
        ai_report=ai_report,
        ai_status=AIStatus.PRESENT,
        ai_dropped_problems=3,
    )
    assert "3" in report and "descart" in report


def test_dropped_notice_shows_even_when_no_problem_remains(simple_project: Path) -> None:
    ai_report = AIReport(summary="s", architecture_health="fair", problems=[])
    report = render(
        simple_project,
        analyzed(simple_project),
        lang=Lang.EN,
        ai_report=ai_report,
        ai_status=AIStatus.PRESENT,
        ai_dropped_problems=2,
    )
    assert "2" in report and "discarded" in report.lower()


def test_no_dropped_notice_when_nothing_was_dropped(simple_project: Path) -> None:
    ai_report = AIReport(summary="s", architecture_health="fair", problems=[_problem("high")])
    report = render(
        simple_project,
        analyzed(simple_project),
        lang=Lang.EN,
        ai_report=ai_report,
        ai_status=AIStatus.PRESENT,
    )
    assert "discarded" not in report.lower()
