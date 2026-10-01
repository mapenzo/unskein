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

## 1. El adapter (`parsers/base.py`, `parsers/models.py`)

Contrato común para que cualquier lenguaje (Python en v0.1, TS/Java después)
se integre al pipeline sin reescribirlo. Los datos (`ImportEdge`,
`ModuleInfo`, `ReExport`, `ParseResult`) viven en `parsers/models.py`, sin
dependencias; `parsers/base.py` solo contiene `LanguageAdapter`. Así
`indirection.py` depende de `models` y `base` de ambos, sin ciclo (antes
`base` ↔ `indirection` se importaban mutuamente — unskein lo detectaba en
su propio código).

```python
# parsers/models.py
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
    warnings: list[ParseWarning] = field(default_factory=list)

class WarningCode(StrEnum):
    STAR_IMPORT, RELATIVE_BEYOND_TOP, UNRESOLVED_IMPORT, FILE_TOO_LARGE,
    PARSE_ERROR, PARSE_TIMEOUT, REEXPORT_CYCLE, REEXPORT_DEPTH_EXCEEDED

@dataclass(frozen=True, slots=True)
class ParseWarning:
    code: WarningCode
    path: Path | None   # None en problemas de proyecto (ciclos de re-export)
    line: int | None
    detail: str         # dato técnico neutro de idioma, nunca una frase traducida

# parsers/base.py
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
    def plan_parse(self, files: list[Path], root: Path) -> ParsePlan: ...
    # ParsePlan(tasks=[(path, nombre)], shared=...): las tareas en el orden en que
    # se combinan los resultados, y lo que todas comparten (el índice de módulos).

    @abstractmethod
    def parse_task(self, task: ParseTask, shared: Any) -> FileParseResult: ...
    # Pura y serializable: es la unidad de trabajo de un worker.

    def parse(self, files: list[Path], root: Path) -> ParseResult:
        """Secuencial, construido sobre plan_parse + parse_task (un solo camino)."""

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
- Los warnings son **estructurados** (`ParseWarning`: `code` + `path` +
  `line` + `detail`), no strings: el reporte los traduce a ES/EN a partir del
  `code` y los agrupa por tipo (un proyecto con 264 star imports muestra una
  línea, no 264). `detail` solo lleva datos neutros de idioma (nombres de
  módulo, tamaños, texto de la excepción). `frozen` → hashables, así la
  deduplicación de `resolve_indirection` sigue funcionando.
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
    index: ReExportIndex = {}
    for re_export in re_exports:  # orden de código: el primero gana
        index.setdefault((re_export.exporting_module, re_export.symbol_name), re_export.original_module)
    return index

def resolve_target(
    module: str, symbol: str | None, index: ReExportIndex, path: list[str] | None = None,
) -> tuple[str, list[str]]:
    if path is None:
        path = []

    if symbol is None or (module, symbol) not in index:
        return module, []
    if module in path:
        members = ", ".join(sorted(path[path.index(module):]))
        detail = f"{symbol}: {members}"
        return module, [ParseWarning(WarningCode.REEXPORT_CYCLE, None, None, detail)]
    if len(path) >= MAX_RESOLUTION_DEPTH:
        detail = f"{symbol}: {module}"
        return module, [ParseWarning(WarningCode.REEXPORT_DEPTH_EXCEEDED, None, None, detail)]

    path.append(module)
    return resolve_target(index[(module, symbol)], symbol, index, path)
```

`resolve_indirection(result) -> ParseResult` aplica `resolve_target` a cada
arista **interna con símbolo** y devuelve un `ParseResult` nuevo (función
pura, no muta la entrada):
- Externos e imports de módulo completo (`symbol_name is None`) quedan igual.
- Las aristas de la propia fachada también se resuelven (`app/__init__` →
  módulo que define el símbolo): la fachada depende realmente de él.
- Si la resolución termina en el propio módulo origen, la arista se descarta
  (igual que los auto-imports en el parser).
- Warnings deduplicados y añadidos tras los del parser. El warning de ciclo
  es **canónico**: nombra el símbolo y los miembros del ciclo ordenados (se
  guarda el camino como `list`, no `set`, para saber dónde empieza el ciclo),
  así cualquier punto de entrada al mismo ciclo produce el mismo texto → un
  único warning por ciclo.

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
    visited_directories: set[Hashable] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if follow_symlinks:
            identity = _directory_identity(dirpath)  # (st_dev, st_ino)
            if identity in visited_directories:
                dirnames.clear()  # ya visitado por otra ruta simbólica — corta el descenso
                continue
            visited_directories.add(identity)
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

### Poda de directorios excluidos

`walk_files` no entra en los directorios que el spec de excludes ya descarta
(`.venv/`, `build/`, `tests/`…): antes de iterar los archivos de cada directorio
quita de `dirnames` los subdirectorios cuya ruta relativa + `/` casa con el spec. Así
el coste del descubrimiento depende del contenido **analizado**, no del ignorado (un
`.venv/` con miles de archivos pasaba de ~300 ms a una fracción).

Semántica de git para las negaciones: un directorio excluido nunca se re-incluye,
así que con `build/` y `!build/keep.py`, `build/keep.py` **no** se analiza. Los
patrones que solo afectan a archivos no podan nada; los archivos se siguen filtrando
uno a uno.

