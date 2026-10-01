import os
import subprocess
import sys
import textwrap
from pathlib import Path

import networkx as nx

from unskein.graph.steps import StepKind
from unskein.graph.untangle import TanglePlan, find_cuts, plan_tangles, simulate
from unskein.parsers.models import ImportKind
from unskein.parsers.usage import ImportEvidence, UseContext


def graph_of(*edges: tuple[str, str]) -> nx.DiGraph:
    """Build a directed graph from edges.

    Args:
        *edges: ``(source, target)`` pairs.

    Returns:
        The graph.
    """
    return nx.DiGraph(list(edges))


def unit_cost(graph: nx.DiGraph) -> dict[tuple[str, str], int]:
    """Give every edge of a graph the same cost.

    Args:
        graph: Graph whose edges are costed.

    Returns:
        Cost 1 per edge.
    """
    return dict.fromkeys(graph.edges, 1)


def test_acyclic_graph_needs_no_cut() -> None:
    graph = graph_of(("a", "b"), ("b", "c"))
    assert find_cuts(graph, unit_cost(graph)) == []


def test_two_cycle_cuts_the_cheaper_edge() -> None:
    graph = graph_of(("a", "b"), ("b", "a"))
    assert find_cuts(graph, {("a", "b"): 5, ("b", "a"): 1}) == [("b", "a")]
    assert find_cuts(graph, {("a", "b"): 1, ("b", "a"): 5}) == [("a", "b")]


def test_cuts_leave_a_dag_on_a_dense_graph() -> None:
    graph = nx.complete_graph(7, create_using=nx.DiGraph)
    graph = nx.relabel_nodes(graph, {i: f"m{i}" for i in graph})
    cuts = find_cuts(graph, unit_cost(graph))
    remaining = graph.copy()
    remaining.remove_edges_from(cuts)
    assert nx.is_directed_acyclic_graph(remaining)
    assert len(cuts) == len(set(cuts)) and len(cuts) < graph.number_of_edges()


def test_re_add_pass_keeps_only_edges_that_close_a_cycle() -> None:
    graph = graph_of(("a", "b"), ("b", "c"), ("c", "a"), ("a", "c"))
    cuts = find_cuts(graph, unit_cost(graph))
    assert len(cuts) == 1


def test_cuts_do_not_depend_on_the_hash_seed() -> None:
    script = textwrap.dedent(
        """
        import networkx as nx
        from unskein.graph.untangle import find_cuts
        graph = nx.gnp_random_graph(40, 0.15, seed=3, directed=True)
        graph = nx.relabel_nodes(graph, {i: f"m{i:02d}" for i in graph})
        print(find_cuts(graph, dict.fromkeys(graph.edges, 1)))
        """
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2", "3")
    }
    assert len(outputs) == 1


def evidence(contexts: set[UseContext], symbols: tuple[str, ...] = ("X",)) -> ImportEvidence:
    """Build evidence for one dependency.

    Args:
        contexts: Where the imported names are read.
        symbols: Symbols imported by name.

    Returns:
        The evidence.
    """
    return ImportEvidence(Path("x.py"), (1,), symbols, frozenset(contexts))


def test_plan_prefers_the_cheapest_step_in_a_cycle() -> None:
    scope = graph_of(("a", "b"), ("b", "a"))
    found = {
        ("a", "b"): evidence({UseContext.MODULE}, ("X", "Y", "Z")),
        ("b", "a"): evidence({UseContext.ANNOTATION}),
    }
    [plan] = plan_tangles(scope, [["a", "b"]], found, facades={}, all_edges=False)
    assert [(c.source, c.target, c.step) for c in plan.cuts] == [("b", "a", StepKind.TYPE_CHECKING)]
    assert plan.members == ("a", "b") and plan.cost == 1


def test_package_structure_is_only_cut_when_unavoidable() -> None:
    scope = graph_of(("pkg", "pkg.mod"), ("pkg.mod", "pkg"))
    found = {
        ("pkg", "pkg.mod"): evidence({UseContext.MODULE}),
        ("pkg.mod", "pkg"): evidence({UseContext.MODULE}, ()),
    }
    [plan] = plan_tangles(
        scope, [["pkg", "pkg.mod"]], found, facades={"pkg": frozenset()}, all_edges=False
    )
    assert [(c.source, c.target, c.step) for c in plan.cuts] == [
        ("pkg.mod", "pkg", StepKind.BYPASS_FACADE)
    ]


def test_an_already_lazy_import_is_not_offered_lazy_again() -> None:
    scope = nx.DiGraph()
    scope.add_edge("a", "b", kind=ImportKind.MODULE)
    scope.add_edge("b", "a", kind=ImportKind.LAZY)
    found = {
        ("a", "b"): evidence({UseContext.MODULE}, ("X", "Y", "Z")),
        ("b", "a"): evidence({UseContext.FUNCTION}),
    }
    [plan] = plan_tangles(scope, [["a", "b"]], found, facades={}, all_edges=False)
    assert [(c.source, c.step) for c in plan.cuts] == [("b", StepKind.MOVE_SYMBOL)]


def test_all_edges_never_offers_lazy_nor_type_checking() -> None:
    scope = graph_of(("a", "b"), ("b", "a"))
    found = {
        ("a", "b"): evidence({UseContext.MODULE}, ("X", "Y", "Z")),
        ("b", "a"): evidence({UseContext.ANNOTATION}),
    }
    [plan] = plan_tangles(scope, [["a", "b"]], found, facades={}, all_edges=True)
    assert [(c.source, c.step) for c in plan.cuts] == [("b", StepKind.MOVE_SYMBOL)]


def test_missing_evidence_falls_back_to_extract_shared() -> None:
    scope = graph_of(("a", "b"), ("b", "a"))
    [plan] = plan_tangles(scope, [["a", "b"]], {}, facades={}, all_edges=False)
    assert [c.step for c in plan.cuts] == [StepKind.EXTRACT_SHARED]


def test_tangle_plan_cost_sums_its_steps() -> None:
    plan = TanglePlan(("a", "b"), ())
    assert plan.cost == 0


def test_simulation_counts_before_and_after_and_coupling_changes() -> None:
    scope = graph_of(("a", "b"), ("b", "a"), ("b", "c"))
    full = graph_of(("a", "b"), ("b", "a"), ("b", "c"), ("c", "a"))
    result = simulate(scope, full, [("b", "a")])
    assert (result.tangles_before, result.tangles_after) == (1, 0)
    assert (result.cycles_before, result.cycles_after) == (1, 0)
    [change] = [c for c in result.changes if c.module == "a"]
    assert (change.before.afferent, change.after.afferent) == (2, 1)
    assert {c.module for c in result.changes} == {"a", "b"}
