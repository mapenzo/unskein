from dataclasses import dataclass, field

import networkx as nx

from unskein.parsers.base import ParseResult

MAX_CYCLES = 100
HIGH_COUPLING_PERCENTILE = 90


@dataclass(slots=True)
class CouplingMetrics:
    module: str
    afferent: int
    efferent: int

    @property
    def instability(self) -> float:
        total = self.afferent + self.efferent
        return self.efferent / total if total else 0.0


@dataclass
class AnalysisResult:
    graph: nx.DiGraph
    coupling_metrics: dict[str, CouplingMetrics]
    cycles: list[list[str]]
    high_coupling_modules: list[str]
    parse_warnings: list[str] = field(default_factory=list)
    cycles_truncated: bool = False


def compute_coupling(graph: nx.DiGraph) -> dict[str, CouplingMetrics]:
    raise NotImplementedError


def find_cycles(graph: nx.DiGraph, limit: int = MAX_CYCLES) -> tuple[list[list[str]], bool]:
    """nx.simple_cycles capped at `limit`; second value tells whether it was truncated."""
    raise NotImplementedError


def find_high_coupling(
    metrics: dict[str, CouplingMetrics], percentile: int = HIGH_COUPLING_PERCENTILE
) -> list[str]:
    raise NotImplementedError


def analyze(result: ParseResult) -> AnalysisResult:
    raise NotImplementedError
