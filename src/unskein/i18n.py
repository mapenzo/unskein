"""Spanish/English message catalog and language detection."""

import locale
import os
from collections.abc import Mapping
from enum import StrEnum

from unskein.config import ENV_LANG
from unskein.errors import UnskeinError
from unskein.parsers.models import ParseWarning


class Lang(StrEnum):
    """Languages supported by the CLI, the report and the AI answers."""

    ES = "es"
    EN = "en"


_ERRORS: dict[str, dict[Lang, str]] = {
    "path_not_found": {
        Lang.ES: "La ruta '{path}' no existe o no es un directorio",
        Lang.EN: "Path '{path}' does not exist or is not a directory",
    },
    "no_files_found": {
        Lang.ES: "No se encontraron archivos .py en '{path}'",
        Lang.EN: "No .py files found in '{path}'",
    },
    "invalid_toml": {
        Lang.ES: "{file} no es un TOML válido: {detail}",
        Lang.EN: "{file} is not valid TOML: {detail}",
    },
    "unknown_key": {
        Lang.ES: "Opción desconocida '{field}' en {file}",
        Lang.EN: "Unknown setting '{field}' in {file}",
    },
    "invalid_value": {
        Lang.ES: "Valor no válido para '{field}' en {file}: {detail}",
        Lang.EN: "Invalid value for '{field}' in {file}: {detail}",
    },
}

_WARNINGS: dict[str, dict[Lang, str]] = {
    "warning.star_import": {
        Lang.ES: "Import con asterisco desde {detail}: no se pueden conocer los nombres exportados",
        Lang.EN: "Star import from {detail}: the exported names cannot be known",
    },
    "warning_title.star_import": {
        Lang.ES: "Imports con asterisco",
        Lang.EN: "Star imports",
    },
    "warning.relative_beyond_top": {
        Lang.ES: "El import relativo '{detail}' sube más allá del paquete raíz",
        Lang.EN: "Relative import '{detail}' goes beyond the top-level package",
    },
    "warning_title.relative_beyond_top": {
        Lang.ES: "Imports relativos fuera del paquete raíz",
        Lang.EN: "Relative imports beyond the top-level package",
    },
    "warning.unresolved_import": {
        Lang.ES: "Import interno no encontrado: {detail}",
        Lang.EN: "Internal import not found: {detail}",
    },
    "warning_title.unresolved_import": {
        Lang.ES: "Imports internos no resueltos",
        Lang.EN: "Unresolved internal imports",
    },
    "warning.file_too_large": {
        Lang.ES: "Archivo omitido por superar el límite de tamaño ({detail} bytes)",
        Lang.EN: "File skipped, larger than the size limit ({detail} bytes)",
    },
    "warning_title.file_too_large": {
        Lang.ES: "Archivos demasiado grandes",
        Lang.EN: "Files too large",
    },
    "warning.parse_error": {
        Lang.ES: "Archivo omitido, no se pudo analizar ({detail})",
        Lang.EN: "File skipped, it could not be parsed ({detail})",
    },
    "warning_title.parse_error": {
        Lang.ES: "Archivos no analizables",
        Lang.EN: "Unparseable files",
    },
    "warning.reexport_cycle": {
        Lang.ES: "Ciclo de re-exports, resolución detenida ({detail})",
        Lang.EN: "Re-export cycle, resolution stopped ({detail})",
    },
    "warning_title.reexport_cycle": {
        Lang.ES: "Ciclos de re-exports",
        Lang.EN: "Re-export cycles",
    },
    "warning.reexport_depth_exceeded": {
        Lang.ES: "Cadena de re-exports demasiado larga, resolución detenida ({detail})",
        Lang.EN: "Re-export chain too long, resolution stopped ({detail})",
    },
    "warning_title.reexport_depth_exceeded": {
        Lang.ES: "Cadenas de re-exports demasiado largas",
        Lang.EN: "Re-export chains too long",
    },
}

