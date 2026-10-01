"""Transitive impact of a module: how many modules a change to it can reach."""

from collections.abc import Iterable

import networkx as nx


def impact_radius(graph: nx.DiGraph, modules: Iterable[str]) -> dict[str, int]:
    """Count the modules that depend on each given module, directly or indirectly.

    An edge ``a -> b`` means ``a`` imports ``b``, so the dependents of ``b`` are its
    ancestors in the graph. A module never counts itself, but the other members of a
    tangle it belongs to do. Each module costs one traversal of the graph, so callers
    pass only the few modules they display.

    Args:
        graph: Internal module dependency graph.
        modules: Modules to measure; names missing from the graph are skipped.

    Returns:
        Dependent count per module, in the order the modules were first given.
    """
    return {
        module: len(nx.ancestors(graph, module))
        for module in dict.fromkeys(modules)
        if module in graph
    }
