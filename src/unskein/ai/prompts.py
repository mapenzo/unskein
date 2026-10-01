"""System prompt and prompt construction for the AI interpretation step."""

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace

import networkx as nx

from unskein.ai.models import (
    AIContext,
    AIReport,
    CycleSummary,
    FindingSummary,
    ModuleCoupling,
    PackageEdgeSummary,
    TangleSummary,
)
from unskein.graph.findings import FindingKind
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang

logger = logging.getLogger("unskein")

# Instability from which a module others depend on counts as volatile in the rubric.
UNSTABLE_THRESHOLD = 0.7

MAX_TANGLES_IN_PROMPT = 5
MAX_TANGLE_MEMBERS_IN_PROMPT = 20
MAX_CYCLES_IN_PROMPT = 10
MAX_CYCLE_MEMBERS_IN_PROMPT = 8
MAX_MODULES_IN_PROMPT = 15
MAX_FINDINGS_PER_KIND_IN_PROMPT = 5
MAX_PACKAGE_EDGES_IN_PROMPT = 10
INSTABILITY_DECIMALS = 2
MAX_PROMPT_CHARS = 16_000

NAME_DECORATION = "`'\". \t\n"
PYTHON_SUFFIX = ".py"
PACKAGE_INIT = "__init__"
SOURCE_ROOT = "src"

LANG_INSTRUCTION: dict[Lang, str] = {
    Lang.ES: "Write the summary, the problem descriptions and the recommendations in Spanish.",
    Lang.EN: "Write the summary, the problem descriptions and the recommendations in English.",
}

SYSTEM_PROMPT = f"""\
You are a software architecture reviewer. You receive pre-computed dependency and
coupling metrics for a Python project. Interpret ONLY the data provided.
Do not invent modules, files or facts not present in the data. When the data is
insufficient for a conclusion, say so explicitly instead of giving generic advice.

Data guide: ca = modules that depend on a module, ce = modules it depends on,
instability = ce / (ca + ce). A tangle is a group of modules that all depend on each
other, directly or not; size and length are real sizes, members may be truncated. Lists are
truncated: compare them with their totals.
impact = modules that depend on a module directly or not (only given for bottleneck
findings); package_edges = imports from one package to another, largest first, with their
real total.

Findings are architecture problems that fixed rules already computed from the graph, each with
the numbers that triggered it and its real total per kind. Treat them as facts: interpret them,
prioritize them and explain their impact, but do not recompute or contradict them, and do not
just list them again.
A layer_violation finding names, in layer_from and layer_to, two layers the user declared;
the importing module sits in the lower layer.

Severity rubric:
- high: a tangle or a dependency cycle.
- medium: a module with top ca + ce that is volatile while others rely on it
  (instability >= {UNSTABLE_THRESHOLD} and ca > 0), or whose ce is far above the rest.
- low: anything else worth mentioning.
Never flag a module only for low instability: a stable module many others depend on is
healthy.

Rules:
- Copy module names exactly as given.
- JSON keys and the values of "severity" and "architecture_health" stay in English.
- Reply with a single JSON object matching the schema in the user message, nothing else.
"""


def build_context(result: AnalysisResult) -> AIContext:
    """Summarize an analysis into a bounded context for the LLM.

    Never sends the full graph, source code or file paths: only aggregates and
    truncated highlights, each next to its real total, to keep size and cost
    under control.

    Args:
        result: The deterministic analysis to summarize.

    Returns:
        Context with the largest tangles, the shortest cycles (members capped), the most coupled
        modules and per-code warning counts.
    """
    ranked = sorted(
        result.coupling_metrics.values(),
        key=lambda metrics: (-(metrics.afferent + metrics.efferent), metrics.module),
    )
    warning_counts = Counter(warning.code.value for warning in result.parse_warnings)
    findings = result.findings if result.findings_enabled else []
    finding_counts = Counter(finding.kind.value for finding in findings)
    summaries: list[FindingSummary] = []
    shown: Counter[str] = Counter()
    for finding in findings:
        if shown[finding.kind.value] < MAX_FINDINGS_PER_KIND_IN_PROMPT:
            shown[finding.kind.value] += 1
            evidence = dict(finding.evidence)
            if finding.kind is FindingKind.BOTTLENECK and finding.modules[0] in result.impact:
                evidence["impact"] = result.impact[finding.modules[0]]
            summaries.append(FindingSummary(finding.kind.value, list(finding.modules), evidence))
    return AIContext(
        total_modules=result.graph.number_of_nodes(),
        total_dependencies=result.graph.number_of_edges(),
        tangles=[
            TangleSummary(size=len(members), members=members[:MAX_TANGLE_MEMBERS_IN_PROMPT])
            for members in result.tangles[:MAX_TANGLES_IN_PROMPT]
        ],
        total_tangles=len(result.tangles),
        cycles=[
            CycleSummary(length=len(cycle), members=cycle[:MAX_CYCLE_MEMBERS_IN_PROMPT])
            for cycle in sorted(result.cycles, key=lambda cycle: (len(cycle), cycle))[
                :MAX_CYCLES_IN_PROMPT
            ]
        ],
        total_cycles=len(result.cycles),
        cycles_truncated=result.cycles_truncated,
        top_coupled_modules=[
            ModuleCoupling(
                module=metrics.module,
                ca=metrics.afferent,
                ce=metrics.efferent,
                instability=round(metrics.instability, INSTABILITY_DECIMALS),
            )
            for metrics in ranked[:MAX_MODULES_IN_PROMPT]
        ],
        warning_counts=dict(sorted(warning_counts.items())),
        findings=summaries,
        finding_counts=dict(sorted(finding_counts.items())),
        package_edges=[
            PackageEdgeSummary(edge.source, edge.target, edge.imports)
            for edge in result.package_edges[:MAX_PACKAGE_EDGES_IN_PROMPT]
        ],
        total_package_edges=len(result.package_edges),
    )


