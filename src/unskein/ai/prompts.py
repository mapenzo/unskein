"""System prompt and prompt construction for the AI interpretation step."""

from collections import Counter

from unskein.ai.models import AIContext, ModuleCoupling, TangleSummary
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang

MAX_TANGLES_IN_PROMPT = 5
MAX_TANGLE_MEMBERS_IN_PROMPT = 20
MAX_CYCLES_IN_PROMPT = 20
MAX_MODULES_IN_PROMPT = 15
INSTABILITY_DECIMALS = 2
MAX_PROMPT_CHARS = 16_000

LANG_INSTRUCTION: dict[Lang, str] = {
    Lang.ES: "Responde en español.",
    Lang.EN: "Respond in English.",
}

SYSTEM_PROMPT = """\
You are a software architecture reviewer. You receive pre-computed dependency and
coupling metrics for a Python project. Interpret ONLY the data provided.
Do not invent modules, files or facts not present in the data. When the data is
insufficient for a conclusion, say so explicitly instead of giving generic advice.
Reply with a single JSON object matching the schema included in the user message.
"""


def build_context(result: AnalysisResult) -> AIContext:
    """Summarize an analysis into a bounded context for the LLM.

    Never sends the full graph, source code or file paths: only aggregates and
    truncated highlights, each next to its real total, to keep size and cost
    under control.

    Args:
        result: The deterministic analysis to summarize.

    Returns:
        Context with the largest tangles, the shortest cycles, the most coupled
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
        cycles=sorted(result.cycles, key=lambda cycle: (len(cycle), cycle))[:MAX_CYCLES_IN_PROMPT],
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


def build_prompt(context: AIContext, lang: Lang) -> str:
    """Build the user prompt, prefixed with the output language instruction.

    Args:
        context: Bounded analysis context.
        lang: Language the LLM must answer in.

    Returns:
        The full user prompt.
    """
    return f"{LANG_INSTRUCTION[lang]}\n\n" + _build_prompt_body(context)


def _build_prompt_body(context: AIContext) -> str:
    """Render the context and the AIReport JSON schema as prompt text.

    The schema is included inline because cheap local models often ignore
    ``response_format``.

    Args:
        context: Bounded analysis context.

    Returns:
        Prompt body without the language instruction.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
