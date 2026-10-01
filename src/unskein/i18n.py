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
    "config_exists": {
        Lang.ES: "{path} ya existe; usa --force para sobrescribirlo",
        Lang.EN: "{path} already exists; use --force to overwrite it",
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
    "warning.parse_timeout": {
        Lang.ES: "Archivo omitido, el análisis superó el límite de tiempo ({detail} s)",
        Lang.EN: "File skipped, parsing exceeded the time limit ({detail} s)",
    },
    "warning_title.parse_timeout": {
        Lang.ES: "Archivos que superaron el límite de tiempo",
        Lang.EN: "Files that exceeded the time limit",
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
    "report.packages": {Lang.ES: "Paquetes", Lang.EN: "Packages"},
    "report.packages_intro": {
        Lang.ES: "Acoplamiento agregado por paquete. Ca y Ce cuentan paquetes distintos, "
        "no módulos; los imports dentro de un mismo paquete no cuentan.",
        Lang.EN: "Coupling aggregated by package. Ca and Ce count other packages, not "
        "modules; imports inside one package do not count.",
    },
    "report.package": {Lang.ES: "Paquete", Lang.EN: "Package"},
    "report.package_modules": {Lang.ES: "Módulos", Lang.EN: "Modules"},
    "report.packages_showing": {
        Lang.ES: "Se muestran los {shown} paquetes más acoplados de {total}.",
        Lang.EN: "Showing the {shown} most coupled of the {total} packages.",
    },
    "report.package_edges": {
        Lang.ES: "Dependencias entre paquetes",
        Lang.EN: "Dependencies between packages",
    },
    "report.package_edge.one": {Lang.ES: "{imports} import", Lang.EN: "{imports} import"},
    "report.package_edge.other": {Lang.ES: "{imports} imports", Lang.EN: "{imports} imports"},
    "report.impact": {Lang.ES: "Impacto", Lang.EN: "Impact"},
    "report.coupled_intro": {
        Lang.ES: "El {top} % de los módulos con mayor Ca + Ce. Ca: cuántos módulos lo "
        "importan. Ce: cuántos importa él. Inestabilidad: Ce / (Ca + Ce), de 0 (otros se "
        "apoyan en él) a 1 (él se apoya en otros). Impacto: cuántos módulos dependen de él, "
        "directa o indirectamente.",
        Lang.EN: "The top {top}% of modules by Ca + Ce. Ca: how many modules import it. "
        "Ce: how many it imports. Instability: Ce / (Ca + Ce), from 0 (others rely on it) "
        "to 1 (it relies on others). Impact: how many modules depend on it, directly or "
        "indirectly.",
    },
    "report.showing": {
        Lang.ES: "Se muestran los {shown} más acoplados de los {total} módulos del {top} % "
        "superior por Ca + Ce.",
        Lang.EN: "Showing the {shown} most coupled of the {total} modules in the top {top}% "
        "by Ca + Ce.",
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
    "report.findings": {Lang.ES: "Hallazgos", Lang.EN: "Findings"},
    "report.no_findings": {
        Lang.ES: "No se detectaron hallazgos.",
        Lang.EN: "No findings detected.",
    },
    "report.summary_findings.one": {
        Lang.ES: "1 hallazgo de arquitectura.",
        Lang.EN: "1 architecture finding.",
    },
    "report.summary_findings.other": {
        Lang.ES: "{count} hallazgos de arquitectura.",
        Lang.EN: "{count} architecture findings.",
    },
}

_FINDINGS: dict[str, dict[Lang, str]] = {
    "finding.impact": {Lang.ES: "impacto {impact}", Lang.EN: "impact {impact}"},
    "finding.unstable_dependency.title": {
        Lang.ES: "Dependencia inestable",
        Lang.EN: "Unstable dependency",
    },
    "finding.unstable_dependency.explanation": {
        Lang.ES: "Un módulo del que otros dependen importa uno mucho más inestable "
        "(I es la inestabilidad, de 0 a 1): los cambios del segundo llegan a todos los "
        "que se apoyan en el primero.",
        Lang.EN: "A module others rely on imports a much more unstable one (I is the "
        "instability, from 0 to 1): the second one's changes reach everything that "
        "relies on the first.",
    },
    "finding.unstable_dependency.recommendation": {
        Lang.ES: "Invertir la dependencia: que el primero dependa de una abstracción estable, "
        "o mover lo que necesita del segundo a un módulo estable.",
        Lang.EN: "Invert the dependency: make the first depend on a stable abstraction, "
        "or move what it needs from the second into a stable module.",
    },
    "finding.bottleneck.title": {Lang.ES: "Cuello de botella", Lang.EN: "Bottleneck"},
    "finding.bottleneck.explanation": {
        Lang.ES: "Módulos muy usados que a la vez dependen de muchos: un cambio en sus "
        "dependencias llega a todos sus usuarios, y un cambio en ellos, a muchos.",
        Lang.EN: "Modules many depend on that also depend on many: a change in their "
        "dependencies reaches all their users, and a change in them reaches many.",
    },
    "finding.bottleneck.recommendation": {
        Lang.ES: "Dividirlo por responsabilidades para que cada parte tenga menos motivos "
        "de cambio.",
        Lang.EN: "Split it by responsibility so each part has fewer reasons to change.",
    },
    "finding.orchestrator.title": {
        Lang.ES: "Orquestador con muchas dependencias",
        Lang.EN: "Orchestrator with many dependencies",
    },
    "finding.orchestrator.explanation": {
        Lang.ES: "Módulos que importan muchos más módulos que el resto del proyecto. Es normal "
        "en puntos de entrada y casos de uso; preocupa si sigue creciendo.",
        Lang.EN: "Modules that import far more modules than the rest of the project. This is "
        "normal for entry points and use cases; it is a concern if it keeps growing.",
    },
    "finding.orchestrator.recommendation": {
        Lang.ES: "Si sigue creciendo, agrupar pasos relacionados en componentes propios.",
        Lang.EN: "If it keeps growing, group related steps into components of their own.",
    },
    "finding.orphan.title": {Lang.ES: "Módulo huérfano", Lang.EN: "Orphan module"},
    "finding.orphan.explanation": {
        Lang.ES: "Módulo que no importa ningún módulo del proyecto y nadie lo importa.",
        Lang.EN: "Module that imports no project module and that nobody imports.",
    },
    "finding.orphan.recommendation": {
        Lang.ES: "Comprobar si es código muerto o un punto de entrada invocado fuera del "
        "código (script, tarea programada); borrarlo o documentarlo, y si es un punto de "
        "entrada, declararlo en `entry_points`.",
        Lang.EN: "Check whether it is dead code or an entry point run from outside the code "
        "(script, scheduled task); delete or document it, and if it is an entry point, "
        "declare it in `entry_points`.",
    },
    "finding.layer_violation.title": {
        Lang.ES: "Violación de capas",
        Lang.EN: "Layer violation",
    },
    "finding.layer_violation.explanation": {
        Lang.ES: "Un módulo de una capa inferior importa uno de una capa superior, según el "
        "orden declarado en `[layers]`: la capa baja ya no puede cambiar ni reutilizarse "
        "sin la alta.",
        Lang.EN: "A module of a lower layer imports one of a higher layer, according to the "
        "order declared in `[layers]`: the lower layer can no longer change or be reused "
        "without the higher one.",
    },
    "finding.layer_violation.recommendation": {
        Lang.ES: "Invertir la dependencia: mover lo que necesita la capa baja a una capa "
        "inferior o pasarlo por una abstracción, para que las capas solo dependan hacia abajo.",
        Lang.EN: "Invert the dependency: move what the lower layer needs into a lower layer "
        "or pass it through an abstraction, so layers only depend downwards.",
    },
    "finding.layers": {
        Lang.ES: "capa {layer_from} → {layer_to}",
        Lang.EN: "layer {layer_from} → {layer_to}",
    },
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
    "cli.config_written": {
        Lang.ES: (
            "Configuración creada en {path}. "
            "Todo está comentado: descomenta lo que quieras cambiar."
        ),
        Lang.EN: (
            "Config written to {path}. "
            "Everything is commented out: uncomment what you want to change."
        ),
    },
}

STRINGS: dict[str, dict[Lang, str]] = _ERRORS | _WARNINGS | _REPORT | _FINDINGS | _CLI


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
