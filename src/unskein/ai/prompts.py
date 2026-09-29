"""System prompt and prompt construction for the AI interpretation step."""

import json
import logging
from collections import Counter
from dataclasses import asdict

import networkx as nx

from unskein.ai.models import AIContext, AIReport, CycleSummary, ModuleCoupling, TangleSummary
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
INSTABILITY_DECIMALS = 2
MAX_PROMPT_CHARS = 16_000

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
    )


def build_messages(context: AIContext, lang: Lang) -> list[dict[str, str]]:
    """Build the system and user messages for the interpretation call.

    The JSON schema of ``AIReport`` goes inside the prompt as well as in the API
    parameter, because cheap local models often ignore ``response_format``.
    Serialization is deterministic, so the same project yields the same prompt.

    Args:
        context: Bounded analysis context.
        lang: Language the LLM must write its free text in.

    Returns:
        The ``[system, user]`` messages.
    """
    data = json.dumps(asdict(context), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    schema = json.dumps(
        AIReport.model_json_schema(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    user = (
        f"Analysis data:\n```json\n{data}\n```\n\n"
        f"Answer with a JSON object that matches this JSON schema:\n```json\n{schema}\n```"
    )
    return [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n{LANG_INSTRUCTION[lang]}"},
        {"role": "user", "content": user},
    ]


def ground_report(report: AIReport, graph: nx.DiGraph) -> AIReport:
    """Anchor an AI report to the graph, so the LLM can never invent a module.

    Removes from each problem the modules that are not in the graph and drops
    problems left with none. Also clears ``code_snippet``, which arrives in v0.2.

    Args:
        report: Validated report from the LLM.
        graph: Internal module dependency graph, the source of truth.

    Returns:
        A new report; the input is not modified.
    """
    problems = []
    for problem in report.problems:
        known = [module for module in problem.affected_modules if module in graph]
        if not known:
            logger.debug("Dropped AI problem %r: it names no known module", problem.title)
            continue
        problems.append(
            problem.model_copy(update={"affected_modules": known, "code_snippet": None})
        )
    return report.model_copy(update={"problems": problems})
