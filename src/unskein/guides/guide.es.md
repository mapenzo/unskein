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

En monorepos no hace falta configurar nada: cada `pyproject.toml`, `setup.py` o
`setup.cfg` marca una distribución y sus archivos se nombran como los importa Python
(`enterprise/litellm_enterprise/x.py` es `litellm_enterprise.x`), así que los imports
entre miembros del workspace cuentan como internos. El código que ninguna distribución
empaqueta y nadie importa (CI, ejemplos, utilidades) se lista aparte como *scripts*: no
cuenta en Ca, métricas ni hallazgos (salvo capas) y aparece como *consumidores* de lo que
importa. Si prefieres el nombrado por carpetas, `[analysis] source_roots` desactiva la
detección.

## Cómo leer el informe

- **Resumen**: módulos, dependencias internas y ciclos, el módulo más acoplado
  y, si las hay, las marañas.
- **Métricas generales**: número de módulos, dependencias, ciclos, marañas, marañas ocultas y
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
- **Distribuciones**: solo en monorepos con dos o más distribuciones con nombre (o si
  alguna importa código que ninguna empaqueta). Por distribución: sus módulos, de qué otras
  importa de verdad y si se puede instalar sola, sin extras, sin que falle ningún import;
  si no, el `archivo:línea` que lo impide. Cada import entre distribuciones cuenta como
  *requerido* (al importar), *perezoso* (dentro de una función) o *protegido* (en el cuerpo
  de un `try` que captura `ImportError`, `ModuleNotFoundError`, `Exception` o un `except:`
  desnudo y no termina en `raise`, o de `with contextlib.suppress(...)` de esos errores); los protegidos son
  opcionales por contrato y nunca impiden instalarla. Las dependencias declaradas se leen de
  `[project] dependencies` y sus extras, `[tool.poetry]` (dependencias y extras) y
  `setup.cfg`. Una dependencia que solo aparece en un grupo de dependencias
  (`[dependency-groups]`, grupos de Poetry) cuenta como no declarada, porque ningún
  instalador instala los grupos con el paquete; el hallazgo dice qué grupo la lista. Con `dynamic = ["dependencies"]` o solo
  `setup.py` son desconocidas, y esa distribución nunca origina una dependencia no declarada.
  Dos manifiestos con el mismo nombre dan un aviso, y solo el menos profundo lo conserva.
  Cada hallazgo entre
  distribuciones trae un **Arreglo** que se puede copiar (la línea a añadir y el manifiesto
  donde va). Se calcula también con `[findings] enabled = false`.
- **Espacios de nombres**: un directorio con código pero sin `__init__.py` (PEP 420) es
  un paquete de espacio de nombres. Si algún módulo lo importa, aparece en el grafo sin
  archivo y con Ce 0, marcado *(espacio de nombres)*, contado aparte en el resumen y en
  las métricas generales, y fuera de los hallazgos de módulos (sí puede ser destino de una
  violación de capas). `import a.b` seguido de `a.b.c.f()` depende de `a.b.c`. Si el
  espacio de nombres no tiene ningún paquete normal por encima (`google/cloud/` sin
  `__init__.py`), otras distribuciones pueden completarlo: lo que el proyecto no tiene ahí
  se queda en aviso, nunca en hallazgo.
