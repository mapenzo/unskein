"""Coupling metrics, cycle detection and the consolidated analysis result."""

from dataclasses import dataclass, field, replace
from itertools import islice

import networkx as nx

from unskein.config import FindingsConfig
from unskein.graph.builder import build_graph
from unskein.graph.coupling import CouplingMetrics
from unskein.graph.distributions import (
    DistributionEdge,
    DistributionSummary,
    analyze_distributions,
)
from unskein.graph.findings import Finding, FindingKind, find_findings
from unskein.graph.impact import impact_radius
from unskein.graph.leaks import LeakModule, summarize_leaks
from unskein.graph.missing import find_missing_modules
from unskein.graph.native import NativeModule, find_optional_native_required, summarize_native
from unskein.graph.packages import PackageEdge, PackageMetrics, summarize_project_packages
from unskein.graph.percentile import nearest_rank_percentile
from unskein.graph.scripts import ScriptGroup, count_consumers, find_scripts, group_scripts
from unskein.graph.stars import WildcardModule, find_wildcard_imports, summarize_wildcards
from unskein.parsers.models import ImportKind, ParseResult, ParseWarning, VirtualKind

MAX_CYCLES = 100
HIGH_COUPLING_PERCENTILE = 90
PACKAGE_INIT_FILE = "__init__.py"
# Impact costs one graph traversal per module, so only what the report shows is measured.
IMPACT_COUPLED_MODULES = 15
IMPACT_BOTTLENECK_MODULES = 10


