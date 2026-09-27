import locale
import os
from enum import StrEnum

from unskein.config import ENV_LANG


class Lang(StrEnum):
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
    return STRINGS[key][lang].format(**kwargs)


def detect_lang(cli_lang: str | None = None, toml_lang: str | None = None) -> Lang:
    """UNSKEIN_LANG -> .unskein.toml -> --lang -> system locale (es* else English)."""
    for candidate in (os.environ.get(ENV_LANG), toml_lang, cli_lang):
        if candidate:
            try:
                return Lang(candidate.lower()[:2])
            except ValueError:
                continue
    system_lang, _ = locale.getlocale()
    if system_lang and system_lang.lower().startswith("es"):
        return Lang.ES
    return Lang.EN