def shrink_context(context: AIContext) -> AIContext:
    """Halve every list of a context, and the members of each tangle and cycle.

    Keeps at least one item of each non-empty list, the order (most relevant
    first) and every real total, so the LLM still sees what was left out.

    Args:
        context: The context to shrink.

    Returns:
        A smaller context, equal to the input when nothing can shrink further.
    """
    return replace(
        context,
        tangles=[
            replace(tangle, members=_halved(tangle.members)) for tangle in _halved(context.tangles)
        ],
        cycles=[
            replace(cycle, members=_halved(cycle.members)) for cycle in _halved(context.cycles)
        ],
        top_coupled_modules=_halved(context.top_coupled_modules),
        findings=_halved(context.findings),
        package_edges=_halved(context.package_edges),
    )


def _halved[T](items: list[T]) -> list[T]:
    """Return the first half of a list, never fewer than one item.

    Args:
        items: The list to cut.

    Returns:
        The first ``len // 2`` items, or the list itself when it has one or none.
    """
    return items[: max(1, len(items) // 2)]


def build_messages(context: AIContext, lang: Lang) -> list[dict[str, str]]:
    """Build the system and user messages for the interpretation call.

    The JSON schema of ``AIReport`` goes inside the prompt as well as in the API
    parameter, because cheap local models often ignore ``response_format``.
    Serialization is deterministic, so the same project yields the same prompt.
    A context too large for ``MAX_PROMPT_CHARS`` is shrunk silently until it
    fits, or until it cannot shrink further and is sent at its smallest.

    Args:
        context: Bounded analysis context.
        lang: Language the LLM must write its free text in.

    Returns:
        The ``[system, user]`` messages.
    """
    user = _user_message(context)
    while len(user) > MAX_PROMPT_CHARS:
        shrunk = shrink_context(context)
        if shrunk == context:
            break
        context = shrunk
        user = _user_message(context)
        logger.debug("Shrank the AI context to %d characters", len(user))
    return [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n{LANG_INSTRUCTION[lang]}"},
        {"role": "user", "content": user},
    ]


def _user_message(context: AIContext) -> str:
    """Serialize the analysis data and the report schema into the user message.

    Args:
        context: Bounded analysis context.

    Returns:
        The user message, with one fenced JSON block for each.
    """
    data = json.dumps(asdict(context), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    schema = json.dumps(
        AIReport.model_json_schema(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return (
        f"Analysis data:\n```json\n{data}\n```\n\n"
        f"Answer with a JSON object that matches this JSON schema:\n```json\n{schema}\n```"
    )


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """An AI report anchored to the graph, and how much of it was discarded.

    Attributes:
        report: The report keeping only modules that exist in the graph.
        dropped_problems: Problems removed because they named no known module.
    """

    report: AIReport
    dropped_problems: int


def normalize_module_name(written: str, graph: nx.DiGraph) -> str | None:
    """Match a module name as the LLM wrote it to a module of the graph.

    Tolerates spaces, quoting and dots around the name (```app.core`.``,
    ``./app/core.py``), file paths (``app/core.py``, ``app/__init__.py``) and a
    ``.py`` suffix on a dotted name. A leading ``src`` segment is dropped only
    when the name does not match with it, because it is usually the source root;
    no other segment is guessed away.

    Args:
        written: The module name as written by the LLM.
        graph: Internal module dependency graph, the source of truth.

    Returns:
        The module as named in the graph, or None when it matches none.
    """
    name = written.strip(NAME_DECORATION)
    if name in graph:
        return name
    parts = [part for part in re.split(r"[/\\]", name) if part]
    if parts and parts[-1].endswith(PYTHON_SUFFIX):
        parts[-1] = parts[-1].removesuffix(PYTHON_SUFFIX)
    if parts and parts[-1] == PACKAGE_INIT:
        parts.pop()
    candidates = [".".join(parts)]
    if len(parts) > 1 and parts[0] == SOURCE_ROOT:
        candidates.append(".".join(parts[1:]))
    return next((candidate for candidate in candidates if candidate in graph), None)


def ground_report(report: AIReport, graph: nx.DiGraph) -> GroundingResult:
    """Anchor an AI report to the graph, so the LLM can never invent a module.

    Matches each module name to the graph (see ``normalize_module_name``),
    removes the ones that match none and drops problems left without any.
    Also clears ``code_snippet``, which arrives in v0.2.

    Args:
        report: Validated report from the LLM.
        graph: Internal module dependency graph, the source of truth.

    Returns:
        The grounded report and the number of problems dropped; the input is
        not modified.
    """
    problems = []
    for problem in report.problems:
        known: list[str] = []
        for written in problem.affected_modules:
            module = normalize_module_name(written, graph)
            if module is not None and module not in known:
                known.append(module)
        if not known:
            logger.debug("Dropped AI problem %r: it names no known module", problem.title)
            continue
        problems.append(
            problem.model_copy(update={"affected_modules": known, "code_snippet": None})
        )
    return GroundingResult(
        report=report.model_copy(update={"problems": problems}),
        dropped_problems=len(report.problems) - len(problems),
    )