**Default: `follow_symlinks=False`** — opción segura, sin fuga de alcance ni
riesgo de ciclo. `--follow-symlinks` la activa explícitamente para quien
tenga symlinks legítimos dentro de su propio proyecto (monorepos con paquetes
compartidos). La detección de ciclos por directorio real visitado es defensa en
profundidad y **solo corre con `--follow-symlinks`**: sin seguir symlinks los
bucles son imposibles y se ahorra una llamada por directorio (con `resolve()`, ~120
de los ~265 ms de Django). Se identifica el directorio por `(st_dev, st_ino)` de
`os.stat` (que sigue el enlace, como `resolve`, pero más barato); si el sistema de
archivos no da inodos (`st_ino == 0`), cae a la ruta resuelta para que todos los
directorios no parezcan el mismo.

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
  `ProcessPoolExecutor`. `iter_statements` (recorrido en profundidad, en orden de
  código, solo por listas de sentencias) captura:

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
  nombre, la resolución se detiene en el módulo intermedio. Si un facade expone
  el mismo símbolo más de una vez (típico: `try: from ._fast import X` /
  `except ImportError: from ._slow import X`), **gana el primero en el código**.
  Los imports se recorren en profundidad y en orden de código, así que los avisos
  de un archivo también salen en ese orden.
- **Errores por archivo** → warning, el archivo se omite y el análisis sigue:
  tamaño > `max_file_size_bytes` (ni se lee; `FILE_TOO_LARGE`, detail
  `"<tamaño> > <límite>"`), `OSError`, `SyntaxError` (incluye bytes nulos
  desde 3.12; `line` = línea del error), `UnicodeDecodeError`,
  `RecursionError` (todos `PARSE_ERROR`, detail `"<Excepción>: <mensaje>"`).
- **`detail` por código**: `STAR_IMPORT` → módulo base; `UNRESOLVED_IMPORT`
  → `"nombre -> ancestro"` o solo `"nombre"` si se omitió;
  `RELATIVE_BEYOND_TOP` → el relativo tal cual (`"...m"`);
  `REEXPORT_CYCLE` → `"Símbolo: m1, m2"` (miembros ordenados);
  `REEXPORT_DEPTH_EXCEEDED` → `"Símbolo: módulo"`.

Limitaciones conocidas, documentadas explícitamente (no bugs a "arreglar" sin
discutirlo primero):
- El recorrido (`iter_statements`) no distingue nivel de anidamiento — un import dentro de una
  función se trata igual que uno a nivel de módulo. Aceptable para v0.1;
  un `NodeVisitor` completo permitiría marcar imports condicionales
  (`TYPE_CHECKING`, `try/except ImportError`) en v0.2.
- **Star-imports (`from x import *`) no resuelven re-exports** — sin ejecutar
  el código o inspeccionar `__all__`, no se puede saber con certeza qué
  símbolos exporta un `*`. Se genera un warning explícito, nunca falla
  silenciosamente.
- **Imports dinámicos vía `importlib.import_module()` con strings son
  invisibles** — limitación conocida y común en análisis estático puro.

---

## 3.5. Modelo de concurrencia y paralelización

Aplica principalmente a la etapa de parseo (la más costosa en CPU), pero el
diseño de colas por etapa cubre todo el pipeline `parse → resolve → metrics`.

### Umbral configurable, no paralelización incondicional

```python
@dataclass
class AnalysisConfig:
    parallel_threshold: int = 500          # archivos; por debajo, secuencial
    max_workers: int | None = None         # None = min(os.cpu_count(), 8)
    queue_maxsize: int = 200               # archivos "en vuelo" como máximo
    max_file_size_bytes: int = 5 * 1024 * 1024   # 5 MB; se salta con warning
    per_file_timeout_seconds: int = 30     # por archivo, al recoger resultados
```

**Calibración del umbral (P4.4).** Medido en una máquina de 16 núcleos
(WSL2, Python 3.14) con networkx 3.4.2, Django 5.1.4 y sympy 1.13.3, tomando
los primeros *N* archivos de cada uno; speedup = secuencial / paralelo, mejor
de 3, con el resultado siempre idéntico al secuencial. `spawn` es el método de
Windows y, desde Python 3.14, también el coste aproximado de `forkserver`, el
default de Linux:

| Archivos | fork, 4 workers | spawn, 4 workers |
|---:|---|---|
| 50 | 0,5–0,9× | 0,04–0,12× |
| 100 | 0,6–1,7× | 0,06–0,36× |
| 200 | 0,9–2,1× | 0,22–0,41× |
| 300–400 | 1,8–2,2× | 0,6–1,6× |
| 365–891 (proyecto entero) | 1,9–2,9× | 1,0–2,6× |

Arrancar el pool con `spawn` cuesta unos 130 ms con 2 workers y unos 300 ms
con 16 (≈10 ms por worker), y el speedup deja de crecer pasados 4–8 workers
(Django, 875 archivos, `spawn`: 1,49× con 4 workers, 1,22× con 16). De ahí los
defaults: **umbral 500** (con el 50 anterior el paralelo era entre 2 y 40 veces
más lento en todo lo medido) y **tope de 8 workers** cuando `max_workers` no
está fijado. El número de archivos es un proxy tosco del coste real (Django y networkx
cuestan unos 0,5 ms por archivo y sympy 1,7 ms); `should_parallelize` es el punto
donde una decisión basada en bytes o en tiempos medidos podría sustituirlo.

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