_REPORT: dict[str, dict[Lang, str]] = {
    "report.title": {Lang.ES: "Análisis de {project}", Lang.EN: "Analysis of {project}"},
    "report.summary": {Lang.ES: "Resumen", Lang.EN: "Summary"},
    "report.summary_counts": {
        Lang.ES: "{modules} módulos, {dependencies} dependencias internas, "
        "{cycles} ciclos de dependencia.",
        Lang.EN: "{modules} modules, {dependencies} internal dependencies, "
        "{cycles} dependency cycles.",
    },
    "report.summary_top_module": {
        Lang.ES: "Módulo más acoplado: `{module}` (Ca {ca}, Ce {ce}).",
        Lang.EN: "Most coupled module: `{module}` (Ca {ca}, Ce {ce}).",
    },
    "report.health": {
        Lang.ES: "Salud de la arquitectura (IA): {health}.",
        Lang.EN: "Architecture health (AI): {health}.",
    },
    "report.health.good": {Lang.ES: "buena", Lang.EN: "good"},
    "report.health.fair": {Lang.ES: "aceptable", Lang.EN: "fair"},
    "report.health.concerning": {Lang.ES: "preocupante", Lang.EN: "concerning"},
    "report.metrics": {Lang.ES: "Métricas generales", Lang.EN: "General metrics"},
    "report.metric": {Lang.ES: "Métrica", Lang.EN: "Metric"},
    "report.value": {Lang.ES: "Valor", Lang.EN: "Value"},
    "report.metric.modules": {Lang.ES: "Módulos", Lang.EN: "Modules"},
    "report.metric.dependencies": {
        Lang.ES: "Dependencias internas",
        Lang.EN: "Internal dependencies",
    },
    "report.metric.cycles": {Lang.ES: "Ciclos de dependencia", Lang.EN: "Dependency cycles"},
    "report.metric.warnings": {Lang.ES: "Advertencias", Lang.EN: "Warnings"},
    "report.metric.tangles": {Lang.ES: "Marañas", Lang.EN: "Tangles"},
    "report.summary_tangles.one": {
        Lang.ES: "1 maraña de módulos que dependen entre sí ({size} módulos).",
        Lang.EN: "1 tangle of mutually dependent modules ({size} modules).",
    },
    "report.summary_tangles.other": {
        Lang.ES: "{count} marañas de módulos que dependen entre sí; la mayor tiene {size} módulos.",
        Lang.EN: "{count} tangles of mutually dependent modules; the largest has {size} modules.",
    },
    "report.tangles_heading": {Lang.ES: "Marañas", Lang.EN: "Tangles"},
    "report.tangle_size": {Lang.ES: "{size} módulos", Lang.EN: "{size} modules"},
    "report.cycles_heading": {Lang.ES: "Ciclos", Lang.EN: "Cycles"},
    "report.cycles": {Lang.ES: "Ciclos de dependencia", Lang.EN: "Dependency cycles"},
    "report.no_cycles": {
        Lang.ES: "No se encontraron ciclos de dependencia.",
        Lang.EN: "No dependency cycles found.",
    },
    "report.cycles_truncated": {
        Lang.ES: "Mostrando los primeros {shown} ciclos: la búsqueda se detuvo en ese "
        "límite y hay más.",
        Lang.EN: "Showing the first {shown} cycles: the search stopped at that limit "
        "and there are more.",
    },
    "report.coupled": {
        Lang.ES: "Módulos con mayor acoplamiento",
        Lang.EN: "Most coupled modules",
    },
    "report.module": {Lang.ES: "Módulo", Lang.EN: "Module"},
    "report.instability": {Lang.ES: "Inestabilidad", Lang.EN: "Instability"},
    "report.no_coupled": {
        Lang.ES: "Ningún módulo destaca por su acoplamiento.",
        Lang.EN: "No module stands out for its coupling.",
    },
    "report.showing": {
        Lang.ES: "Mostrando {shown} de {total}.",
        Lang.EN: "Showing {shown} of {total}.",
    },
    "report.ai": {Lang.ES: "Problemas señalados (IA)", Lang.EN: "Problems flagged (AI)"},
    "report.ai.disabled": {
        Lang.ES: "Interpretación con IA desactivada con `--no-ai`.",
        Lang.EN: "AI interpretation disabled with `--no-ai`.",
    },
    "report.ai.not_configured": {
        Lang.ES: "No hay modelo de IA configurado. Define `UNSKEIN_AI_MODEL` o `[ai] model` "
        "en `.unskein.toml` para obtener una interpretación de estos resultados.",
        Lang.EN: "No AI model configured. Set `UNSKEIN_AI_MODEL` or `[ai] model` in "
        "`.unskein.toml` to get an interpretation of these results.",
    },
    "report.ai.failed.timeout": {
        Lang.ES: "El modelo no respondió a tiempo. El análisis determinista está completo.",
        Lang.EN: "The model did not answer in time. The deterministic analysis is complete.",
    },
    "report.ai.failed.call_error": {
        Lang.ES: "No se pudo contactar con el modelo ({error_type}). "
        "El análisis determinista está completo.",
        Lang.EN: "The model could not be reached ({error_type}). "
        "The deterministic analysis is complete.",
    },
    "report.ai.failed.invalid_response": {
        Lang.ES: "La respuesta del modelo no cumple el formato esperado. "
        "El análisis determinista está completo.",
        Lang.EN: "The model's answer does not follow the expected format. "
        "The deterministic analysis is complete.",
    },
    "report.ai.dropped": {
        Lang.ES: "Se descartaron {count} problema(s) de la IA que no nombraban ningún "
        "módulo del proyecto.",
        Lang.EN: "Discarded {count} AI problem(s) that named no module of the project.",
    },
    "report.ai.no_problems": {
        Lang.ES: "La IA no señaló problemas de la severidad seleccionada o superior.",
        Lang.EN: "The AI flagged no problems at or above the selected severity.",
    },
    "report.recommendation": {Lang.ES: "Recomendación", Lang.EN: "Recommendation"},
    "report.warnings": {Lang.ES: "Advertencias del análisis", Lang.EN: "Analysis warnings"},
    "report.more": {Lang.ES: "…y {count} más", Lang.EN: "…and {count} more"},
}

