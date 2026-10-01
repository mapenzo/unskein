"""Deterministic architecture findings derived from the dependency graph and its metrics."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase

import networkx as nx

from unskein.config import FindingsConfig
from unskein.graph.coupling import CouplingMetrics
from unskein.graph.percentile import nearest_rank_percentile

MAIN_MODULE_SUFFIX = "__main__"
INSTABILITY_DECIMALS = 2


class FindingKind(StrEnum):
    """Kinds of finding, in the order the report lists them.

    Attributes:
        UNSTABLE_DEPENDENCY: A module others rely on imports a much more unstable one.
        BOTTLENECK: A module many depend on that also depends on many.
        ORCHESTRATOR: A module with far more dependencies than the rest.
        ORPHAN: A module that imports no project module and is imported by none.
    """

    UNSTABLE_DEPENDENCY = "unstable_dependency"
    BOTTLENECK = "bottleneck"
    ORCHESTRATOR = "orchestrator"
    ORPHAN = "orphan"


@dataclass(frozen=True, slots=True)
class Finding:
    """One architecture finding and the numbers that triggered it.

    Attributes:
        kind: Which rule produced it.
        modules: The module, or ``(importer, imported)`` for an unstable dependency.
        evidence: Metrics that triggered the rule, shown so it can be checked.
    """

    kind: FindingKind
    modules: tuple[str, ...]
    evidence: dict[str, float]


def find_findings(
    graph: nx.DiGraph,
    metrics: Mapping[str, CouplingMetrics],
    config: FindingsConfig,
    *,
    packages: Collection[str] = frozenset(),
) -> list[Finding]:
    """Apply every rule to the graph and its coupling metrics.

    Package facades (``__init__.py``) are left out of every rule and of the
    percentiles: their coupling says nothing about the design.

    Args:
        graph: Internal module dependency graph.
        metrics: Coupling metrics keyed by module name.
        config: Thresholds and entry points.
        packages: Names of modules that are package ``__init__`` files.

    Returns:
        The findings, ordered by kind and then by module; empty when disabled.
    """
    if not config.enabled:
        return []
    candidates = {name: m for name, m in metrics.items() if name not in packages}
    return [
        *_unstable_dependencies(graph, candidates, config),
        *_bottlenecks(candidates, config),
        *_orchestrators(candidates, config),
        *_orphans(candidates, config),
    ]


def _unstable_dependencies(
    graph: nx.DiGraph, metrics: Mapping[str, CouplingMetrics], config: FindingsConfig
) -> list[Finding]:
    """Find modules others rely on that import a much more unstable module.

    Args:
        graph: Internal module dependency graph.
        metrics: Coupling metrics of the modules under analysis.
        config: Stability thresholds.

    Returns:
        One finding per offending import, sorted by the pair of modules.
    """
    found = []
    for source, target in graph.edges:
        if source not in metrics or target not in metrics:
            continue
        importer, imported = metrics[source], metrics[target]
        # Rounding absorbs float noise (0.8333 - 0.3333) and matches the 2-decimal report.
        gap = round(imported.instability - importer.instability, INSTABILITY_DECIMALS)
        if importer.afferent >= config.stability_min_afferent and gap >= config.stability_gap:
            evidence = {
                "afferent_from": importer.afferent,
                "instability_from": round(importer.instability, INSTABILITY_DECIMALS),
                "instability_to": round(imported.instability, INSTABILITY_DECIMALS),
            }
            found.append(Finding(FindingKind.UNSTABLE_DEPENDENCY, (source, target), evidence))
    return sorted(found, key=lambda finding: finding.modules)


def _bottlenecks(metrics: Mapping[str, CouplingMetrics], config: FindingsConfig) -> list[Finding]:
    """Find modules whose Ca and Ce are both high for this project.

    Args:
        metrics: Coupling metrics of the modules under analysis.
        config: Percentile and minimum coupling.

    Returns:
        One finding per bottleneck, sorted by module.
    """
    if not metrics:
        return []
    afferent_limit = _limit(
        [m.afferent for m in metrics.values()],
        config.bottleneck_percentile,
        config.bottleneck_min_coupling,
    )
    efferent_limit = _limit(
        [m.efferent for m in metrics.values()],
        config.bottleneck_percentile,
        config.bottleneck_min_coupling,
    )
    found = [
        Finding(FindingKind.BOTTLENECK, (m.module,), _coupling_evidence(m))
        for m in metrics.values()
        if m.afferent >= afferent_limit and m.efferent >= efferent_limit
    ]
    return sorted(found, key=lambda finding: finding.modules)


def _orchestrators(metrics: Mapping[str, CouplingMetrics], config: FindingsConfig) -> list[Finding]:
    """Find modules with far more dependencies than the rest of the project.

    Args:
        metrics: Coupling metrics of the modules under analysis.
        config: Percentile and minimum Ce.

    Returns:
        One finding per orchestrator, sorted by module.
    """
    if not metrics:
        return []
    limit = _limit(
        [m.efferent for m in metrics.values()],
        config.orchestrator_percentile,
        config.orchestrator_min_efferent,
    )
    found = [
        Finding(FindingKind.ORCHESTRATOR, (m.module,), _coupling_evidence(m))
        for m in metrics.values()
        if m.efferent >= limit
    ]
    return sorted(found, key=lambda finding: finding.modules)


def _orphans(metrics: Mapping[str, CouplingMetrics], config: FindingsConfig) -> list[Finding]:
    """Find modules that neither import nor are imported and are no entry point.

    Args:
        metrics: Coupling metrics of the modules under analysis.
        config: Entry points that never count as orphans.

    Returns:
        One finding per orphan, sorted by module.
    """
    found = [
        Finding(FindingKind.ORPHAN, (m.module,), {})
        for m in metrics.values()
        if m.afferent == 0 and m.efferent == 0 and not _is_entry_point(m.module, config)
    ]
    return sorted(found, key=lambda finding: finding.modules)


def _limit(values: list[int], percentile: int, minimum: int) -> int:
    """Return the larger of a percentile of the project and an absolute minimum.

    Args:
        values: Metric of every module.
        percentile: Percentile to take.
        minimum: Floor, so small projects are not flooded with findings.

    Returns:
        The value a module must reach.
    """
    return max(nearest_rank_percentile(values, percentile), minimum)


def _coupling_evidence(metrics: CouplingMetrics) -> dict[str, float]:
    """Return the Ca and Ce of a module as finding evidence.

    Args:
        metrics: Coupling metrics of the module.

    Returns:
        ``{"afferent": Ca, "efferent": Ce}``.
    """
    return {"afferent": metrics.afferent, "efferent": metrics.efferent}


def _is_entry_point(module: str, config: FindingsConfig) -> bool:
    """Tell whether a module is run from outside the code, so nothing imports it.

    Args:
        module: Dotted module name.
        config: Configured entry points (names or ``fnmatch`` patterns).

    Returns:
        True for ``__main__`` modules and for any module matching an entry point.
    """
    if module.rsplit(".", 1)[-1] == MAIN_MODULE_SUFFIX:
        return True
    return any(fnmatchcase(module, pattern) for pattern in config.entry_points)