- **Extensiones compiladas y stubs**: un módulo sin `.py` que existe como binario (`.so`,
  `.pyd`), fuente Cython (`.pyx`), `module-name` de `[tool.maturin]` o solo stub `.pyi`
  aparece en el grafo marcado *(extensión compilada)* o *(solo stub)*, con su Ca exacto y
  su Ce como `?`: lo que importa el código compilado no se ve (los imports del `.pyi` son
  tipos, no dependencias). `from pkg import _native` y `from pkg._native import X` llevan
  al mismo nodo, sin aviso. La sección **Frontera nativa** dice, por módulo, qué lo
  prueba, cómo lo usa el código empaquetado (requeridos / perezosos / protegidos / solo
  tipos) y si funciona sin él; un binario que nadie importa no aparece. `.gitignore` no se
  aplica a stubs ni binarios (un `.so` compilado en su sitio suele estar ignorado por git y
  sí existe); `.unskeinignore` y `--exclude`, sí. Un nombre bajo código compilado nunca se
  informa como módulo inexistente: la extensión puede aportarlo.
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
- **Ciclos de dependencia**: módulos que acaban importándose a sí mismos al importar
  el código (imports a nivel de módulo).
  - Primero van las **marañas**: grupos donde cada módulo alcanza a todos los
    demás. Su tamaño es exacto aunque la lista de ciclos se corte.
  - Después, los **ciclos** como bucles de ejemplo, como máximo 100; el
    informe avisa cuando la búsqueda se detuvo en ese límite.
  - **Acoplamiento oculto** lista los grupos que dependen entre sí, o los grupos mayores
    que una maraña de las anteriores, solo si se cuentan los imports dentro de funciones
    o bajo `TYPE_CHECKING`. Esos imports no fallan al importar, pero siguen siendo
    acoplamiento de diseño y cuentan en el resto de números del informe.
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
  - **Violación de capas**: solo si declaras `[layers]`: un módulo de una capa inferior
    importa uno de una capa superior.
  - **Dependencia no declarada**: una distribución del repositorio importa otra que su
    manifiesto no declara; instalada sola, falla al importar.
  - **Dependencia opcional usada como requerida**: la declara solo en un extra, pero la
    importa al cargarse y sin `try`/`except ImportError`.
  - **Import de código no empaquetado**: importa código que ninguna distribución
    empaqueta (solo existe en el repositorio).
  - **Import de un módulo inexistente**: código empaquetado importa, al cargarse o en una
    función y sin protegerlo, un módulo del proyecto que no existe; al ejecutarse lanza
    `ImportError`. Los de `TYPE_CHECKING`, los protegidos y los de tests quedan como aviso.
    El arreglo nombra el módulo que define el símbolo, o dice que ninguno lo define.
  - **Extensión opcional usada como obligatoria**: el código protege el import de un
    módulo compilado (o solo stub) en un sitio, porque cuenta con que puede faltar, y lo
    importa sin protección en otros, donde lanza `ImportError` si falta. Lista las
    `ruta:línea` sin protección (hasta cinco, con el total); el arreglo es protegerlas igual
    o quitar el respaldo. Un nombre tomado de una fachada que lo importa en ese `try` también
    cuenta como protegido. No sigue el flujo de control: una comprobación previa
    (`if available():`) no se ve.
  - **Import con asterisco** (solo con `--star-fixes`, ver «Imports con asterisco y
    `--star-fixes`»): un hallazgo por módulo importado con `from x import *` fuera de una
    fachada, con el import explícito que escribir en cada sentencia cuando unskein puede
    demostrar que es seguro, y el motivo cuando no puede.
  - **Fuga de API** (solo con `--api-leaks`, ver «Fugas de API y `--api-leaks`»): código de
    fuera de un paquete que importa lo que el paquete mantiene interno, o rodea una fachada que
    ya ofrece el nombre, con el import que escribir en su lugar cuando unskein puede demostrar
    que es seguro, y la razón cuando no puede.
  - **Ciclo entre distribuciones**: distribuciones que se importan entre sí; dice qué
    arista cortar.

  Los umbrales son relativos al proyecto (percentiles, con un mínimo absoluto) y se
  pueden ajustar en `[findings]`. Los hallazgos nunca cambian el código de salida.
- **Problemas señalados (IA)**: solo con un modelo configurado. Cada problema
  tiene una severidad (`low`, `medium`, `high`), los módulos implicados y una
  recomendación. Los problemas que nombran módulos inexistentes se descartan,
  y el informe dice cuántos.
- **Advertencias del análisis**: archivos omitidos o imports que no se
  pudieron resolver (imports con asterisco fuera de las fachadas: sin analizar salvo que
  pases `--star-fixes`, y con ella solo los que no se pueden saber, porque el módulo no se
  pudo analizar o calcula su `__all__`; imports relativos fuera del paquete raíz, archivos demasiado grandes, no
  analizables o demasiado lentos, ciclos o cadenas de re-exports demasiado largas; un contrato
  `[api]` declarado con `--api-leaks` apagado). Una advertencia nunca detiene el análisis.

Los imports a través del `__init__.py` de un paquete se siguen hasta el módulo
que define el nombre, así que un ciclo escondido tras una fachada también
aparece. Eso incluye `import pkg as p` seguido de `p.nombre`: la dependencia va al
módulo que define `nombre`, salvo que no se pueda seguir el uso de `p` (se pasa como
valor, se reasigna o se escribe en él), y entonces se queda en el paquete. Los `from x import *` del
`__init__.py` de un paquete también se siguen.

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
| `--star-fixes` / `--no-star-fixes` | Calcula el import explícito de cada `from x import *` (desactivado por defecto; ver «Imports con asterisco»). |
| `--api-leaks` / `--no-api-leaks` | Señala los imports que entran en lo que un paquete mantiene interno, con el import que escribir en su lugar (desactivado por defecto). |
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

