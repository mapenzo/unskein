# unskein {version} — guía de uso

## Qué hace unskein

unskein lee los imports de un proyecto Python y construye un grafo de sus
módulos. Con ese grafo mide cuánto acoplamiento tiene cada módulo, encuentra
ciclos de dependencia y marañas, y genera un informe en Markdown. Si hay un
modelo de IA configurado, el informe añade una interpretación breve: un
resumen, una valoración de la salud de la arquitectura y los problemas que
conviene revisar.

El grafo y las métricas nunca dependen de la IA: se calculan igual en cada
ejecución. La IA solo interpreta los números que el grafo ya produjo.

Esta versión analiza **solo Python**, a **nivel de módulo** (un nodo por
archivo `.py`). No mira dentro de clases o funciones, no busca
vulnerabilidades y no dibuja un mapa de arquitectura.

## Instalación y primer análisis

```bash
pip install unskein          # o: uv tool install unskein / pipx install unskein
unskein scan ruta/al/proyecto --no-ai
```

`--no-ai` da el informe determinista completo sin llamar a ningún modelo. No
hace falta ningún archivo de configuración: todas las opciones tienen un valor
por defecto.

## Cómo leer el informe

- **Resumen**: módulos, dependencias internas y ciclos, el módulo más acoplado
  y, si las hay, las marañas.
- **Métricas generales**: número de módulos, dependencias, ciclos, marañas y
  advertencias.
- **Paquetes**: la misma medida de acoplamiento entre paquetes, que da la visión de
  conjunto que una tabla de módulos no puede (se muestra con dos o más). Un módulo pertenece
  al paquete en el que está, nombrado por como máximo los primeros `package_depth` segmentos
  de su nombre (`core.db` y `core.http` están en `core`); los módulos que no están en ningún
  paquete, como un archivo suelto de primer nivel, van a `(root)`. Por defecto la profundidad
  es automática: empieza en 1 y baja un nivel más cuando todo el proyecto es un único paquete
  de primer nivel; un número en `package_depth` la fija. Ca y Ce cuentan otros paquetes, no
  módulos, y los imports dentro de un mismo paquete no cuentan. Bajo la tabla, las mayores
  dependencias entre paquetes con su número de imports. Ambos se muestran, y se pasan a la
  IA, incluso con `[findings] enabled = false`.
- **Módulos con mayor acoplamiento**: el 10 % superior por `Ca + Ce` (hasta
  15 filas).
  - **Ca** (acoplamiento aferente): cuántos módulos importan este. Un Ca alto
    significa que muchos módulos se rompen si este cambia.
  - **Ce** (acoplamiento eferente): cuántos módulos importa este. Un Ce alto
    significa que se rompe cuando cambia cualquiera de ellos.
  - **Inestabilidad** = `Ce / (Ca + Ce)`, de 0 (estable, otros dependen de
    él) a 1 (inestable, depende de otros).
  - **Impacto**: cuántos módulos dependen de este, directa o indirectamente: hasta dónde
    puede llegar un cambio. Se muestra para los módulos listados y para los cuellos de botella.
- **Ciclos de dependencia**: módulos que acaban importándose a sí mismos.
  - Primero van las **marañas**: grupos donde cada módulo alcanza a todos los
    demás. Su tamaño es exacto aunque la lista de ciclos se corte.
  - Después, los **ciclos** como bucles de ejemplo, como máximo 100; el
    informe avisa cuando la búsqueda se detuvo en ese límite.
- **Hallazgos**: reglas calculadas a partir del grafo, también con `--no-ai`. Cada
  tipo tiene una explicación y una recomendación, y luego sus módulos con los
  números que lo justifican (como máximo 10 por tipo):
  - **Dependencia inestable**: un módulo del que otros dependen importa uno mucho más
    inestable.
  - **Cuello de botella**: Ca alto y Ce alto a la vez, así que los cambios entran y
    salen.
  - **Orquestador con muchas dependencias**: muchos más imports que el resto; es
    normal en puntos de entrada y casos de uso.
  - **Módulo huérfano**: no importa ningún módulo del proyecto y nadie lo importa:
    código muerto o un punto de entrada que se ejecuta desde fuera del código.

  Los umbrales son relativos al proyecto (percentiles, con un mínimo absoluto) y se
  pueden ajustar en `[findings]`. Los hallazgos nunca cambian el código de salida.