El paralelo no usa una `queue.Queue` explícita, sino una **ventana deslizante
de lotes** con el mismo efecto: `_parse_in_pool` envía lotes de archivos al pool
y no deja más de `queue_maxsize` archivos en vuelo (backpressure: no se
materializa todo el trabajo de una vez). Cada worker toma el siguiente lote
libre, así que el autobalanceo es el mismo que el de una cola compartida. Los
resultados se recogen **en el orden de los archivos**, de modo que la salida es
idéntica a la secuencial (determinismo).

```python
plan = adapter.plan_parse(files, root)         # tareas + datos compartidos
with ProcessPoolExecutor(
    max_workers=worker_count(config),
    initializer=_init_worker,                  # variables de módulo del worker
    initargs=(adapter, plan.shared),           # el índice viaja UNA vez por worker
) as pool:
    results = _parse_in_pool(pool, batches, config)
```

- **El índice de módulos se serializa una vez por worker**, no por archivo.
  Enviarlo con cada tarea costaba 23 MiB en total en sympy y crecía de forma
  cuadrática con el proyecto.
- **Lotes** (`batch_size`): entre 1 y 32 archivos, unos 4 lotes por worker, sin
  superar `queue_maxsize`. Con un archivo por mensaje, el IPC añade ≈0,85 ms
  por archivo.
- **Un pool que muere** (`BrokenProcessPool`) no tumba el análisis: se avisa por
  el log y se vuelve a parsear en secuencial.

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

**C — cuelgue de un worker individual sin timeout.** Con lotes compartidos
(no sharding), un archivo pesado ralentiza solo a su propio worker — el resto
sigue tomando trabajo sin bloquearse. Mitigación: `per_file_timeout_seconds` al
recoger resultados, aplicado a cada lote como `timeout × archivos del lote`:

```python
try:
    return future.result(timeout=per_file_timeout_seconds * len(batch))
except TimeoutError:
    ...  # se reintenta el lote archivo por archivo para señalar al culpable
```

Al vencer el plazo de un lote, sus archivos se reenvían de uno en uno y solo
el que vuelve a vencer se omite, con un warning `PARSE_TIMEOUT` (detail = el
límite en segundos); el resto se analiza con normalidad.

**Limitación aceptada y documentada (decisión del mantenedor).** El timeout
solo deja de *esperar* el resultado: no puede cancelar un proceso que ya está
parseando. El worker sigue con ese archivo y, al cerrar el pool, se espera a que
termine, así que un archivo patológico de verdad puede retrasar el cierre del
análisis. Reciclar el proceso afectado (terminar y recrear el pool) resolvería
eso, pero es bastante más complejo y queda diferido. El plazo se cuenta desde
que se empieza a esperar el lote, no desde que empieza a ejecutarse, así que
solo puede ser más generoso que el nominal.

Ningún caso de los tres debe tumbar el análisis completo del resto del
proyecto — mismo principio que ya rige para `SyntaxError`/`UnicodeDecodeError`
desde el diseño original del parser.

## 4. Grafo y métricas (`graph/builder.py`, `graph/metrics.py`)

Toma el `ParseResult` ya resuelto (imports normalizados, re-exports
aplicados) y construye el grafo real.

- **Construcción del grafo**: `networkx.DiGraph`. Solo contiene módulos
  internos del proyecto como nodos — las dependencias externas ya cumplieron
  su función en `is_external` y no aportan valor en el grafo de acoplamiento.
  Son nodos también los módulos aislados (cuentan en el total con Ca=Ce=0) y
  los destinos internos cuyo archivo no se pudo parsear. Una arista por par
  importador/importado, con `weight` = número de sentencias de import. Nodos
  insertados en orden alfabético → recorridos y reportes deterministas.
- **Métricas de acoplamiento** (por módulo):
  - `Ca` (acoplamiento aferente) = `in_degree` — cuántos módulos dependen de este.
  - `Ce` (acoplamiento eferente) = `out_degree` — de cuántos módulos depende este.
  - Ambos cuentan módulos distintos, no el `weight`.
  - `Instability = Ce / (Ca + Ce)`, rango `[0, 1]`.
  - Interpretación: I cercana a 1 = módulo de orquestación/aplicación
    (depende de muchos, nadie depende de él). I cercana a 0 = módulo
    core/utilidad (muy dependido, no depende de nada). Ninguno es "malo" por
    sí solo — lo problemático es Ca y Ce altos simultáneamente, o un módulo
    core que cambia con frecuencia.
- **Detección de ciclos**: `nx.simple_cycles(graph)`. En grafos muy densos el
  número de ciclos puede crecer exponencialmente — se consumen como máximo
  `MAX_CYCLES + 1` (100 + 1) con `itertools.islice`; el extra solo indica si
  hay más (`cycles_truncated`). Cada ciclo se rota para empezar por su módulo
  menor: el mismo ciclo siempre se escribe igual. networkx recorre conjuntos
  internos cuyo orden depende de la semilla del hash de los `str`
  (`PYTHONHASHSEED`), así que el grafo se enumera con etiquetas enteras (índice
  del nombre ordenado): la lista y el punto de truncado son idénticos entre
  ejecuciones (coste medido: 0,7 s con 20.000 nodos y 200.000 aristas).