Otros comandos: `unskein init` y `unskein config save` (ver Configuración), `unskein guide` (esta
guía, `--lang` para elegir su idioma; `unskein guide > guia.md` la guarda) y
`unskein --version`.

## Imports con asterisco y `--star-fixes`

`from x import *` oculta qué nombres toma un módulo de `x`. Por defecto unskein no los
calcula: los lista como aviso («Imports con asterisco sin analizar») y el análisis no
cuesta nada más. Pasa `--star-fixes` (o pon `star_fixes = true` en `[analysis]` de
`.unskein.toml`) y calcula, para cada import con asterisco, el import explícito que
escribir:

```bash
unskein scan . --no-ai --star-fixes
```

El informe trae entonces un hallazgo «Import con asterisco» por cada módulo que otros
importan con `*`:

```
- `app.types` (5 módulos, 5 sentencias; usan de 0 a 4 de 4 nombres; 1 no usa nada)
  - `app/api.py:1`: `from app.types import A, B`
  - `app/dead.py:1`: eliminar (no usa nada; la línea carga `app.types` al importar, ...)
  - `app/m.py:1`: sin arreglo seguro: `app.b` puede dejar `Foo` sin ligar cuando corre la estrella (...)
```

Cómo leerlo y usarlo:

- **El arreglo solo se da cuando unskein puede demostrar que es seguro**, con el proyecto
  entero: los nombres que el módulo lee, los que otros módulos importan desde él o leen
  como atributos suyos, y los que pasan a quienes lo importan con asterisco. Ante la duda,
  el nombre se conserva. Un módulo que se usa entero, que se carga con
  `importlib.import_module` o que re-exporta un paquete sin `__all__` (API pública)
  conserva todos sus nombres.
- **«Sin arreglo seguro»** dice el motivo en vez de adivinar: un nombre puede quedar sin
  ligar cuando corre la estrella (se define bajo `TYPE_CHECKING`, dentro de un `if` o se
  borra), los dos módulos se importan entre sí, o el módulo lee un submódulo que otro
  módulo puede haber importado. Revísalos a mano.
- **«Eliminar»** significa que la sentencia no necesita ningún nombre. La línea aun así
  carga el módulo al importar, así que borrarla también quita los efectos de esa carga:
  compruébalo.
- **Antes de aplicar los arreglos**, ejecuta con `--include-tests` (un test puede importar
  un nombre a través del módulo) y analiza la raíz del proyecto, no la carpeta de un
  paquete, para que unskein reconozca tu código empaquetado.
- unskein nunca edita tus archivos: copias la línea.
- **Coste**: vuelve a leer los módulos implicados. En un proyecto de unos 2.900 módulos el
  análisis tardó entre un 15 y un 20 % más; con la opción apagada no cuesta nada.
- **Límites**: no ve los nombres leídos con `eval`, `globals()` o un `getattr` calculado.

## Fugas de API y `--api-leaks`

Un paquete tiene una parte pública y otra interna. Cuando código de fuera —otro paquete
raíz, otra distribución, un script o un plugin— importa la parte interna, el dueño no
puede refactorizar sin romperlo. unskein señala esos imports con el hallazgo **Fuga de
API**. Está desactivado por defecto; añade unos 0,05 s (alrededor de un 2 %) a un análisis
de un proyecto de 2.900 módulos, porque resuelve el módulo que escribió cada import y
demuestra cada arreglo.

```
unskein scan . --no-ai --api-leaks
```

También puedes poner `api_leaks = true` en `[analysis]` de `.unskein.toml`
(`--no-api-leaks` lo anula).

Qué cuenta como interno, por orden:

1. `[api]` en `.unskein.toml`. El prefijo más largo que coincida entre `public` e
   `internal` decide un módulo.
2. Si no, un módulo con un segmento `_privado` en su nombre.
3. Si no, es público. Aun así, importarlo se señala como *rodeado* cuando un paquete por
   encima ya ofrece el mismo nombre (`from lib.core.logger import Logger` cuando
   `from lib import Logger` funciona).

```toml
[api]
public = ["app.internal.contracts"]   # una excepción dentro de un prefijo interno
internal = ["app.internal"]
```

