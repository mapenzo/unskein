"""Structured LLM output models and the bounded context sent to the LLM."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel
from pydantic.json_schema import SkipJsonSchema

Severity = Literal["low", "medium", "high"]
ArchitectureHealth = Literal["good", "fair", "concerning"]


class Problem(BaseModel):
    """An architecture problem flagged by the LLM.

    Attributes:
        severity: How serious the problem is.
        title: Short name of the problem.
        description: Explanation in the selected output language.
        affected_modules: Modules involved in the problem.
        recommendation: Suggested way to address it.
        code_snippet: Proposed code; always None in v0.1 and hidden from the
            JSON schema the model sees, snippets arrive in v0.2.
    """

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

    summary: str
    architecture_health: ArchitectureHealth
    problems: list[Problem]


@dataclass
class AIContext:
    """Bounded, aggregated view of an analysis sent to the LLM instead of the full graph.

    Attributes:
        total_modules: Number of internal modules analyzed.
        total_dependencies: Number of internal dependency edges.
        cycles: Dependency cycles, truncated to the prompt limit.
        top_coupled_modules: Metrics of the most coupled modules, truncated.
        parse_warnings: Analysis warnings, truncated.
        total_cycles: Total cycles before truncation.
        total_warnings: Total warnings before truncation.
        truncation_notes: Human-readable notes on what was truncated.
    """

    total_modules: int
    total_dependencies: int
    cycles: list[list[str]]
    top_coupled_modules: list[dict]
    parse_warnings: list[str]
    total_cycles: int = 0
    total_warnings: int = 0
    truncation_notes: list[str] = field(default_factory=list)


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
    """

    report: AIReport | None = None
    failure: AIFailure | None = None
    error_type: str | None = None

    def __post_init__(self) -> None:
        """Enforce that exactly one of ``report`` and ``failure`` is set.

        Raises:
            ValueError: If both or neither are set.
        """
        if (self.report is None) == (self.failure is None):
            raise ValueError("AIOutcome needs exactly one of report and failure")
