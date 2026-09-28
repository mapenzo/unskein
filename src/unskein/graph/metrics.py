"""Coupling metrics, cycle detection and the consolidated analysis result."""

from dataclasses import dataclass, field

import networkx as nx

from unskein.parsers.models import ParseResult

MAX_CYCLES = 100
HIGH_COUPLING_PERCENTILE = 90


@dataclass(slots=True)
class CouplingMetrics:
    """Afferent/efferent coupling of a single module.

    Attributes:
        module: Dotted module name.
        afferent: Ca, number of modules that depend on this one.
        efferent: Ce, number of modules this one depends on.
    """

    module: str
    afferent: int
    efferent: int

    @property
    def instability(self) -> float:
        """Instability ``Ce / (Ca + Ce)`` in ``[0, 1]``; 0.0 for isolated modules."""
        total = self.afferent + self.efferent
        return self.efferent / total if total else 0.0


@dataclass
class AnalysisResult:
    """Deterministic analysis output; the handoff point to the AI and report layers.

    Attributes:
        graph: Internal module dependency graph.
        coupling_metrics: Metrics per module name.
        cycles: Dependency cycles found, each as a list of module names.
        high_coupling_modules: Modules in the top coupling percentile.
        parse_warnings: Warnings collected while parsing and resolving.
        cycles_truncated: Whether cycle detection stopped at its limit.
    """

    graph: nx.DiGraph
    coupling_metrics: dict[str, CouplingMetrics]
    cycles: list[list[str]]
    high_coupling_modules: list[str]
    parse_warnings: list[str] = field(default_factory=list)
    cycles_truncated: bool = False


def compute_coupling(graph: nx.DiGraph) -> dict[str, CouplingMetrics]:
    """Compute Ca and Ce for every module in the graph.

    Args:
        graph: Internal module dependency graph.

    Returns:
        Coupling metrics keyed by module name.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def find_cycles(graph: nx.DiGraph, limit: int = MAX_CYCLES) -> tuple[list[list[str]], bool]:
    """Find dependency cycles, stopping after ``limit`` to avoid blowups in dense graphs.

    Args:
        graph: Internal module dependency graph.
        limit: Maximum number of cycles to collect.

    Returns:
        The cycles found and whether the search was truncated at ``limit``.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def find_high_coupling(
    metrics: dict[str, CouplingMetrics], percentile: int = HIGH_COUPLING_PERCENTILE
) -> list[str]:
    """Select modules whose combined ``Ca + Ce`` is in the top percentile.

    Args:
        metrics: Coupling metrics keyed by module name.
        percentile: Percentile threshold; modules at or above it are selected.

    Returns:
        Names of the most coupled modules, candidates for AI interpretation.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def analyze(result: ParseResult) -> AnalysisResult:
    """Run graph construction, coupling metrics and cycle detection.

    Args:
        result: Parse result with re-exports already resolved.

    Returns:
        The consolidated deterministic analysis.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