- **Problemas señalados (IA)**: solo con un modelo configurado. Cada problema
  tiene una severidad (`low`, `medium`, `high`), los módulos implicados y una
  recomendación. Los problemas que nombran módulos inexistentes se descartan,
  y el informe dice cuántos.
- **Advertencias del análisis**: archivos omitidos o imports que no se
  pudieron resolver (imports con asterisco, imports relativos fuera del
  paquete raíz, archivos demasiado grandes, no analizables o demasiado lentos,
  ciclos o cadenas de re-exports demasiado largas). Una advertencia nunca
  detiene el análisis.

Los imports a través del `__init__.py` de un paquete se siguen hasta el módulo
que define el nombre, así que un ciclo escondido tras una fachada también
aparece.

## Opciones de `scan`

```bash
unskein scan [RUTA] [opciones]
```

| Opción | Qué hace |
|---|---|
| `PATH` | Carpeta a analizar (por defecto, la actual). |
| `--no-ai` | Omite la interpretación con IA. |
| `--exclude PATRÓN` | Excluye más rutas, sintaxis gitignore (repetible). |
| `--min-severity low\|medium\|high` | Severidad mínima de los problemas de IA que se muestran. |
| `--include-tests` / `--no-include-tests` | Analiza también el código de tests (desactivado por defecto). |
| `--findings` / `--no-findings` | Muestra u oculta la sección de hallazgos (se muestra por defecto). |
| `--follow-symlinks` / `--no-follow-symlinks` | Sigue carpetas enlazadas (desactivado por defecto). |
| `--encoding NOMBRE` | Encoding de reserva para archivos que no declaran ninguno. |
| `--lang es\|en` | Idioma del informe. |
| `-o`, `--output ARCHIVO` | Guarda también el informe Markdown en un archivo. |
| `-v`, `--verbose` | Muestra progreso, duración y pico de memoria. |
| `--log-file ARCHIVO` | Escribe también los logs de depuración en un archivo. |
| `--api-key CLAVE` | Solo para pruebas rápidas: queda en el historial de la shell. |

Ejemplos:

```bash
unskein scan . --no-ai -o informe.md         # guarda el informe
unskein scan . --exclude "migrations/"       # omite todas las carpetas migrations/
unskein scan . --min-severity high           # solo problemas de IA de severidad alta
```

Otros comandos: `unskein init` (ver Configuración), `unskein guide` (esta
guía, `--lang` para elegir su idioma; `unskein guide > guia.md` la guarda) y
`unskein --version`.

## Excluir rutas

Se combinan tres orígenes; ninguno sustituye a los demás:

1. El `.gitignore` de la raíz del proyecto.
2. Un `.unskeinignore` en la raíz, con la misma sintaxis, para código que está
   en git pero no debe analizarse (código generado, paquetes vendorizados).
3. Las flags `--exclude` y `exclude` en `.unskein.toml`.

El código de tests (`tests/`, `test/`, `test_*.py`, `*_test.py`,
`conftest.py`) se omite salvo que pases `--include-tests`.

Un patrón con una barra en medio queda anclado a la raíz: `migrations/**`
solo omite la carpeta de primer nivel, mientras que `migrations/` o
`**/migrations/**` la omiten a cualquier profundidad.

## Configuración

```bash
unskein init                # escribe ./.unskein.toml
unskein init --user         # escribe ~/.config/unskein/config.toml
unskein init --force        # sustituye un archivo existente
```

