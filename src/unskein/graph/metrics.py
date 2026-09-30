"""Coupling metrics, cycle detection and the consolidated analysis result."""

from dataclasses import dataclass, field
from itertools import islice

import networkx as nx

from unskein.config import FindingsConfig
from unskein.graph.builder import build_graph
from unskein.graph.findings import Finding, find_findings
from unskein.graph.percentile import nearest_rank_percentile
from unskein.parsers.models import ParseResult, ParseWarning

MAX_CYCLES = 100
HIGH_COUPLING_PERCENTILE = 90
PACKAGE_INIT_FILE = "__init__.py"


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
        tangles: Groups of mutually dependent modules (strongly connected
            components with more than one module), largest first; never truncated.
        findings: Architecture findings, ordered by kind and module.
        findings_enabled: Whether findings were computed; the report omits its section when False.
    """

    graph: nx.DiGraph
    coupling_metrics: dict[str, CouplingMetrics]
    cycles: list[list[str]]
    high_coupling_modules: list[str]
    parse_warnings: list[ParseWarning] = field(default_factory=list)
    cycles_truncated: bool = False
    tangles: list[list[str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    findings_enabled: bool = True


def compute_coupling(graph: nx.DiGraph) -> dict[str, CouplingMetrics]:
    """Compute Ca and Ce for every module in the graph.

    Ca counts distinct importing modules and Ce distinct imported modules;
    the edge ``weight`` (number of import statements) is ignored.

    Args:
        graph: Internal module dependency graph.

    Returns:
        Coupling metrics keyed by module name.
    """
    return {
        module: CouplingMetrics(module, graph.in_degree(module), graph.out_degree(module))
        for module in graph.nodes
    }


def _canonical_cycle(cycle: list[str]) -> list[str]:
    """Rotate a cycle so it starts at its smallest module name.

    Args:
        cycle: Modules of one cycle, in dependency order.

    Returns:
        The same cycle and direction, starting at its minimum element.
    """
    start = cycle.index(min(cycle))
    return cycle[start:] + cycle[:start]


def find_cycles(graph: nx.DiGraph, limit: int = MAX_CYCLES) -> tuple[list[list[str]], bool]:
    """Find dependency cycles, stopping after ``limit`` to avoid blowups in dense graphs.

    The number of simple cycles can grow exponentially, so at most
    ``limit + 1`` are ever enumerated: the extra one only tells whether more exist.
    networkx walks internal sets whose order follows the string hash seed, so the
    graph is enumerated over integer labels, whose set order is fixed, to keep
    both the cycles and the truncation point identical between runs.

    Args:
        graph: Internal module dependency graph.
        limit: Maximum number of cycles to collect.

    Returns:
        The cycles found, each rotated to start at its smallest module, and
        whether the search was truncated at ``limit``.
    """
    names = sorted(graph.nodes)
    indexed = nx.relabel_nodes(graph, {name: index for index, name in enumerate(names)})
    found = list(islice(nx.simple_cycles(indexed), limit + 1))
    truncated = len(found) > limit
    named = [[names[index] for index in cycle] for cycle in found[:limit]]
    return [_canonical_cycle(cycle) for cycle in named], truncated


def find_tangles(graph: nx.DiGraph) -> list[list[str]]:
    """Find groups of modules that all depend on each other, directly or not.

    A tangle is a strongly connected component with more than one module:
    every cycle lives inside one. Unlike cycle enumeration it is linear and
    exact, so it shows the true size of a knot even when ``find_cycles`` is
    truncated (networkx: 100+ cycles, but one tangle of 279 modules).

    Args:
        graph: Internal module dependency graph.

    Returns:
        Tangles with their members sorted, largest first, then by first member.
    """
    tangles = [sorted(c) for c in nx.strongly_connected_components(graph) if len(c) > 1]
    return sorted(tangles, key=lambda members: (-len(members), members[0]))


def find_high_coupling(
    metrics: dict[str, CouplingMetrics], percentile: int = HIGH_COUPLING_PERCENTILE
) -> list[str]:
    """Select modules whose combined ``Ca + Ce`` is in the top percentile.

    The threshold is the nearest-rank percentile of all modules' scores (the
    ``ceil(percentile / 100 * n)``-th smallest score): no interpolation, so it
    is always a real score and easy to explain in the report. Ties at the
    threshold are all selected; modules with no coupling never are.

    Args:
        metrics: Coupling metrics keyed by module name.
        percentile: Percentile threshold; modules at or above it are selected.

    Returns:
        Names of the most coupled modules, candidates for AI interpretation,
        ordered by score descending, then by name.
    """
    if not metrics:
        return []
    score = {name: m.afferent + m.efferent for name, m in metrics.items()}
    threshold = nearest_rank_percentile(list(score.values()), percentile)
    selected = [name for name, s in score.items() if s > 0 and s >= threshold]
    return sorted(selected, key=lambda name: (-score[name], name))


def analyze(result: ParseResult, findings_config: FindingsConfig | None = None) -> AnalysisResult:
    """Run graph construction, coupling metrics, cycle detection and findings.

    Expects re-exports to be resolved already (``resolve_indirection``);
    otherwise dependencies routed through package facades point at the facade.

    Args:
        result: Parse result with re-exports already resolved.
        findings_config: Findings thresholds; None means the defaults.

    Returns:
        The consolidated deterministic analysis.
    """
    if findings_config is None:
        findings_config = FindingsConfig()
    graph = build_graph(result)
    coupling = compute_coupling(graph)
    cycles, cycles_truncated = find_cycles(graph)
    packages = {m.name for m in result.modules if m.file_path.name == PACKAGE_INIT_FILE}
    return AnalysisResult(
        graph=graph,
        coupling_metrics=coupling,
        cycles=cycles,
        high_coupling_modules=find_high_coupling(coupling),
        parse_warnings=list(result.warnings),
        cycles_truncated=cycles_truncated,
        tangles=find_tangles(graph),
        findings=find_findings(graph, coupling, findings_config, packages=packages),
        findings_enabled=findings_config.enabled,
    )
