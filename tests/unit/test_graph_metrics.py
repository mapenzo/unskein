import networkx as nx

from unskein.config import AnalysisConfig
from unskein.graph.metrics import (
    MAX_CYCLES,
    CouplingMetrics,
    compute_coupling,
    find_cycles,
    find_high_coupling,
    find_tangles,
)
from unskein.pipeline import should_parallelize


def graph_of(*edges: tuple[str, str], isolated: tuple[str, ...] = ()) -> nx.DiGraph:
    """Build a DiGraph from edges plus optional isolated nodes.

    Args:
        *edges: Directed ``(source, target)`` pairs.
        isolated: Extra nodes without edges.

    Returns:
        The graph.
    """
    graph = nx.DiGraph(edges)
    graph.add_nodes_from(isolated)
    return graph


def scores(**ca_ce: tuple[int, int]) -> dict[str, CouplingMetrics]:
    """Build coupling metrics from ``module=(Ca, Ce)`` keyword pairs.

    Args:
        **ca_ce: Afferent and efferent coupling per module name.

    Returns:
        Coupling metrics keyed by module name.
    """
    return {name: CouplingMetrics(name, ca, ce) for name, (ca, ce) in ca_ce.items()}


def test_coupling_counts_distinct_modules_not_weight() -> None:
    graph = graph_of(("app", "core"), ("api", "core"), isolated=("lonely",))
    graph.edges["app", "core"]["weight"] = 7
    metrics = compute_coupling(graph)
    assert (metrics["core"].afferent, metrics["core"].efferent) == (2, 0)
    assert (metrics["app"].afferent, metrics["app"].efferent) == (0, 1)
    assert (metrics["lonely"].afferent, metrics["lonely"].efferent) == (0, 0)


def test_acyclic_graph_has_no_cycles() -> None:
    assert find_cycles(graph_of(("a", "b"), ("b", "c"))) == ([], False)


def test_two_module_cycle_is_found() -> None:
    assert find_cycles(graph_of(("app.b", "app.a"), ("app.a", "app.b"))) == (
        [["app.a", "app.b"]],
        False,
    )


def test_cycle_is_rotated_to_start_at_smallest_module() -> None:
    cycles, _ = find_cycles(graph_of(("c", "a"), ("b", "c"), ("a", "b")))
    assert cycles == [["a", "b", "c"]]


def test_dense_graph_is_truncated_at_limit() -> None:
    cycles, truncated = find_cycles(nx.complete_graph(6, create_using=nx.DiGraph))
    assert len(cycles) == MAX_CYCLES
    assert truncated


def test_exactly_limit_cycles_is_not_truncated() -> None:
    graph = graph_of(("a", "b"), ("b", "a"), ("c", "d"), ("d", "c"))
    assert find_cycles(graph, limit=2)[1] is False
    cycles, truncated = find_cycles(graph, limit=1)
    assert len(cycles) == 1
    assert truncated


def test_high_coupling_selects_top_percentile() -> None:
    metrics = scores(a=(1, 0), b=(1, 1), c=(2, 1), d=(2, 2), hub=(6, 4))
    assert find_high_coupling(metrics, percentile=90) == ["hub"]


def test_high_coupling_keeps_ties() -> None:
    metrics = scores(x=(3, 2), y=(2, 3), z=(1, 0), w=(0, 0))
    assert find_high_coupling(metrics, percentile=90) == ["x", "y"]


def test_high_coupling_orders_by_score_then_name() -> None:
    metrics = scores(a=(2, 1), b=(3, 2), c=(4, 1), d=(1, 0))
    assert find_high_coupling(metrics, percentile=50) == ["b", "c", "a"]


def test_high_coupling_ignores_uncoupled_modules() -> None:
    assert find_high_coupling(scores(a=(0, 0), b=(0, 0))) == []
    assert find_high_coupling({}) == []


def test_single_coupled_module_is_selected() -> None:
    assert find_high_coupling(scores(only=(1, 1))) == ["only"]


def test_instability_bounds() -> None:
    assert CouplingMetrics("core", afferent=5, efferent=0).instability == 0.0
    assert CouplingMetrics("app", afferent=0, efferent=4).instability == 1.0
    assert CouplingMetrics("mid", afferent=1, efferent=3).instability == 0.75


def test_isolated_module_instability_is_zero() -> None:
    assert CouplingMetrics("lonely", afferent=0, efferent=0).instability == 0.0


def test_should_parallelize_uses_threshold() -> None:
    config = AnalysisConfig(parallel_threshold=50)
    assert not should_parallelize(49, config)
    assert should_parallelize(50, config)


def test_acyclic_graph_has_no_tangles() -> None:
    assert find_tangles(graph_of(("a", "b"), ("b", "c"))) == []


def test_two_module_cycle_is_one_tangle() -> None:
    assert find_tangles(graph_of(("b", "a"), ("a", "b"), ("a", "c"))) == [["a", "b"]]


def test_dense_graph_is_one_tangle_even_when_cycles_are_truncated() -> None:
    graph = nx.complete_graph(6, create_using=nx.DiGraph)
    graph = nx.relabel_nodes(graph, {i: f"m{i}" for i in range(6)})
    assert find_cycles(graph)[1] is True
    assert find_tangles(graph) == [[f"m{i}" for i in range(6)]]


def test_tangles_are_ordered_by_size_then_name() -> None:
    graph = graph_of(
        ("x", "y"),
        ("y", "x"),
        ("a", "b"),
        ("b", "c"),
        ("c", "a"),
        ("p", "q"),
        ("q", "p"),
    )
    assert find_tangles(graph) == [["a", "b", "c"], ["p", "q"], ["x", "y"]]