- **Hallazgos** (`graph/findings.py`, `find_findings(graph, metrics, config)`): reglas
  deterministas sobre el grafo y las métricas, sin LLM. `analyze(result,
  findings_config)` las calcula tras los ciclos y las guarda en `AnalysisResult.findings`
  (`findings_enabled` dice si el informe debe mostrar la sección). Las fachadas
  `__init__.py` quedan excluidas de todas las reglas. Defaults en `FindingsConfig`
  (`[findings]` de `.unskein.toml`, sin flags por umbral; solo `--findings/--no-findings`).

  | Regla | Condición | Defaults |
  |---|---|---|
  | Dependencia inestable | arista A→B con `I(B) − I(A) ≥ gap` y `Ca(A) ≥ min_afferent` | gap 0,5 · min_afferent 2 |
  | Cuello de botella | `Ca ≥ max(P(Ca), mín)` y `Ce ≥ max(P(Ce), mín)` | P90 · mín 5 |
  | Orquestador creciente | `Ce ≥ max(P(Ce), mín)` | P95 · mín 10 |
  | Huérfano | `Ca = 0` y `Ce = 0`, sin puntos de entrada conocidos | — |
  | Violación de capas | arista A→B con capa(A) más baja que capa(B); solo con `[layers]` | — |

  `CouplingMetrics` vive en `graph/coupling.py` y no en `metrics.py`: `findings.py` lo
  necesita y `metrics.py` importa `findings.py`, así que dejarlo en `metrics.py` creaba
  un ciclo que unskein detectaba en su propio código (lo vigila
  `tests/integration/test_self_analysis.py`). `metrics.py` lo reexporta.

  `P(x)` es el percentil por rango más cercano (`graph/percentile.py`, compartido con
  `find_high_coupling`): sin interpolación, siempre un valor real. Se combina con un
  mínimo absoluto porque el percentil solo marcaría siempre a alguien (en un proyecto
  pequeño, cualquier módulo sería «el peor»); el mínimo evita inundar de hallazgos un
  proyecto de pocos módulos. Un módulo puede ser a la vez cuello de botella y
  orquestador. Puntos de entrada: `entry_points.py` (la capa con E/S, llamada desde
  `scan.py`) lee `[project.scripts]` y `[project.gui-scripts]` del `pyproject.toml` de la
  raíz y los pasa, junto a `__main__` y `[findings] entry_points`, en
  `FindingsConfig.entry_points`; así las reglas siguen siendo puras. Un `pyproject.toml`
  ausente no es un error; uno ilegible o inválido se avisa (WARNING) y se ignora. En el
  informe: a lo sumo 10 módulos por tipo; en el contexto de la IA, 5 por tipo con el total
  real, como hechos ya calculados. Los hallazgos **no** cambian el código de salida.

  Calibración medida antes de fijar los defaults:

  | Proyecto | Módulos | Cuellos | Orquestadores | Dep. inestables | Huérfanos |
  |---|---:|---:|---:|---:|---:|
  | swo-aura-rag_api | 281 | 1 (`app_settings`) | 7 | 1 | 1 |
  | unskein (`src`) | 31 | 0 | 2 (`cli`, `scan`) | 0 | 0 |

  Coste medido: 0,05 s con 20.000 nodos y 200.000 aristas.

  Regla de capas (`_layer_violations`, `_layer_of`): `[layers] order` lista las capas de
  la más alta a la más baja como prefijos de paquete; el rango es la posición. Un módulo
  pertenece a la capa de su prefijo más largo que coincida por segmentos completos
  (`app.web` no abarca `app.webhooks`); sin capa, no se comprueba. Hay violación cuando
  el importador está en una capa más baja (posterior en la lista) que el importado. Las
  fachadas quedan excluidas, y se ordenan por par de módulos tras los huérfanos. Sin
  `[layers]` la regla no existe. Validación: cada nombre cumple `LAYER_NAME_PATTERN`, sin
  repetidos, y el error nunca repite el valor. Una capa declarada que no abarca ningún módulo
  (`unmatched_layers`) se avisa (WARNING) en `analyze_project`, para que una errata no
  se lea como cumplimiento. Calibración en swo-aura-rag_api: orden
  declarado (`webapi, application, nexus_ai, core`) 0 violaciones; invertido, 158.
