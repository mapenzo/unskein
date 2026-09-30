import os
import subprocess
import sys
import textwrap

import networkx as nx
import pytest

from unskein.config import FindingsConfig
from unskein.graph.findings import Finding, FindingKind, find_findings
from unskein.graph.metrics import compute_coupling
from unskein.graph.percentile import nearest_rank_percentile


def findings_of(graph: nx.DiGraph, **overrides: object) -> list[Finding]:
    """Run the rules on a graph with its real coupling metrics.

    Args:
        graph: Module dependency graph.
        **overrides: ``FindingsConfig`` fields to change.

    Returns:
        The findings.
    """
    config = FindingsConfig(**overrides)
    return find_findings(graph, compute_coupling(graph), config)


def kinds(findings: list[Finding]) -> list[FindingKind]:
    """Return the kind of each finding, in order.

    Args:
        findings: Findings to inspect.

    Returns:
        Their kinds.
    """
    return [finding.kind for finding in findings]


def star(center: str, importers: int, imported: int) -> nx.DiGraph:
    """Build a graph where ``center`` has the given Ca and Ce.

    Args:
        center: Name of the central module.
        importers: Modules that import it (its Ca).
        imported: Modules it imports (its Ce).

    Returns:
        The graph.
    """
    graph = nx.DiGraph()
    graph.add_node(center)
    graph.add_edges_from((f"user{i}", center) for i in range(importers))
    graph.add_edges_from((center, f"dep{i}") for i in range(imported))
    return graph


@pytest.mark.parametrize(
    ("values", "percentile", "expected"),
    [
        ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90, 9),
        ([5], 90, 5),
        ([3, 1, 2], 100, 3),
        ([3, 1, 2], 1, 1),
    ],
)
def test_nearest_rank_percentile_is_always_a_real_value(
    values: list[int], percentile: int, expected: int
) -> None:
    assert nearest_rank_percentile(values, percentile) == expected


def test_bottleneck_needs_high_ca_and_high_ce() -> None:
    graph = star("hub", importers=6, imported=6)

    found = findings_of(graph)

    assert [(f.kind, f.modules) for f in found] == [(FindingKind.BOTTLENECK, ("hub",))]
    assert found[0].evidence == {"afferent": 6, "efferent": 6}


def test_high_ca_alone_is_not_a_bottleneck() -> None:
    assert kinds(findings_of(star("base", importers=8, imported=0))) == []


def test_bottleneck_below_the_absolute_minimum_is_ignored() -> None:
    assert kinds(findings_of(star("hub", importers=3, imported=3))) == []


def test_bottleneck_minimum_comes_from_the_config() -> None:
    graph = star("hub", importers=3, imported=3)

    found = findings_of(graph, bottleneck_min_coupling=3)

    assert FindingKind.BOTTLENECK in kinds(found)


def test_orchestrator_is_a_module_with_many_dependencies() -> None:
    found = findings_of(star("app.main", importers=0, imported=12))

    assert [(f.kind, f.modules) for f in found] == [(FindingKind.ORCHESTRATOR, ("app.main",))]
    assert found[0].evidence == {"afferent": 0, "efferent": 12}


def test_orchestrator_below_the_absolute_minimum_is_ignored() -> None:
    assert kinds(findings_of(star("app.main", importers=0, imported=9))) == []


def test_stable_module_depending_on_an_unstable_one_is_flagged() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("user1", "core"), ("user2", "core"), ("core", "flaky")])
    graph.add_edges_from(("flaky", f"dep{i}") for i in range(5))

    found = findings_of(graph)

    assert [(f.kind, f.modules) for f in found] == [
        (FindingKind.UNSTABLE_DEPENDENCY, ("core", "flaky"))
    ]
    assert found[0].evidence == {
        "afferent_from": 2,
        "instability_from": 0.33,
        "instability_to": 0.83,
    }


def test_module_nobody_relies_on_is_not_an_unstable_dependency_source() -> None:
    graph = nx.DiGraph()
    graph.add_edge("cli", "flaky")
    graph.add_edges_from(("flaky", f"dep{i}") for i in range(5))

    assert kinds(findings_of(graph)) == []


def test_unstable_dependency_gap_comes_from_the_config() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("user1", "core"), ("user2", "core"), ("core", "flaky")])
    graph.add_edges_from(("flaky", f"dep{i}") for i in range(5))

    assert kinds(findings_of(graph, stability_gap=0.9)) == []


def test_module_with_no_dependencies_either_way_is_an_orphan() -> None:
    graph = nx.DiGraph()
    graph.add_node("lonely")

    found = findings_of(graph)

    assert [(f.kind, f.modules, f.evidence) for f in found] == [
        (FindingKind.ORPHAN, ("lonely",), {})
    ]


@pytest.mark.parametrize("pattern", ["tool.run", "tool.*"])
def test_configured_entry_points_are_never_orphans(pattern: str) -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(["tool.run", "stray"])

    found = findings_of(graph, entry_points=(pattern,))

    assert [f.modules for f in found] == [("stray",)]


def test_main_modules_are_never_orphans() -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(["app.__main__", "stray"])

    assert [f.modules for f in findings_of(graph)] == [("stray",)]


def test_package_facades_are_excluded_from_every_rule() -> None:
    graph = nx.DiGraph()
    graph.add_node("pkg")
    metrics = compute_coupling(graph)

    found = find_findings(graph, metrics, FindingsConfig(), packages={"pkg"})

    assert found == []


def test_disabled_findings_compute_nothing() -> None:
    graph = nx.DiGraph()
    graph.add_node("lonely")

    assert findings_of(graph, enabled=False) == []


@pytest.mark.parametrize("module_count", [0, 1, 2])
def test_tiny_projects_never_crash_and_flag_nothing_but_orphans(module_count: int) -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(f"m{i}" for i in range(module_count))

    found = findings_of(graph)

    assert set(kinds(found)) <= {FindingKind.ORPHAN}


def test_findings_are_ordered_by_kind_then_module() -> None:
    graph = star("hub", importers=6, imported=6)
    graph.add_nodes_from(["zeta", "alpha"])

    found = findings_of(graph)

    assert [(f.kind, f.modules) for f in found] == [
        (FindingKind.BOTTLENECK, ("hub",)),
        (FindingKind.ORPHAN, ("alpha",)),
        (FindingKind.ORPHAN, ("zeta",)),
    ]


FINDINGS_SCRIPT = textwrap.dedent("""
    import networkx as nx
    from unskein.config import FindingsConfig
    from unskein.graph.findings import find_findings
    from unskein.graph.metrics import compute_coupling

    graph = nx.DiGraph()
    graph.add_nodes_from(f"m{i:02d}" for i in range(30))
    for i in range(30):
        for step in (1, 3, 7):
            graph.add_edge(f"m{i:02d}", f"m{(i * step + 1) % 30:02d}")
    for i in range(14):
        graph.add_edge("m00", f"x{i}")
    print(find_findings(graph, compute_coupling(graph), FindingsConfig()))
""")


def test_findings_do_not_depend_on_the_hash_seed() -> None:
    outputs = {
        subprocess.run(
            [sys.executable, "-c", FINDINGS_SCRIPT],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("0", "1", "2", "3")
    }

    assert len(outputs) == 1
