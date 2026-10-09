from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import networkx as nx
import pathspec
import pytest

from unskein.ai.models import AIFailure, AIReport, Problem
from unskein.config import AnalysisConfig, FindingsConfig
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
    MAX_HIDDEN_TANGLES_SHOWN,
    MAX_MODULES_IN_TABLE,
    MAX_NATIVE_IN_TABLE,
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
    assert "No dependency cycles found at import time." in render(
        simple_project, analyzed(simple_project)
    )


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


@pytest.mark.parametrize("lang", list(Lang))
def test_missing_model_message_names_where_the_config_is_read(
    simple_project: Path, lang: Lang
) -> None:
    report = render(
        simple_project, analyzed(simple_project), ai_status=AIStatus.NOT_CONFIGURED, lang=lang
    )

    assert "~/.config/unskein/config.toml" in report
    assert "unskein init --user" in report


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


HIDDEN_PROJECT = {
    "app/__init__.py": "",
    "app/a.py": "from app import b\n",
    "app/b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app import a\n",
}


def test_hidden_coupling_is_reported_apart_from_import_cycles(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project(HIDDEN_PROJECT)
    report = render(root, analyzed(root))
    summary = report.split("## General metrics", maxsplit=1)[0]
    assert "lazy or type-only imports" in summary
    assert "| Hidden tangles | 1 |" in report
    assert "| Tangles | 0 |" in report
    assert "No dependency cycles found at import time." in report
    assert "### Hidden coupling" in report
    assert "- **2 modules**: `app.a`, `app.b`" in report
    assert "### Tangles" not in report


GROWN_TANGLE_PROJECT = {
    "app/__init__.py": "",
    "app/a.py": "from app import b\n",
    "app/b.py": "from app import a\n\ndef run():\n    from app import c\n",
    "app/c.py": "from app import a\n",
}


def test_hidden_coupling_lists_a_tangle_grown_by_a_lazy_import(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    root = make_project(GROWN_TANGLE_PROJECT)
    report = render(root, analyzed(root))
    assert "- **2 modules**: `app.a`, `app.b`" in report
    assert "- **3 modules**: `app.a`, `app.b`, `app.c`" in report
    assert "or groups larger than a tangle above" in report


def test_hidden_coupling_in_spanish(make_project: Callable[[dict[str, str]], Path]) -> None:
    root = make_project(HIDDEN_PROJECT)
    report = render(root, analyzed(root), Lang.ES)
    assert "### Acoplamiento oculto" in report
    assert "| Marañas ocultas | 1 |" in report
    assert "No se encontraron ciclos de dependencia al importar." in report


def test_no_hidden_coupling_section_without_hidden_tangles(
    circular_imports: Path, simple_project: Path
) -> None:
    for root in (circular_imports, simple_project):
        report = render(root, analyzed(root))
        assert "Hidden coupling" not in report
        assert "| Hidden tangles | 0 |" in report


def test_hidden_tangles_are_truncated(tmp_path: Path) -> None:
    hidden = [[f"a{i:02d}", f"b{i:02d}"] for i in range(MAX_HIDDEN_TANGLES_SHOWN + 2)]
    result = AnalysisResult(
        graph=nx.DiGraph(),
        coupling_metrics={},
        cycles=[],
        high_coupling_modules=[],
        hidden_tangles=hidden,
    )
    report = render(tmp_path, result)
    assert f"`a{MAX_HIDDEN_TANGLES_SHOWN - 1:02d}`" in report
    assert f"`a{MAX_HIDDEN_TANGLES_SHOWN:02d}`" not in report
    assert "…and 2 more" in report


def test_summary_points_to_untangle_when_there_are_tangles(
    circular_imports: Path, simple_project: Path
) -> None:
    tangled = render(circular_imports, analyzed(circular_imports))
    assert "`unskein untangle`" in tangled.split("## General metrics", maxsplit=1)[0]
    clean = render(simple_project, analyzed(simple_project))
    assert "unskein untangle" not in clean


SCRIPTS_ROOT = Path(__file__).parent.parent / "fixtures" / "scripts_project"


def _scripts_report(lang: Lang) -> str:
    """Render the report of the scripts fixture without AI.

    Args:
        lang: Report language.

    Returns:
        The Markdown report.
    """
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(
        adapter.parse(sorted(SCRIPTS_ROOT.rglob("*.py")), SCRIPTS_ROOT)
    )
    return render(SCRIPTS_ROOT, analyze(parsed), lang)


def test_summary_and_metrics_count_scripts() -> None:
    report = _scripts_report(Lang.EN)
    assert "modules + 4 scripts, " in report
    assert "| Scripts | 4 |" in report


def test_scripts_section_groups_by_directory() -> None:
    report = _scripts_report(Lang.ES)
    assert "## Scripts" in report
    assert "- `cookbook/` (2 scripts) → `lib`" in report
    assert "- `.github/` (1 script) → `lib`" in report


def test_consumers_column_appears_only_with_consumers(simple_project: Path) -> None:
    assert "| Consumers |" in _scripts_report(Lang.EN)
    plain = render(simple_project, analyzed(simple_project))
    assert "Consumers" not in plain
    assert "## Scripts" not in plain
    assert "scripts" not in plain.split("## General metrics", maxsplit=1)[0]


def test_coupled_intro_and_consumers_note_are_separate_paragraphs() -> None:
    lines = _scripts_report(Lang.EN).splitlines()
    note = next(i for i, line in enumerate(lines) if line.startswith("Consumers:"))
    assert lines[note - 1] == ""
    assert lines[note - 2] != ""


DISTRIBUTIONS_ROOT = Path(__file__).parent.parent / "fixtures" / "distributions_monorepo"


def _distributions_report(lang: Lang) -> str:
    """Render the report of the distributions fixture without AI.

    Args:
        lang: Report language.

    Returns:
        The Markdown report.
    """
    return render(DISTRIBUTIONS_ROOT, analyzed(DISTRIBUTIONS_ROOT), lang)


def test_distributions_section_and_installability_es() -> None:
    report = _distributions_report(Lang.ES)
    assert "## Distribuciones" in report
    assert (
        "| `core-plugins` | 2 | `core` | no: `plugins/core_plugins/__init__.py:1 → core` |"
        in report
    )
    assert "2 distribuciones; 2 no se pueden instalar solas." in report


def test_undeclared_dependency_line_and_fix_en() -> None:
    report = _distributions_report(Lang.EN)
    assert (
        "- `core-plugins` → `core` (2 required, 0 lazy, 0 guarded; "
        "first: `plugins/core_plugins/__init__.py:1`)" in report
    )
    assert (
        '  - Fix: add `"core>=2.3.0"` to `[project] dependencies` in `plugins/pyproject.toml`'
        in report
    )


def test_cycle_lists_each_edge_with_its_status_en() -> None:
    report = _distributions_report(Lang.EN)
    assert "- `core` ↔ `core-plugins`" in report
    assert (
        "  - `core` → `core-plugins`: optional (extra `plugins`); 0 required, 0 lazy, 1 guarded"
        in report
    )
    assert "  - `core-plugins` → `core`: undeclared; 2 required, 0 lazy, 0 guarded" in report
    assert "  - Fix: cut `core` → `core-plugins`" in report


def test_unpackaged_import_fix_es() -> None:
    report = _distributions_report(Lang.ES)
    assert "`legacy/` no lo empaqueta ninguna distribución" in report


def test_distributions_section_comes_after_packages_and_before_scripts_en() -> None:
    report = _distributions_report(Lang.EN)
    distributions = report.index("## Distributions")
    assert report.index("## Most coupled modules") > distributions


def test_no_distributions_section_without_named_distributions(simple_project: Path) -> None:
    plain = render(simple_project, analyzed(simple_project))
    assert "Distribuciones" not in plain
    assert "Distributions" not in plain


def test_optional_required_line_and_fix_en(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "a"\nversion = "1"\n'
        '[project.optional-dependencies]\nx = ["b"]\n',
        "a/__init__.py": "import b_pkg\n",
        "bdist/pyproject.toml": '[project]\nname = "b"\nversion = "1"\ndependencies = []\n'
        '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
        "bdist/b_pkg/__init__.py": "",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    report = render(tmp_path, analyzed(tmp_path))
    assert "- `a` → `b` (1 required, 0 lazy, 0 guarded; first: `a/__init__.py:1`)" in report
    assert (
        "  - Fix: move `b` from the extras `x` to the required dependencies in `pyproject.toml`, "
        "or guard the import at `a/__init__.py:1` with `try`/`except ImportError`" in report
    )


def test_unknown_dependencies_do_not_claim_to_be_dynamic_en(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n',
        "a/__init__.py": "",
        "poet/pyproject.toml": '[project]\nname = "p"\ndynamic = ["dependencies"]\n'
        '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "p_pkg"\n',
        "poet/p_pkg/__init__.py": "import a\n",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    report = render(tmp_path, analyzed(tmp_path))
    assert "| `p` | 1 | `a` | unknown (its dependencies cannot be read) |" in report


def test_spanish_use_counts_do_not_put_a_plural_after_one() -> None:
    report = _distributions_report(Lang.ES)
    assert "requeridos: 2, perezosos: 0, protegidos: 0" in report


def test_distributions_section_does_not_depend_on_findings(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[build-system]\nbuild-backend = "hatchling.build"\n'
        '[project]\nname = "a"\ndependencies = []\n',
        "a/__init__.py": "import legacy.tool\n",
        "legacy/__init__.py": "",
        "legacy/tool.py": "",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    adapter = PythonAdapter(AnalysisConfig())
    parsed = adapter.resolve_indirection(adapter.parse(sorted(tmp_path.rglob("*.py")), tmp_path))
    result = analyze(parsed, FindingsConfig(enabled=False))
    assert "## Distributions" in render(tmp_path, result)


def test_undeclared_dependency_listed_only_in_a_group_says_so_en(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "a"\ndependencies = []\n'
        '[dependency-groups]\ndev = ["b"]\n',
        "a/__init__.py": "import b_pkg\n",
        "bdist/pyproject.toml": '[project]\nname = "b"\nversion = "1"\n'
        '[tool.uv.build-backend]\nmodule-root = ""\nmodule-name = "b_pkg"\n',
        "bdist/b_pkg/__init__.py": "",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    report = render(tmp_path, analyzed(tmp_path))
    assert (
        "- `a` → `b` (1 required, 0 lazy, 0 guarded; first: `a/__init__.py:1`; "
        "only in group `dev`, never installed with the package)" in report
    )


NAMESPACE_ROOT = Path(__file__).parent.parent / "fixtures" / "namespace_project"


def test_summary_counts_namespaces_apart_en() -> None:
    report = render(NAMESPACE_ROOT, analyzed(NAMESPACE_ROOT))
    assert "6 modules + 1 namespace package, " in report
    assert "| Namespace packages | 1 |" in report


def test_namespace_names_are_marked_es(tmp_path: Path) -> None:
    files = {"app/__init__.py": "", "app/types/models.py": ""}
    for user in ("a", "b", "c"):
        files[f"app/{user}.py"] = "import app.types\ndef f(x):\n    return x(app.types)\n"
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    report = render(tmp_path, analyzed(tmp_path), Lang.ES)
    assert "| `app.types` *(espacio de nombres)* | 3 | 0 |" in report
    assert "Módulo más acoplado: `app.types` *(espacio de nombres)* (Ca 3, Ce 0)." in report


def test_projects_without_namespaces_do_not_mention_them(simple_project: Path) -> None:
    plain = render(simple_project, analyzed(simple_project))
    assert "namespace" not in plain.lower()


def test_missing_module_line_and_fix_en() -> None:
    report = render(NAMESPACE_ROOT, analyzed(NAMESPACE_ROOT))
    assert "### Import of a module that does not exist (1)" in report
    assert "- `app.helpers.gone` (0 required, 1 lazy, 0 guarded; first: `app/core.py:14`)" in report
    assert (
        "  - Fix: `app.helpers.gone` does not exist and no module of the project defines "
        "`helper`: restore the module or remove the import" in report
    )


def test_missing_module_fix_lists_each_symbol_es(tmp_path: Path) -> None:
    files = {
        "app/__init__.py": "",
        "app/models.py": "class Model: ...\n",
        "app/util.py": "def helper(): ...\n",
        "app/other.py": "def helper(): ...\n",
        "app/a.py": "from app.gone import helper, Model, Nowhere\n",
    }
    for relative, content in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(content)
    report = render(tmp_path, analyzed(tmp_path), Lang.ES)
    assert (
        "  - Arreglo: importa `Model` desde `app.models`, que lo define; `helper` desde "
        "`app.other`, que lo define (y en 1 módulo(s) más); ningún módulo del proyecto "
        "define `Nowhere`" in report
    )


NATIVE_ROOT = Path(__file__).parent.parent / "fixtures" / "native_project"


def test_summary_counts_compiled_and_stub_modules_apart_en() -> None:
    report = render(NATIVE_ROOT, analyzed(NATIVE_ROOT))
    assert "5 modules + 4 compiled extensions + 1 stub-only module + 1 script," in report
    assert "| Compiled extensions | 4 |" in report
    assert "| Stub-only modules | 1 |" in report


def test_summary_counts_compiled_and_stub_modules_apart_es() -> None:
    report = render(NATIVE_ROOT, analyzed(NATIVE_ROOT), Lang.ES)
    assert "5 módulos + 4 extensiones compiladas + 1 módulo solo stub + 1 script," in report
    assert "| Extensiones compiladas | 4 |" in report
    assert "| Módulos solo stub | 1 |" in report


def test_native_module_has_unknown_efferent_coupling_in_the_table() -> None:
    result = replace(analyzed(NATIVE_ROOT), high_coupling_modules=["pkg._native", "pkg.stubonly"])
    report = render(NATIVE_ROOT, result)
    assert "| `pkg._native` *(compiled extension)* | 3 | ? | — |" in report
    assert "| `pkg.stubonly` *(stub only)* | 1 | ? | — |" in report
    assert "Most coupled module: `pkg._native` *(compiled extension)* (Ca 3, Ce ?)." in report


def test_projects_without_native_modules_do_not_mention_them(simple_project: Path) -> None:
    report = render(simple_project, analyzed(simple_project))
    assert "compiled" not in report.lower()
    assert "stub" not in report.lower()


def test_native_boundary_section_en() -> None:
    report = render(NATIVE_ROOT, analyzed(NATIVE_ROOT))
    assert "## Native boundary" in report
    assert (
        "| `pkg._native` | compiled extension | `pkg/_native.pyi`, `pyproject.toml:10` | 3 "
        "| 0 / 1 / 1 / 1 | no: 1 unguarded use (`pkg/api.py:8`) | unknown (compiled code) |"
    ) in report
    assert (
        "| `pkg.stubonly` | stub only | `pkg/stubonly.pyi` | 1 | 1 / 0 / 0 / 0 "
        "| no: 1 unguarded use (`pkg/api.py:2`) | unknown (stub only) |"
    ) in report
    assert "cycles that go through it cannot be seen either" in report


def test_native_boundary_section_es() -> None:
    report = render(NATIVE_ROOT, analyzed(NATIVE_ROOT), Lang.ES)
    assert "## Frontera nativa" in report
    assert (
        "| no: 1 uso sin protección (`pkg/api.py:8`) | desconocida (código compilado) |" in report
    )


def test_native_boundary_says_yes_when_every_use_is_guarded(make_project) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/_native.pyi": "",
            "app/loader.py": (
                "try:\n    from app import _native\nexcept ImportError:\n    _native = None\n"
            ),
        }
    )
    assert "| 0 / 0 / 1 / 0 | yes |" in render(root, analyzed(root))


def test_rule_11_line_lists_the_unguarded_uses_and_the_fix() -> None:
    report = render(NATIVE_ROOT, analyzed(NATIVE_ROOT))
    assert "### Optional extension used as required (1)" in report
    assert (
        "- `pkg._native` *(compiled extension)* (0 required, 1 lazy, 1 guarded; "
        "guarded at `pkg/loader.py:3`)\n"
        "  - Unguarded: `pkg/api.py:8`\n"
        "  - Fix: guard those imports like `pkg/loader.py:3` does, or drop that fallback if "
        "`pkg._native` is required."
    ) in report


def test_projects_without_native_modules_have_no_boundary(simple_project: Path) -> None:
    assert "## Native boundary" not in render(simple_project, analyzed(simple_project))


def test_summary_uses_the_singular_for_one_en(make_project, circular_imports: Path) -> None:
    single = make_project({"app/__init__.py": "", "app/a.py": "import app\n"})
    assert "2 modules, 1 internal dependency, 0 dependency cycles." in render(
        single, analyzed(single)
    )
    assert ", 1 dependency cycle." in render(circular_imports, analyzed(circular_imports))


def test_summary_uses_the_singular_for_one_es(make_project) -> None:
    single = make_project({"app.py": ""})
    report = render(single, analyzed(single), Lang.ES)
    assert "1 módulo, 0 dependencias internas, 0 ciclos de dependencia." in report


def test_native_boundary_table_is_capped(make_project) -> None:
    files = {"app/__init__.py": ""}
    for number in range(MAX_NATIVE_IN_TABLE + 2):
        files[f"app/_n{number:02d}.pyi"] = ""
        files[f"app/u{number:02d}.py"] = f"from app import _n{number:02d}\n"
    root = make_project(files)
    report = render(root, analyzed(root))
    assert "| `app._n14` |" in report
    assert "| `app._n15` |" not in report
    assert "…and 2 more" in report


STAR_ROOT = Path(__file__).parent.parent / "fixtures" / "star_project"


def test_wildcard_findings_en() -> None:
    report = render(STAR_ROOT, analyzed(STAR_ROOT))
    assert "### Wildcard import (5)" in report
    assert (
        "- `app.types` (5 modules, 5 statements; they use 0 to 2 of 4 names; 1 uses nothing; "
        "1 name kept because other modules import it through the modules that star-import it)\n"
        "  - `app/annot.py:1`: `from app.types import D`\n"
        "  - `app/api.py:1`: `from app.types import A, B`\n"
        "  - `app/both.py:1`: `from app.types import A`\n"
        "  - `app/chain_mid.py:1`: `from app.types import C` (kept for `app.chain_top`: `C`)\n"
        "  - `app/dead.py:1`: remove (it uses nothing; the line loads `app.types` when "
        "imported, so removing it also drops its load-time effects)"
    ) in report
    assert (
        "- `app.models` (2 modules, 2 statements; they use 1 to 3 of 3 names; 1 name kept "
        "because other modules import it through the modules that star-import it)\n"
        "  - `app/both.py:2`: `from app.models import A, Model, json` (defined in "
        "`app.types`: `A`; from a third-party import: `json`)\n"
        "  - `app/relay.py:1`: `from app.models import Model` (kept for `app.consumer`: "
        "`Model`)"
    ) in report
    assert "- `app.listed` (1 module, 1 statement; it uses 1 of 1 name)" in report
    assert (
        "- `app.sub` (1 `from . import *` with no effect)\n"
        "  - `app/sub/__init__.py:1`: remove (it imports itself and, without `__all__`, does "
        "nothing)"
    ) in report


def test_wildcard_findings_es() -> None:
    report = render(STAR_ROOT, analyzed(STAR_ROOT), Lang.ES)
    assert "### Import con asterisco (5)" in report
    assert (
        "- `app.types` (5 módulos, 5 sentencias; usan de 0 a 2 de 4 nombres; 1 no usa nada; "
        "1 nombre se conserva porque otros módulos lo importan a través de quienes lo "
        "importan con asterisco)"
    ) in report
    assert "eliminar (no usa nada; la línea carga `app.types` al importar" in report
    assert "(se conservan para `app.chain_top`: `C`)" in report
    assert "(1 `from . import *` sin efecto)" in report


def test_wildcard_fixes_show_every_statement_and_name(make_project) -> None:
    names = [f"N{number:02d}" for number in range(25)]
    files = {
        "app/__init__.py": "",
        "app/types.py": "".join(f"{name} = 1\n" for name in names),
    }
    reader = "def f():\n    return " + ", ".join(names) + "\n"
    for number in range(7):
        files[f"app/m{number}.py"] = "from app.types import *\n\n\n" + reader
    root = make_project(files)
    report = render(root, analyzed(root))
    assert "`from app.types import " + ", ".join(names) + "`" in report
    assert "`app/m6.py:1`" in report
    assert "more" not in report.split("### Wildcard import")[1]


def test_every_wildcard_finding_is_listed(make_project) -> None:
    files = {"app/__init__.py": ""}
    for number in range(12):
        files[f"app/t{number:02d}.py"] = "A = 1\n"
        files[f"app/u{number:02d}.py"] = f"from app.t{number:02d} import *\nprint(A)\n"
    root = make_project(files)
    section = render(root, analyzed(root)).split("### Wildcard import (12)")[1]
    assert "- `app.t11` (" in section


def test_kept_names_are_grouped_by_the_module_that_needs_them(make_project) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/b.py": "X = 1\nY = 2\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "from app.m import X\n",
            "app/user2.py": "from app.m import Y\n",
        }
    )
    report = render(root, analyzed(root))
    assert "(kept for `app.user`: `X`; kept for `app.user2`: `Y`)" in report
    assert "2 names kept because other modules import them through the modules" in report


def test_a_package_star_imported_by_itself_and_by_others_shows_both(make_project) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/selfp/__init__.py": "from . import *\nA = 1\n",
            "app/use.py": "from app.selfp import *\nprint(A)\n",
        }
    )
    report = render(root, analyzed(root))
    assert "  - `app/use.py:1`: `from app.selfp import A`" in report
    assert "  - `app/selfp/__init__.py:1`: remove (it imports itself" in report


def test_one_name_reads_in_the_singular(make_project) -> None:
    root = make_project(
        {"app/__init__.py": "", "app/b.py": "A = 1\n", "app/m.py": "from app.b import *\n"}
    )
    assert "(1 module, 1 statement; it uses 0 of 1 name;" in render(root, analyzed(root))


def test_the_recommendation_warns_when_tests_are_not_analyzed() -> None:
    report = render(STAR_ROOT, analyzed(STAR_ROOT))
    assert "--include-tests" in report.split("### Wildcard import")[1]


def test_a_module_used_by_itself_keeps_every_name_and_says_why(make_project) -> None:
    root = make_project(
        {
            "app/__init__.py": "",
            "app/b.py": "X = 1\nY = 2\n",
            "app/m.py": "from app.b import *\n",
            "app/user.py": "import app.m\n\n\ndef f(handler):\n    return handler(app.m)\n",
        }
    )
    report = render(root, analyzed(root))
    assert (
        "`from app.b import X, Y` (all kept: `app.m` is used by itself elsewhere or through "
        "a star import whose names cannot be known, so any of its names may be read)"
    ) in report
