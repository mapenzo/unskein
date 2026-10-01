from dataclasses import replace
from pathlib import Path

import networkx as nx
import pathspec
import pytest

from unskein.ai.models import AIFailure, AIReport, Problem
from unskein.graph.findings import Finding, FindingKind
from unskein.graph.metrics import (
    IMPACT_BOTTLENECK_MODULES,
    IMPACT_COUPLED_MODULES,
    AnalysisResult,
    CouplingMetrics,
    analyze,
)
from unskein.graph.packages import PackageEdge, PackageMetrics
from unskein.i18n import Lang
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import ParseWarning, WarningCode
from unskein.parsers.python_parser import PythonAdapter
from unskein.report.markdown import (
    MAX_FINDINGS_PER_KIND,
    MAX_MODULES_IN_TABLE,
    MAX_PACKAGE_EDGES_SHOWN,
    MAX_PACKAGES_IN_TABLE,
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
        "## Findings",
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


def result_with(*findings: Finding, **fields: object) -> AnalysisResult:
    """Build a minimal analysis carrying the given findings.

    Args:
        *findings: Findings to attach.
        **fields: Other ``AnalysisResult`` fields to set.

    Returns:
        The analysis.
    """
    return AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={},
        cycles=[],
        high_coupling_modules=[],
        findings=list(findings),
        **fields,
    )


def test_findings_section_lists_each_kind_with_its_evidence(tmp_path: Path) -> None:
    result = result_with(
        Finding(FindingKind.BOTTLENECK, ("core.settings",), {"afferent": 25, "efferent": 9}),
        Finding(
            FindingKind.UNSTABLE_DEPENDENCY,
            ("core.svc", "web.factory"),
            {"afferent_from": 2, "instability_from": 0.33, "instability_to": 0.83},
        ),
        Finding(FindingKind.ORPHAN, ("tools.stray",), {}),
    )

    report = render(tmp_path, result)

    assert "## Findings" in report
    assert "### Bottleneck (1)" in report
    assert "- `core.settings` (Ca 25, Ce 9)" in report
    assert "- `core.svc` → `web.factory` (Ca 2, I 0.33 → 0.83)" in report
    assert "- `tools.stray`" in report
    assert report.index("Unstable dependency") < report.index("Bottleneck") < report.index("Orphan")


def test_findings_section_is_in_spanish_when_asked(tmp_path: Path) -> None:
    result = result_with(Finding(FindingKind.ORPHAN, ("tools.stray",), {}))

    report = render(tmp_path, result, lang=Lang.ES)

    assert "## Hallazgos" in report
    assert "Recomendación" in report


def test_no_findings_says_so(tmp_path: Path) -> None:
    assert "No findings detected." in render(tmp_path, result_with())


def test_disabled_findings_leave_no_section(tmp_path: Path) -> None:
    report = render(tmp_path / "project", result_with(findings_enabled=False))

    assert "Findings" not in report
    assert "findings" not in report


def test_findings_per_kind_are_capped_with_a_note(tmp_path: Path) -> None:
    orphans = [
        Finding(FindingKind.ORPHAN, (f"m{i:02d}",), {}) for i in range(MAX_FINDINGS_PER_KIND + 3)
    ]

    report = render(tmp_path, result_with(*orphans))

    assert f"### Orphan module ({len(orphans)})" in report
    assert f"`m{MAX_FINDINGS_PER_KIND:02d}`" not in report
    assert "…and 3 more" in report


def test_summary_counts_the_findings(tmp_path: Path) -> None:
    one = result_with(Finding(FindingKind.ORPHAN, ("a",), {}))
    two = result_with(
        Finding(FindingKind.ORPHAN, ("a",), {}), Finding(FindingKind.ORPHAN, ("b",), {})
    )

    assert "1 architecture finding." in render(tmp_path, one)
    assert "2 architecture findings." in render(tmp_path, two)


TWO_PACKAGES = [PackageMetrics("core", 5, 3, 0), PackageMetrics("web", 4, 0, 2)]


def test_packages_section_lists_packages_and_their_dependencies(tmp_path: Path) -> None:
    result = result_with(packages=TWO_PACKAGES, package_edges=[PackageEdge("web", "core", 7)])

    report = render(tmp_path, result)

    assert "## Packages" in report
    assert "| `core` | 5 | 3 | 0 | 0.00 |" in report
    assert "| `web` | 4 | 0 | 2 | 1.00 |" in report
    assert "- `web` → `core` (7 imports)" in report


