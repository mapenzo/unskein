# Arquitectura de unskein (v0.1)

Este documento recoge el diseño técnico completo acordado para v0.1, capa por
capa, en el orden en que se ejecuta el pipeline. Es la referencia de diseño
antes de escribir código — si algo del código diverge de aquí, o se actualiza
este documento, o se discute el cambio explícitamente.

Pipeline general:

```
discovery → parse → resolve_indirection → analyze (grafo + métricas) → IA (opcional) → report
```

---

## 1. El adapter (`parsers/base.py`)

Contrato común para que cualquier lenguaje (Python en v0.1, TS/Java después)
se integre al pipeline sin reescribirlo.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ImportEdge:
    source: str
    target: str
    is_external: bool
    symbol_name: str | None = None   # None si es import de módulo completo
    line_number: int | None = None

@dataclass
class ModuleInfo:
    name: str
    file_path: Path
    imports: list[ImportEdge] = field(default_factory=list)

@dataclass
class ReExport:
    exporting_module: str
    original_module: str
    symbol_name: str

@dataclass
class ParseResult:
    modules: list[ModuleInfo]
    language: str
    re_exports: list[ReExport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

class LanguageAdapter(ABC):
    @property
    @abstractmethod
    def language_name(self) -> str: ...

    @property
    @abstractmethod
    def file_extensions(self) -> list[str]: ...

    @abstractmethod
    def discover_files(self, root: Path, exclude: list[str]) -> list[Path]: ...

    @abstractmethod
    def parse(self, files: list[Path], root: Path) -> ParseResult: ...

    @abstractmethod
    def normalize_module_name(self, file_path: Path, root: Path) -> str: ...

    def resolve_indirection(self, result: ParseResult) -> ParseResult:
        """Implementación default, compartida entre lenguajes (ver sección 2)."""
        ...
```

Decisiones clave:
- `is_external` vive en el propio `ImportEdge`, calculado por cada adapter
  comparando el primer segmento del import contra los módulos del proyecto
  (no contra una lista de stdlib/paquetes conocidos — más robusto).
- `ParseResult.warnings` en vez de excepciones duras: un archivo con sintaxis
  inválida no debe tumbar el análisis completo del proyecto.
- `resolve_indirection` tiene implementación default en la clase base porque
  la lógica de "seguir la cadena de re-exports" es un problema de grafos, igual
  en cualquier lenguaje. Lo que cambia por lenguaje es cómo se *detecta* un
  re-export (eso sí vive en `parse()`).

---

## 2. Resolución de indirección (re-exports)

Objetivo: reescribir `ImportEdge.target` cuando apunta a un módulo "fachada"
(que solo re-exporta), para que apunte al módulo real donde vive el símbolo.
Necesario desde v0.1 — sin esto, ciclos reales de acoplamiento quedan
invisibles cuando pasan por un `__init__.py` que re-exporta.

```python
MAX_RESOLUTION_DEPTH = 10

ReExportIndex = dict[tuple[str, str], str]  # (módulo_exportador, símbolo) -> módulo_original

def build_reexport_index(re_exports: list[ReExport]) -> ReExportIndex:
    return {(re.exporting_module, re.symbol_name): re.original_module for re in re_exports}

def resolve_target(
    module: str, symbol: str | None, index: ReExportIndex, visited: set[str] | None = None,
) -> tuple[str, list[str]]:
    if visited is None:
        visited = set()
    warnings = []

    if symbol is None or (module, symbol) not in index:
        return module, warnings
    if module in visited:
        warnings.append(f"Ciclo de re-exports detectado en '{module}', deteniendo resolución")
        return module, warnings
    if len(visited) >= MAX_RESOLUTION_DEPTH:
        warnings.append(f"Profundidad máxima de re-exports excedida en '{module}'")
        return module, warnings

    visited.add(module)
    next_module = index[(module, symbol)]
    return resolve_target(next_module, symbol, index, visited)
```

Decisiones:
- Ciclos de re-export no rompen el análisis, degradan con warning (misma
  filosofía que archivos no parseables).
- Externos (`is_external=True`) nunca se resuelven — no tiene sentido seguir
  la cadena dentro del código de una librería.
- Resolución recursiva simple en v0.1, sin memoización — optimizar solo si el
  perfilado en proyectos grandes muestra que es necesario.

---

## 2.5. Discovery de archivos: excludes, symlinks, encoding

Cambios acordados tras revisar el escenario en detalle — afectan a
`discover_files` de cualquier `LanguageAdapter`, no solo Python.

### Excludes combinados de tres orígenes

```python
def load_exclude_spec(root: Path, cli_exclude: list[str]) -> pathspec.PathSpec:
    patterns = []
    if (root / ".gitignore").exists():
        patterns += (root / ".gitignore").read_text().splitlines()
    if (root / ".unskeinignore").exists():
        patterns += (root / ".unskeinignore").read_text().splitlines()
    patterns += cli_exclude
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
```

`.gitignore` + `.unskeinignore` (nuevo) + `--exclude` se **combinan** (unión
de patrones), ninguno pisa a otro. `.unskeinignore` cubre el caso de código
versionado en git que se quiere excluir solo del análisis (ej. código
generado que sí vive en el repo).

### Symlinks: no seguir por defecto

`Path.rglob()` sigue symlinks siempre en Python 3.12 (el parámetro para
desactivarlo no existe hasta 3.13, y el mínimo del proyecto es 3.12) — por
eso el discovery usa `os.walk` en su lugar, con control explícito:

```python
def discover_files(
    root: Path, exclude_spec: pathspec.PathSpec, follow_symlinks: bool = False,
) -> Iterator[Path]:
    visited_real_dirs: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        real = Path(dirpath).resolve()
        if real in visited_real_dirs:
            dirnames.clear()  # ya visitado por otra ruta simbólica — corta el descenso
            continue
        visited_real_dirs.add(real)
        for fname in filenames:
            if fname.endswith(".py"):
                rel_path = Path(dirpath, fname).relative_to(root)
                if not exclude_spec.match_file(str(rel_path)):
                    yield Path(dirpath, fname)
```

Dos riesgos distintos que esto evita:
- **Bucle infinito:** un symlink que apunta a un ancestro suyo (directo o en
  cadena) crea un ciclo de recorrido sin fin.
- **Fuga de alcance:** un symlink que apunta fuera del proyecto (otro repo, un
  venv compartido) haría que se analice código que el usuario no consideraba
  parte de "su proyecto".

**Default: `follow_symlinks=False`** — opción segura, sin fuga de alcance ni
riesgo de ciclo. `--follow-symlinks` la activa explícitamente para quien
tenga symlinks legítimos dentro de su propio proyecto (monorepos con paquetes
compartidos). `visited_real_dirs` es defensa en profundidad incluso con
symlinks activados — corta cualquier ciclo aunque `followlinks=True`.

### Detección de encoding por archivo

```python
import tokenize

def detect_encoding(file_path: Path, config_default: str | None) -> str:
    try:
        with open(file_path, "rb") as f:
            encoding, _ = tokenize.detect_encoding(f.readline)
        return encoding
    except SyntaxError:
        return config_default or "utf-8"
```

`tokenize.detect_encoding` es stdlib y ya implementa PEP 263 (encoding cookie
`# -*- coding: ... -*-`) y detección de BOM — no hace falta reinventar el
parser de la cookie. `--encoding` / `.unskein.toml` (`[analysis]
default_encoding`) es solo el *fallback* para cuando el archivo no declara
cookie y la detección automática falla — nunca fuerza un encoding sobre un
archivo que ya lo declara explícitamente.

## 3. Parser de Python (`parsers/python_parser.py`)

Implementación concreta de `LanguageAdapter` usando `ast` de la stdlib.
`PythonAdapter(config: AnalysisConfig)` recibe la config por constructor, así
`parse(files, root)` mantiene la firma del contrato común.

- **`discover_files`**: `os.walk` (ver sección 2.5). El código de tests se
  excluye por defecto (`tests/`, `test/`, `test_*.py`, `*_test.py`,
  `conftest.py`) porque infla el `Ca` de casi todo el proyecto;
  `--include-tests` / `include_tests = true` lo reactiva.
- **`normalize_module_name`**: dotted-path relativo a la *source root* más
  específica que contenga el archivo, colapsando `__init__.py` al nombre del
  paquete. Source roots: `[analysis] source_roots` en `.unskein.toml`; sin
  config, se auto-detecta `src/` (directorio `src` sin `__init__.py`). El root
  del proyecto es siempre la raíz de respaldo — `src/pkg/core.py` →
  `pkg.core`, `scripts/run.py` → `scripts.run`. Las rutas se normalizan con
  `os.path.abspath`, no `resolve()`: un symlink seguido conserva su nombre
  dentro del proyecto.
- **`parse`**: calcula primero los nombres de todos los archivos
  (`ProjectIndex`), luego llama `parse_file(path, name, index, config)` por
  archivo — función de módulo pura y picklable, unidad de trabajo del futuro
  `ProcessPoolExecutor`. `ast.walk` captura:

  | Caso | `target` | `symbol_name` |
  |---|---|---|
  | `import a.b.c` | prefijo más largo existente en el proyecto | `None` |
  | `from a.b import c`, `a.b.c` es módulo | `a.b.c` | `None` |
  | `from a.b import X`, `X` es símbolo | `a.b` | `X` |
  | relativo (`from ..m import X`) | resuelto con `node.level` desde el paquete del archivo | igual |
  | `from x import *` | `x` + warning | `None` |

  Import interno inexistente → ancestro existente más cercano + warning (o se
  omite con warning si no hay ninguno, p. ej. namespace packages). Relativo
  más allá del paquete raíz → warning, se omite. Auto-import → sin arista.
- **Detección de re-exports**: solo en `__init__.py`, cada `ImportFrom`
  interno de un *símbolo* (no de un submódulo) genera
  `ReExport(paquete, módulo_origen, asname or name)`. Con alias, la cadena se
  sigue con el nombre exportado: si un eslabón posterior re-exporta con otro
  nombre, la resolución se detiene en el módulo intermedio.
- **Errores por archivo** → warning, el archivo se omite y el análisis sigue:
  tamaño > `max_file_size_bytes` (ni se lee), `OSError`, `SyntaxError`
  (incluye bytes nulos desde 3.12), `UnicodeDecodeError`, `RecursionError`.

Limitaciones conocidas, documentadas explícitamente (no bugs a "arreglar" sin
discutirlo primero):
- `ast.walk` no distingue nivel de anidamiento — un import dentro de una
  función se trata igual que uno a nivel de módulo. Aceptable para v0.1;
  un `NodeVisitor` completo permitiría marcar imports condicionales
  (`TYPE_CHECKING`, `try/except ImportError`) en v0.2.
- **Star-imports (`from x import *`) no resuelven re-exports** — sin ejecutar
  el código o inspeccionar `__all__`, no se puede saber con certeza qué
  símbolos exporta un `*`. Se genera un warning explícito, nunca falla
  silenciosamente.
- **Imports dinámicos vía `importlib.import_module()` con strings son
  invisibles** — limitación conocida y común en análisis estático puro.
- **Warnings en inglés** — `ParseResult.warnings` son strings sin traducir.
  El i18n completo requiere warnings estructurados (`code` + `detail`)
  traducidos en la capa de reporte; se hace junto con `report/markdown.py`.

---

## 3.5. Modelo de concurrencia y paralelización

Aplica principalmente a la etapa de parseo (la más costosa en CPU), pero el
diseño de colas por etapa cubre todo el pipeline `parse → resolve → metrics`.

### Umbral configurable, no paralelización incondicional

```python
@dataclass
class AnalysisConfig:
    parallel_threshold: int = 50           # archivos; por debajo, secuencial
    max_workers: int | None = None         # None = os.cpu_count()
    queue_maxsize: int = 200               # archivos "en vuelo" como máximo
    max_file_size_bytes: int = 5 * 1024 * 1024   # 5 MB; se salta con warning
    per_file_timeout_seconds: int = 30     # por archivo, al recoger resultados
```

Por debajo de `parallel_threshold`, el overhead de arrancar
`ProcessPoolExecutor` (serialización, spawn de procesos) supera la ganancia —
proyectos pequeños se parsean secuencial.

La decisión de paralelizar está aislada en una función propia, no inline en
`parse_all`, para que la lógica pueda volverse adaptativa sin tocar el resto
del pipeline:

```python
def should_parallelize(file_count: int, config: AnalysisConfig) -> bool:
    """v0.1: umbral fijo. v0.2+: podría considerar núcleos disponibles,
    tamaño total en bytes de los archivos, tiempos medidos en análisis
    previos, etc. — el contrato con parse_all no cambia."""
    return file_count >= config.parallel_threshold

def parse_all(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig,
) -> ParseResult:
    if not should_parallelize(len(files), config):
        return adapter.parse(files, root)
    return _parse_parallel(files, adapter, root, config)
```

### Por qué `ProcessPoolExecutor` y no free-threading

Python 3.14 soporta oficialmente builds sin GIL (free-threaded, PEP 779), lo
que en teoría sería una alternativa más liviana que procesos separados para
paralelizar el parseo de archivos (evita el overhead de serialización entre
procesos). **Se descarta para v0.1** porque el ecosistema de wheels de
extensiones en C (`pydantic-core`, y el futuro `tree-sitter` para v0.3+) no
tiene todavía soporte confiable para el ABI `cp314t`. `ProcessPoolExecutor`
funciona igual en cualquier Python `>=3.12` sin depender de esa madurez.
Reevaluar cuando el ecosistema esté más consolidado — no antes.

### Cola única compartida, no sharding por hash

Para repartir archivos entre workers de una misma etapa, se usa **una cola
única compartida** (`queue.Queue` acotada por `queue_maxsize`), no
sharding estático por hash del path.

Razón: con archivos de tamaño/costo desigual, el sharding por hash puede
producir el "efecto straggler" — si por azar del hash varios archivos costosos
caen en la misma partición, ese worker se vuelve cuello de botella mientras el
resto termina y queda ocioso. Una cola compartida se autobalancea
dinámicamente: cualquier worker libre toma el siguiente archivo, sin importar
cuán desigual sea el costo de cada uno.

```python
def _parse_parallel(
    files: Iterator[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig,
) -> ParseResult:
    work_queue: queue.Queue[Path | None] = queue.Queue(maxsize=config.queue_maxsize)
    # el productor bloquea al llenar la cola — esto ES el backpressure,
    # evita materializar miles de Path en memoria de una sola vez
    ...
```

### Colas por etapa del pipeline (estilo SEDA)

En vez de una sola cola global, cada etapa (`parse`, `resolve`, `metrics`)
tiene su propia cola acotada de entrada y su propio `StageConfig`,
dimensionado según su naturaleza:

```python
@dataclass
class StageConfig:
    max_workers: int | None = None
    queue_maxsize: int = 200

@dataclass
class PipelineConfig:
    parse: StageConfig = field(default_factory=lambda: StageConfig(max_workers=None))   # CPU-bound
    resolve: StageConfig = field(default_factory=lambda: StageConfig(max_workers=2))     # liviano
    metrics: StageConfig = field(default_factory=lambda: StageConfig(max_workers=1))     # NetworkX no paraleliza bien internamente
```

Esto desacopla el ritmo de cada etapa de la siguiente: si el cálculo de
métricas es más lento que el parseo, su propia cola absorbe el backpressure
sin bloquear que el parseo siga avanzando (hasta que esa cola se llena).

### Qué se descarta explícitamente en v0.1, y por qué

- **Pub/sub real (bus de eventos, tópicos, múltiples suscriptores):** el
  proceso es de una sola pasada con un productor y un consumidor lógico por
  etapa — no hay múltiples suscriptores independientes reaccionando al mismo
  evento, que es lo que justificaría esa complejidad. Reconsiderar solo si se
  agrega un modo *watch* (re-análisis incremental al detectar cambios) o
  integración en vivo con un IDE, donde sí habría varios consumidores
  (terminal, IDE, log) reaccionando a los mismos eventos.
- **Hash-sharding para distribuir carga:** diferido explícitamente a una
  eventual arquitectura distribuida en contenedores, donde el hash decidiría
  qué *nodo/contenedor* procesa qué archivos (típicamente sobre una cola
  externa como Redis o SQS, no una `queue.Queue` en memoria) — útil ahí para
  afinidad (mismo archivo siempre al mismo nodo, aprovechando caché local por
  proceso) o para anclar reintentos. No aporta nada sobre una cola compartida
  local, y no se diseña v0.1 anticipando esa arquitectura.

### Archivos anómalos: tamaño, timeout, recursión profunda

Análisis detallado de tres riesgos distintos que un archivo individual
patológico puede introducir, y su mitigación:

**A — `RecursionError` en AST profundamente anidado.** `ast.NodeVisitor` (y
`ast.walk`) son recursivos internamente. Código generado (o algo patológico,
expresiones anidadas miles de niveles) puede agotar el límite de recursión.
Mitigación: capturar `RecursionError` junto con `SyntaxError` /
`UnicodeDecodeError` en el mismo bloque de manejo de errores de
`_extract_imports` — se trata como warning de parseo de ese archivo, no
como crash del comando completo:

```python
try:
    imports = self._extract_imports(tree, module_name, project_modules)
except (SyntaxError, RecursionError, UnicodeDecodeError) as e:
    warnings.append(f"No se pudo parsear {file_path}: {e}")
    continue
```

**B — archivo desproporcionadamente grande** (generado, minificado, vendored).
Parsearlo consume tiempo/memoria sin aportar señal real de arquitectura —
nadie diseña acoplamiento en un bundle generado. Mitigación:
`max_file_size_bytes` (default 5 MB, configurable) — archivos que lo superan
se saltan con warning explícito, **ni siquiera se leen**:

```python
if file_path.stat().st_size > config.max_file_size_bytes:
    warnings.append(f"Archivo {file_path} excede max_file_size_bytes, se omite")
    continue
```

**C — cuelgue de un worker individual sin timeout.** Con la cola compartida
(no sharding), un archivo pesado ralentiza solo a su propio worker — el resto
sigue tomando trabajo sin bloquearse. Pero si algo se cuelga de verdad (bug
real del parser en un caso extremo), ese worker nunca libera su slot.
Mitigación: `per_file_timeout_seconds` al recoger resultados del
`ProcessPoolExecutor`:

```python
try:
    result = future.result(timeout=config.per_file_timeout_seconds)
except concurrent.futures.TimeoutError:
    warnings.append(f"Timeout parseando {file_path}, se omite")
```

Ningún caso de los tres debe tumbar el análisis completo del resto del
proyecto — mismo principio que ya rige para `SyntaxError`/`UnicodeDecodeError`
desde el diseño original del parser.

## 4. Grafo y métricas (`graph/builder.py`, `graph/metrics.py`)

Toma el `ParseResult` ya resuelto (imports normalizados, re-exports
aplicados) y construye el grafo real.

- **Construcción del grafo**: `networkx.DiGraph`. Solo contiene módulos
  internos del proyecto como nodos — las dependencias externas ya cumplieron
  su función en `is_external` y no aportan valor en el grafo de acoplamiento.
- **Métricas de acoplamiento** (por módulo):
  - `Ca` (acoplamiento aferente) = `in_degree` — cuántos módulos dependen de este.
  - `Ce` (acoplamiento eferente) = `out_degree` — de cuántos módulos depende este.
  - `Instability = Ce / (Ca + Ce)`, rango `[0, 1]`.
  - Interpretación: I cercana a 1 = módulo de orquestación/aplicación
    (depende de muchos, nadie depende de él). I cercana a 0 = módulo
    core/utilidad (muy dependido, no depende de nada). Ninguno es "malo" por
    sí solo — lo problemático es Ca y Ce altos simultáneamente, o un módulo
    core que cambia con frecuencia.
- **Detección de ciclos**: `nx.simple_cycles(graph)`. En grafos muy densos el
  número de ciclos puede crecer exponencialmente — cortar tras encontrar los
  primeros ~100 ciclos para evitar cuelgues en codebases patológicos.
- **"God modules" / alto acoplamiento**: percentil superior (default 90%) de
  `Ca + Ce` combinado, como candidatos que la capa de IA interpretará.

Output consolidado (`AnalysisResult`): `graph`, `coupling_metrics`, `cycles`,
`high_coupling_modules`, `parse_warnings`. Este objeto es el punto de unión
entre el análisis determinista y la interpretación por IA/reporte.

---

## 5. Pipeline de IA (`ai/client.py`, `ai/prompts.py`)

Principio rector: **el LLM interpreta agregados y casos destacados, nunca el
grafo completo** (problema de tamaño de contexto y costo).

### Serialización acotada

```python
@dataclass
class AIContext:
    total_modules: int
    total_dependencies: int
    cycles: list[list[str]]          # truncado (default: primeros 20)
    top_coupled_modules: list[dict]  # solo los N peores (default: 15)
    parse_warnings: list[str]        # truncado (default: 10)
```

Si se trunca, el reporte final debe decirlo explícitamente ("mostrando N de M
totales") — nunca ocultar silenciosamente que hay más.

### Salida estructurada (Pydantic)

```python
class Problem(BaseModel):
    severity: str   # "low" | "medium" | "high"
    title: str
    description: str
    affected_modules: list[str]
    recommendation: str
    code_snippet: str | None = None   # siempre None en v0.1 — snippets son v0.2

class AIReport(BaseModel):
    summary: str
    architecture_health: str   # "good" | "fair" | "concerning"
    problems: list[Problem]
```

### Cliente — vía LiteLLM, agnóstico de proveedor

```python
@dataclass
class AIConfig:
    model: str
    api_key: str | None = None
    api_base: str | None = None
```

`fallback_models`, `max_retries` y `timeout_seconds` se eliminaron
deliberadamente de `AIConfig` — LiteLLM gestiona fallback entre modelos,
reintentos y timeout de forma transparente (vía su propio Router o un
`config.yaml` de proxy). `unskein` solo pasa `model`, `api_key`, `api_base`.

```python
class AIClient:
    def __init__(self, config: AIConfig):
        self.config = config

    def generate_report(self, context: AIContext) -> AIReport | None:
        prompt = build_prompt(context)
        try:
            response = litellm.completion(
                model=self.config.model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        except litellm.exceptions.APIError as e:
            logger.warning(f"Fallo en análisis de IA: {e}")
            return None
        return self._parse_and_validate(response)

    def _parse_and_validate(self, response) -> AIReport | None:
        raw = response.choices[0].message.content
        try:
            return AIReport.model_validate_json(raw)
        except ValidationError:
            extracted = extract_json_block(raw)  # busca ```json ... ``` o { ... }
            if extracted:
                try:
                    return AIReport.model_validate_json(extracted)
                except ValidationError as e:
                    logger.warning(f"Respuesta del modelo no cumple el schema: {e}")
            return None
```

**Nota importante sobre modelos económicos (Ollama/HuggingFace):** el soporte
de `response_format`/JSON mode varía mucho según el modelo. Reforzar incluyendo
el JSON schema completo *dentro del prompt* además del parámetro de API, y
mantener el fallback de extracción de JSON embebido — con estos modelos va a
activarse con más frecuencia que con modelos grandes de proveedores cloud.

### System prompt

Debe instruir explícitamente a no inventar información no presente en los
datos, y a declarar cuando los datos son insuficientes para una conclusión —
sin esto, el LLM tiende a rellenar con "buenas prácticas" genéricas sin
relación con el proyecto real analizado.

### Gestión de costo

LiteLLM expone `success_callback` para trackear costo por llamada
(`litellm.completion_cost`). Usarlo para logging local de costo acumulado, en
vez de implementar tracking propio.

### Degradación

Si falla la config (`load_ai_config` devuelve `None`), la llamada, o la
validación del schema, el reporte se genera igual sin la sección de IA, con
aviso claro. **Nunca** debe caerse el comando completo por un fallo del LLM.

---

## 5.5. Internacionalización (i18n)

Español + inglés desde v0.1, con soporte completo: CLI, reporte, y las
respuestas generadas por el LLM.

### Diccionario simple, no `gettext`

Con solo 2 idiomas, un diccionario Python es más simple de mantener y testear
que catálogos `.mo`/`gettext` (pensado para decenas de idiomas):

```python
# unskein/i18n.py
from enum import Enum

class Lang(str, Enum):
    ES = "es"
    EN = "en"

STRINGS: dict[str, dict[Lang, str]] = {
    "no_files_found": {
        Lang.ES: "No se encontraron archivos .py en '{path}'",
        Lang.EN: "No .py files found in '{path}'",
    },
    "ai_config_missing": {
        Lang.ES: "No se encontró configuración de IA, generando reporte sin sección de IA",
        Lang.EN: "No AI configuration found, generating report without AI section",
    },
    # ... resto de mensajes de CLI y reporte
}

def t(key: str, lang: Lang, **kwargs) -> str:
    return STRINGS[key][lang].format(**kwargs)
```

### Detección del idioma

Misma jerarquía de configuración que el resto del proyecto: env var
(`UNSKEIN_LANG`) → `.unskein.toml` (`[general] lang = "es"`) → flag `--lang`.
Si nada está configurado, se usa `locale.getlocale()`; si no es `es*`,
**default a inglés** — más seguro para adopción OSS amplia, no asumir que
quien instala el CLI habla español.

### Impacto en el pipeline de IA

`build_prompt` recibe el idioma y lo incluye como instrucción explícita en el
`SYSTEM_PROMPT` — el LLM debe generar `AIReport.summary` y
`Problem.description` en el idioma seleccionado, no solo el CLI/reporte:

```python
def build_prompt(context: AIContext, lang: Lang) -> str:
    lang_instruction = {
        Lang.ES: "Responde en español.",
        Lang.EN: "Respond in English.",
    }[lang]
    return f"{lang_instruction}\n\n" + _build_prompt_body(context)
```

El `SYSTEM_PROMPT` base (instrucción de no inventar información, declarar
insuficiencia de datos) se mantiene igual en ambos idiomas — solo cambia el
idioma de salida esperado, no el criterio de análisis.

## 6. Reporte (`report/markdown.py`)

Combina `AnalysisResult` (siempre presente) y `AIReport | None` en un único
string Markdown, reutilizado tanto para salida a terminal (renderizado con
`rich.markdown.Markdown`) como para archivo (`-o/--output`, escritura cruda).

Estructura del reporte:

```
# Análisis de <proyecto>
## Resumen                          (con o sin IA — nunca vacío)
## Métricas generales
## Ciclos de dependencia
## Módulos con mayor acoplamiento   (tabla, top 15, con nota de truncado)
## Problemas señalados (IA)         (omitida solo si no hay AIReport; con aviso)
## Advertencias del análisis        (solo si hay parse_warnings)
```

Reglas:
- El "no hay IA" nunca es un hueco vacío ni un error crudo — siempre da un
  resumen basado en números + sugerencia de cómo obtener más (quitar
  `--no-ai`).
- `--min-severity` se aplica en esta capa (filtrando `ai_report.problems`
  antes de renderizar), no se le pide al LLM que filtre — mantiene la
  generación de IA independiente de la presentación.
- Sin lógica de negocio en las funciones de renderizado, solo formateo — la
  interpretación ya viene resuelta desde `graph/builder.py` o `AIReport`.

---

## 7. CLI (`cli.py`)

Framework: `typer` (type hints, genera `--help` automático).

Comando único en v0.1: `unskein scan <path> [opciones]`.

Flags:

| Flag | Propósito |
|---|---|
| `<path>` (posicional) | Directorio a analizar (default: `.`) |
| `--no-ai` | Omite la interpretación con IA |
| `--exclude <patrón>` | Excluir rutas adicionales (repetible) |
| `--min-severity <nivel>` | Filtrar problemas por severidad (low/medium/high) |
| `--verbose` / `-v` | Progreso detallado del análisis |
| `-o, --output <archivo>` | Guardar reporte en archivo en vez de solo imprimir |
| `--api-key` | API key vía flag (documentado como inseguro) |
| `--version` | Versión del CLI |

Orquestación separada del decorador de `typer` (`run_scan`, testeable sin
invocar el CLI completo; reutilizable como librería más adelante):

```
run_scan:
  1. valida que <path> existe
  2. adapter = PythonAdapter()  # hardcodeado en v0.1, único lenguaje
  3. discover_files → parse → resolve_indirection
  4. analyze() → AnalysisResult
  5. si no --no-ai: load_ai_config() → AIClient.generate_report()
     (config ausente o fallo de IA → ai_report = None, se continúa igual)
  6. filtra por --min-severity si aplica
  7. devuelve (AnalysisResult, AIReport | None) a output_report()
```

`load_ai_config` implementa la jerarquía de configuración (env var → `.unskein.toml`
→ flag `--api-key`), devolviendo `None` si no hay modelo configurado en
ninguna capa.

Manejo de errores: `UnskeinError` para casos de uso esperados (ruta inválida,
sin archivos Python) → mensaje limpio sin traceback. Cualquier excepción no
capturada (bug real) debe dejar el traceback visible — no tragarse errores
reales detrás de un mensaje genérico.

---

## 7.5. Logging, códigos de salida y telemetría

### Logging: `logging` estándar, consola + archivo opcional

```python
import logging

def setup_logging(verbose: bool, log_file: Path | None) -> logging.Logger:
    logger = logging.getLogger("unskein")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(message)s"))  # limpio en terminal
    logger.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)

    return logger
```

Consola siempre activa; archivo solo con `--log-file <ruta>` (flag nuevo,
nadie escribe a disco sin pedirlo explícitamente). **La API key nunca aparece
en ningún log, en ningún handler, en ningún nivel** — regla ya establecida
para la config de IA, sin excepción aquí tampoco.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | Análisis completado, sin problemas de severidad ≥ `--min-severity` |
| `1` | Error de uso (ruta inválida, sin archivos `.py`, config inválida) |
| `2` | Análisis completado, con problemas de severidad `high` encontrados |
| `3` | Error interno inesperado (bug real — traceback completo visible) |

```python
app = typer.Typer(
    add_completion=False,
    epilog="Códigos de salida: 0=OK, 1=error de uso, 2=problemas de severidad alta, 3=error interno.",
)
```

`run_scan` determina el código según el resultado (`UnskeinError` → 1,
`ai_report` con algún `Problem.severity == "high"` → 2, excepción no
capturada → 3 con traceback completo, éxito limpio → 0). Útil para quien
quiera scriptear `unskein` por su cuenta, aunque v0.1 no es un gate de CI
dedicado.

### Telemetría: ninguna de uso, solo rendimiento local

Cero telemetría de uso — nada sale del equipo del usuario, ni siquiera
anónimo. Declarado explícitamente en el README, sección de privacidad.

Medición de rendimiento (duración, pico de memoria) es **local y solo
informativa**, mostrada al propio usuario con `--verbose`, nunca enviada a
ningún servidor:

```python
import psutil
import time
from dataclasses import dataclass

@dataclass
class PerformanceStats:
    duration_seconds: float
    peak_memory_mb: float

def measure(fn):
    process = psutil.Process()
    start = time.perf_counter()
    result = fn()
    duration = time.perf_counter() - start
    peak_mb = process.memory_info().rss / (1024 * 1024)
    return result, PerformanceStats(duration, peak_mb)
```

`psutil` en vez de `resource` (stdlib, pero solo Unix) — necesario porque el
soporte de rendimiento es **Windows + Linux/macOS** desde v0.1, no solo Unix.

## Notas sobre extensión futura (no implementar en v0.1)

- **Multi-lenguaje**: el punto de selección dinámica del adapter (por
  extensión de archivo o flag `--lang`) es exactamente donde hoy está
  `adapter = PythonAdapter()` hardcodeado en `run_scan`. Al agregar TS/Java,
  introducir un registro/factory ahí.
- **`tree-sitter`** se adopta recién al implementar el segundo lenguaje, no
  antes — Python usa `ast` de la stdlib en v0.1 sin necesidad de esa capa.
- **Snippets de código en recomendaciones de IA** (v0.2): requiere pasarle al
  LLM fragmentos reales de código (no solo grafo/métricas), lo que aumenta
  contexto y costo, y exige decidir cómo validar que el snippet propuesto
  tiene sentido.
- **CVE y mapa de arquitectura completo**: fase 2, sin diseño aún.
- **Free-threading (`cp314t`)** como alternativa a `ProcessPoolExecutor`: solo
  cuando el ecosistema de wheels de extensiones en C (pydantic-core,
  tree-sitter) tenga soporte confiable — no antes.
- **Hash-sharding para distribución en contenedores**: ver sección 3.5. Es una
  arquitectura de concurrencia distinta (multi-nodo, cola externa) a la de
  v0.1 (proceso único, colas en memoria) — no diseñar v0.1 anticipándola.

## Versión de Python y criterio de estilo

- **Mínimo soportado: `>=3.12`. Desarrollo/CI principal: 3.14.** No se asume
  free-threading en el diseño de v0.1 (ver sección 3.5).
- **Funcional para composición entre capas, imperativo en bucles calientes.**
  El flujo `discover → parse → resolve → analyze` se escribe como composición
  de funciones puras. Dentro de cada capa, en bucles sobre miles de
  nodos/edges (`ast.walk`, métricas por módulo), usar bucles explícitos o
  comprensiones — no cadenas de `map`/`filter`/`reduce` con lambdas. En
  CPython el estilo funcional puro no reduce RAM ni mejora rendimiento por sí
  solo (esa ventaja existe en lenguajes con compilación nativa, no en un
  intérprete de bytecode).
- **Técnicas de reducción de memoria a aplicar donde corresponda:**
  generadores (`Iterator[Path]`) en vez de listas materializadas,
  `@dataclass(slots=True)` en estructuras instanciadas en masa (`ImportEdge`,
  `ModuleInfo`), `itertools` para composición sin overhead de lambdas
  anidadas.

## Testing (decisión revertida: desde el inicio, no pospuesto)

Una versión anterior de este documento pospuso el diseño de tests. Se revirtió:
**testing desde el primer commit**, con `pytest` + `pytest-cov`, en CI contra
Python 3.12/3.13/3.14.

```
tests/
├── unit/
│   ├── test_python_parser.py
│   ├── test_reexport_resolution.py
│   ├── test_graph_metrics.py
│   └── test_report_markdown.py
├── integration/
│   └── test_cli_scan.py          # invoca `scan` end-to-end sobre fixtures reales
└── fixtures/
    ├── simple_project/            # proyecto sin ciclos, caso feliz
    ├── circular_imports/           # ciclo directo A→B→A
    ├── reexport_chain/             # __init__.py con re-exports multinivel
    └── reexport_cycle/             # ciclo de re-exports (warning de profundidad)
```

Sin umbral de cobertura numérico rígido desde el día uno (incentiva tests
vacíos solo para subir el número) — se revisa como señal, no como gate
automático, hasta que el proyecto tenga más rodaje.

## Empaquetado y plantilla OSS

- Build backend: `hatchling` (estándar actual para layout `src/`).
- Versionado semver desde `0.1.0`; `CHANGELOG.md` formato *Keep a Changelog*.
- Publicación a PyPI vía **Trusted Publishing** (OIDC desde GitHub Actions,
  sin token de PyPI almacenado como secreto — misma filosofía de higiene de
  credenciales que la API key del LLM).
- Plantilla estándar OSS con licencia MIT: `README.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md` (Contributor Covenant), `SECURITY.md`,
  `.github/ISSUE_TEMPLATE/` (bug report + feature request),
  `.github/PULL_REQUEST_TEMPLATE.md`, workflows de CI/release en
  `.github/workflows/`.
