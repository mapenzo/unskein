from pathlib import Path

import networkx as nx
import pathspec

from unskein.graph.builder import build_graph
from unskein.parsers.models import ImportEdge, ModuleInfo, ParseResult
from unskein.parsers.python_parser import PythonAdapter


def make_result(imports: dict[str, list[str]], external: dict[str, list[str]] | None = None):
    """Build a ParseResult from ``{module: [internal targets]}`` (+ optional external ones).

    Args:
        imports: Internal import targets per module; every key becomes a module.
        external: External import targets per module.

    Returns:
        A ParseResult whose edges mirror the given mapping.
    """
    external = external or {}
    modules = []
    for name, targets in imports.items():
        edges = [ImportEdge(name, t, False) for t in targets]
        edges += [ImportEdge(name, t, True) for t in external.get(name, [])]
        modules.append(ModuleInfo(name, Path(f"{name}.py"), edges))
    return ParseResult(modules=modules, language="python")


def test_internal_imports_become_edges_and_externals_are_dropped() -> None:
    graph = build_graph(make_result({"a": ["b"], "b": []}, external={"a": ["os", "requests"]}))
    assert set(graph.nodes) == {"a", "b"}
    assert set(graph.edges) == {("a", "b")}


def test_isolated_module_is_still_a_node() -> None:
    graph = build_graph(make_result({"a": [], "lonely": []}))
    assert "lonely" in graph
    assert graph.degree("lonely") == 0


def test_repeated_imports_collapse_into_one_weighted_edge() -> None:
    graph = build_graph(make_result({"a": ["b", "b", "b"], "b": []}))
    assert graph.number_of_edges() == 1
    assert graph.edges["a", "b"]["weight"] == 3


def test_target_without_parsed_module_is_still_a_node() -> None:
    graph = build_graph(make_result({"a": ["broken"]}))
    assert set(graph.nodes) == {"a", "broken"}


def test_nodes_are_inserted_in_sorted_order() -> None:
    graph = build_graph(make_result({"c": ["a"], "b": [], "a": []}))
    assert list(graph.nodes) == ["a", "b", "c"]


def test_simple_project_graph(simple_project: Path) -> None:
    adapter = PythonAdapter()
    files = sorted(adapter.discover_files(simple_project, pathspec.PathSpec([])))
    graph = build_graph(adapter.parse(files, simple_project))
    assert isinstance(graph, nx.DiGraph)
    assert set(graph.edges) == {
        ("app.main", "app.services.user"),
        ("app.services.user", "app.models"),
    }