@dataclass
class AnalysisResult:
    """Deterministic analysis output; the handoff point to the AI and report layers.

    Attributes:
        graph: Internal module dependency graph, scripts excluded.
        coupling_metrics: Metrics per module name.
        cycles: Dependency cycles that exist at import time (module-level imports
            only), each as a list of module names.
        high_coupling_modules: Modules in the top coupling percentile.
        parse_warnings: Warnings collected while parsing and resolving.
        cycles_truncated: Whether cycle detection stopped at its limit.
        tangles: Groups of mutually dependent modules at import time (strongly
            connected components with more than one module), largest first; never truncated.
        findings: Architecture findings, ordered by kind and module.
        findings_enabled: Whether findings were computed; the report omits its section when False.
        impact: Modules that depend on each displayed module, directly or not.
        packages: Coupling per package, most coupled first.
        package_edges: Dependencies between packages, with the most imports first.
        hidden_tangles: Groups that depend on each other only once lazy and
            type-only imports are counted, largest first.
        scripts: Unpackaged modules nothing imports; outside every metric.
        script_groups: Scripts by top-level directory, most first.
        distributions: Installability of each named distribution, by name.
        distribution_edges: Imports between distributions with what each declares.
        virtual: Graph nodes with no parsed file (namespace packages, compiled extensions,
            stubs), with their kind, sorted.
        native: How packaged code uses each compiled extension and stub-only module, by name.
        wildcards: Star imports of packaged code with their fixes, by star-imported module;
            empty with findings off.
        leaks: Imports of package internals with their fixes, by written module; empty with
            findings or api_leaks off.
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
    impact: dict[str, int] = field(default_factory=dict)
    packages: list[PackageMetrics] = field(default_factory=list)
    package_edges: list[PackageEdge] = field(default_factory=list)
    hidden_tangles: list[list[str]] = field(default_factory=list)
    scripts: frozenset[str] = field(default_factory=frozenset)
    script_groups: list[ScriptGroup] = field(default_factory=list)
    distributions: list[DistributionSummary] = field(default_factory=list)
    distribution_edges: list[DistributionEdge] = field(default_factory=list)
    virtual: dict[str, VirtualKind] = field(default_factory=dict)
    native: list[NativeModule] = field(default_factory=list)
    wildcards: list[WildcardModule] = field(default_factory=list)
    leaks: list[LeakModule] = field(default_factory=list)

    @property
    def namespaces(self) -> frozenset[str]:
        """Return the namespace packages among the graph nodes."""
        return frozenset(
            name for name, kind in self.virtual.items() if kind is VirtualKind.NAMESPACE
        )


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


def import_time_graph(graph: nx.DiGraph) -> nx.DiGraph:
    """Keep only the dependencies that exist when modules are imported.

    Args:
        graph: Internal module dependency graph, whose edges carry their ``kind``.

    Returns:
        A copy with every module and only the edges of kind ``MODULE``, in the
        same order, so traversals stay deterministic.
    """
    runtime = nx.DiGraph()
    runtime.add_nodes_from(graph.nodes)
    runtime.add_edges_from(
        (source, target, data)
        for source, target, data in graph.edges(data=True)
        if data["kind"] is ImportKind.MODULE
    )
    return runtime


def find_hidden_tangles(graph: nx.DiGraph, import_tangles: list[list[str]]) -> list[list[str]]:
    """Find tangles that appear only when lazy and type-only imports are counted.

    A tangle of the complete graph that is also a tangle at import time is not
    hidden; one that is larger than any of those (an import-time tangle grown by
    a lazy import) is.

    Args:
        graph: Internal module dependency graph, whose edges carry their ``kind``.
        import_tangles: Tangles at import time, as ``find_tangles`` returns them.

    Returns:
        The hidden tangles with their members sorted, largest first.
    """
    import_time = {tuple(tangle) for tangle in import_tangles}
    return [tangle for tangle in find_tangles(graph) if tuple(tangle) not in import_time]


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


def _impact_targets(high_coupling: list[str], findings: list[Finding]) -> list[str]:
    """Pick the modules whose impact is worth measuring: the ones the report displays.

    Args:
        high_coupling: Most coupled modules, most coupled first.
        findings: Architecture findings, ordered by kind and module.

    Returns:
        The first coupled modules plus the first bottleneck modules.
    """
    bottlenecks = [f.modules[0] for f in findings if f.kind is FindingKind.BOTTLENECK]
    return [*high_coupling[:IMPACT_COUPLED_MODULES], *bottlenecks[:IMPACT_BOTTLENECK_MODULES]]


def analyze(result: ParseResult, findings_config: FindingsConfig | None = None) -> AnalysisResult:
    """Run the graph, coupling, cycles, findings, impact and package analyses.

    Expects re-exports to be resolved already (``resolve_indirection``);
    otherwise dependencies routed through package facades point at the facade.

    Args:
        result: Parse result with re-exports already resolved.
        findings_config: Findings thresholds; None means the defaults.

    Returns:
        The consolidated deterministic analysis. Cycles and tangles are computed
        at import time (module-level imports only); the rest counts every import.
    """
    if findings_config is None:
        findings_config = FindingsConfig()
    findings_config = replace(
        findings_config, entry_points=(*result.entry_points, *findings_config.entry_points)
    )
    full_graph = build_graph(result)
    unpackaged = {m.name for m in result.modules if not m.is_packaged}
    scripts = find_scripts(full_graph, unpackaged)
    # A virtual module only scripts import is no part of the measured system either.
    script_only = {
        name
        for name in result.virtual
        if name in full_graph
        and all(importer in scripts for importer in full_graph.predecessors(name))
    }
    hidden = scripts | script_only
    graph = nx.subgraph_view(full_graph, filter_node=lambda node: node not in hidden)
    coupling = compute_coupling(graph)
    for module, consumers in count_consumers(full_graph, scripts).items():
        if module in coupling:
            coupling[module].consumers = consumers
    import_graph = import_time_graph(graph)
    cycles, cycles_truncated = find_cycles(import_graph)
    tangles = find_tangles(import_graph)
    facades = {m.name for m in result.modules if m.file_path.name == PACKAGE_INIT_FILE}
    virtual = {name: module.kind for name, module in result.virtual.items() if name in graph}
    namespaces = frozenset(name for name, kind in virtual.items() if kind is VirtualKind.NAMESPACE)
    high_coupling = find_high_coupling(coupling)
    findings = find_findings(
        full_graph,
        coupling,
        findings_config,
        packages=facades | virtual.keys(),
        scripts=scripts,
        virtual=frozenset(virtual),
    )
    distribution_analysis = analyze_distributions(result, scripts)
    native = summarize_native(result, graph, scripts)
    impact_targets = _impact_targets(high_coupling, findings)
    wildcards: list[WildcardModule] = []
    leaks: list[LeakModule] = []
    if findings_config.enabled:
        missing = find_missing_modules(result, scripts)
        wildcards = summarize_wildcards(result, scripts) if result.star_fixes else []
        if result.api_leaks:
            leaks = summarize_leaks(result, import_graph, findings_config.api)
        findings = [
            *findings,
            *distribution_analysis.findings,
            *missing,
            *find_optional_native_required(native),
            *find_wildcard_imports(wildcards),
        ]
    package_metrics, package_edges = summarize_project_packages(
        graph, findings_config.package_depth, facades=facades, virtual=namespaces
    )
    return AnalysisResult(
        graph=graph,
        coupling_metrics=coupling,
        cycles=cycles,
        high_coupling_modules=high_coupling,
        parse_warnings=list(result.warnings),
        cycles_truncated=cycles_truncated,
        tangles=tangles,
        findings=findings,
        findings_enabled=findings_config.enabled,
        impact=impact_radius(graph, impact_targets),
        packages=package_metrics,
        package_edges=package_edges,
        hidden_tangles=find_hidden_tangles(graph, tangles),
        scripts=scripts,
        script_groups=group_scripts(full_graph, scripts),
        distributions=distribution_analysis.summaries,
        distribution_edges=distribution_analysis.edges,
        virtual=virtual,
        native=native,
        wildcards=wildcards,
        leaks=leaks,
    )
