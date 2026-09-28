"""Spanish/English message catalog and language detection."""

import locale
import os
from collections.abc import Mapping
from enum import StrEnum

from unskein.config import ENV_LANG


class Lang(StrEnum):
    """Languages supported by the CLI, the report and the AI answers."""

    ES = "es"
    EN = "en"


STRINGS: dict[str, dict[Lang, str]] = {
    "no_files_found": {
        Lang.ES: "No se encontraron archivos .py en '{path}'",
        Lang.EN: "No .py files found in '{path}'",
    },
    "path_not_found": {
        Lang.ES: "La ruta '{path}' no existe o no es un directorio",
        Lang.EN: "Path '{path}' does not exist or is not a directory",
    },
    "ai_config_missing": {
        Lang.ES: "No se encontró configuración de IA, generando reporte sin sección de IA",
        Lang.EN: "No AI configuration found, generating report without AI section",
    },
}


def t(key: str, lang: Lang, **kwargs: object) -> str:
    """Translate a message key and fill in its placeholders.

    Args:
        key: Message identifier in ``STRINGS``.
        lang: Language to render the message in.
        **kwargs: Values for the message's ``{placeholder}`` fields.

    Returns:
        The formatted message.

    Raises:
        KeyError: If the key has no entry in ``STRINGS``.
    """
    return STRINGS[key][lang].format(**kwargs)


def detect_lang(
    cli_lang: str | None = None,
    toml_lang: str | None = None,
    env: Mapping[str, str] = os.environ,
) -> Lang:
    """Pick the output language: --lang > UNSKEIN_LANG > .unskein.toml > system locale.

    Unsupported values are skipped. With nothing configured, a Spanish system
    locale (``es*``) selects Spanish; anything else defaults to English, the
    safer choice for broad OSS adoption.

    Args:
        cli_lang: Value of the ``--lang`` flag, if given.
        toml_lang: Value of ``[general] lang`` in ``.unskein.toml``, if set.
        env: Environment variables (``os.environ`` in production).

    Returns:
        The selected language.
    """
    for candidate in (cli_lang, env.get(ENV_LANG), toml_lang):
        if candidate:
            try:
                return Lang(candidate.lower()[:2])
            except ValueError:
                continue
    system_lang, _ = locale.getlocale()
    if system_lang and system_lang.lower().startswith("es"):
        return Lang.ES
    return Lang.EN
