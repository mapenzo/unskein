"""Build the module dependency graph from resolved parse results."""

from collections import Counter

import networkx as nx

from unskein.parsers.models import ParseResult


def build_graph(result: ParseResult) -> nx.DiGraph:
    """Build a directed graph of internal module dependencies.

    Only the project's own modules become nodes; external imports are dropped,
    since they already served their purpose through ``is_external``. Isolated
    modules and internal targets whose file could not be parsed are nodes too.
    Nodes are inserted in sorted order so traversals are deterministic.

    Args:
        result: Parse result with re-exports already resolved.

    Returns:
        Graph with one edge ``a -> b`` per importing/imported module pair,
        whose ``weight`` counts the import statements behind it.
    """
    edge_counts: Counter[tuple[str, str]] = Counter()
    nodes = {module.name for module in result.modules}
    for module in result.modules:
        for edge in module.imports:
            if not edge.is_external:
                edge_counts[edge.source, edge.target] += 1
                nodes.add(edge.target)

    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(nodes))
    for (source, target), weight in sorted(edge_counts.items()):
        graph.add_edge(source, target, weight=weight)
    return graph
