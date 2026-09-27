from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

Severity = Literal["low", "medium", "high"]
ArchitectureHealth = Literal["good", "fair", "concerning"]


class Problem(BaseModel):
    severity: Severity
    title: str
    description: str
    affected_modules: list[str]
    recommendation: str
    code_snippet: str | None = None  # always None in v0.1; snippets are v0.2


class AIReport(BaseModel):
    summary: str
    architecture_health: ArchitectureHealth
    problems: list[Problem]


@dataclass
class AIContext:
    total_modules: int
    total_dependencies: int
    cycles: list[list[str]]
    top_coupled_modules: list[dict]
    parse_warnings: list[str]
    total_cycles: int = 0
    total_warnings: int = 0
    truncation_notes: list[str] = field(default_factory=list)
