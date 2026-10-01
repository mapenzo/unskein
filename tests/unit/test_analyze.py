from collections.abc import Callable
from pathlib import Path

import pathspec
import pytest

from unskein.graph.metrics import AnalysisResult, analyze
from unskein.parsers.indirection import resolve_indirection
from unskein.parsers.models import WarningCode
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
    assert result.tangles == [["app.a", "app.b"]]


def test_resolved_reexports_reach_the_graph(reexport_chain: Path) -> None:
    result = analyze_fixture(reexport_chain)
    assert result.graph.has_edge("app.consumer", "app.core.impl.engine")
    assert not result.graph.has_edge("app.consumer", "app")
    assert result.coupling_metrics["app.core.impl.engine"].afferent >= 1


def test_warnings_are_carried_over(reexport_cycle: Path) -> None:
    result = analyze_fixture(reexport_cycle)
    assert [w.code for w in result.parse_warnings] == [WarningCode.REEXPORT_CYCLE]


def test_simple_project_has_no_cycles(simple_project: Path) -> None:
    result = analyze_fixture(simple_project)
    assert result.cycles == []
    assert set(result.coupling_metrics) == set(result.graph.nodes)


TYPE_ONLY_CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app import b\n",
    "app/b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app import a\n",
}
LAZY_CYCLE = {
    "app/__init__.py": "",
    "app/a.py": "from app import b\n",
    "app/b.py": "def run():\n    from app import a\n",
}


@pytest.mark.parametrize("files", [TYPE_ONLY_CYCLE, LAZY_CYCLE], ids=["type_only", "lazy"])
def test_cycle_that_does_not_exist_at_import_time_is_hidden_coupling(
    make_project: Callable[[dict[str, str]], Path], files: dict[str, str]
) -> None:
    result = analyze_fixture(make_project(files))
    assert result.cycles == []
    assert result.tangles == []
    assert result.hidden_tangles == [["app.a", "app.b"]]
    a = result.coupling_metrics["app.a"]
    assert (a.afferent, a.efferent) == (1, 1)


def test_real_cycle_has_no_hidden_tangle(circular_imports: Path) -> None:
    result = analyze_fixture(circular_imports)
    assert result.tangles == [["app.a", "app.b"]]
    assert result.hidden_tangles == []


def test_tangle_grown_by_a_lazy_import_is_reported_at_both_sizes(
    make_project: Callable[[dict[str, str]], Path],
) -> None:
    result = analyze_fixture(
        make_project(
            {
                "app/__init__.py": "",
                "app/a.py": "from app import b\n",
                "app/b.py": "from app import a\ndef run():\n    from app import c\n",
                "app/c.py": "from app import b\n",
            }
        )
    )
    assert result.tangles == [["app.a", "app.b"]]
    assert result.hidden_tangles == [["app.a", "app.b", "app.c"]]