_CLI: dict[str, dict[Lang, str]] = {
    "cli.ai_waiting": {
        Lang.ES: "Consultando al modelo {model}…",
        Lang.EN: "Asking the model {model}…",
    },
    "cli.stats": {
        Lang.ES: "Duración: {seconds} s, pico de memoria: {memory} MB",
        Lang.EN: "Duration: {seconds} s, peak memory: {memory} MB",
    },
}

STRINGS: dict[str, dict[Lang, str]] = _ERRORS | _WARNINGS | _REPORT | _CLI


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


def translate_error(error: UnskeinError, lang: Lang) -> str:
    """Render an expected error as a user-facing message.

    Args:
        error: Structured error raised by the pipeline or the config loader.
        lang: Language to render the message in.

    Returns:
        The translated message.
    """
    return t(error.key, lang, **error.params)


def translate_warning(warning: ParseWarning, lang: Lang) -> str:
    """Render an analysis warning's message (without its file location).

    Args:
        warning: Structured warning from parsing or re-export resolution.
        lang: Language to render the message in.

    Returns:
        The translated message.
    """
    return t(f"warning.{warning.code}", lang, detail=warning.detail)


def detect_lang(
    cli_lang: str | None = None,
    toml_lang: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Lang:
    """Pick the output language: --lang > UNSKEIN_LANG > .unskein.toml > system locale.

    Unsupported values are skipped. With nothing configured, a Spanish system
    locale (``es*``) selects Spanish; anything else defaults to English, the
    safer choice for broad OSS adoption.

    Args:
        cli_lang: Value of the ``--lang`` flag, if given.
        toml_lang: Value of ``[general] lang`` in ``.unskein.toml``, if set.
        env: Environment variables; None means ``os.environ`` at call time.

    Returns:
        The selected language.
    """
    env = os.environ if env is None else env
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
