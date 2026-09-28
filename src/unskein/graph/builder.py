"""Build the module dependency graph from resolved parse results."""

import networkx as nx

from unskein.parsers.models import ParseResult


def build_graph(result: ParseResult) -> nx.DiGraph:
    """Build a directed graph of internal module dependencies.

    Only the project's own modules become nodes; external imports are dropped,
    since they already served their purpose through ``is_external``.

    Args:
        result: Parse result with re-exports already resolved.

    Returns:
        Graph with an edge ``a -> b`` for every internal import of ``b`` by ``a``.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