Los imports dentro del mismo paquete raíz nunca son fugas (para eso está `[layers]`). Una
sentencia que ya pasa por la fachada (`from lib import Logger`) nunca se señala, aunque el
grafo apunte al módulo que define el nombre. Un *nombre* privado tomado de un módulo
público (`from lib.util import _helper`) no es una fuga: la regla trata de módulos.

El informe tiene una entrada por módulo con cada sentencia debajo:

```
- `lib._private` (interno por convención de nombre; 2 módulos consumidores; 2 sentencias desde app 2)
  - `app/a.py:2`: sin arreglo seguro: ningún paquete ofrece `SECRET`; decide el dueño
  - `app/b.py:2`: sin arreglo seguro: importa un módulo, no un nombre
- `lib.core.logger` (rodeado: un paquete superior ofrece el nombre; 1 módulo consumidor; 1 sentencia desde app 1)
  - `app/a.py:1`: `from lib import Logger as L`
```

Un arreglo como ``from lib import Logger as L`` solo aparece cuando unskein puede demostrar
que es seguro: la sentencia es un `from x import nombre` normal; la fachada es un paquete
ancestro (importarla no carga nada que no cargara el original); cada módulo por el que pasa el
nombre lo importa con un único `from x import nombre` directamente en su cuerpo —no en un `if`,
una función o una clase, no con otro nombre, ni vuelto a ligar, borrado o escrito con
`globals()`—, y ningún submódulo de la fachada se llama igual; y la fachada no importa tu módulo
mientras se carga. Si no, la entrada dice por qué: *ningún paquete ofrece el nombre* (decide el
dueño: decláralo público en `[api]` o deja de depender de él), *solo lo ofrece un paquete que no
es ancestro*, *la fachada importa este módulo al cargarse*, *la fachada lo importa dentro de un
`try`*, *dentro de un `if`, una función o una clase*, *con otro nombre*, *la fachada vuelve a
ligar el nombre* o *importa un módulo, no un nombre*. Una fachada que solo importa el nombre de
forma condicional o con otro nombre no lo ofrece, así que rodearla no es una fuga. unskein nunca
edita archivos: copia la línea. Una sentencia con varios nombres se juzga nombre a nombre: mueve
los que tienen arreglo y deja el resto.

Lo que no ve: los nombres que una fachada sirve desde un `__getattr__` del módulo (carga
perezosa), una función que la fachada llama al cargarse y que importa tu módulo, las llamadas a
`importlib`, y el código que asigna un atributo de la fachada (`lib.Nombre = ...`).

Con `api_leaks` apagado y una tabla `[api]` declarada, el informe avisa «Contrato `[api]` sin
comprobar», para que un contrato que nada comprueba no pase desapercibido.

## Desenredar: `untangle`

`unskein untangle [RUTA]` planifica qué imports cortar para deshacer cada maraña. Para
cada una lista los imports a cortar, el paso de refactor más barato de cada uno y la
evidencia que lo apoya (archivo, línea y símbolos importados), y simula el resultado:
marañas, ciclos y acoplamiento de los módulos afectados, antes y después.

Los pasos, del más barato al más caro: mover bajo `TYPE_CHECKING` (nombres que solo
se usan en anotaciones), importar del módulo que lo define (el import pasa por el
`__init__.py` de un paquete que no define él mismo el nombre), import perezoso (nombres
que solo se usan dentro de funciones, o también en anotaciones si el módulo tiene
`from __future__ import annotations`), mover el símbolo (se importan uno o dos
símbolos), extraer un módulo compartido y revisar la estructura del paquete (un paquete
importando su propio submódulo, solo cuando nada más rompe el ciclo). Con `--all-edges`
solo se ofrecen los pasos estructurales, porque un import perezoso o bajo
`TYPE_CHECKING` conserva el acoplamiento. Ninguno de los dos se ofrece cuando otro
módulo lee alguno de los nombres a través del módulo origen (`from a import Thing`,
`a.Thing`, `from a import *`): el nombre dejaría de existir ahí. Los cortes salen de una heurística y la
simulación es optimista: léelo como un plan que hay que revisar.

Como `scan`, `untangle` respeta los ajustes `exclude` e `include_tests` de
`.unskein.toml`. Si algún archivo no se pudo analizar, el plan dice cuántas advertencias
del análisis hubo; `unskein scan` las muestra en detalle.

- `--all-edges`: desenreda también el acoplamiento oculto (imports dentro de funciones
  o bajo `TYPE_CHECKING`).
