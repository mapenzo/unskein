"""Find which imports to cut to undo each tangle, and simulate the result."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace

import networkx as nx

from unskein.graph.coupling import CouplingMetrics
from unskein.graph.metrics import compute_coupling, find_cycles, find_tangles
from unskein.graph.steps import STEP_COSTS, STRUCTURAL_STEPS, StepKind, choose_step
from unskein.parsers.models import ImportKind
from unskein.parsers.usage import NO_EVIDENCE, ImportEvidence

Edge = tuple[str, str]


def _peel(graph: nx.DiGraph, cost: Mapping[Edge, int]) -> list[str]:
    """Order the nodes as Eades–Lin–Smyth does: sinks last, sources first, then by cost balance.

    Args:
        graph: Graph to order; it is not modified.
        cost: Cost of each edge.

    Returns:
        The nodes in an order that leaves few, cheap edges pointing backwards.
    """
    remaining = graph.copy()
    head: list[str] = []
    tail: list[str] = []
    while remaining:
        changed = True
        while changed:
            changed = False
            for node in sorted(n for n in remaining if remaining.out_degree(n) == 0):
                tail.append(node)
                remaining.remove_node(node)
                changed = True
            for node in sorted(n for n in remaining if remaining.in_degree(n) == 0):
                head.append(node)
                remaining.remove_node(node)
                changed = True
        if remaining:
            best = max(
                sorted(remaining),
                key=lambda n: (
                    sum(cost[e] for e in remaining.out_edges(n))
                    - sum(cost[e] for e in remaining.in_edges(n))
                ),
            )
            head.append(best)
            remaining.remove_node(best)
    return head + list(reversed(tail))


def find_cuts(graph: nx.DiGraph, cost: Mapping[Edge, int]) -> list[Edge]:
    """Find a cheap set of edges whose removal leaves the graph acyclic.

    A heuristic (weighted Eades–Lin–Smyth ordering), not the minimum: backward edges of
    the ordering are cut, then each one that does not close a cycle is put back, the
    most expensive first.

    Args:
        graph: Dependency graph, usually one tangle.
        cost: Cost of cutting each edge.

    Returns:
        The edges to cut, sorted by cost, then by source and target.
    """
    position = {node: index for index, node in enumerate(_peel(graph, cost))}
    backward = [(a, b) for a, b in graph.edges if position[a] > position[b]]
    acyclic = graph.copy()
    acyclic.remove_edges_from(backward)
    cuts = []
    for edge in sorted(backward, key=lambda e: (-cost[e], e)):
        source, target = edge
        if nx.has_path(acyclic, target, source):
            cuts.append(edge)
        else:
            acyclic.add_edge(source, target)
    return sorted(cuts, key=lambda e: (cost[e], e))


@dataclass(frozen=True)
class Cut:
    """One import to cut and how.

    Attributes:
        source: Importing module.
        target: Imported module.
        step: Cheapest step that removes the dependency.
        evidence: What supports that step.
    """

    source: str
    target: str
    step: StepKind
    evidence: ImportEvidence


@dataclass(frozen=True)
class TanglePlan:
    """The cuts that undo one tangle.

    Attributes:
        members: Modules of the tangle, sorted.
        cuts: Imports to cut, cheapest first.
    """

    members: tuple[str, ...]
    cuts: tuple[Cut, ...]

    @property
    def cost(self) -> int:
        """Return the summed cost of the plan's steps."""
        return sum(STEP_COSTS[cut.step] for cut in self.cuts)


@dataclass(frozen=True)
class ModuleChange:
    """How cutting changes one module's coupling.

    Attributes:
        module: Dotted module name.
        before: Its coupling before the cuts.
        after: Its coupling after them.
    """

    module: str
    before: CouplingMetrics
    after: CouplingMetrics


@dataclass(frozen=True)
class Simulation:
    """What the graph looks like once every planned import is cut.

    Attributes:
        tangles_before: Tangles in the scope graph before cutting.
        tangles_after: Tangles left after cutting.
        cycles_before: Cycles found before cutting (capped like the report's).
        cycles_after: Cycles found after cutting.
        cycles_before_truncated: Whether the cycle search stopped at its limit before.
        cycles_after_truncated: Whether it stopped at its limit after.
        changes: Coupling of the modules at either end of a cut, the largest
            instability change first.
    """

    tangles_before: int
    tangles_after: int
    cycles_before: int
    cycles_after: int
    cycles_before_truncated: bool
    cycles_after_truncated: bool
    changes: tuple[ModuleChange, ...]


