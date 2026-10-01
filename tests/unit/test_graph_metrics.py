import os
import subprocess
import sys
import textwrap
from pathlib import Path

import networkx as nx
import pytest

from unskein.config import AnalysisConfig, FindingsConfig
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import (
    IMPACT_BOTTLENECK_MODULES,
    IMPACT_COUPLED_MODULES,
    MAX_CYCLES,
    CouplingMetrics,
    analyze,
    compute_coupling,
    find_cycles,
    find_hidden_tangles,
    find_high_coupling,
    find_tangles,
    import_time_graph,
)
from unskein.graph.packages import PackageEdge
from unskein.parsers.models import ImportEdge, ImportKind, ModuleInfo, ParseResult
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


CYCLES_SCRIPT = textwrap.dedent("""
    import random
    import networkx as nx
    from unskein.graph.metrics import find_cycles

    random.seed(1)
    names = [f"m{i:03d}" for i in range(40)]
    graph = nx.DiGraph()
    graph.add_nodes_from(names)
    for source in names:
        for target in random.sample(names, 4):
            if source != target:
                graph.add_edge(source, target)
    print(find_cycles(graph, limit=LIMIT))
""")


@pytest.mark.parametrize("limit", [MAX_CYCLES, 100_000])
def test_cycles_do_not_depend_on_the_hash_seed(limit: int) -> None:
    script = CYCLES_SCRIPT.replace("LIMIT", str(limit))

    outputs = {
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("0", "1", "2", "3")
    }

    assert len(outputs) == 1


def parse_result_of(
    *modules: tuple[str, str], imports: tuple[tuple[str, str], ...] = ()
) -> ParseResult:
    """Build a ParseResult with the given ``(name, file name)`` modules and imports.

    Args:
        *modules: ``(module name, file name)`` pairs.
        imports: ``(importer, imported)`` pairs, all internal.

    Returns:
        The parse result.
    """
    infos = [ModuleInfo(name=name, file_path=Path(file)) for name, file in modules]
    for source, target in imports:
        next(m for m in infos if m.name == source).imports.append(
            ImportEdge(source=source, target=target, is_external=False)
        )
    return ParseResult(language="python", modules=infos)


def test_analyze_reports_unstable_dependency_through_imports() -> None:
    names = ["user1", "user2", "core", "flaky", *[f"dep{n}" for n in range(5)]]
    imports = (
        ("user1", "core"),
        ("user2", "core"),
        ("core", "flaky"),
        *[("flaky", f"dep{n}") for n in range(5)],
    )

    result = analyze(parse_result_of(*[(n, f"{n}.py") for n in names], imports=imports))

    assert [(f.kind, f.modules) for f in result.findings] == [
        (FindingKind.UNSTABLE_DEPENDENCY, ("core", "flaky"))
    ]


def test_analyze_reports_orphans_but_not_package_facades() -> None:
    result = analyze(parse_result_of(("pkg", "pkg/__init__.py"), ("pkg.lonely", "pkg/lonely.py")))

    assert [(f.kind, f.modules) for f in result.findings] == [(FindingKind.ORPHAN, ("pkg.lonely",))]
    assert result.findings_enabled is True


def test_analyze_with_findings_disabled_computes_none() -> None:
    parsed = parse_result_of(("pkg.lonely", "pkg/lonely.py"))

    result = analyze(parsed, FindingsConfig(enabled=False))

    assert (result.findings, result.findings_enabled) == ([], False)


def test_analyze_summarizes_packages_and_their_imports() -> None:
    parsed = parse_result_of(
        ("core", "core/__init__.py"),
        ("core.db", "core/db.py"),
        ("web.views", "web/views.py"),
        ("web.forms", "web/forms.py"),
        imports=(("web.views", "core.db"), ("web.forms", "core.db"), ("web.views", "web.forms")),
    )

    result = analyze(parsed)

    assert [(p.name, p.modules, p.afferent, p.efferent) for p in result.packages] == [
        ("core", 2, 1, 0),
        ("web", 2, 0, 1),
    ]
    assert result.package_edges == [PackageEdge("web", "core", 2)]


