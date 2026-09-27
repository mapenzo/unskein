import logging

from unskein.ai.models import AIContext, AIReport
from unskein.config import AIConfig
from unskein.i18n import Lang

logger = logging.getLogger("unskein")


def extract_json_block(raw: str) -> str | None:
    """Find a ```json fenced block or the outermost {...} in free-form model output."""
    raise NotImplementedError


class AIClient:
    def __init__(self, config: AIConfig):
        self.config = config

    def generate_report(self, context: AIContext, lang: Lang) -> AIReport | None:
        """litellm.completion; any failure -> warning + None, never raises."""
        raise NotImplementedError

    def _parse_and_validate(self, raw: str) -> AIReport | None:
        raise NotImplementedError
