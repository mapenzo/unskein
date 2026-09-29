"""Provider-agnostic LLM client built on LiteLLM."""

import logging
import os
import re
from dataclasses import dataclass
from types import ModuleType

from pydantic import ValidationError

from unskein.ai.models import AIContext, AIReport
from unskein.config import AIConfig
from unskein.i18n import Lang

logger = logging.getLogger("unskein")

JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
REASONING_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

DIRECT_CALL_TIMEOUT_SECONDS = 60
PROXY_MODEL_PREFIX = "litellm_proxy/"
DEFAULT_TEMPERATURE = 0.2
REASONING_TEMPERATURE = 1.0
ENV_LOCAL_COST_MAP = "LITELLM_LOCAL_MODEL_COST_MAP"


@dataclass(frozen=True)
class ModelProfile:
    """How to call one model, resolved once when the client is built.

    Attributes:
        temperature: Sampling temperature; reasoning models only accept 1.0.
        response_format: The ``AIReport`` class when the model supports JSON
            schemas, otherwise plain JSON mode.
        timeout_seconds: Per-call limit for direct calls; None when a LiteLLM
            Proxy is in charge of timeouts.
    """

    temperature: float
    response_format: type[AIReport] | dict[str, str]
    timeout_seconds: int | None


def load_litellm() -> ModuleType:
    """Import LiteLLM lazily, with remote lookups and telemetry turned off.

    The import costs about 1.5 s that ``--no-ai`` must not pay, and by default
    LiteLLM downloads its price map from a remote URL on import, a network
    request nobody asked for. Safe to call repeatedly.

    Returns:
        The ``litellm`` module.
    """
    os.environ.setdefault(ENV_LOCAL_COST_MAP, "True")
    import litellm  # pylint: disable=import-outside-toplevel  # lazy: see docstring

    litellm.telemetry = False
    litellm.suppress_debug_info = True
    return litellm


def build_profile(model: str) -> ModelProfile:
    """Decide how to call a model from what LiteLLM knows about it.

    Args:
        model: LiteLLM model string, e.g. ``ollama/qwen2.5-coder:7b``.

    Returns:
        The temperature, response format and timeout to use with that model.
    """
    litellm = load_litellm()
    is_reasoning = litellm.supports_reasoning(model)
    supports_schema = litellm.supports_response_schema(model)
    return ModelProfile(
        temperature=REASONING_TEMPERATURE if is_reasoning else DEFAULT_TEMPERATURE,
        response_format=AIReport if supports_schema else {"type": "json_object"},
        timeout_seconds=None
        if model.startswith(PROXY_MODEL_PREFIX)
        else DIRECT_CALL_TIMEOUT_SECONDS,
    )


def extract_json_block(raw: str) -> str | None:
    """Extract a JSON object from free-form model output.

    Looks for a fenced json code block first, then the outermost ``{...}``.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The JSON text, or None if none was found.
    """
    fenced = JSON_FENCE.search(raw)
    if fenced:
        return fenced.group(1)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        return None
    return raw[start : end + 1]


def strip_reasoning_blocks(raw: str) -> str:
    """Remove ``<think>...</think>`` sections some models leave in their answer.

    Their braces would otherwise confuse the JSON extraction.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The text without reasoning sections.
    """
    return REASONING_BLOCK.sub("", raw)


def parse_report(raw: str) -> AIReport | None:
    """Validate model output against ``AIReport``, falling back to embedded JSON.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The validated report, or None if the output does not match the schema.
    """
    cleaned = strip_reasoning_blocks(raw)
    for candidate in (cleaned, extract_json_block(cleaned)):
        if candidate is None:
            continue
        try:
            return AIReport.model_validate_json(candidate)
        except ValidationError:
            continue
    logger.debug("Model output does not match the AIReport schema")
    return None


class AIClient:
    """Generate AI reports through LiteLLM.

    Args:
        config: Model, API key and API base to use.
    """

    def __init__(self, config: AIConfig):
        self.config = config

    def generate_report(self, context: AIContext, lang: Lang) -> AIReport | None:
        """Ask the model to interpret the analysis context.

        Never raises: any call or validation failure is logged as a warning and
        yields None, so the report is still produced without the AI section.

        Args:
            context: Bounded analysis context.
            lang: Language the model must answer in.

        Returns:
            The validated report, or None on any failure.

        Raises:
            NotImplementedError: Not implemented yet.
        """
        raise NotImplementedError

    def _parse_and_validate(self, raw: str) -> AIReport | None:
        """Validate model output against AIReport, falling back to embedded JSON.

        Args:
            raw: Raw text returned by the model.

        Returns:
            The validated report, or None if the output does not match the schema.

        Raises:
            NotImplementedError: Not implemented yet.
        """
        raise NotImplementedError
