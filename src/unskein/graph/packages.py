"""Coupling aggregated by package: the overview a table of modules cannot give."""

from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass

import networkx as nx

from unskein.config import DEFAULT_PACKAGE_DEPTH

ROOT_PACKAGE = "(root)"
AUTO_START_DEPTH = DEFAULT_PACKAGE_DEPTH


@dataclass(slots=True)
class PackageMetrics:
    """Coupling of a package with the other packages of the project.

    Attributes:
        name: Dotted package name, or ``ROOT_PACKAGE``.
        modules: Number of modules the package holds.
        afferent: Ca, number of other packages that import this one.
        efferent: Ce, number of other packages this one imports.
    """

    name: str
    modules: int
    afferent: int
    efferent: int

    @property
    def instability(self) -> float:
        """Instability ``Ce / (Ca + Ce)`` in ``[0, 1]``; 0.0 for isolated packages."""
        total = self.afferent + self.efferent
        return self.efferent / total if total else 0.0


@dataclass(frozen=True, slots=True)
class PackageEdge:
    """Dependencies from one package to another.

    Attributes:
        source: Package that imports.
        target: Package that is imported.
        imports: Module-level dependencies from ``source`` to ``target``.
    """

    source: str
    target: str
    imports: int


def package_of(module: str, depth: int, facades: Collection[str]) -> str:
    """Return the package a module belongs to at a given depth.

    A facade (``__init__``) is the package itself, named by its first ``depth``
    segments. A plain module belongs to the package it sits in, cut to ``depth``
    segments; only a module with no package above it (a top-level single file)
    goes to ``ROOT_PACKAGE``.

    Args:
        module: Dotted module name.
        depth: Dotted segments that name a package.
        facades: Names of modules that are package ``__init__`` files.

    Returns:
        The package name, or ``ROOT_PACKAGE``.
    """
    segments = module.split(".")
    if module in facades:
        return ".".join(segments[:depth])
    return ".".join(segments[: min(depth, len(segments) - 1)]) or ROOT_PACKAGE


def summarize_packages(
    graph: nx.DiGraph, depth: int, *, facades: Collection[str] = frozenset()
) -> tuple[list[PackageMetrics], list[PackageEdge]]:
    """Group the modules of a graph into packages and count the dependencies between them.

    Imports between modules of the same package are not package dependencies.

    Args:
        graph: Internal module dependency graph.
        depth: Dotted segments that name a package.
        facades: Names of modules that are package ``__init__`` files.

    Returns:
        The packages ordered by ``Ca + Ce`` (highest first, then by name) and the
        dependencies between them ordered by import count (highest first, then by names).
    """
    owner = {module: package_of(module, depth, facades) for module in graph.nodes}
    module_counts = Counter(owner.values())
    import_counts: Counter[tuple[str, str]] = Counter()
    for source, target in graph.edges:
        if owner[source] != owner[target]:
            import_counts[owner[source], owner[target]] += 1
    importers: defaultdict[str, set[str]] = defaultdict(set)
    imported: defaultdict[str, set[str]] = defaultdict(set)
    for source, target in import_counts:
        importers[target].add(source)
        imported[source].add(target)
    packages = [
        PackageMetrics(name, count, len(importers[name]), len(imported[name]))
        for name, count in module_counts.items()
    ]
    packages.sort(key=lambda package: (-(package.afferent + package.efferent), package.name))
    edges = [
        PackageEdge(source, target, count) for (source, target), count in import_counts.items()
    ]
    edges.sort(key=lambda edge: (-edge.imports, edge.source, edge.target))
    return packages, edges


def summarize_project_packages(
    graph: nx.DiGraph, depth: int | None, *, facades: Collection[str] = frozenset()
) -> tuple[list[PackageMetrics], list[PackageEdge]]:
    """Summarize packages at a fixed depth, or at an automatically chosen one.

    The automatic depth starts at ``AUTO_START_DEPTH`` and goes one level deeper
    when the whole project is a single top-level package, where that first
    summary would say nothing.

    Args:
        graph: Internal module dependency graph.
        depth: Dotted segments that name a package; None for automatic.
        facades: Names of modules that are package ``__init__`` files.

    Returns:
        The same pair as ``summarize_packages``.
    """
    if depth is not None:
        return summarize_packages(graph, depth, facades=facades)
    packages, edges = summarize_packages(graph, AUTO_START_DEPTH, facades=facades)
    if len(packages) == 1 and packages[0].name != ROOT_PACKAGE:
        return summarize_packages(graph, AUTO_START_DEPTH + 1, facades=facades)
    return packages, edges