`init` acepta una carpeta (`PATH`, por defecto la actual), `--user`, `--force`
y `--lang` para sus mensajes. Escribe un archivo con todas las opciones comentadas en su valor por
defecto y una línea que explica cada una. Descomenta solo lo que quieras
cambiar. Nunca sobrescribe un archivo existente sin `--force`.

Precedencia, de mayor a menor:

- **La mayoría de opciones**: flag > variable de entorno > `.unskein.toml` >
  valor por defecto. La única variable de entorno documentada aquí es
  `UNSKEIN_LANG`.
- **Modelo de IA y secretos**: `UNSKEIN_AI_MODEL`, `UNSKEIN_API_KEY`,
  `UNSKEIN_AI_API_BASE` > `.unskein.toml` > `--api-key`.

El `.unskein.toml` del proyecto gana al de usuario clave por clave, y los
excludes de ambos se suman. Una errata o un tipo erróneo en cualquiera de los
dos detiene el análisis con código 1 y nombra el archivo y la clave.

Si tus paquetes no están en la raíz ni en `src/`, define `source_roots` en
`[analysis]`.

La tabla `[findings]` ajusta los hallazgos; los módulos que se ejecutan desde fuera
del código se pueden listar en `entry_points` (los scripts de `pyproject.toml` y los
módulos `__main__` se detectan solos). El ajuste `package_depth` cambia cómo se
nombran los paquetes.

## Interpretación con IA

Funciona cualquier modelo compatible con LiteLLM: un modelo local de Ollama,
un proveedor en la nube o un LiteLLM Proxy.

```bash
# Ollama local
export UNSKEIN_AI_MODEL="ollama/qwen2.5-coder:7b"
export UNSKEIN_AI_API_BASE="http://localhost:11434"

# Proveedor en la nube
export UNSKEIN_AI_MODEL="gpt-4o-mini"
export UNSKEIN_API_KEY="sk-..."
```

Qué sale de tu equipo: nombres de módulos y sus métricas (acoplamiento,
ciclos, marañas). Nunca código fuente. Con `--no-ai` o un modelo local, nada.
unskein no tiene telemetría de ningún tipo.

Si el modelo falla, no responde a tiempo (60 s en llamadas directas) o
responde con un formato incorrecto, el informe se genera igual sin la sección
de IA y explica por qué. La respuesta llega en el idioma del informe.

## Códigos de salida

| Código | Significado |
|---|---|
| `0` | Análisis completado, sin problemas de severidad `high`. |
| `1` | Error de uso: ruta inválida, sin archivos `.py`, config inválida, archivo existente en `init`. |
| `2` | Análisis completado y la IA señaló un problema de severidad `high`. |
| `3` | Error interno (un bug): se muestra el traceback completo. Por favor, repórtalo. |

`--min-severity` solo filtra lo que se muestra; no cambia el código de salida.

## Rendimiento

A partir de 500 archivos, el parseo se hace en paralelo con hasta 8 procesos
(ajustable con `parallel_threshold` y `max_workers` en `.unskein.toml`). Los
archivos de 5 MB o más se omiten con una advertencia, y en el parseo paralelo
también se omite un archivo que tarde más de 30 s. `--verbose` muestra la
duración y el pico de memoria, medidos en local y nunca enviados a ningún
sitio.

## Problemas frecuentes

- **«No se encontraron archivos .py»**: revisa la ruta, y que `.gitignore`,
  `.unskeinignore` o `--exclude` no lo estén excluyendo todo. Los tests se
  omiten por defecto.
- **Imports marcados como no resueltos**: puede que tus paquetes estén fuera
  de la raíz y de `src/`; define `source_roots`.
- **Sin sección de IA**: no hay modelo configurado, o se pasó `--no-ai`. El
  informe dice cuál de los dos.
- **Idioma equivocado**: pasa `--lang`, o define `UNSKEIN_LANG` o
  `[general] lang`.
- **Un bug**: abre un issue en https://github.com/mapenzo/unskein/issues con
  la salida de `--verbose`.