- **Marañas** (`find_tangles`, #8): componentes fuertemente conexas de más
  de un módulo (`nx.strongly_connected_components`, lineal y exacto, nunca
  se trunca). Todo ciclo vive dentro de una maraña, así que dan el tamaño
  real del problema aunque la lista de ciclos se corte en 100: en networkx,
  "100+ ciclos" es en realidad **una maraña de 279 de 288 módulos**.
  Miembros ordenados; marañas de mayor a menor tamaño.
- **"God modules" / alto acoplamiento**: percentil superior (default 90%) de
  `Ca + Ce` combinado, como candidatos que la capa de IA interpretará.
  Umbral por *nearest-rank* sobre todos los módulos (el
  `ceil(p/100·n)`-ésimo menor valor): sin interpolación, siempre es una
  puntuación real y explicable. Empates incluidos, puntuación 0 nunca;
  orden por puntuación descendente y luego nombre.
- **Fachadas con `import paquete as alias`**: el uso `alias.func()` no se
  puede resolver estáticamente, así que el paquete raíz acumula un Ca muy
  alto (en networkx, 253 de 288 módulos). Es un dato real — todo depende de
  la fachada —, pero el reporte/IA deben interpretarlo como tal, no como un
  "god module" clásico.

### Impacto transitivo y paquetes (`graph/impact.py`, `graph/packages.py`)

- **Radio de impacto** (`impact_radius(graph, modules)`): para cada módulo, cuántos módulos
  dependen de él directa o indirectamente, es decir sus ancestros en el grafo (`a -> b`
  significa que `a` importa a `b`). El propio módulo no cuenta, pero los demás miembros de
  una maraña a la que pertenece sí. Cuesta un recorrido del grafo por módulo, así que
  `analyze` lo calcula solo para el conjunto que el informe muestra: los 15 primeros de la
  tabla de acoplamiento más los 10 primeros cuellos de botella (`AnalysisResult.impact`).
  Coste medido: 0,44 s para 25 módulos en un grafo de 20.000 nodos y 200.000 aristas.
- **Resumen por paquetes** (`summarize_packages(graph, depth, facades=...)`): `package_of`
  asigna cada módulo a un paquete. Una fachada `__init__` es el paquete mismo, nombrado por
  los primeros `depth` segmentos de su nombre. Un módulo normal pertenece al paquete en el
  que está, recortado a `depth` segmentos (`min(depth, segmentos - 1)`): `core.db` está en
  `core` con profundidad 1, 2 o 5. Solo un módulo sin paquete encima (un archivo suelto de
  primer nivel, como `manage`) va a `ROOT_PACKAGE` (`"(root)"`). Ca y Ce cuentan paquetes
  distintos, no módulos, y los imports dentro de un mismo paquete se ignoran. Los paquetes
  salen ordenados por `Ca + Ce` descendente y luego por nombre; las dependencias, por número
  de imports descendente y luego por nombres. Coste medido: 0,013 s con 20.000 nodos y
  200.000 aristas. Resultado en `AnalysisResult.packages` y `.package_edges`.
- **Profundidad automática** (`summarize_project_packages(graph, depth, facades=...)`):
  `package_depth` es `int | None` y por defecto `None`. Con un número se usa tal cual. Con
  `None` se resume a `AUTO_START_DEPTH` (1) y, si el resultado es un único paquete que no es
  `ROOT_PACKAGE` (todo el proyecto cuelga de un solo paquete de primer nivel, como `unskein`),
  se resume una vez más a `AUTO_START_DEPTH + 1` y se devuelve ese. Si no, se queda con el
  primero. Nunca baja más de un nivel.
- `package_depth` vive en `[findings]`, pero el resumen por paquetes **no** depende de
  `enabled`: se calcula también con los hallazgos desactivados. El informe lo muestra solo
  con dos o más paquetes (a lo sumo 15 paquetes y 10 dependencias); la IA recibe las 10
  mayores dependencias con su total real y el impacto de los cuellos de botella. Nada de
  esto cambia el código de salida.
- Calibración medida:

  | Proyecto | Paquetes | Impacto máximo |
  |---|---|---|
  | swo-aura-rag_api | `core` (81 módulos, Ca 5), `nexus_ai`, `application`, `webapi`, `tools`, `docs` | `core.logging.logger` 152, `core.configuration.load_env` 110, `core.configuration.app_settings` 75 |
  | unskein (`src`) | profundidad automática (un solo paquete de primer nivel, baja a 2): `unskein` (14 módulos), `unskein.graph` (8), `unskein.parsers` (6), `unskein.ai` (4), `unskein.report` (2) | `unskein.config` 16 (0 marañas) |

Output consolidado (`AnalysisResult`): `graph`, `coupling_metrics`, `cycles`,
`high_coupling_modules`, `parse_warnings`, `cycles_truncated`, `tangles`, `findings`,
`findings_enabled`, `impact`, `packages` y `package_edges`.
`analyze()` es composición pura `build_graph → compute_coupling → find_cycles →
find_high_coupling → find_findings → summarize_project_packages → find_tangles →
impact_radius` y espera un `ParseResult` ya pasado por `resolve_indirection`. Este objeto es
el punto de unión entre el análisis determinista y la interpretación por IA/reporte.

---

## 5. Pipeline de IA (`ai/client.py`, `ai/prompts.py`)

Principio rector: **el LLM interpreta agregados y casos destacados, nunca el
grafo completo**, y **el grafo es la verdad**: lo que el LLM diga se contrasta con
él antes de mostrarse.

```
analyze → build_context → build_messages → AIClient.generate_report → ground_report
```

### Contexto acotado (`AIContext`)

Solo nombres de módulo y métricas (nunca código fuente ni rutas): las mayores
marañas (5, con hasta 20 miembros), los ciclos más cortos (10, con hasta 8 miembros
cada uno y su longitud real en `CycleSummary.length`), los 15 módulos con mayor
`Ca + Ce` y el recuento de warnings por código. Cada lista truncada lleva su total al
lado, para que el LLM sepa que hay más. Los ciclos se resumen porque `find_cycles`
no acota su longitud (dentro de una maraña son casi tan largos como ella); el peor
caso medido (maraña de 120 módulos, 100 ciclos, nombres de ~45 caracteres, 2000
módulos) queda por debajo de `MAX_PROMPT_CHARS` (16 000). Si aun así el mensaje no
cabe (p. ej. nombres de módulo muy largos), `build_messages` aplica `shrink_context`
en silencio (solo `DEBUG`): parte a la mitad cada lista y los miembros de cada
maraña/ciclo, sin bajar de uno y conservando los totales, hasta que cabe o ya no se
puede reducir más; en ese caso se envía en su tamaño mínimo.

### Prompt

`build_messages(context, lang)` devuelve `[system, user]`. El system lleva una
rúbrica de severidad anclada en los datos (`high`: maraña o ciclo; `medium`: módulo
en el top de `Ca + Ce` volátil del que otros dependen — inestabilidad ≥
`UNSTABLE_THRESHOLD` (0.7) y `Ca > 0` — o con `Ce` muy por encima del resto; `low`: el
resto; nunca se señala un módulo solo por ser estable, porque inestabilidad baja con
muchos dependientes es sano), la regla de
copiar los nombres de módulo literalmente y la instrucción de idioma. El user lleva
los datos y el JSON schema de `AIReport` (dentro del prompt además de en la API:
los modelos económicos ignoran `response_format`). La serialización es
determinista.

### Cliente

`AIClient(config)` resuelve un `ModelProfile` **una sola vez**, al construirse, y
solo si la IA está activa (`--no-ai` nunca importa `litellm`):

- `temperature`: 1.0 para los modelos de razonamiento (solo aceptan 1.0), 0.2 en
  los demás. Con `litellm_proxy/…` se pregunta antes al proxy (`ai/proxy.py`):
  un `GET {api_base}/model/info` con la clave virtual como bearer, límite de 10 s,
  solo con `api_base` http(s), y se usa el `supports_reasoning` del alias. El alias
  lo elige quien administra el proxy ("GPT 5.6 Luna"), así que LiteLLM no puede
  deducir de él el modelo real; sin ese dato, un modelo de razonamiento recibía 0.2
  y fallaba con `BadRequestError`. Si el proxy no responde, no está autorizado,
  devuelve algo inesperado o no conoce el alias, decide
  `litellm.supports_reasoning(model)`, como en las llamadas directas. El fallo solo
  se registra en DEBUG con el tipo de error, nunca el mensaje (podría repetir la
  clave).
- `response_format`: la clase `AIReport` si el modelo soporta JSON schema; si no,
  `{"type": "json_object"}`.
- `timeout`: 60 s en llamadas directas; ninguno con `litellm_proxy/…` (manda el
  proxy).

`generate_report(messages)` hace **una** llamada a `litellm.completion` (reintentos
y fallback son de LiteLLM/proxy) y devuelve un `AIOutcome`: `Timeout` →
`TIMEOUT`; el resto de `litellm.LITELLM_EXCEPTION_TYPES` → `CALL_ERROR` (solo el
nombre de la clase); respuesta vacía, truncada o que no cumple el schema →
`INVALID_RESPONSE`. Cualquier otra excepción es un bug y sale con exit 3.

La validación quita los bloques `<think>…</think>`, prueba el JSON tal cual y
después el extraído (bloque cercado o del primer `{` al último `}`).

El import de LiteLLM es perezoso y endurecido: `LITELLM_LOCAL_MODEL_COST_MAP=True`
(sin descarga remota del mapa de precios), `telemetry = False` y
`suppress_debug_info = True`. Nunca se activa `set_verbose`.

### Anclaje al grafo (`ground_report`)

Cada nombre de módulo se normaliza antes de compararlo con el grafo
(`normalize_module_name`): se quitan espacios, comillas/backticks y puntos en los
extremos, y una ruta (`app/core.py`, `./app/core.py`, `app/__init__.py`,
`src/app/core.py`) o un nombre con `.py` se convierte a nombre con puntos. Un segmento
inicial `src` (raíz de fuentes) solo se quita si el nombre con él no existe en el
grafo; ningún otro segmento se adivina. Luego se eliminan de cada problema los módulos que no son nodos del grafo
(sin duplicados) y se descartan los problemas que se quedan sin ninguno;
`code_snippet` se fuerza a `None` (v0.2). `ground_report` devuelve
`GroundingResult(report, dropped_problems)`; si hubo descartes, se avisa por consola
(`WARNING`, solo el número, nunca el texto del LLM) y en el reporte.

### Seguridad

La API key nunca aparece en logs, `repr`, reporte ni errores. `WARNING` solo lleva
el tipo de fallo y la clase de la excepción; el mensaje del proveedor solo va a
`DEBUG`, con la key sustituida por `***`. Sin key de unskein, LiteLLM lee la variable
del proveedor (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, credenciales de AWS…), así que
también se sustituyen los valores de las variables cuyo nombre termina en `_API_KEY`,
`_SECRET_ACCESS_KEY`, `_ACCESS_KEY_ID` o `_SESSION_TOKEN` (`secrets_to_redact`), si
tienen al menos 8 caracteres: uno más corto es un marcador, y sustituirlo destrozaría
palabras normales del mensaje.

### Degradación

Modelo no configurado, `--no-ai` o fallo de la llamada/validación: el reporte se
genera igual. `AIStatus` (`PRESENT`, `DISABLED`, `NOT_CONFIGURED`, `FAILED`)
explica por qué la sección de IA está vacía; con `FAILED`, el `AIFailure` elige el
aviso. **Nunca** cae el comando por un fallo del LLM.

### Coste

`DEBUG` local con los tokens y el coste de `litellm.completion_cost`; no aparece
en el reporte.

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

Precedencia de las opciones no secretas: flag `--lang` > env var
(`UNSKEIN_LANG`) > `.unskein.toml` (`[general] lang = "es"`). Si el toml es
inválido, el idioma se decide sin él (para poder traducir ese mismo error).
Si nada está configurado, se usa `locale.getlocale()`; si no es `es*`,
**default a inglés** — más seguro para adopción OSS amplia, no asumir que
quien instala el CLI habla español.

### Impacto en el pipeline de IA

`build_messages(context, lang)` incluye el idioma como instrucción explícita
(`LANG_INSTRUCTION`) en el mensaje `system` — el LLM debe generar
`AIReport.summary` y `Problem.description` en el idioma seleccionado, no solo
el CLI/reporte. El resto del `SYSTEM_PROMPT` (rúbrica de severidad, no inventar
información, declarar insuficiencia de datos) es el mismo en ambos idiomas —
solo cambia el idioma de salida esperado, no el criterio de análisis.

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
## Problemas señalados (IA)         (siempre presente: los problemas si hay AIReport;
                                    si no, el aviso de por qué no hay: DISABLED,
                                    NOT_CONFIGURED o FAILED)