def test_packages_section_is_in_spanish_when_asked(tmp_path: Path) -> None:
    result = result_with(packages=TWO_PACKAGES, package_edges=[PackageEdge("web", "core", 1)])

    report = render(tmp_path, result, lang=Lang.ES)

    assert "## Paquetes" in report
    assert "- `web` → `core` (1 import)" in report


def test_packages_section_comes_before_the_coupled_modules(tmp_path: Path) -> None:
    result = result_with(packages=TWO_PACKAGES, package_edges=[])

    report = render(tmp_path, result)

    assert report.index("## Packages") < report.index("## Most coupled modules")


@pytest.mark.parametrize("packages", [[], [PackageMetrics("only", 3, 0, 0)]])
def test_fewer_than_two_packages_leave_no_packages_section(
    tmp_path: Path, packages: list[PackageMetrics]
) -> None:
    report = render(tmp_path, result_with(packages=packages))

    assert "## Packages" not in report


def test_packages_and_dependencies_are_capped_with_a_note(tmp_path: Path) -> None:
    packages = [PackageMetrics(f"p{i:02d}", 1, 1, 1) for i in range(MAX_PACKAGES_IN_TABLE + 3)]
    edges = [
        PackageEdge(f"p{i:02d}", f"p{i + 1:02d}", 1) for i in range(MAX_PACKAGE_EDGES_SHOWN + 4)
    ]

    report = render(tmp_path, result_with(packages=packages, package_edges=edges))

    assert f"`p{MAX_PACKAGES_IN_TABLE:02d}` |" not in report
    assert (
        f"Showing the {MAX_PACKAGES_IN_TABLE} most coupled of the {len(packages)} packages."
        in report
    )
    assert "…and 4 more" in report


def test_coupled_table_has_an_impact_column(tmp_path: Path) -> None:
    result = AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={"a": CouplingMetrics("a", 2, 1), "b": CouplingMetrics("b", 1, 1)},
        cycles=[],
        high_coupling_modules=["a", "b"],
        impact={"a": 7},
    )

    report = render(tmp_path, result)

    assert "| Module | Ca | Ce | Instability | Impact |" in report
    assert "| `a` | 2 | 1 | 0.33 | 7 |" in report
    assert "| `b` | 1 | 1 | 0.50 | — |" in report


def test_bottleneck_line_shows_its_impact(tmp_path: Path) -> None:
    finding = Finding(FindingKind.BOTTLENECK, ("core.settings",), {"afferent": 25, "efferent": 9})

    report = render(tmp_path, result_with(finding, impact={"core.settings": 54}))

    assert "- `core.settings` (Ca 25, Ce 9, impact 54)" in report


def test_bottleneck_line_without_a_measured_impact_stays_as_before(tmp_path: Path) -> None:
    finding = Finding(FindingKind.BOTTLENECK, ("core.settings",), {"afferent": 25, "efferent": 9})

    assert "- `core.settings` (Ca 25, Ce 9)" in render(tmp_path, result_with(finding))


def test_report_and_analysis_agree_on_how_many_modules_are_shown() -> None:
    assert MAX_MODULES_IN_TABLE == IMPACT_COUPLED_MODULES
    assert MAX_FINDINGS_PER_KIND == IMPACT_BOTTLENECK_MODULES


LAYER_VIOLATION = Finding(
    FindingKind.LAYER_VIOLATION, ("core.db", "web.views"), {"layer_from": "core", "layer_to": "web"}
)


def test_layer_violation_line_names_both_layers(tmp_path: Path) -> None:
    report = render(tmp_path, result_with(LAYER_VIOLATION))

    assert "### Layer violation (1)" in report
    assert "- `core.db` → `web.views` (layer core → web)" in report


def test_layer_violation_is_in_spanish_when_asked(tmp_path: Path) -> None:
    report = render(tmp_path, result_with(LAYER_VIOLATION), lang=Lang.ES)

    assert "### Violación de capas (1)" in report
    assert "- `core.db` → `web.views` (capa core → web)" in report
