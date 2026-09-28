"""System prompt and prompt construction for the AI interpretation step."""

from unskein.ai.models import AIContext
from unskein.graph.metrics import AnalysisResult
from unskein.i18n import Lang

MAX_CYCLES_IN_PROMPT = 20
MAX_MODULES_IN_PROMPT = 15
MAX_WARNINGS_IN_PROMPT = 10

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

    Never sends the full graph: only aggregates and truncated highlights, to
    keep context size and cost under control.

    Args:
        result: The deterministic analysis to summarize.

    Returns:
        Context with truncated cycles, top coupled modules and warnings.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


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