## Advertencias del análisis        (solo si hay parse_warnings)
```

API: `render_report(context: ReportContext, lang) -> str`, con
`ReportContext(root, result, ai_report, ai_status, min_severity, ai_failure,
ai_error_type)`. `root`
nombra el reporte y hace **relativas** las rutas de los warnings.

Reglas:
- El "no hay IA" nunca es un hueco vacío ni un error crudo: `AIStatus`
  (`PRESENT`, `DISABLED` por `--no-ai`, `NOT_CONFIGURED` sin modelo — con
  cómo configurarlo —, `FAILED` si la llamada falló; el `AIFailure` elige el
  aviso) elige el aviso de la sección.
- **Warnings agrupados por `WarningCode`**: `### <título> (<n>)` con
  `MAX_WARNING_EXAMPLES` (5) ejemplos `ruta:línea — mensaje` y "…y N más".
  Con networkx: 264 star imports → 1 grupo, 5 líneas.
- Sección de ciclos: primero las **marañas** (tamaño + hasta
  `MAX_TANGLE_MEMBERS_SHOWN` = 10 miembros y "…y N más"), luego los ciclos
  como ejemplos, en bucle cerrado (`a` → `b` → `a`), con aviso si se
  truncaron. El resumen menciona la maraña mayor y la tabla de métricas
  cuenta las marañas.