- `--max-tangles N`: cuántas marañas detallar, de mayor a menor (por defecto 5).
- `--output FICHERO` / `-o FICHERO`: guarda también el plan en Markdown.
- `--lang es|en`: idioma de la salida.

Códigos de salida: 0 si el plan se construyó (con o sin marañas), 1 en errores de uso y
3 en errores internos. `untangle` nunca llama a la IA.

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

unskein lee dos archivos, ambos opcionales:

- **Archivo del proyecto**: `.unskein.toml` (con el punto inicial) en la carpeta
  que **analizas**, no en la carpeta desde la que lanzas el comando.
  `unskein scan ~/code/app` lee `~/code/app/.unskein.toml`.
- **Archivo de usuario**: `~/.config/unskein/config.toml`, que se usa en todos
  los proyectos que analices. Es el sitio para tu modelo de IA cuando analizas
  proyectos que no son tuyos.

```bash
unskein init                # escribe ./.unskein.toml
unskein init --user         # escribe ~/.config/unskein/config.toml (crea la carpeta)
unskein init --force        # sustituye un archivo existente
unskein config save         # valida ./.unskein.toml y lo guarda como archivo de usuario
```

`init` acepta una carpeta (`PATH`, por defecto la actual), `--user`, `--force`
y `--lang` para sus mensajes. Escribe un archivo con todas las opciones comentadas en su valor por
defecto y una línea que explica cada una. Descomenta solo lo que quieras
cambiar. Nunca sobrescribe un archivo existente sin `--force`.

`config save` acepta un archivo (`SOURCE`, por defecto `./.unskein.toml`),
`--force` y `--lang`. Primero valida el archivo, así que una errata lo detiene
antes de escribir nada; después lo copia tal cual, comentarios incluidos, a
`~/.config/unskein/config.toml`, y crea la carpeta si hace falta. Nunca
sustituye un archivo de usuario existente sin `--force`. Un camino habitual:
`unskein init` en cualquier carpeta, editar el archivo, probarlo con
`unskein scan` y después `unskein config save`. Si el archivo lleva
`[ai] api_key`, se guarda legible solo por ti y verás un aviso: mejor usa la
variable `UNSKEIN_API_KEY`.

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

Para comprobar las capas de tu arquitectura, enuméralas de la más alta a la más baja
como prefijos de paquete:

```toml
[layers]
order = ["app.web", "app.services", "app.core"]
```

Un módulo pertenece a la capa con el prefijo más largo que coincida; un import de una
capa inferior a una superior se informa como violación de capas. Los módulos que no
están en ninguna capa no se comprueban, y sin `[layers]` no hay regla de capas.

Para declarar qué módulos son API pública y cuáles internos, usa `[api]` (ver «Fugas de API y
`--api-leaks`»): `public` e `internal` son listas de prefijos de módulo y decide el prefijo más
largo que coincida.

## Interpretación con IA

El paso de IA es opcional y pasa por LiteLLM, así que funciona con un modelo
local, un proveedor en la nube o un LiteLLM Proxy. Lo controlan tres ajustes:

| Ajuste | Variable de entorno | `.unskein.toml` | Qué es |
|---|---|---|---|
| Modelo | `UNSKEIN_AI_MODEL` | `[ai] model` | `proveedor/modelo`, como lo nombra LiteLLM. Sin él, no hay IA. |
| Clave de API | `UNSKEIN_API_KEY` | `[ai] api_key` | Opcional: si no está, LiteLLM lee la variable propia del proveedor (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`...). |
| Endpoint | `UNSKEIN_AI_API_BASE` | `[ai] api_base` | Solo para servidores locales, Azure y proxies. |

Las variables de entorno ganan a `.unskein.toml`. Guarda las claves en
variables de entorno: una clave escrita en `.unskein.toml` puede acabar en git.

unskein lee variables de entorno, no archivos `.env`. Para usar uno, cárgalo
antes en tu shell (`set -a; source .env; set +a`) o con una herramienta como
direnv. El `.env.example` del repositorio enumera las variables.

### Proveedores

| Proveedor | `model` | Clave y endpoint |
|---|---|---|
| Ollama (local) | `ollama/qwen2.5-coder:7b` | `api_base` `http://localhost:11434`; sin clave |
| OpenAI | `openai/<modelo>` | `OPENAI_API_KEY` |
| Claude (Anthropic) | `anthropic/<modelo>` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini/<modelo>` | `GEMINI_API_KEY` |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY`, `AZURE_API_VERSION` y `api_base` (la URL de tu recurso) |
| AWS Bedrock | `bedrock/<id del modelo>` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |
| Mistral | `mistral/<modelo>` | `MISTRAL_API_KEY` |
| Groq | `groq/<modelo>` | `GROQ_API_KEY` |
| DeepSeek | `deepseek/<modelo>` | `DEEPSEEK_API_KEY` |
| LiteLLM Proxy | `litellm_proxy/<alias>` | `api_base` (la URL del proxy) y tu clave virtual |
| Servidor compatible con OpenAI (LM Studio, vLLM) | `openai/<modelo>` | `api_base` (p. ej. `http://localhost:1234/v1`); cualquier clave no vacía (p. ej. `sk-local`) si el servidor no la comprueba |

Sustituye `<modelo>` por un modelo actual del proveedor; la documentación de
LiteLLM lista los nombres. `UNSKEIN_API_KEY` puede sustituir a cualquiera de
las claves de arriba, salvo las credenciales de AWS. Algunos ejemplos:

```bash
# Claude
export UNSKEIN_AI_MODEL="anthropic/<modelo>"
export ANTHROPIC_API_KEY="sk-ant-..."

# Azure OpenAI
export UNSKEIN_AI_MODEL="azure/mi-deployment"
export UNSKEIN_AI_API_BASE="https://mi-recurso.openai.azure.com"
export AZURE_API_KEY="..."
export AZURE_API_VERSION="2024-10-21"

# LiteLLM Proxy
export UNSKEIN_AI_MODEL="litellm_proxy/mi-alias"
export UNSKEIN_AI_API_BASE="https://litellm.example.com"
export UNSKEIN_API_KEY="sk-..."
```

O, para un modelo sin secreto, en `.unskein.toml`:

```toml
[ai]
model = "ollama/qwen2.5-coder:7b"
api_base = "http://localhost:11434"
```

Los modelos de razonamiento solo aceptan temperatura 1, y unskein la elige
según lo que LiteLLM sabe del modelo. Un alias de proxy puede llamarse de
cualquier forma, así que con los modelos `litellm_proxy/` unskein pregunta
antes al proxy (`/model/info`, con la misma clave) si el alias es un modelo de
razonamiento.

Para comprobar la configuración, ejecuta `unskein scan . --verbose`: una línea
con los tokens usados indica que el modelo respondió. Si el informe no tiene
sección de IA, explica por qué.

Qué sale de tu equipo: nombres de módulos y sus métricas (acoplamiento,
ciclos, marañas). Nunca código fuente. Con `--no-ai` o un modelo local, nada.
unskein no tiene telemetría de ningún tipo.

Si el modelo falla, no responde a tiempo (60 s en llamadas directas; detrás
de un proxy, decide el proxy) o responde con un formato incorrecto, el
informe se genera igual sin la sección de IA y explica por qué. La respuesta
llega en el idioma del informe.

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
sitio. `--star-fixes` añade trabajo (entre un 15 y un 20 % en un proyecto de 2.900
módulos) y está desactivada por defecto; `--api-leaks` añade un 2 % (0,05 s) y también está
desactivada por defecto.

## Problemas frecuentes

- **«No se encontraron archivos .py»**: revisa la ruta, y que `.gitignore`,
  `.unskeinignore` o `--exclude` no lo estén excluyendo todo. Los tests se
  omiten por defecto.
- **Imports marcados como no resueltos**: puede que tus paquetes estén fuera
  de la raíz y de `src/`; define `source_roots`.
- **Sin sección de IA**: no hay modelo configurado, o se pasó `--no-ai`. El
  informe dice cuál de los dos.
- **«No se pudo contactar con el modelo (AuthenticationError)»**: falta la
  clave o es incorrecta. Revisa `UNSKEIN_API_KEY` o la variable del proveedor.
- **«…(NotFoundError)» o «(BadRequestError)»**: el nombre del modelo es
  incorrecto o falta el prefijo del proveedor (`anthropic/`, `azure/`...).
  `--verbose` muestra el mensaje del proveedor.
- **«El modelo no respondió a tiempo»**: prueba un modelo más rápido; con un
  modelo local grande, uno más pequeño.
- **«La respuesta del modelo no cumple el formato esperado»**: habitual en
  modelos locales pequeños. Vuelve a intentarlo o usa un modelo mayor.
- **Idioma equivocado**: pasa `--lang`, o define `UNSKEIN_LANG` o
  `[general] lang`.
- **Un bug**: abre un issue en https://github.com/mapenzo/unskein/issues con
  la salida de `--verbose`.
