from pathlib import Path

import pathspec

from unskein.graph.metrics import AnalysisResult, analyze
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.python_parser import PythonAdapter


def analyze_fixture(root: Path) -> AnalysisResult:
    """Discover, parse, resolve and analyze a fixture project.

    Args:
        root: Fixture project directory.

    Returns:
        The analysis of the fixture.
    """
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(root, pathspec.PathSpec([])))
    return analyze(resolve_indirection(adapter.parse(files, root)))


def test_circular_imports_analysis(circular_imports: Path) -> None:
    result = analyze_fixture(circular_imports)
    assert result.cycles == [["app.a", "app.b"]]
    assert result.cycles_truncated is False
    module_a = result.coupling_metrics["app.a"]
    assert (module_a.afferent, module_a.efferent) == (1, 1)
    assert result.high_coupling_modules == ["app.a", "app.b"]


def test_resolved_reexports_reach_the_graph(reexport_chain: Path) -> None:
    result = analyze_fixture(reexport_chain)
    assert result.graph.has_edge("app.consumer", "app.core.impl.engine")
    assert not result.graph.has_edge("app.consumer", "app")
    assert result.coupling_metrics["app.core.impl.engine"].afferent >= 1


def test_warnings_are_carried_over(reexport_cycle: Path) -> None:
    result = analyze_fixture(reexport_cycle)
    assert len(result.parse_warnings) == 1
    assert "cycle" in result.parse_warnings[0].lower()


def test_simple_project_has_no_cycles(simple_project: Path) -> None:
    result = analyze_fixture(simple_project)
    assert result.cycles == []
    assert set(result.coupling_metrics) == set(result.graph.nodes)