- Todo texto sale del catálogo `i18n` (ES/EN); un test exige que cada
  `WarningCode`, cada `ErrorKey` y cada clave tengan ambos idiomas con los
  mismos placeholders.
- `--min-severity` se aplica en esta capa (filtrando `ai_report.problems`
  antes de renderizar), no se le pide al LLM que filtre — mantiene la
  generación de IA independiente de la presentación.
- Sin lógica de negocio en las funciones de renderizado, solo formateo — la
  interpretación ya viene resuelta desde `graph/builder.py` o `AIReport`.

---

## 7. CLI (`cli.py`)

Framework: `typer` (type hints, genera `--help` automático).

Comandos: `unskein scan <path> [opciones]`, `unskein init [path]`,
`unskein config save [source]` y `unskein guide`.

`unskein init` escribe `<path>/.unskein.toml` (default `.`), o
`~/.config/unskein/config.toml` con `--user`, copiando la plantilla que viaja en
el paquete (`src/unskein/templates/unskein.toml`, leída con
`importlib.resources`). Toda clave está comentada con su valor por defecto, así
que el archivo generado no cambia nada hasta que se descomenta una línea. Si el
archivo existe no lo toca (`UnskeinError CONFIG_EXISTS`, código 1) salvo con
`--force`. Tests en `tests/unit/test_init_config.py` fijan que la plantilla
documenta todas las claves del esquema `TomlConfig`, que descomentada valida en
modo estricto y que sus valores coinciden con los defaults de `AnalysisConfig`:
un default que cambie sin actualizar la plantilla rompe la CI.

`unskein config save [source]` (grupo `config` de typer, `init_config.save_user_config`)
promueve un archivo ya probado (default `./.unskein.toml`) a
`~/.config/unskein/config.toml`. Lo valida con el mismo `read_toml_file` que el
escaneo antes de escribir nada (`ConfigError`, código 1), lo copia tal cual,
comentarios incluidos, y crea la carpeta. Origen inexistente: `CONFIG_NOT_FOUND`;
destino existente sin `--force`: `CONFIG_EXISTS`. Se escribe con modo `0600`
(abierto ya privado con `os.open`, y `chmod` para un archivo previo) porque puede
llevar `[ai] api_key`; en ese caso el CLI avisa y recomienda `UNSKEIN_API_KEY`, sin
mostrar nunca el valor. El `.unskein.toml` del proyecto se busca en la carpeta
**analizada**, no en el directorio de trabajo; el aviso de "sin modelo" del informe
nombra ambas rutas (la de usuario literal, `~/...`, para no filtrar el home).

