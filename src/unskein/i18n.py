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
    "config_not_found": {
        Lang.ES: "No existe el archivo de configuración '{path}'",
        Lang.EN: "Config file '{path}' does not exist",
    },
}

_WARNINGS: dict[str, dict[Lang, str]] = {
    "warning.invalid_requirement": {
        Lang.ES: "Dependencia declarada sin nombre válido, se ignora: {detail}",
        Lang.EN: "Declared dependency without a valid name, ignored: {detail}",
    },
    "warning_title.invalid_requirement": {
        Lang.ES: "Dependencias declaradas no válidas",
        Lang.EN: "Invalid declared dependencies",
    },
    "warning.star_import": {
        Lang.ES: "Import con asterisco desde {detail}: no se siguen los nombres que trae",
        Lang.EN: "Star import from {detail}: the names it brings in are not followed",
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
    "warning.invalid_module_name": {
        Lang.ES: "El manifiesto declara un módulo compilado con nombre inválido, se ignora: "
        "{detail}",
        Lang.EN: "The manifest declares a compiled module with an invalid name, ignored: {detail}",
    },
    "warning_title.invalid_module_name": {
        Lang.ES: "Módulos compilados con nombre inválido",
        Lang.EN: "Compiled modules with an invalid name",
    },
    "warning.manifest_unreadable": {
        Lang.ES: "Manifiesto ilegible, se detectan sus paquetes por convención: {detail}",
        Lang.EN: "Unreadable manifest, its packages are detected by convention: {detail}",
    },
    "warning_title.manifest_unreadable": {
        Lang.ES: "Manifiestos ilegibles",
        Lang.EN: "Unreadable manifests",
    },
    "warning.declared_package_missing": {
        Lang.ES: "El manifiesto declara el paquete '{detail}', que no existe",
        Lang.EN: "The manifest declares package '{detail}', which does not exist",
    },
    "warning_title.declared_package_missing": {
        Lang.ES: "Paquetes declarados inexistentes",
        Lang.EN: "Declared packages that do not exist",
    },
    "warning.module_name_collision": {
        Lang.ES: "Nombre de módulo repetido, este archivo se nombra por su ruta: {detail}",
        Lang.EN: "Repeated module name, this file is named by its path: {detail}",
    },
    "warning.duplicate_distribution_name": {
        Lang.ES: "Otro manifiesto (menos profundo, o el primero por ruta) ya declara la "
        "distribución {detail}; este pierde el nombre",
        Lang.EN: "Another manifest (shallower, or first by path) already declares the "
        "distribution {detail}; this one loses the name",
    },
    "warning_title.duplicate_distribution_name": {
        Lang.ES: "Nombres de distribución repetidos",
        Lang.EN: "Repeated distribution names",
    },
    "warning_title.module_name_collision": {
        Lang.ES: "Nombres de módulo repetidos",
        Lang.EN: "Repeated module names",
    },
}

_REPORT: dict[str, dict[Lang, str]] = {
    "report.title": {Lang.ES: "Análisis de {project}", Lang.EN: "Analysis of {project}"},
    "report.summary": {Lang.ES: "Resumen", Lang.EN: "Summary"},
    "report.summary_counts": {
        Lang.ES: "{modules} módulos{scripts}, {dependencies} dependencias internas, "
        "{cycles} ciclos de dependencia.",
        Lang.EN: "{modules} modules{scripts}, {dependencies} internal dependencies, "
        "{cycles} dependency cycles.",
    },
    "report.summary_scripts.one": {Lang.ES: " + {count} script", Lang.EN: " + {count} script"},
    "report.summary_scripts.other": {Lang.ES: " + {count} scripts", Lang.EN: " + {count} scripts"},
    "report.metric.scripts": {Lang.ES: "Scripts", Lang.EN: "Scripts"},
    "report.summary_namespaces.one": {
        Lang.ES: " + {count} espacio de nombres",
        Lang.EN: " + {count} namespace package",
    },
    "report.summary_namespaces.other": {
        Lang.ES: " + {count} espacios de nombres",
        Lang.EN: " + {count} namespace packages",
    },
    "report.metric.namespaces": {
        Lang.ES: "Espacios de nombres",
        Lang.EN: "Namespace packages",
    },
    "report.namespace_marker": {
        Lang.ES: "*(espacio de nombres)*",
        Lang.EN: "*(namespace package)*",
    },
    "report.summary_compiled.one": {
        Lang.ES: " + {count} extensión compilada",
        Lang.EN: " + {count} compiled extension",
    },
    "report.summary_compiled.other": {
        Lang.ES: " + {count} extensiones compiladas",
        Lang.EN: " + {count} compiled extensions",
    },
    "report.summary_stubs.one": {
        Lang.ES: " + {count} módulo solo stub",
        Lang.EN: " + {count} stub-only module",
    },
    "report.summary_stubs.other": {
        Lang.ES: " + {count} módulos solo stub",
        Lang.EN: " + {count} stub-only modules",
    },
    "report.metric.compiled": {Lang.ES: "Extensiones compiladas", Lang.EN: "Compiled extensions"},
    "report.metric.stubs": {Lang.ES: "Módulos solo stub", Lang.EN: "Stub-only modules"},
    "report.compiled_marker": {
        Lang.ES: "*(extensión compilada)*",
        Lang.EN: "*(compiled extension)*",
    },
    "report.stub_marker": {Lang.ES: "*(solo stub)*", Lang.EN: "*(stub only)*"},
    "report.packages_native_note": {
        Lang.ES: "Las extensiones compiladas y los stubs cuentan como módulos de su paquete, "
        "sin aportar Ce: lo que importan no se ve.",
        Lang.EN: "Compiled extensions and stubs count as modules of their package, without "
        "adding Ce: what they import cannot be seen.",
    },
    "report.consumers": {Lang.ES: "Consumidores", Lang.EN: "Consumers"},
    "report.coupled_consumers_note": {
        Lang.ES: "Consumidores: scripts, ejemplos o CI del repositorio que importan el "
        "módulo; no cuentan en Ca.",
        Lang.EN: "Consumers: scripts, examples or CI in the repository that import the "
        "module; they do not count in Ca.",
    },
    "report.scripts": {Lang.ES: "Scripts", Lang.EN: "Scripts"},
    "report.scripts_intro": {
        Lang.ES: "Código que ninguna distribución empaqueta y que nadie importa: scripts, "
        "ejemplos, CI. Usan el proyecto pero no forman parte de él, así que no cuentan en "
        "las métricas ni en los hallazgos (salvo las capas).",
        Lang.EN: "Code no distribution ships and nothing imports: scripts, examples, CI. "
        "They use the project but are not part of it, so they count in no metric and no "
        "finding (except layers).",
    },
    "report.script_group.one": {
        Lang.ES: "- `{directory}/` ({count} script) → {uses}",
        Lang.EN: "- `{directory}/` ({count} script) → {uses}",
    },
    "report.script_group.other": {
        Lang.ES: "- `{directory}/` ({count} scripts) → {uses}",
        Lang.EN: "- `{directory}/` ({count} scripts) → {uses}",
    },
    "report.summary_top_module": {
        Lang.ES: "Módulo más acoplado: {module} (Ca {ca}, Ce {ce}).",
        Lang.EN: "Most coupled module: {module} (Ca {ca}, Ce {ce}).",
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
    "report.untangle_hint": {
        Lang.ES: "Para ver qué imports cortar para deshacerlas: `unskein untangle`.",
        Lang.EN: "To see which imports to cut to undo them: `unskein untangle`.",
    },
    "report.tangles_heading": {Lang.ES: "Marañas", Lang.EN: "Tangles"},
    "report.tangle_size": {Lang.ES: "{size} módulos", Lang.EN: "{size} modules"},
    "report.cycles_heading": {Lang.ES: "Ciclos", Lang.EN: "Cycles"},
    "report.cycles": {Lang.ES: "Ciclos de dependencia", Lang.EN: "Dependency cycles"},
    "report.no_cycles": {
        Lang.ES: "No se encontraron ciclos de dependencia al importar.",
        Lang.EN: "No dependency cycles found at import time.",
    },
    "report.metric.hidden_tangles": {Lang.ES: "Marañas ocultas", Lang.EN: "Hidden tangles"},
    "report.summary_hidden.one": {
        Lang.ES: "1 grupo de módulos que dependen entre sí si se cuentan los imports "
        "perezosos o de tipos ({size} módulos).",
        Lang.EN: "1 group of modules that depend on each other once lazy or type-only "
        "imports are counted ({size} modules).",
    },
    "report.summary_hidden.other": {
        Lang.ES: "{count} grupos de módulos que dependen entre sí si se cuentan los imports "
        "perezosos o de tipos; el mayor tiene {size} módulos.",
        Lang.EN: "{count} groups of modules that depend on each other once lazy or type-only "
        "imports are counted; the largest has {size} modules.",
    },
    "report.hidden_heading": {Lang.ES: "Acoplamiento oculto", Lang.EN: "Hidden coupling"},
    "report.hidden_explanation": {
        Lang.ES: "Grupos de módulos que dependen entre sí, o grupos mayores que una maraña de "
        "las anteriores, cuando se cuentan los imports dentro de funciones o bajo "
        "`TYPE_CHECKING`. Esos imports no fallan al importar, pero siguen siendo "
        "acoplamiento de diseño.",
        Lang.EN: "Groups of modules that depend on each other, or groups larger than a tangle "
        "above, once imports inside functions or under `TYPE_CHECKING` are counted. Those "
        "imports do not fail at import time, but they are still design coupling.",
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
    "report.distributions": {Lang.ES: "Distribuciones", Lang.EN: "Distributions"},
    "report.distributions_intro": {
        Lang.ES: "Cada distribución del repositorio, lo que importa de verdad de las demás y "
        "si se puede instalar sola (sin extras) sin que falle ningún import.",
        Lang.EN: "Each distribution in the repository, what it really imports from the others "
        "and whether it can be installed alone (without extras) with no failing import.",
    },
    "report.distribution": {Lang.ES: "Distribución", Lang.EN: "Distribution"},
    "report.distribution_uses": {Lang.ES: "Usa", Lang.EN: "Uses"},
    "report.distribution_installable": {
        Lang.ES: "¿Instalable sola?",
        Lang.EN: "Installable alone?",
    },
    "report.installable.yes": {Lang.ES: "sí", Lang.EN: "yes"},
    "report.installable.no": {Lang.ES: "no: `{blocker}`", Lang.EN: "no: `{blocker}`"},
    "report.installable.unknown": {
        Lang.ES: "desconocido (no se pueden leer sus dependencias)",
        Lang.EN: "unknown (its dependencies cannot be read)",
    },
    "report.summary_distributions": {
        Lang.ES: "{count} distribuciones; {blocked} no se pueden instalar solas.",
        Lang.EN: "{count} distributions; {blocked} cannot be installed alone.",
    },
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
        Lang.ES: "No hay modelo de IA configurado. Para obtener una interpretación de estos "
        "resultados, define `UNSKEIN_AI_MODEL`, o `[ai] model` en el `.unskein.toml` de la "
        "carpeta analizada o en `~/.config/unskein/config.toml` (lo crea "
        "`unskein init --user`).",
        Lang.EN: "No AI model configured. To get an interpretation of these results, set "
        "`UNSKEIN_AI_MODEL`, or `[ai] model` in the `.unskein.toml` of the analyzed folder or "
        "in `~/.config/unskein/config.toml` (`unskein init --user` creates it).",
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
    "untangle.title": {
        Lang.ES: "Plan de desenredo de {project}",
        Lang.EN: "Untangle plan for {project}",
    },
    "untangle.scope.import": {
        Lang.ES: "Alcance: marañas al importar (imports a nivel de módulo).",
        Lang.EN: "Scope: import-time tangles (module-level imports).",
    },
    "untangle.scope.all": {
        Lang.ES: "Alcance: todas las dependencias, incluido el acoplamiento oculto "
        "(imports perezosos y bajo `TYPE_CHECKING`).",
        Lang.EN: "Scope: every dependency, hidden coupling included "
        "(lazy and `TYPE_CHECKING` imports).",
    },
    "untangle.summary": {
        Lang.ES: "Marañas: {tangles} · imports a cortar: {cuts} · coste total: {cost}.",
        Lang.EN: "Tangles: {tangles} · imports to cut: {cuts} · total cost: {cost}.",
    },
    "untangle.simulation": {
        Lang.ES: "Simulación tras los cortes: marañas {tangles_before} → {tangles_after}, "
        "ciclos {cycles_before} → {cycles_after}.",
        Lang.EN: "Simulation after the cuts: tangles {tangles_before} → {tangles_after}, "
        "cycles {cycles_before} → {cycles_after}.",
    },
    "untangle.none": {
        Lang.ES: "No hay marañas al importar: no hay nada que desenredar.",
        Lang.EN: "No import-time tangles: nothing to untangle.",
    },
    "untangle.none_all": {
        Lang.ES: "No hay marañas, ni siquiera contando el acoplamiento oculto.",
        Lang.EN: "No tangles, not even counting hidden coupling.",
    },
    "untangle.warnings": {
        Lang.ES: "Advertencias del análisis: {count} (detalle con `unskein scan`).",
        Lang.EN: "Analysis warnings: {count} (details with `unskein scan`).",
    },
    "untangle.hidden_hint": {
        Lang.ES: "Grupos de acoplamiento oculto: {count}; `unskein untangle --all-edges` "
        "también los incluye.",
        Lang.EN: "Hidden-coupling groups: {count}; `unskein untangle --all-edges` "
        "includes them too.",
    },
    "untangle.tangle_heading": {
        Lang.ES: "Maraña {index}: {size} módulos",
        Lang.EN: "Tangle {index}: {size} modules",
    },
    "untangle.tangle_line": {
        Lang.ES: "Imports a cortar: {cuts} · coste: {cost} · miembros: {members}",
        Lang.EN: "Imports to cut: {cuts} · cost: {cost} · members: {members}",
    },
    "untangle.col.import": {Lang.ES: "Import", Lang.EN: "Import"},
    "untangle.col.cost": {Lang.ES: "Coste", Lang.EN: "Cost"},
    "untangle.col.step": {Lang.ES: "Paso", Lang.EN: "Step"},
    "untangle.col.evidence": {Lang.ES: "Evidencia", Lang.EN: "Evidence"},
    "untangle.col.module": {Lang.ES: "Módulo", Lang.EN: "Module"},
    "untangle.col.instability": {Lang.ES: "Inestabilidad", Lang.EN: "Instability"},
    "untangle.cuts_truncated": {
        Lang.ES: "Cortes sin mostrar: {count}.",
        Lang.EN: "Cuts not shown: {count}.",
    },
    "untangle.tangles_truncated": {
        Lang.ES: "Se muestran {shown} de {total} marañas (las mayores); `--max-tangles` "
        "cambia el límite.",
        Lang.EN: "Showing {shown} of {total} tangles (the largest); `--max-tangles` "
        "changes the limit.",
    },
    "untangle.changes_heading": {Lang.ES: "Módulos afectados", Lang.EN: "Affected modules"},
    "untangle.steps_heading": {
        Lang.ES: "Qué significa cada paso",
        Lang.EN: "What each step means",
    },
    "untangle.note": {
        Lang.ES: "Los cortes salen de una heurística (Eades–Lin–Smyth) que no garantiza el "
        "mínimo. La simulación quita los imports cortados de las marañas; en el acoplamiento, "
        "los imports perezosos y bajo `TYPE_CHECKING` siguen contando. Mover un símbolo "
        "traslada su dependencia, así que el resultado real puede ser algo peor.",
        Lang.EN: "The cuts come from a heuristic (Eades–Lin–Smyth) that does not guarantee "
        "the minimum. The simulation removes the cut imports from the tangles; in the "
        "coupling, lazy and `TYPE_CHECKING` imports still count. Moving a symbol moves its "
        "dependency, so the real result can be somewhat worse.",
    },
    "untangle.step.type_checking": {
        Lang.ES: "Mover bajo TYPE_CHECKING",
        Lang.EN: "Move under TYPE_CHECKING",
    },
    "untangle.step.type_checking.help": {
        Lang.ES: "Los nombres solo se usan en anotaciones: importarlos bajo "
        "`if TYPE_CHECKING:` (con `from __future__ import annotations` o anotaciones entre "
        "comillas) quita la dependencia al importar. Las bibliotecas que leen anotaciones en "
        "ejecución (modelos de pydantic, firmas de typer o FastAPI, `typing.get_type_hints`, "
        "`functools.singledispatch`) necesitan el nombre en ejecución: ahí no sirve.",
        Lang.EN: "The names are only used in annotations: importing them under "
        "`if TYPE_CHECKING:` (with `from __future__ import annotations` or quoted "
        "annotations) removes the import-time dependency. Libraries that read annotations at "
        "runtime (pydantic models, typer or FastAPI signatures, `typing.get_type_hints`, "
        "`functools.singledispatch`) need the name at runtime: it does not work there.",
    },
    "untangle.step.bypass_facade": {
        Lang.ES: "Importar del módulo que lo define",
        Lang.EN: "Import from the defining module",
    },
    "untangle.step.bypass_facade.help": {
        Lang.ES: "La dependencia va al `__init__.py` de un paquete: importar cada nombre "
        "del módulo que lo define evita depender del paquete entero. Si el paquete se usa "
        "como estado global (`paquete.ajuste = ...`), el cambio es de diseño.",
        Lang.EN: "The dependency goes to a package's `__init__.py`: importing each name from "
        "the module that defines it avoids depending on the whole package. When the package "
        "is used as global state (`package.setting = ...`), it is a design change.",
    },
    "untangle.step.lazy": {Lang.ES: "Import perezoso", Lang.EN: "Lazy import"},
    "untangle.step.lazy.help": {
        Lang.ES: "Los nombres solo se usan dentro de funciones (o también en anotaciones, si el "
        "módulo tiene `from __future__ import annotations`): importarlos ahí rompe el ciclo al "
        "importar, aunque el acoplamiento sigue (aparecerá como acoplamiento oculto). Si una "
        "anotación usa el nombre, las bibliotecas que leen anotaciones en ejecución (modelos de "
        "pydantic, firmas de typer o FastAPI, `typing.get_type_hints`) ya no lo encuentran.",
        Lang.EN: "The names are only used inside functions (or in annotations too, when the "
        "module has `from __future__ import annotations`): importing them there breaks the "
        "import-time cycle, though the coupling stays (it will show as hidden coupling). If an "
        "annotation uses the name, libraries that read annotations at runtime (pydantic models, "
        "typer or FastAPI signatures, `typing.get_type_hints`) no longer find it.",
    },
    "untangle.step.move_symbol": {Lang.ES: "Mover el símbolo", Lang.EN: "Move the symbol"},
    "untangle.step.move_symbol.help": {
        Lang.ES: "Se importan uno o dos símbolos: moverlos a un módulo que no dependa del "
        "importador suele bastar. Revisa antes de qué dependen esos símbolos.",
        Lang.EN: "One or two symbols are imported: moving them to a module that does not "
        "depend on the importer usually does it. Check first what those symbols depend on.",
    },
    "untangle.step.extract_shared": {
        Lang.ES: "Extraer un módulo compartido",
        Lang.EN: "Extract a shared module",
    },
    "untangle.step.extract_shared.help": {
        Lang.ES: "Se usa mucho de ese módulo: extraer lo compartido a un módulo nuevo del que "
        "dependan los dos.",
        Lang.EN: "Much of that module is used: extract what is shared into a new module that "
        "both depend on.",
    },
    "untangle.step.package_structure": {
        Lang.ES: "Revisar la estructura del paquete",
        Lang.EN: "Review the package structure",
    },
    "untangle.step.package_structure.help": {
        Lang.ES: "Es un paquete importando uno de sus propios submódulos: el ciclo solo se "
        "rompe reorganizando el paquete (qué exporta su `__init__.py` y quién lo importa).",
        Lang.EN: "A package imports one of its own submodules: the cycle only breaks by "
        "reorganizing the package (what its `__init__.py` exports and who imports it).",
    },
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
    "finding.uses": {
        Lang.ES: "requeridos: {required}, perezosos: {lazy}, protegidos: {guarded}",
        Lang.EN: "{required} required, {lazy} lazy, {guarded} guarded",
    },
    "finding.first": {Lang.ES: "primero: `{first}`", Lang.EN: "first: `{first}`"},
    "finding.only_in_groups": {
        Lang.ES: "solo en el grupo {groups}, que nunca se instala con el paquete",
        Lang.EN: "only in group {groups}, never installed with the package",
    },
    "finding.fix": {Lang.ES: "Arreglo", Lang.EN: "Fix"},
    "report.native": {Lang.ES: "Frontera nativa", Lang.EN: "Native boundary"},
    "report.native_intro": {
        Lang.ES: "Módulos sin código Python legible: extensiones compiladas y módulos que solo "
        "tienen stub `.pyi`. Los usos cuentan solo el código empaquetado (sin tests ni "
        "scripts): requeridos / perezosos / protegidos / solo tipos.",
        Lang.EN: "Modules with no readable Python code: compiled extensions and modules that "
        "only have a `.pyi` stub. Uses count only packaged code (no tests or scripts): "
        "required / lazy / guarded / type-only.",
    },
    "report.native_note": {
        Lang.ES: "Lo que importa el código compilado no se ve: su Ce es desconocido, y los "
        "ciclos que pasen por él tampoco se ven.",
        Lang.EN: "What compiled code imports cannot be seen: its Ce is unknown, and cycles "
        "that go through them cannot be seen either.",
    },
    "report.native_kind": {Lang.ES: "Tipo", Lang.EN: "Kind"},
    "report.native_kind.compiled": {Lang.ES: "extensión compilada", Lang.EN: "compiled extension"},
    "report.native_kind.stub": {Lang.ES: "solo stub", Lang.EN: "stub only"},
    "report.native_evidence": {Lang.ES: "Prueba", Lang.EN: "Evidence"},
    "report.native_uses": {
        Lang.ES: "Usos (req / perez / prot / tipos)",
        Lang.EN: "Uses (req / lazy / guard / types)",
    },
    "report.native_works": {Lang.ES: "¿Funciona sin él?", Lang.EN: "Works without it?"},
    "report.native_works.yes": {Lang.ES: "sí", Lang.EN: "yes"},
    "report.native_works.no.one": {
        Lang.ES: "no: {count} uso sin protección (`{first}`)",
        Lang.EN: "no: {count} unguarded use (`{first}`)",
    },
    "report.native_works.no.other": {
        Lang.ES: "no: {count} usos sin protección (`{first}`)",
        Lang.EN: "no: {count} unguarded uses (`{first}`)",
    },
    "report.native_out": {Lang.ES: "Salida", Lang.EN: "Outgoing"},
    "report.native_out.compiled": {
        Lang.ES: "desconocida (código compilado)",
        Lang.EN: "unknown (compiled code)",
    },
    "report.native_out.stub": {Lang.ES: "desconocida (solo stub)", Lang.EN: "unknown (stub only)"},
    "finding.native_guarded": {Lang.ES: "protegido en `{first}`", Lang.EN: "guarded at `{first}`"},
    "finding.native_unguarded": {Lang.ES: "Sin protección", Lang.EN: "Unguarded"},
    "finding.fix.guard_or_drop_fallback": {
        Lang.ES: "protege esos imports como hace `{first_guarded}`, o quita ese respaldo si "
        "`{module}` es obligatorio.",
        Lang.EN: "guard those imports like `{first_guarded}` does, or drop that fallback if "
        "`{module}` is required.",
    },
    "finding.status.required": {Lang.ES: "requerida", Lang.EN: "required"},
    "finding.status.optional": {
        Lang.ES: "opcional (extra {extras})",
        Lang.EN: "optional (extra {extras})",
    },
    "finding.status.undeclared": {Lang.ES: "no declarada", Lang.EN: "undeclared"},
    "finding.status.unknown": {Lang.ES: "desconocida", Lang.EN: "unknown"},
    "finding.fix.add_dependency": {
        Lang.ES: "añade `{requirement}` a `{table}` en `{manifest}`",
        Lang.EN: "add `{requirement}` to `{table}` in `{manifest}`",
    },
    "finding.fix.promote_or_guard": {
        Lang.ES: "mueve `{target}` de los extras {extras} a las dependencias requeridas en "
        "`{manifest}`, o protege el import de `{first}` con `try`/`except ImportError`",
        Lang.EN: "move `{target}` from the extras {extras} to the required dependencies in "
        "`{manifest}`, or guard the import at `{first}` with `try`/`except ImportError`",
    },
    "finding.fix.package_or_move": {
        Lang.ES: "`{directory}` no lo empaqueta ninguna distribución: muévelo dentro de un "
        "paquete de `{source}` o decláralo en sus paquetes",
        Lang.EN: "`{directory}` is shipped by no distribution: move it inside a package of "
        "`{source}` or declare it among its packages",
    },
    "finding.fix.cut_edge": {
        Lang.ES: "corta {cuts}: las aristas con menos usos que rompen, hasta que no quede "
        "ningún ciclo",
        Lang.EN: "cut {cuts}: the edges with the fewest breaking uses, until no cycle is left",
    },
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
    "finding.undeclared_dependency.title": {
        Lang.ES: "Dependencia no declarada",
        Lang.EN: "Undeclared dependency",
    },
    "finding.undeclared_dependency.explanation": {
        Lang.ES: "Una distribución del repositorio importa otra que su manifiesto no declara: "
        "en el monorepo funciona porque todo está instalado, pero instalada sola falla al "
        "importar.",
        Lang.EN: "A distribution in the repository imports another one its manifest does not "
        "declare: it works in the monorepo because everything is installed, but installed "
        "alone it fails at import time.",
    },
    "finding.undeclared_dependency.recommendation": {
        Lang.ES: "Declarar la dependencia en el manifiesto de la distribución que importa, o "
        "dejar de importarla.",
        Lang.EN: "Declare the dependency in the manifest of the importing distribution, or stop "
        "importing it.",
    },
    "finding.optional_required.title": {
        Lang.ES: "Dependencia opcional usada como requerida",
        Lang.EN: "Optional dependency used as required",
    },
    "finding.optional_required.explanation": {
        Lang.ES: "Una distribución declara otra solo en un extra, pero la importa al cargarse y "
        "sin protegerla: quien la instale sin ese extra la verá fallar al importar.",
        Lang.EN: "A distribution declares another one only in an extra, but imports it at load "
        "time without guarding it: whoever installs it without that extra sees it fail on "
        "import.",
    },
    "finding.optional_required.recommendation": {
        Lang.ES: "Pasarla a las dependencias requeridas, o importarla dentro de un "
        "`try`/`except ImportError`.",
        Lang.EN: "Make it a required dependency, or import it inside a `try`/`except ImportError`.",
    },
    "finding.unpackaged_import.title": {
        Lang.ES: "Import de código no empaquetado",
        Lang.EN: "Import of unpackaged code",
    },
    "finding.unpackaged_import.explanation": {
        Lang.ES: "Una distribución importa código que ninguna distribución empaqueta: solo "
        "existe en el repositorio, así que instalada desde un paquete falla al importar.",
        Lang.EN: "A distribution imports code that no distribution ships: it only exists in the "
        "repository, so once installed from a package the import fails.",
    },
    "finding.unpackaged_import.recommendation": {
        Lang.ES: "Mover ese código dentro de un paquete de la distribución o declararlo entre "
        "sus paquetes.",
        Lang.EN: "Move that code inside a package of the distribution or declare it among its "
        "packages.",
    },
    "finding.distribution_cycle.title": {
        Lang.ES: "Ciclo entre distribuciones",
        Lang.EN: "Cycle between distributions",
    },
    "finding.distribution_cycle.explanation": {
        Lang.ES: "Varias distribuciones se importan entre sí: ninguna se puede publicar, "
        "versionar ni instalar sin las demás.",
        Lang.EN: "Several distributions import each other: none can be released, versioned or "
        "installed without the others.",
    },
    "finding.distribution_cycle.recommendation": {
        Lang.ES: "Cortar la arista con menos usos que rompen, para que las dependencias entre "
        "distribuciones vayan en un solo sentido.",
        Lang.EN: "Cut the edge with the fewest breaking uses, so dependencies between "
        "distributions go one way only.",
    },
    "finding.missing_module.title": {
        Lang.ES: "Import de un módulo inexistente",
        Lang.EN: "Import of a module that does not exist",
    },
    "finding.missing_module.explanation": {
        Lang.ES: "Código empaquetado importa un módulo del proyecto que no existe, al cargarse "
        "o dentro de una función y sin protegerlo: cuando se ejecuta, lanza ImportError.",
        Lang.EN: "Packaged code imports a project module that does not exist, at load time or "
        "inside a function and unguarded: when it runs, it raises ImportError.",
    },
    "finding.missing_module.recommendation": {
        Lang.ES: "Restaurar el módulo, importar el nombre desde el módulo que lo define, o "
        "eliminar el import.",
        Lang.EN: "Restore the module, import the name from the module that defines it, or "
        "remove the import.",
    },
    "finding.optional_native_required.title": {
        Lang.ES: "Extensión opcional usada como obligatoria",
        Lang.EN: "Optional extension used as required",
    },
    "finding.optional_native_required.explanation": {
        Lang.ES: "El código protege el import de este módulo compilado en un sitio: cuenta con "
        "que puede faltar (PyPy, una plataforma sin wheel, una instalación sin compilador). En "
        "otros sitios lo importa sin protección, y ahí lanza ImportError si falta. unskein no "
        "sigue el flujo de control: comprueba cada línea por si una comprobación previa "
        "(`if disponible():`) ya la protege.",
        Lang.EN: "The code guards the import of this compiled module in one place: it expects "
        "that it can be missing (PyPy, a platform without a wheel, an install without a "
        "compiler). Elsewhere it imports it unguarded, and there it raises ImportError when it "
        "is missing. unskein does not follow control flow: check each line in case an earlier "
        "check (`if available():`) already guards it.",
    },
    "finding.optional_native_required.recommendation": {
        Lang.ES: "Proteger esos usos con el mismo respaldo, o quitar el respaldo si la extensión "
        "es obligatoria.",
        Lang.EN: "Guard those uses with the same fallback, or drop the fallback if the "
        "extension is required.",
    },
    "finding.fix.import_from": {Lang.ES: "importa {items}", Lang.EN: "import {items}"},
    "finding.fix.import_from.item": {
        Lang.ES: "`{symbol}` desde `{module}`, que lo define{others}",
        Lang.EN: "`{symbol}` from `{module}`, which defines it{others}",
    },
    "finding.fix.undefined": {
        Lang.ES: "ningún módulo del proyecto define {symbols}",
        Lang.EN: "no module of the project defines {symbols}",
    },
    "finding.fix.restore_or_remove": {
        Lang.ES: "`{module}` no existe y ningún módulo del proyecto define {symbols}: "
        "restaura el módulo o elimina el import",
        Lang.EN: "`{module}` does not exist and no module of the project defines {symbols}: "
        "restore the module or remove the import",
    },
    "finding.fix.restore_or_remove.module": {
        Lang.ES: "`{module}` no existe; el más cercano que existe es {closest}: restaura el "
        "módulo o elimina el import",
        Lang.EN: "`{module}` does not exist; the closest that exists is {closest}: restore "
        "the module or remove the import",
    },
    "finding.also_defined": {
        Lang.ES: " (y en {count} módulo(s) más)",
        Lang.EN: " (and in {count} more module(s))",
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
    "cli.config_project_hint": {
        Lang.ES: (
            "unskein lo lee al analizar esta carpeta. "
            "Para usarlo en todos tus proyectos: unskein config save"
        ),
        Lang.EN: (
            "unskein reads it when analyzing this folder. "
            "To use it in all your projects: unskein config save"
        ),
    },
    "cli.config_saved": {
        Lang.ES: (
            "Configuración guardada en {path}. unskein la usa en todos tus proyectos; "
            "el .unskein.toml de un proyecto la sustituye clave a clave."
        ),
        Lang.EN: (
            "Config saved to {path}. unskein uses it in all your projects; "
            "a project's .unskein.toml overrides it key by key."
        ),
    },
    "cli.config_saved_key": {
        Lang.ES: (
            "Aviso: el archivo guardado contiene [ai] api_key en claro. "
            "Mejor quítala de ahí y usa la variable de entorno UNSKEIN_API_KEY."
        ),
        Lang.EN: (
            "Warning: the saved file holds [ai] api_key in plain text. "
            "Better remove it from there and use the UNSKEIN_API_KEY environment variable."
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
