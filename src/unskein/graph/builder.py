"""Build the module dependency graph from resolved parse results."""

from collections import Counter

import networkx as nx

from unskein.parsers.models import ImportKind, ParseResult

NAMESPACE_ATTRIBUTE = "namespace"


def build_graph(result: ParseResult) -> nx.DiGraph:
    """Build a directed graph of internal module dependencies.

    Only the project's own modules become nodes; external imports are dropped,
    since they already served their purpose through ``is_external``. Isolated
    modules and internal targets whose file could not be parsed are nodes too;
    namespace packages that are imported are nodes marked ``namespace=True``.
    Nodes are inserted in sorted order so traversals are deterministic.

    Args:
        result: Parse result with re-exports already resolved.

    Returns:
        Graph with one edge ``a -> b`` per importing/imported module pair,
        whose ``weight`` counts the import statements behind it and whose
        ``kind`` is the strongest ``ImportKind`` among them.
    """
    edge_counts: Counter[tuple[str, str]] = Counter()
    edge_kinds: dict[tuple[str, str], ImportKind] = {}
    nodes = {module.name for module in result.modules}
    for module in result.modules:
        for edge in module.imports:
            if not edge.is_external:
                pair = (edge.source, edge.target)
                edge_counts[pair] += 1
                edge_kinds[pair] = edge_kinds.get(pair, edge.kind).stronger(edge.kind)
                nodes.add(edge.target)

    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(nodes))
    for (source, target), weight in sorted(edge_counts.items()):
        graph.add_edge(source, target, weight=weight, kind=edge_kinds[source, target])
    for name in result.namespaces:
        if name in graph:
            graph.nodes[name][NAMESPACE_ATTRIBUTE] = True
    return graph
