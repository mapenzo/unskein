"""Provider-agnostic LLM client built on LiteLLM."""

import logging

from unskein.ai.models import AIContext, AIReport
from unskein.config import AIConfig
from unskein.i18n import Lang

logger = logging.getLogger("unskein")


def extract_json_block(raw: str) -> str | None:
    """Extract a JSON object from free-form model output.

    Looks for a fenced json code block first, then the outermost ``{...}``.

    Args:
        raw: Raw text returned by the model.

    Returns:
        The JSON text, or None if none was found.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


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
