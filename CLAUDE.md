# unskein — Contexto del proyecto

Este archivo da contexto a Claude Code sobre el proyecto `unskein`. Léelo antes de
proponer cambios de diseño o generar código nuevo.

## Qué es

`unskein` es un CLI de análisis estático de código, impulsado por IA, escrito en
Python. Detecta dependencias, acoplamiento y ciclos entre módulos, y usa un LLM
para interpretar esas señales y generar recomendaciones.

Nombre elegido tras verificar disponibilidad en PyPI (evitamos "cortex" y variantes
por saturación de namespace y por un competidor directo llamado CodeCortex).
El nombre evoca "desenredar" (unskein = deshacer una madeja) la maraña de
dependencias de un proyecto.

## Audiencia y forma de uso

- **Proyecto open source**, licencia MIT.
- Se usa como **CLI manual** (`unskein scan <path>`), no como servicio ni gate de
  CI/CD en v0.1 (eso podría venir después, pero no es el foco ahora).

## Alcance funcional (v0.1)

Solo dos de los cuatro requisitos originales del proyecto, deliberadamente acotado:

1. **Análisis de dependencias** — grafo de imports entre módulos.
2. **Acoplamiento de sistemas** — métricas Ca/Ce/Inestabilidad + detección de ciclos.

Quedan **fuera de v0.1** (fase 2, sin diseñar aún):
- Análisis de vulnerabilidades CVE.
- Mapa de arquitectura completo (más allá del grafo de dependencias).

Granularidad: **nivel de módulo/archivo**, no de clase/función.

## Lenguajes

- **v0.1: solo Python.**
- Roadmap futuro (no implementar todavía): TypeScript/JavaScript (v0.3), luego
  Java (v0.4), usando `tree-sitter` como capa de abstracción de parseo para no
  reescribir el pipeline por cada lenguaje nuevo.
- El diseño del adapter (`parsers/base.py`) ya está pensado para esto: es una
  interfaz (`LanguageAdapter`) que cada lenguaje implementa.

## Discovery de archivos

- **Excludes combinados de tres orígenes** (unión, no se pisan entre sí):
  `.gitignore` + `.unskeinignore` (nuevo, para excluir del análisis algo que
  sí está versionado en git, ej. código generado) + `--exclude` del CLI.
- **Symlinks NO se siguen por defecto** (`follow_symlinks=False`). Se usa
  `os.walk(followlinks=...)`, no `Path.rglob()` (que en Python 3.12 sigue
  symlinks siempre — el parámetro para desactivarlo no existe hasta 3.13).
  Flag `--follow-symlinks` para quien los necesite explícitamente. Con
  symlinks seguidos, además, hay detección de ciclos por directorio real
  visitado (defensa en profundidad, no depender solo de `followlinks`).
  Motivo del default seguro: seguir symlinks puede causar bucles infinitos
  (symlink que apunta a un ancestro) o fuga de alcance (analizar código fuera
  del proyecto, ej. un venv compartido).
- **Encoding se detecta por archivo** vía `tokenize.detect_encoding` (stdlib,
  ya implementa PEP 263 — encoding cookie `# -*- coding: ... -*-` — y
  detección de BOM). `--encoding`/`.unskein.toml` (`default_encoding`) es
  solo un *fallback* para cuando el archivo no declara cookie y la detección
  automática no puede resolverlo — nunca fuerza un encoding sobre un archivo
  que ya lo declara.
- **Límites de tamaño y tiempo por archivo**, para evitar que un archivo
  anómalo (generado, minificado, vendored) degrade el análisis completo:
  `max_file_size_bytes` (default 5 MB — se salta con warning, ni se lee) y
  `per_file_timeout_seconds` (default 30s, vía `future.result(timeout=...)`
  del `ProcessPoolExecutor` — se salta con warning ese archivo, no tumba el
  análisis; solo deja de esperar: el worker no se cancela). Ver `docs/architecture.md`, sección 3.5.

## Stack técnico