def test_analyze_uses_the_configured_package_depth() -> None:
    parsed = parse_result_of(
        ("app.api.users", "app/api/users.py"),
        ("app.db.models", "app/db/models.py"),
        imports=(("app.api.users", "app.db.models"),),
    )

    result = analyze(parsed, FindingsConfig(package_depth=2))

    assert [p.name for p in result.packages] == ["app.api", "app.db"]


def test_analyze_measures_the_impact_of_the_most_coupled_modules() -> None:
    parsed = parse_result_of(
        ("a", "a.py"), ("b", "b.py"), ("c", "c.py"), imports=(("a", "b"), ("b", "c"))
    )

    result = analyze(parsed)

    assert result.high_coupling_modules == ["b"]
    assert result.impact == {"b": 1}


def bottleneck_parse_result() -> ParseResult:
    """Build a project where ``hub`` is a bottleneck with six dependents.

    Returns:
        The parse result: six importers, ``hub`` and six modules it imports.
    """
    users = [f"user{i}" for i in range(6)]
    deps = [f"dep{i}" for i in range(6)]
    modules = [(name, f"{name}.py") for name in [*users, "hub", *deps]]
    imports = tuple((user, "hub") for user in users) + tuple(("hub", dep) for dep in deps)
    return parse_result_of(*modules, imports=imports)


def test_analyze_measures_the_impact_of_bottlenecks() -> None:
    result = analyze(bottleneck_parse_result())

    assert FindingKind.BOTTLENECK in [f.kind for f in result.findings]
    assert result.impact["hub"] == 6


def test_disabled_findings_still_give_packages_but_no_bottleneck_impact() -> None:
    parsed = bottleneck_parse_result()
    enabled = analyze(parsed)
    disabled = analyze(parsed, FindingsConfig(enabled=False))

    assert disabled.packages == enabled.packages
    assert disabled.findings == []
    assert set(disabled.impact) <= set(disabled.high_coupling_modules[:IMPACT_COUPLED_MODULES])


def test_impact_is_bounded_by_the_displayed_modules() -> None:
    names = [f"m{i:03d}" for i in range(60)]
    parsed = parse_result_of(
        *[(name, f"{name}.py") for name in names],
        imports=tuple((a, b) for a, b in zip(names, names[1:], strict=False)),
    )

    result = analyze(parsed)

    assert len(result.impact) <= IMPACT_COUPLED_MODULES + IMPACT_BOTTLENECK_MODULES


def kinded_graph(*edges: tuple[str, str, ImportKind]) -> nx.DiGraph:
    """Build a DiGraph whose edges carry their import kind.

    Args:
        *edges: ``(source, target, kind)`` triples.

    Returns:
        The graph, with a ``kind`` attribute on every edge.
    """
    graph = nx.DiGraph()
    for source, target, kind in edges:
        graph.add_edge(source, target, weight=1, kind=kind)
    return graph


def test_import_time_graph_keeps_every_module_but_only_module_edges() -> None:
    graph = kinded_graph(
        ("a", "b", ImportKind.MODULE),
        ("b", "c", ImportKind.LAZY),
        ("c", "a", ImportKind.TYPE_CHECKING),
    )
    runtime = import_time_graph(graph)
    assert list(runtime.nodes) == ["a", "b", "c"]
    assert set(runtime.edges) == {("a", "b")}


def test_hidden_tangles_exist_only_when_lazy_or_type_imports_are_counted() -> None:
    graph = kinded_graph(
        ("a", "b", ImportKind.MODULE),
        ("b", "a", ImportKind.TYPE_CHECKING),
        ("x", "y", ImportKind.MODULE),
        ("y", "x", ImportKind.MODULE),
    )
    import_tangles = find_tangles(import_time_graph(graph))
    assert import_tangles == [["x", "y"]]
    assert find_hidden_tangles(graph, import_tangles) == [["a", "b"]]


def test_a_tangle_grown_by_a_lazy_import_is_hidden_too() -> None:
    graph = kinded_graph(
        ("a", "b", ImportKind.MODULE),
        ("b", "a", ImportKind.MODULE),
        ("b", "c", ImportKind.LAZY),
        ("c", "b", ImportKind.MODULE),
    )
    import_tangles = find_tangles(import_time_graph(graph))
    assert import_tangles == [["a", "b"]]
    assert find_hidden_tangles(graph, import_tangles) == [["a", "b", "c"]]