`unskein guide [--lang]` imprime la guía de uso que viaja en el paquete
(`src/unskein/guides/guide.{es,en}.md`, con `{version}` sustituido por la versión
instalada), así que siempre describe la versión que se ejecuta. El idioma sigue
flag > `UNSKEIN_LANG` > locale (no lee `.unskein.toml`, igual que `init`). En
terminal se renderiza con rich; redirigida sale el Markdown crudo. Ambos comandos
leen sus recursos con `resources.read_package_text`. `tests/unit/test_guide.py`
exige que las dos guías nombren cada comando y cada opción larga (introspección de
los parámetros de typer), los cuatro códigos de salida y el mismo número de
secciones: una flag nueva sin documentar rompe la CI.

Flags de `scan`:

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

Orquestación en `scan.py`, separada de `typer` (testeable sin el CLI y
reutilizable como librería), en **dos fases** para que cualquier error
posterior a la config salga en el idioma configurado:

```
prepare_scan(options) -> ScanContext        # única fase que lee .unskein.toml
  load_toml_config → detect_lang → resolve_analysis_config → ai_config
  (ConfigError → el CLI lo traduce con flag > env > locale, sin el toml)
execute_scan(context) -> ScanOutcome        # = analyze_project + interpret
  1. valida que <path> es un directorio          (UnskeinError PATH_NOT_FOUND)
  2. adapter = PythonAdapter(config)             # único lenguaje en v0.1
  3. discover (excludes + tests) → sin .py       (UnskeinError NO_FILES_FOUND)
  4. adapter.parse (secuencial hasta el PR de paralelismo)
     → resolve_indirection → analyze
  5. interpret: con modelo configurado y sin --no-ai, build_context →
     build_messages → AIClient.generate_report → ground_report; el AIStatus
     final (PRESENT/DISABLED/NOT_CONFIGURED/FAILED) va al reporte
     (spinner en stderr, solo TTY, mientras responde el modelo)
```

El CLI (`cli.py`) solo parsea flags, renderiza (`rich.markdown` en terminal,
Markdown crudo UTF-8 con `-o`), muestra `--verbose` y elige el código de
salida. Ayuda en formato click clásico (`rich_markup_mode=None`): las tablas
de rich truncaban `--no-follow-symlinks` a 80 columnas.

**Entry point `run()`** (también `python -m unskein`): ejecuta la app con
`standalone_mode=False` y traduce errores de uso a **1** (click usa 2, que en
unskein significa "severidad alta"). typer 0.27 trae su propio click
vendorizado, así que solo se capturan tipos públicos de typer
(`typer.TyperException`, `typer.Abort`), nunca los de `click`. También
configura stdout/stderr con `errors="replace"`: las tuberías de Windows usan
cp1252, sin `→`, y sin esto imprimir un ciclo acababa en código 3.

Configuración (`config.py`): `load_toml_config(root)` es la única función con
E/S (lee y valida cada archivo, combina); `resolve_analysis_config(toml,
flags)` (flag > toml > default, excludes sumados) y `resolve_ai_config(toml,
env, cli_api_key)` (secretos: env > toml > flag; `None` si no hay modelo en
ninguna capa) son puras y se testean sin disco ni entorno real.

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
| `0` | Análisis completado, sin problemas de severidad `high` (`--min-severity` solo filtra lo que se muestra) |
| `1` | Error de uso (ruta inválida, sin archivos `.py`, config inválida) |
| `2` | Análisis completado, con problemas de severidad `high` encontrados |
| `3` | Error interno inesperado (bug real — traceback completo visible) |

```python
app = typer.Typer(
    add_completion=False,
    epilog="Códigos de salida: 0=OK, 1=error de uso, 2=problemas de severidad alta, 3=error interno.",
)
```

El CLI determina el código según el resultado (`UnskeinError` o error de uso → 1,
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
def peak_rss_bytes() -> int:
    if sys.platform == "win32":
        return psutil.Process().memory_info().peak_wset
    import resource  # solo Unix
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return max_rss if sys.platform == "darwin" else max_rss * 1024  # Linux: KiB

def measure(fn):
    start = time.perf_counter()
    result = fn()
    duration = time.perf_counter() - start
    return result, PerformanceStats(duration, peak_rss_bytes() / (1024 * 1024))
```

**Pico real** (#9): la versión anterior leía el RSS *después* del análisis,
así que un pico de 200 MB liberado antes de terminar aparecía como 21 MB.
`psutil` solo expone el pico en Windows (`peak_wset`); en Linux/macOS la
fuente portable es `resource.ru_maxrss` (KiB en Linux, bytes en macOS), por
eso `resource` se usa **solo en la rama Unix**. Es la marca máxima de todo
el proceso (incluye el arranque, no se puede reiniciar): la cifra honesta de
cuánta memoria usó unskein. La memoria de los workers del futuro parseo
paralelo no está incluida — se decide en ese PR (p. ej. `RUSAGE_CHILDREN`).
La rama macOS no tiene runner en CI.

## Notas sobre extensión futura (no implementar en v0.1)

- **Multi-lenguaje**: el punto de selección dinámica del adapter (por
  extensión de archivo o flag `--lang`) es exactamente donde hoy está
  `adapter = PythonAdapter(config)` hardcodeado en `execute_scan`. Al agregar TS/Java,
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
- **Clean Code obligatorio**, con docstrings estilo Google en todo módulo,
  clase y función (privados incluidos), exigidos en CI con las reglas `D` de
  ruff. Reglas completas en `CLAUDE.md`, sección *Clean Code (obligatorio)*.

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
