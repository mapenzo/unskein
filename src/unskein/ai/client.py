"""Provider-agnostic LLM client built on LiteLLM."""

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from pydantic import ValidationError

from unskein.ai.models import AIFailure, AIOutcome, AIReport
from unskein.ai.proxy import is_proxy_model, proxy_supports_reasoning
from unskein.config import AIConfig

logger = logging.getLogger("unskein")

JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
REASONING_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

DIRECT_CALL_TIMEOUT_SECONDS = 60
DEFAULT_TEMPERATURE = 0.2
REASONING_TEMPERATURE = 1.0
ENV_LOCAL_COST_MAP = "LITELLM_LOCAL_MODEL_COST_MAP"
REDACTED = "***"
# Variables that hold provider credentials LiteLLM may read when unskein passes no key:
# OPENAI_API_KEY, ANTHROPIC_API_KEY... and AWS's access key, secret and session token.
SECRET_VARIABLE = re.compile(r".+_(API_KEY|SECRET_ACCESS_KEY|ACCESS_KEY_ID|SESSION_TOKEN)")
# Shorter values are placeholders, and replacing them would mangle ordinary words.
MIN_SECRET_LENGTH = 8


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


def build_profile(config: AIConfig) -> ModelProfile:
    """Decide how to call a model from what LiteLLM, or its proxy, knows about it.

    Args:
        config: Model, API key and API base; the last two are only used to ask
            a LiteLLM Proxy about its alias.

    Returns:
        The temperature, response format and timeout to use with that model.
    """
    supports_schema = load_litellm().supports_response_schema(config.model)
    return ModelProfile(
        temperature=REASONING_TEMPERATURE if _is_reasoning(config) else DEFAULT_TEMPERATURE,
        response_format=AIReport if supports_schema else {"type": "json_object"},
        timeout_seconds=None if is_proxy_model(config.model) else DIRECT_CALL_TIMEOUT_SECONDS,
    )


def _is_reasoning(config: AIConfig) -> bool:
    """Tell whether a model only accepts the reasoning temperature.

    A proxy alias is an arbitrary name, so the proxy is asked first; LiteLLM's
    own model map answers otherwise.

    Args:
        config: Model, API key and API base.

    Returns:
        True for reasoning models.
    """
    if is_proxy_model(config.model):
        declared = proxy_supports_reasoning(config)
        if declared is not None:
            return declared
    return bool(load_litellm().supports_reasoning(config.model))


def find_json_candidates(raw: str) -> list[str]:
    """List every JSON object that could be the answer in free-form model output.

    Fenced json blocks come first, in order of appearance, followed by the
    outermost ``{...}`` span when it differs from all of them. Small models often
    echo the requested schema in a fence before answering in another one.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The candidate JSON texts, possibly empty.
    """
    candidates = [match.group(1) for match in JSON_FENCE.finditer(raw)]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end >= start:
        outermost = raw[start : end + 1]
        if outermost not in candidates:
            candidates.append(outermost)
    return candidates


