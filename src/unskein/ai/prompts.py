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
    """Bounded serialization: never send the full graph to the LLM."""
    raise NotImplementedError


def build_prompt(context: AIContext, lang: Lang) -> str:
    return f"{LANG_INSTRUCTION[lang]}\n\n" + _build_prompt_body(context)


def _build_prompt_body(context: AIContext) -> str:
    """Includes AIReport JSON schema inline for weak models ignoring response_format."""
    raise NotImplementedError
