"""Structured LLM output models and the bounded context sent to the LLM."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import SkipJsonSchema

Severity = Literal["low", "medium", "high"]
ArchitectureHealth = Literal["good", "fair", "concerning"]


def _drop_class_description(schema: dict[str, Any]) -> None:
    """Remove the class docstring that Pydantic copies into a JSON schema.

    The docstrings are written for developers; the model reading the schema
    would take them as instructions.

    Args:
        schema: Generated JSON schema of one model, modified in place.
    """
    schema.pop("description", None)


class Problem(BaseModel):
    """An architecture problem flagged by the LLM.

    Attributes:
        severity: How serious the problem is.
        title: Short name of the problem.
        description: Explanation in the selected output language.
        affected_modules: Modules involved in the problem.
        recommendation: Suggested way to address it.
        code_snippet: Proposed code; always None for now and hidden from the
            JSON schema the model sees, until code suggestions are offered.
    """

    model_config = ConfigDict(json_schema_extra=_drop_class_description)

    severity: Severity
    title: str
    description: str
    affected_modules: list[str]
    recommendation: str
    code_snippet: SkipJsonSchema[str | None] = None


class AIReport(BaseModel):
    """Validated LLM interpretation of an analysis.

    Attributes:
        summary: Overall summary in the selected output language.
        architecture_health: Coarse health rating of the project.
        problems: Problems flagged by the LLM.
    """

    model_config = ConfigDict(json_schema_extra=_drop_class_description)

    summary: str
    architecture_health: ArchitectureHealth
    problems: list[Problem]


@dataclass(frozen=True, slots=True)
class ModuleCoupling:
    """Coupling of one module, as shown to the LLM.

    Attributes:
        module: Dotted module name.
        ca: Afferent coupling, modules that depend on it.
        ce: Efferent coupling, modules it depends on.
        instability: ``Ce / (Ca + Ce)``, rounded.
    """

    module: str
    ca: int
    ce: int
    instability: float


@dataclass(frozen=True, slots=True)
class TangleSummary:
    """A tangle of mutually dependent modules, as shown to the LLM.

    Attributes:
        size: Real number of modules in the tangle.
        members: Some of its modules, truncated to the prompt limit.
    """

    size: int
    members: list[str]


@dataclass(frozen=True, slots=True)
class CycleSummary:
    """A dependency cycle, as shown to the LLM.

    Attributes:
        length: Real number of modules in the cycle.
        members: Some of its modules, truncated to the prompt limit.
    """

    length: int
    members: list[str]


@dataclass(frozen=True, slots=True)
class FindingSummary:
    """A deterministic finding, as shown to the LLM.

    Attributes:
        kind: Rule that produced it, e.g. ``"bottleneck"``.
        modules: The module, or ``[importer, imported]`` for unstable dependencies and layer
            violations.
        evidence: Numbers or short strings (layer names, locations, fixes) that triggered
            the rule.
    """

    kind: str
    modules: list[str]
    evidence: dict[str, float | str]


@dataclass(frozen=True, slots=True)
class PackageEdgeSummary:
    """Dependencies from one package to another, as shown to the LLM.

    Attributes:
        source: Package that imports.
        target: Package that is imported.
        imports: Module-level dependencies from ``source`` to ``target``.
    """

    source: str
    target: str
    imports: int


@dataclass(frozen=True)
class AIContext:
    """Bounded, aggregated view of an analysis sent to the LLM instead of the full graph.

    Attributes:
        total_modules: Number of internal modules analyzed.
        total_dependencies: Number of internal dependency edges.
        tangles: Largest tangles, truncated.
        total_tangles: Tangles before truncation.
        cycles: Shortest dependency cycles, truncated and with capped members.
        total_cycles: Cycles found before truncation.
        cycles_truncated: Whether the cycle search itself stopped at its limit.
        top_coupled_modules: Most coupled modules by ``Ca + Ce``, truncated.
        warning_counts: Analysis warnings per warning code; no paths or messages.
        findings: Deterministic findings, capped per kind.
        finding_counts: Real number of findings per kind, before the cap.
        package_edges: Largest dependencies between packages, truncated.
        total_package_edges: Package dependencies before truncation.
        hidden_tangles: Largest groups coupled only through lazy or type-only imports,
            truncated.
        total_hidden_tangles: Hidden tangles before truncation.
    """

    total_modules: int
    total_dependencies: int
    tangles: list[TangleSummary]
    total_tangles: int
    cycles: list[CycleSummary]
    total_cycles: int
    cycles_truncated: bool
    top_coupled_modules: list[ModuleCoupling]
    warning_counts: dict[str, int]
    findings: list[FindingSummary] = field(default_factory=list)
    finding_counts: dict[str, int] = field(default_factory=dict)
    package_edges: list[PackageEdgeSummary] = field(default_factory=list)
    total_package_edges: int = 0
    hidden_tangles: list[TangleSummary] = field(default_factory=list)
    total_hidden_tangles: int = 0


class AIFailure(StrEnum):
    """Why an AI call produced no report.

    Attributes:
        TIMEOUT: The model did not answer in time.
        CALL_ERROR: The provider or the connection failed (auth, network, rate limit...).
        INVALID_RESPONSE: The answer was empty, truncated or did not match the schema.
    """

    TIMEOUT = "timeout"
    CALL_ERROR = "call_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class AIOutcome:
    """Result of one AI call: a report or the reason there is none.

    Attributes:
        report: The validated report, or None on failure.
        failure: Why there is no report, or None on success.
        error_type: Exception class name for ``CALL_ERROR`` (never its message).
        dropped_problems: Problems discarded on grounding for naming no known module.
    """

    report: AIReport | None = None
    failure: AIFailure | None = None
    error_type: str | None = None
    dropped_problems: int = 0

    def __post_init__(self) -> None:
        """Enforce that exactly one of ``report`` and ``failure`` is set.

        Raises:
            ValueError: If both or neither are set.
        """
        if (self.report is None) == (self.failure is None):
            raise ValueError("AIOutcome needs exactly one of report and failure")