def extract_json_block(raw: str) -> str | None:
    """Extract the first JSON object candidate from free-form model output.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The first candidate (see ``find_json_candidates``), or None if none.
    """
    candidates = find_json_candidates(raw)
    return candidates[0] if candidates else None


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

    Tries the whole text, then every embedded candidate, and keeps the first
    that validates.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The validated report, or None if the output does not match the schema.
    """
    cleaned = strip_reasoning_blocks(raw)
    for candidate in (cleaned, *find_json_candidates(cleaned)):
        try:
            return AIReport.model_validate_json(candidate)
        except ValidationError:
            continue
    logger.debug("Model output does not match the AIReport schema")
    return None


class AIClient:
    """Generate AI reports through LiteLLM.

    The model profile is resolved here, once: switching model means building a
    new client, which resolves it again.

    Args:
        config: Model, API key and API base to use.
    """

    def __init__(self, config: AIConfig):
        self.config = config
        self.profile = build_profile(config)

    def generate_report(self, messages: list[dict[str, str]]) -> AIOutcome:
        """Ask the model to interpret the analysis.

        Never raises for expected failures: a timeout, a provider error or an
        unusable answer become an outcome with a failure, so the report is still
        produced without the AI section. Anything else is a bug and propagates.

        Args:
            messages: System and user messages built from the analysis context.

        Returns:
            The validated report, or the reason there is none.
        """
        litellm = load_litellm()
        call_errors = tuple(litellm.LITELLM_EXCEPTION_TYPES)
        try:
            response = litellm.completion(**self._request(messages))
        except litellm.Timeout:
            logger.warning("AI call failed: %s", AIFailure.TIMEOUT)
            return AIOutcome(failure=AIFailure.TIMEOUT)
        except call_errors as error:
            error_type = type(error).__name__
            logger.warning("AI call failed: %s (%s)", AIFailure.CALL_ERROR, error_type)
            logger.debug("Provider message: %s", self._redact(str(error)))
            return AIOutcome(failure=AIFailure.CALL_ERROR, error_type=error_type)
        return self._interpret(response)

    def _request(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Build the keyword arguments of the ``litellm.completion`` call.

        Args:
            messages: System and user messages.

        Returns:
            The request, with a timeout only when the profile has one.
        """
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "api_key": self.config.api_key,
            "api_base": self.config.api_base,
            "temperature": self.profile.temperature,
            "response_format": self.profile.response_format,
            "drop_params": True,
        }
        if self.profile.timeout_seconds is not None:
            request["timeout"] = self.profile.timeout_seconds
        return request

    def _interpret(self, response: Any) -> AIOutcome:
        """Turn a completion response into an outcome.

        Args:
            response: What ``litellm.completion`` returned.

        Returns:
            The report, or ``INVALID_RESPONSE`` if the answer is missing,
            truncated or does not match the schema.
        """
        _log_usage(response)
        if not response.choices:
            return AIOutcome(failure=AIFailure.INVALID_RESPONSE)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.debug("Model output was truncated (finish_reason=length)")
            return AIOutcome(failure=AIFailure.INVALID_RESPONSE)
        report = parse_report(choice.message.content) if choice.message.content else None
        if report is None:
            return AIOutcome(failure=AIFailure.INVALID_RESPONSE)
        return AIOutcome(report=report)

    def _redact(self, text: str) -> str:
        """Hide every key the call may have used in a provider message before it is logged.

        Args:
            text: Message that may repeat a key.

        Returns:
            The text with every occurrence of each key replaced.
        """
        # Only exact key strings are replaced: a provider that echoes a masked or
        # transformed key (truncated, base64, URL-encoded) is not covered.
        for secret in secrets_to_redact(self.config.api_key, os.environ):
            text = text.replace(secret, REDACTED)
        return text


def secrets_to_redact(api_key: str | None, env: Mapping[str, str]) -> list[str]:
    """List the keys a LiteLLM call may have used, longest first.

    Without an unskein key, LiteLLM reads the provider's own variable, so those
    values must be hidden too.

    Args:
        api_key: Key given to unskein, if any.
        env: Environment variables.

    Returns:
        The unskein key and every credential-like variable value long enough to be
        a real secret, longest first so no key is left half replaced.
    """
    found = {
        value
        for name, value in env.items()
        if SECRET_VARIABLE.fullmatch(name) and len(value) >= MIN_SECRET_LENGTH
    }
    if api_key:
        found.add(api_key)
    return sorted(found, key=lambda secret: (-len(secret), secret))


def _log_usage(response: Any) -> None:
    """Log token usage and cost at DEBUG level; purely informational.

    Args:
        response: What ``litellm.completion`` returned.
    """
    litellm = load_litellm()
    try:
        cost: float | None = litellm.completion_cost(completion_response=response)
    except Exception as error:  # pylint: disable=broad-exception-caught  # cost is informational
        logger.debug("AI cost unknown (%s)", type(error).__name__)
        cost = None
    total_tokens = getattr(getattr(response, "usage", None), "total_tokens", "unknown")
    logger.debug("AI call used %s tokens, cost %s", total_tokens, cost)
