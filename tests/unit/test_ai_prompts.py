"""Tests for AI prompt context construction."""

from pathlib import Path

import networkx as nx
import pathspec

from unskein.ai.prompts import (
    MAX_CYCLES_IN_PROMPT,
    MAX_MODULES_IN_PROMPT,
    MAX_TANGLE_MEMBERS_IN_PROMPT,
    MAX_TANGLES_IN_PROMPT,
    build_context,
)
from unskein.graph.metrics import AnalysisResult, analyze, compute_coupling
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


def synthetic_result(module_count: int, cycle_count: int, tangle_count: int) -> AnalysisResult:
    """Build an analysis with many long-named modules, cycles and tangles.

    Args:
        module_count: Number of modules (a dependency chain).
        cycle_count: Number of two-to-eight-module cycles.
        tangle_count: Number of tangles with 30 members each.

    Returns:
        The synthetic analysis.
    """
    names = [f"company.platform.service_{i:04d}.handlers" for i in range(module_count)]
    graph = nx.DiGraph()
    graph.add_nodes_from(names)
    graph.add_edges_from(zip(names, names[1:], strict=False))
    cycles = [names[i : i + 2 + i % 7] for i in range(cycle_count)]
    tangles = [names[i * 30 : i * 30 + 30] for i in range(tangle_count)]
    return AnalysisResult(
        graph=graph,
        coupling_metrics=compute_coupling(graph),
        cycles=cycles,
        high_coupling_modules=[],
        cycles_truncated=True,
        tangles=tangles,
    )


def test_context_summarizes_a_small_project(circular_imports: Path) -> None:
    context = build_context(analyze_fixture(circular_imports))
    assert context.total_modules == 3
    assert context.total_cycles == 1
    assert context.cycles == [["app.a", "app.b"]]
    assert [t.size for t in context.tangles] == [2]
    assert context.warning_counts == {}


def test_project_without_cycles_tangles_or_warnings_gives_a_valid_context(
    simple_project: Path,
) -> None:
    context = build_context(analyze_fixture(simple_project))
    assert (context.cycles, context.tangles, context.warning_counts) == ([], [], {})
    assert context.total_tangles == 0


def test_lists_are_truncated_but_totals_are_kept() -> None:
    context = build_context(synthetic_result(module_count=400, cycle_count=60, tangle_count=8))
    assert len(context.cycles) == MAX_CYCLES_IN_PROMPT
    assert context.total_cycles == 60
    assert context.cycles_truncated is True
    assert len(context.tangles) == MAX_TANGLES_IN_PROMPT
    assert context.total_tangles == 8
    assert all(len(t.members) <= MAX_TANGLE_MEMBERS_IN_PROMPT for t in context.tangles)
    assert context.tangles[0].size == 30
    assert len(context.top_coupled_modules) == MAX_MODULES_IN_PROMPT


def test_cycles_come_shortest_first() -> None:
    context = build_context(synthetic_result(module_count=100, cycle_count=40, tangle_count=0))
    lengths = [len(cycle) for cycle in context.cycles]
    assert lengths == sorted(lengths)


def test_top_coupled_modules_are_ranked_by_ca_plus_ce_then_name() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("z", "hub"), ("a", "hub"), ("hub", "leaf")])
    result = AnalysisResult(
        graph=graph,
        coupling_metrics=compute_coupling(graph),
        cycles=[],
        high_coupling_modules=[],
    )
    top = build_context(result).top_coupled_modules
    assert [m.module for m in top] == ["hub", "a", "leaf", "z"]
    assert (top[0].ca, top[0].ce, top[0].instability) == (2, 1, 0.33)