- **Python `>=3.12`** como mínimo soportado; **3.14 como versión de desarrollo/CI
  principal**. No se diseña v0.1 asumiendo builds free-threaded (`cp314t`): el
  ecosistema de wheels de extensiones en C (pydantic-core, y el futuro
  tree-sitter para v0.3+) todavía no tiene soporte maduro y confiable para
  free-threading. Revisar de nuevo cuando se evalúe activarlo como optimización
  opcional, no asumirlo como base.
- `ast` (stdlib) para parseo de Python — no usar `tree-sitter` todavía en v0.1,
  solo se adoptará al agregar el segundo lenguaje.
- `networkx` para el grafo de dependencias y sus métricas.
- `pydantic` para validar la salida estructurada del LLM.
- `typer` + `rich` para el CLI y el renderizado en terminal.
- `litellm` como capa de abstracción del proveedor de IA — **no** usar SDKs de
  proveedores específicos (ni `openai`, ni `azure-openai` directo). Todo el
  fallback entre modelos y reintentos se gestiona vía LiteLLM, no con lógica
  propia.
- Proveedor de IA previsto: Ollama local con modelos económicos de HuggingFace,
  con fallback configurable a un proveedor cloud vía LiteLLM.
- `hatchling` como build backend (estándar actual para layout `src/`).
- `psutil` para medición de rendimiento (CPU/RAM) multiplataforma — soporte
  Windows y Linux desde v0.1. `resource` (solo Unix) únicamente como rama
  Unix del pico de memoria, que `psutil` no expone fuera de Windows; nunca
  como única vía (#9).
- `pytest` + `pytest-cov` — testing desde el primer commit, no pospuesto.

## Internacionalización (i18n)

- **Español + inglés desde v0.1**, ambos con soporte completo (CLI, reporte,
  y las respuestas generadas por el LLM).
- Diccionario simple de traducciones (`unskein/i18n.py`), no `gettext`/catálogos
  `.mo` — con solo 2 idiomas es innecesario y complica testing.
- Detección de idioma con la precedencia de las opciones no secretas: flag
  `--lang` > env var (`UNSKEIN_LANG`) > `.unskein.toml` (`[general] lang =
  "es"`). Si nada está configurado: `locale.getlocale()`, y si no es `es*`,
  **default a inglés** (más seguro para adopción OSS amplia — no asumir que
  quien instala el CLI habla español).
- El `SYSTEM_PROMPT` de IA se parametriza por idioma — el LLM debe responder
  (`AIReport.summary`, `Problem.description`) en el idioma seleccionado, no
  solo el CLI/reporte. Ver `docs/architecture.md`.

## Estructura del repo

```
src/unskein/
├── cli.py                 # typer: flags, salida, códigos de salida (capa fina)
├── scan.py                # orquestación: prepare_scan + execute_scan
├── entry_points.py        # puntos de entrada de pyproject.toml (scripts)
├── config.py              # AnalysisConfig, AIConfig, jerarquía de config
├── init_config.py         # `unskein init`: plantilla .unskein.toml comentada
├── templates/unskein.toml # plantilla (viaja en el wheel)
├── guide.py               # `unskein guide`: guía de uso ES/EN de la versión instalada
├── guides/guide.{es,en}.md # la guía (viaja en el wheel; un test exige cada opción)
├── resources.py           # lectura de archivos del paquete (importlib.resources)
├── i18n.py                # diccionario ES/EN
├── pipeline.py            # parse_all + should_parallelize
├── parsers/
│   ├── models.py           # ImportEdge, ModuleInfo, ReExport, ParseResult
│   ├── base.py             # interfaz LanguageAdapter (el "adapter")
│   ├── discovery.py        # os.walk, excludes, encoding
│   ├── indirection.py      # resolución de re-exports
│   └── python_parser.py    # implementación para Python con ast
├── graph/
│   ├── builder.py           # construcción del grafo con NetworkX
│   ├── metrics.py           # Ca, Ce, inestabilidad, ciclos
│   ├── findings.py          # hallazgos: reglas deterministas sobre el grafo
│   └── percentile.py        # percentil por rango más cercano (compartido)
├── ai/
│   ├── client.py             # wrapper de litellm.completion
│   └── prompts.py            # system prompt + construcción de prompts
└── report/
    └── markdown.py           # generación del reporte final
```

Layout `src/` deliberado (evita bugs de import en desarrollo, estándar actual
para paquetes Python distribuibles).

## Decisiones de diseño importantes (no revertir sin discutirlo)

- **Separación estricta grafo (determinista) vs. IA (interpretativa).** El grafo
  y las métricas de acoplamiento se calculan siempre, sin LLM. La IA solo
  interpreta lo que el grafo ya calculó — nunca decide qué es un módulo o un
  import.
- **Los hallazgos (`graph/findings.py`) son reglas deterministas sobre el grafo**;
  la IA solo los interpreta y nunca cambian el código de salida.
- **`is_external` se calcula comparando el primer segmento del import contra los
  módulos del proyecto**, no contra una lista de stdlib/paquetes conocidos.
- **Resolución de re-exports (indirección) es parte de v0.1**, no se pospuso.
  Ver `docs/architecture.md` para el algoritmo completo (incluye límite de
  profundidad y detección de ciclos de re-export).
- **Fallos de IA nunca detienen el comando.** Si falla la config, la llamada, o
  la validación del schema de salida, el reporte se genera igual sin la sección
  de IA, con un aviso claro.
- **Salida estructurada del LLM vía Pydantic**, con fallback de extracción de
  JSON embebido para modelos económicos que no respetan bien `response_format`.
- **Snippets de código en las recomendaciones de IA son v0.2**, no v0.1. En v0.1
  la IA solo da resumen + problemas señalados, sin proponer código de solución.

## Jerarquía de configuración

**Secretos y modelo de IA** — precedencia (mayor a menor):
1. Variable de entorno (`UNSKEIN_AI_MODEL`, `UNSKEIN_API_KEY`, `UNSKEIN_AI_API_BASE`)
2. Archivo de config (`.unskein.toml` en el proyecto, o `~/.config/unskein/config.toml`)
3. Flag `--api-key` (documentado explícitamente como inseguro, solo para pruebas)

**Resto de opciones (no secretas)** — `--lang`, `--include-tests`,
`--follow-symlinks`, `--encoding`…: **flag > env var > `.unskein.toml` >
default**. Lo escrito en la terminal siempre gana. Solo hay env vars donde
están documentadas (`UNSKEIN_LANG`); no se inventa una por opción. Los
booleanos son de tres estados (`--include-tests/--no-include-tests`, `None`
si no se escribe) para poder ganarle al toml en ambos sentidos. Los
`exclude` no compiten: se **suman** (toml + flags), como todo exclude.

**`.unskein.toml`**: se leen `~/.config/unskein/config.toml` y el del
proyecto, cada uno **validado por separado** con Pydantic (`extra="forbid"`,
`strict=True`) para que el error nombre el archivo; luego se combinan tabla a
tabla, ganando el del proyecto clave por clave. Clave desconocida (errata),
tipo erróneo o TOML inválido → `ConfigError` (código 1), estructurado
(`key` + `params`, nunca el valor ofensivo) para traducirlo en el CLI.

Nunca loguear la API key, ni siquiera en modo `--verbose`. `.env.example` sin
valores reales debe existir desde el scaffold inicial, con `.gitignore` ya
configurado para `.env` y `.unskein.toml`. La plantilla de `.unskein.toml` la
genera `unskein init` (todas las claves comentadas con su default; un test
falla si un default cambia sin actualizarla).

## Criterios de rendimiento y estilo de código

- **Funcional para composición entre capas, imperativo en los bucles calientes.**
  El flujo de alto nivel (`discover → parse → resolve → analyze`) se escribe
  como composición de funciones puras — favorece legibilidad y testabilidad.
  Dentro de cada capa, en los bucles que recorren miles de nodos/edges
  (`ast.walk`, cálculo de métricas por módulo), usar bucles explícitos o
  comprensiones de listas, no cadenas de `map`/`filter`/`reduce` con lambdas.
  **Motivo:** en CPython el estilo funcional puro no reduce RAM ni mejora
  ciclos de CPU por sí solo — el overhead de invocación de funciones lambda
  frecuentemente hace que sea más lento que un bucle plano. Esa ventaja sí
  existe en lenguajes con compilación nativa (Rust, Haskell), pero no en un
  intérprete de bytecode como CPython.
- **Reducción de memoria real, técnicas concretas a aplicar:**
  - Generadores (`Iterator[Path]`) en vez de listas materializadas donde el
    pipeline lo permita — evita cargar en memoria más de lo necesario en
    proyectos grandes.
  - `@dataclass(slots=True)` en las estructuras que se instancian en masa
    (`ImportEdge`, `ModuleInfo`) — reduce memoria por instancia de forma
    significativa cuando hay miles de imports.
  - `itertools` para composición de transformaciones sin el overhead de
    lambdas anidadas.

## Clean Code (obligatorio)

Norma obligatoria para todo código nuevo o modificado. Un PR que no la cumpla
no se mergea.

**Docstrings — en todo módulo, clase, función y método, privados incluidos.**
- Estilo **Google**, en **inglés** (como el resto del código).
- Resumen de una línea en **modo imperativo** ("Return…", "Build…"),
  terminado en punto. Línea en blanco antes de las secciones.
- Secciones solo cuando aportan: `Args:` para cada parámetro (su significado,
  no su tipo — el tipo ya está en el type hint), `Returns:` si no devuelve
  `None` (`Yields:` en generadores), `Raises:` para las excepciones que el
  llamador debe esperar.
- Clases: los argumentos de `__init__` van en `Args:` del docstring de la
  clase (nunca docstring en `__init__`). Dataclasses/modelos Pydantic:
  sección `Attributes:` con cada campo.
- Módulos y `__init__.py` de paquete: una línea con su responsabilidad.
- Excepción: comandos de `typer` (`scan`, `main`) — su docstring se muestra
  en `--help`, así que solo resumen, orientado al usuario, sin `Args:`
  (las opciones ya tienen `help=`).
- Tests **no** llevan docstring: el nombre del test describe el
  comportamiento (`test_reexport_cycle_yields_one_warning_per_cycle`).
  Helpers y fixtures de tests sí, cuando no sean triviales.
- **Enforcement en CI, doble:** reglas `D` de ruff (`pydocstyle`,
  `convention = "google"`) validan presencia y formato de los docstrings
  públicos; como pydocstyle **no** revisa nombres privados (`_x`),
  `tests/integration/test_docstrings.py` recorre `src/` y `scripts/` con
  `ast` y falla si falta el docstring de cualquier módulo, clase o función,
  privados incluidos (`__init__` exento). El formato Google de los privados
  se sigue verificando en revisión.

**Reglas de código:**
- **Nombres que revelan intención.** Sin abreviaturas crípticas; booleanos
  como predicado (`is_external`, `follow_symlinks`); funciones con verbo.
- **Funciones pequeñas, una responsabilidad, sin efectos secundarios
  ocultos.** Entre capas, funciones puras que devuelven valores nuevos en
  vez de mutar la entrada (p. ej. `resolve_indirection`).
- **Máximo 3 parámetros posicionales**; más allá, agruparlos en un
  dataclass de configuración (patrón de `AnalysisConfig`). Excepción
  documentada: los comandos `typer` (`scan`), donde cada parámetro *es* una
  flag del CLI y no se pueden agrupar; se marcan con `# pylint: disable=...`
  en línea y la lógica se delega enseguida a un dataclass (`ScanOptions`).
  Los dataclasses de datos/config pueden tener hasta 12 campos.
- **Sin números mágicos**: constantes con nombre (`MAX_CYCLES`,
  `MAX_RESOLUTION_DEPTH`, `DEFAULT_TEST_PATTERNS`).
- **Errores explícitos, nunca silenciados**: los esperados como warning en el
  resultado o `UnskeinError`; nada de `except: pass`.
- **Comentarios solo para el porqué** (restricción oculta, workaround,
  decisión no obvia). El *qué* lo cuentan los nombres y el docstring.
- **Sin código muerto ni comentado**; sin duplicación (DRY) salvo que
  abstraer empeore la lectura.
- **Regla del boy scout**: el código que se toca queda mejor de lo que
  estaba (dentro del alcance del PR).
- **Tests F.I.R.S.T.** (rápidos, independientes, repetibles, auto-validados,
  escritos antes que el código — TDD). Aislados del entorno real: una
  fixture `autouse` apunta la config de usuario a un archivo inexistente y
  elimina las `UNSKEIN_*`.
- **Pylint** (`[tool.pylint]` en `pyproject.toml`) está alineado con estas
  reglas para el IDE; ruff sigue siendo el gate de CI. Desactivar un aviso
  solo con motivo escrito (en la config o en línea), nunca "para que calle".

## Modelo de concurrencia

- **Paralelización del parseo de archivos**, no asumida siempre: se activa solo
  si `len(files) >= config.parallel_threshold` (configurable, ver abajo). Por
  debajo del umbral, el overhead de arrancar procesos supera la ganancia.
- **`ProcessPoolExecutor`**, no builds free-threaded — funciona en cualquier
  Python 3.12+ sin depender de la madurez de wheels `cp314t`.
- **`AnalysisConfig` parametriza el umbral y los workers** desde ya (no
  hardcodeado), configurable desde `.unskein.toml` (`[analysis]`) con la
  precedencia de las opciones no secretas (ver *Jerarquía de configuración*):
  ```python
  @dataclass
  class AnalysisConfig:
      parallel_threshold: int = 500    # calibrado, ver docs/architecture.md §3.5
      max_workers: int | None = None   # None = min(os.cpu_count(), 8)
      queue_maxsize: int = 200
  ```
- **La decisión de paralelizar vive en una función aislada**,
  `should_parallelize(file_count, config)` — punto de extensión explícito para
  cuando se introduzca lógica adaptativa (v0.2+: calibrar según núcleos
  disponibles, tamaño total en bytes, etc.) sin tocar el resto del pipeline.
- **Cola única compartida entre workers de una misma etapa** (no sharding por
  hash) — el autobalanceo dinámico de una cola compartida evita el "efecto
  straggler" que el sharding estático puede introducir cuando el costo de
  procesar cada archivo es desigual.
- **Colas separadas por etapa del pipeline** (parse → resolve → metrics), estilo
  SEDA (*staged event-driven architecture*): cada etapa tiene su propia cola
  acotada de entrada y su propio `StageConfig` (workers, `queue_maxsize`),
  dimensionado según si la etapa es CPU-bound (parseo) o liviana (resolución de
  indirección, cálculo de métricas con NetworkX, difícil de paralelizar
  internamente).
- **No se usa un bus de eventos / pub-sub real (tópicos, múltiples
  suscriptores) en v0.1.** El proceso es de una sola pasada, con un productor y
  un consumidor lógico por etapa — un event bus añadiría complejidad sin
  contraparte real en este flujo. Reconsiderar solo si se agrega un modo
  *watch* (re-análisis incremental) o integración en vivo con un IDE.
- **Hash-sharding queda diferido explícitamente** a una eventual arquitectura
  distribuida en contenedores (enrutamiento determinista de archivos entre
  nodos/colas externas tipo Redis o SQS) — no tiene sentido para concurrencia
  local con colas en memoria, donde la cola compartida ya da balanceo óptimo.
  No diseñar v0.1 anticipando esto.

## Logging

- `logging` estándar de la stdlib, logger `"unskein"`, `propagate=False`.
- **Consola + archivo opcional.** Consola siempre activa (nivel `WARNING`, o
  `DEBUG` con `--verbose`); archivo solo si se pasa `--log-file <ruta>` (nadie
  escribe a disco sin pedirlo). Formato de archivo con timestamp/nivel/logger;
  formato de consola limpio (solo el mensaje, sin ruido).
- **La API key nunca aparece en ningún log**, en ningún handler, en ningún
  nivel — regla ya establecida para la config de IA, se mantiene sin excepción.

## Códigos de salida del CLI

| Código | Significado |
|---|---|
| `0` | Análisis completado, sin problemas de severidad `high` (`--min-severity` solo filtra lo que se muestra) |
| `1` | Error de uso (ruta inválida, sin archivos `.py`, config inválida) |
| `2` | Análisis completado, con problemas de severidad `high` encontrados |
| `3` | Error interno inesperado (bug real — traceback completo visible) |

Documentado en el `epilog` del `--help` de `typer`. Útil para quien quiera
scriptear `unskein` por su cuenta, aunque v0.1 no es un gate de CI dedicado.

## Telemetría y métricas de rendimiento

- **Cero telemetría de uso.** Nada sale del equipo del usuario — ni siquiera
  anónimo. Declarado explícitamente en el README (sección de privacidad),
  la comunidad OSS lo pregunta rápido.
- **Medición de rendimiento es local y solo informativa** (Windows +
  Linux/macOS). Se muestra solo con `--verbose` (duración + **pico real** de
  memoria del proceso: `psutil` `peak_wset` en Windows, `resource.ru_maxrss`
  en Unix), nunca se envía a ningún servidor.

## Roadmap de versiones

| Versión | Alcance |
|---|---|
| v0.1 | Python, nivel módulo, dependencias + acoplamiento, salida texto/Markdown, IA = resumen + problemas señalados (sin snippets) |
| v0.2 | Recomendaciones con snippets de código, salida JSON opcional |
| v0.3 | Segundo lenguaje (TypeScript/JavaScript) vía tree-sitter |
| v0.4 | Tercer lenguaje (Java) |
| Fase 2 | CVE + mapa de arquitectura completo |

## Estado actual

El diseño de todas las capas de v0.1 está cerrado a nivel de arquitectura
(ver `docs/architecture.md` para el detalle técnico completo de cada módulo).
Implementado y funcionando end-to-end (`unskein scan <path>`): discovery, parser
de Python, resolución de re-exports, grafo + métricas, carga de config, reporte
Markdown ES/EN, IA vía LiteLLM (con degradación a aviso) y CLI con códigos de
salida, y el parseo paralelo (`pipeline._parse_parallel`, desde `parallel_threshold`
archivos).

## Convenciones al trabajar en este proyecto

- Dataclasses (o Pydantic donde haya validación de I/O externo, como la salida
  del LLM) para todas las estructuras de datos del pipeline.
- **Testing desde el primer commit, no pospuesto** (decisión revertida
  respecto a una versión anterior de este documento). `pytest` +
  `pytest-cov`, corriendo en CI contra Python 3.12/3.13/3.14. Fixtures con
  mini-proyectos Python sintéticos (`simple_project`, `circular_imports`,
  `reexport_chain`, `reexport_cycle`) — ver `docs/architecture.md`. Sin
  umbral de cobertura numérico rígido de entrada; se revisa como señal, no
  como gate automático, hasta que el proyecto tenga más rodaje.
- No introducir dependencias de SDKs de proveedores de IA específicos — todo
  pasa por LiteLLM.
- Repo sigue la plantilla estándar OSS con licencia MIT: `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md` (Contributor Covenant), `SECURITY.md`,
  `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, workflows de
  CI/release en `.github/workflows/`. Versionado semver desde `0.1.0`,
  `CHANGELOG.md` formato *Keep a Changelog*, publicación a PyPI vía Trusted
  Publishing (OIDC desde GitHub Actions, sin token de PyPI almacenado).