def _usable(
    scope: nx.DiGraph, edge: Edge, evidence: Mapping[Edge, ImportEvidence], *, all_edges: bool
) -> ImportEvidence:
    """Return an edge's evidence, without use contexts when moving the import cannot help.

    An import that already sits in a function or under ``TYPE_CHECKING`` cannot be
    removed by moving it there again; and when hidden coupling counts, moving any import
    there keeps the dependency. Then only the structural steps stay applicable.

    Args:
        scope: Graph whose edges carry their ``kind`` (edges without one count as module level).
        edge: The dependency.
        evidence: Evidence per dependency.
        all_edges: Whether the goal is removing the coupling itself, hidden or not.

    Returns:
        The evidence to choose the step from.
    """
    found = evidence.get(edge, NO_EVIDENCE)
    is_module_level = scope.edges[edge].get("kind", ImportKind.MODULE) is ImportKind.MODULE
    if is_module_level and not all_edges:
        return found
    return replace(found, contexts=frozenset())


@dataclass(frozen=True)
class UntanglePlan:
    """The cuts for every tangle and what the project looks like after them.

    Attributes:
        all_edges: Whether hidden coupling was included.
        tangles: One plan per tangle, largest first.
        simulation: Tangles, cycles and coupling before and after every cut.
        hidden_tangles: Hidden-coupling groups of the project (shown as a hint when
            only import-time tangles were planned).
        warnings: Problems found while parsing (skipped files or imports), which the plan
            cannot account for.
    """

    all_edges: bool
    tangles: tuple[TanglePlan, ...]
    simulation: Simulation
    hidden_tangles: int
    warnings: int


def plan_tangles(
    scope: nx.DiGraph,
    tangles: Sequence[Sequence[str]],
    evidence: Mapping[Edge, ImportEvidence],
    *,
    facades: Mapping[str, Collection[str]],
    all_edges: bool,
) -> tuple[TanglePlan, ...]:
    """Plan the cuts of every tangle, each step chosen from its evidence.

    Args:
        scope: Graph the tangles come from (import-time, or every dependency).
        tangles: Tangles, each with its members sorted.
        evidence: Evidence per dependency; missing entries count as no evidence.
        facades: The project's package facades, each with the names it defines itself.
        all_edges: Whether hidden coupling counts, so only structural steps remove an edge.

    Returns:
        One plan per tangle, in the given order.
    """
    plans = []
    for members in tangles:
        subgraph = scope.subgraph(members)
        steps = {
            edge: choose_step(
                *edge, _usable(scope, edge, evidence, all_edges=all_edges), facades=facades
            )
            for edge in subgraph.edges
        }
        cuts = find_cuts(subgraph, {edge: STEP_COSTS[step] for edge, step in steps.items()})
        plans.append(
            TanglePlan(
                tuple(members),
                tuple(Cut(*edge, steps[edge], evidence.get(edge, NO_EVIDENCE)) for edge in cuts),
            )
        )
    return tuple(plans)


def simulate(scope: nx.DiGraph, full: nx.DiGraph, cuts: Collection[Cut]) -> Simulation:
    """Measure tangles, cycles and coupling before and after cutting.

    Tangles and cycles are measured on the scope graph, without every cut. Coupling,
    like the report's, is measured on every dependency, and only structural cuts leave
    it: a lazy or type-only import still depends on its target. Removing an edge is
    optimistic: moving a symbol moves its dependency.

    Args:
        scope: Graph the cuts were planned on.
        full: Every dependency of the project.
        cuts: Imports to cut, each with its step.

    Returns:
        The simulation.
    """
    edges = [(cut.source, cut.target) for cut in cuts]
    scope_after = scope.copy()
    scope_after.remove_edges_from(edges)
    full_after = full.copy()
    full_after.remove_edges_from(
        (cut.source, cut.target) for cut in cuts if cut.step in STRUCTURAL_STEPS
    )
    cycles_before, truncated_before = find_cycles(scope)
    cycles_after, truncated_after = find_cycles(scope_after)
    coupling_before = compute_coupling(full)
    coupling_after = compute_coupling(full_after)
    touched = sorted({module for edge in edges for module in edge})
    changes = [
        ModuleChange(module, coupling_before[module], coupling_after[module]) for module in touched
    ]
    changes.sort(key=lambda c: (-abs(c.after.instability - c.before.instability), c.module))
    return Simulation(
        tangles_before=len(find_tangles(scope)),
        tangles_after=len(find_tangles(scope_after)),
        cycles_before=len(cycles_before),
        cycles_after=len(cycles_after),
        cycles_before_truncated=truncated_before,
        cycles_after_truncated=truncated_after,
        changes=tuple(changes),
    )
