"""Scripts: code no distribution ships and nothing imports, kept apart from the system."""

from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass

import networkx as nx

PATH_SEPARATOR = "/"
NAME_SEPARATOR = "."


@dataclass(frozen=True, slots=True)
class ScriptGroup:
    """Scripts under one top-level directory and the packages they use.

    Attributes:
        directory: First segment of the scripts' names (``cookbook``, ``.circleci``).
        scripts: How many scripts it holds.
        uses: Top-level packages of the modules its scripts import, sorted.
    """

    directory: str
    scripts: int
    uses: tuple[str, ...]


def find_scripts(graph: nx.DiGraph, unpackaged: Collection[str]) -> frozenset[str]:
    """Return the unpackaged modules that no project module imports.

    Args:
        graph: Full dependency graph, every import kind included.
        unpackaged: Modules no distribution ships.

    Returns:
        The scripts.
    """
    return frozenset(name for name in unpackaged if name in graph and graph.in_degree(name) == 0)


def count_consumers(graph: nx.DiGraph, scripts: Collection[str]) -> dict[str, int]:
    """Count, for each module, the distinct scripts that import it.

    Args:
        graph: Full dependency graph.
        scripts: The scripts.

    Returns:
        Number of consumer scripts per imported module; modules without any are absent.
    """
    consumers: Counter[str] = Counter()
    for script in scripts:
        for target in graph.successors(script):
            if target not in scripts:
                consumers[target] += 1
    return dict(consumers)


def group_scripts(graph: nx.DiGraph, scripts: Collection[str]) -> list[ScriptGroup]:
    """Group scripts by their top-level directory, most scripts first.

    Args:
        graph: Full dependency graph.
        scripts: The scripts.

    Returns:
        One group per directory, by decreasing size, then by name.
    """
    counts: Counter[str] = Counter()
    uses: dict[str, set[str]] = defaultdict(set)
    for script in scripts:
        directory = _first_segment(script)
        counts[directory] += 1
        for target in graph.successors(script):
            if target not in scripts:
                uses[directory].add(_first_segment(target))
    ordered = sorted(counts, key=lambda d: (-counts[d], d))
    return [ScriptGroup(d, counts[d], tuple(sorted(uses[d]))) for d in ordered]


def _first_segment(name: str) -> str:
    """Return the first segment of a dotted or path-like module name.

    Args:
        name: Module name.

    Returns:
        Its top-level directory or package.
    """
    separator = PATH_SEPARATOR if PATH_SEPARATOR in name else NAME_SEPARATOR
    return name.split(separator, 1)[0]
