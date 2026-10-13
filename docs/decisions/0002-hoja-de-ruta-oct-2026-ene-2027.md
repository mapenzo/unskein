# 0002. Hoja de ruta 2026-10 → 2027-01: release, descubrimiento y caso con tests

- **Estado:** propuesta
- **Fecha:** 2026-10-12 (versión final 2026-10-13)
- **Tipo:** hoja de ruta

## Contexto
Hay que priorizar qué construir en los próximos tres meses (2026-10-13 → 2027-01-12).
Un solo mantenedor, 5-10 h/semana y 0 € de presupuesto (dicho por el mantenedor,
2026-10-13). Objetivo: «un caso real», un equipo con un monolito Python que use unskein;
horizonte de 6 o 12 meses: no sé (preguntado 2026-10-12). Diferenciación: «radiografiar
un monolito Python y aportar evidencias comprobadas de cómo desacoplarlo, sin el coste de
CAST Imaging» (confirmada por el mantenedor, 2026-10-13). El mantenedor probó CAST Imaging
y sus clientes no quisieron pagar ese precio; hoy no tiene clientes ni ex-clientes a los
que preguntar (dicho por el mantenedor, 2026-10-13). Ningún usuario externo conocido.
`develop` lleva 19.094 líneas sin publicar desde v0.3.0 (2026-10-01): `untangle --prove`,
fugas de API, imports con asterisco y módulos nativos. Python 3.15 se publicó el
2026-10-09 con `lazy import` (PEP 810), y unskein no lo soporta.

## Decisión
1. Python 3.15 (variante Y, elegida por el mantenedor el 2026-10-13): 3.15 en la matriz
   del CI dentro de la release. `lazy import` y `__lazy_modules__` se tratan como un
   import normal (arista MODULE) y el README lo dice: puede marcar un ciclo que en
   ejecución no ocurre, nunca oculta uno. Con Python ≤3.14 un `lazy import` da
   `SyntaxError` y el archivo se salta con un aviso que lo diga.
2. Publicar v0.4.0. README y ficha de PyPI con el lema provisional del ADR 0003, que
   describe literalmente lo que se comprueba, hasta tener el resultado del caso.
3. Descubrimiento en frío con equipos desconocidos que tengan un monolito Python,
   1 h/semana todo el trimestre, sin demo: preguntar qué les bloquea al desacoplarlo.
   Objetivo: 2 conversaciones. Lo hace el mantenedor; unskein no contacta a nadie.
4. Caso con tests antes y después en un proyecto público. Antes, triage con
   `untangle --prove` en 2-3 monolitos Django públicos, publicando el resultado de todos.
   El caso sigue solo si hay 5 o más cortes comprobados, alguno de tipo TYPE_CHECKING o
   de anotaciones aplazadas; si no, se publica el triage y no se hace el caso. Se aplican
   los cortes, se ejecuta la suite del proyecto antes y después y se ofrecen los cortes
   como PR al proyecto, cuyo CI da la evidencia de comportamiento. El PR lo abre el
   mantenedor; unskein no contacta a nadie.
5. Al cerrar el caso, ver «Ramas condicionales».

## Capacidad y calendario
- Capacidad: 5-10 h/semana x 13 semanas / 40 = 1,6-3,3 semanas a tiempo completo (FT).
- Esfuerzos: estimados, no medidos en el código; la sensibilidad de rice.py los duplica.
- Conjunto de datos: `d89c70f7` (rice.py, 2026-10-13); entrada en
  `docs/decisions/data/0002-rice-d89c70f7.json`, reproducida con `rice.py` el 2026-10-13. Sustituye a X `03640384`,
  Y `687bf069` y `61762fc6`; el PR suma 0,05 FT al caso.

| Paso | E (FT) | Semanas naturales | Acumulado | h/sem para caber | ¿Cabe con 5 h/sem? |
|---|---|---|---|---|---|
| v0.4.0 + 3.15 en CI | 0,35 | 1,4-2,8 | 1,4-2,8 | 1,1 | sí |
| Descubrimiento (1 h/sem, repartido) | 0,33 | 1,3-2,6 | 2,7-5,4 | 2,1 | sí |
| Caso con tests y PR | 0,8 | 3,2-6,4 | 5,9-11,8 | 4,6 | sí |

- Punto de decisión: semana natural 5,9-11,8, al cerrar el caso.
- Margen con la dedicación mínima (5 h/sem), el que cuenta: 0,15 FT ≈ 5,8 h. Está dentro
  del error de estimación (<25 % de lo comprometido): se trata como nulo.
- Margen con la dedicación alta (10 h/sem), solo si se mantiene: 1,77 FT ≈ 70,8 h.
- Con sensibilidad (E x2), el caso (1,6 FT) no cabe con 5 h/sem.
- Ramas condicionales (alternativas excluyentes desde el final del caso):
  - Con 5 h/sem: nada más.
  - Con dedicación alta: salida JSON (0,75; desde 6,9 h/sem) o `[contexts]` (2,5;
    12,2 h/sem, no cabe). Lazy correcto (0,25; 5,3 h/sem) queda «al límite» según
    `rice.py`: se trata como que no cabe y no se ofrece como rama.
  - Si el descubrimiento da un equipo: lo que pida solo cabe con 5 h/sem si cuesta
    ≤5,8 h; si no, se aplaza o exige dedicación alta.
- Umbrales:
  - 2 conversaciones de descubrimiento — de criterio.
  - Caso: ≥5 cortes comprobados con alguno TYPE_CHECKING o de anotaciones aplazadas —
    de criterio (propuesto por el tercer revisor).
  - Éxito del caso: la suite y el CI del proyecto pasan con los cortes — de criterio.
  - PR aceptado — de criterio; no depende del plan.
- Robustez del orden: NO robusta. Con sensibilidad, el descubrimiento pasa delante de
  la release; no cambia la ejecución (va en paralelo).

## Alternativas consideradas
- Soporte mínimo de `lazy` (todo `lazy` como LAZY, E 0,15) — retirado por el cuarto
  ataque: PEP 810 dice que si un módulo accede al otro al importar, el ciclo sigue
  fallando; clasificarlo como LAZY ocultaría ciclos reales (falso negativo).
- Escenario A original (prueba mínima de instalación y `scan` en 3.15) — sustituido: el
  tercer ataque mostró que las wheels ya existen (p. ej. jiter 0.17.0 con cp315,
  PyPI 2026-09-12) y la prueba aportaba poca información. Lo sustituyó el soporte
  mínimo de `lazy`, retirado después (ver arriba); 3.15 entra en el CI en X y en Y.
- Escenario B (publicar sin probar 3.15) — descartado al elegir A (mantenedor, 2026-10-13).
- Variante X, lazy correcto antes de la release (E 0,25) — con ella el caso no cabía
  con 5 h/sem; queda como alternativa con dedicación alta (mantenedor, 2026-10-13).
- Lema del ADR 0001 con una aclaración en la v0.4.0 — el quinto ataque mostró que se
  publicaba antes del caso que lo valida; sustituido por el lema provisional del ADR 0003.
- Soporte completo de 3.15 (emitir cortes como `lazy`, semántica de «potencialmente
  perezoso») — degradado POR CRITERIO: un monolito tardará en exigir 3.15; ningún dato
  mide la adopción de `lazy` ni de `__lazy_modules__`.
- Spike en NetBox con bifurcación 30 % / 70 % — resultado previsible (fuera de litellm,
  19 %) y la rama más probable no cabía. Umbral retirado (era de criterio).
- Contactar con demo desde la semana 1 — gasta los primeros contactos sin resultado de
  comportamiento en Django.
- Descubrimiento con ex-clientes — no hay (mantenedor, 2026-10-13).
- Caso sobre código de un cliente — no hay clientes.
- `[contexts]` completo — 2,5 FT, no cabe.
- Salida JSON — demanda real en competidores y paridad; solo con dedicación alta.
- `--prove --run-tests` como producto — sin demanda; el caso ejecuta los tests a mano.
- Gate CI `--fail-on` — commodity y choca con un principio declarado.
- Adaptador Django, Mermaid, otros lenguajes — puntuación baja o esfuerzo fuera de alcance.

## Argumentos en contra y respuesta
- La demanda observada en competidores pide JSON, fronteras y Django, no cortes de
  ciclos. → El descubrimiento pregunta justo eso. Riesgo aceptado: el diferenciador no
  tiene señal de demanda.
- «Se comprueban sobre una copia» se lee como «funciona», pero el veredicto estático
  solo mira si la arista sigue al reanalizar (`_static_verdict`,
  `src/unskein/prove.py:539`). → La v0.4.0 usa el lema literal del ADR 0003; el caso
  con tests y el CI del proyecto deciden si se recupera «se comprueban».
- Sin soporte de `lazy`, unskein puede marcar ciclos que en 3.15 no ocurren. → Se
  documenta y se aplaza (error por exceso, no oculta ciclos). Inferido, no ejecutado;
  con 3.15 publicado el 2026-10-09, pocos monolitos lo usarán este trimestre (de
  criterio). El quinto revisor no encontró argumento fuerte en contra.
- `is_lazy` aparece en la gramática de `ast` de 3.15, no en las firmas documentadas de
  las clases (cuarto revisor, 2026-10-13; no reverificado). → Riesgo de API poco
  documentada; no se usa en este trimestre (variante Y).
- El descubrimiento en frío, sin canal ni red, puede no producir el caso real; con 389
  descargas/mes (CI incluido) el cuello de botella puede ser la visibilidad. → Se
  publica el triage completo, que también da visibilidad. Riesgo aceptado; de criterio.
- Montar la suite de un monolito Django (bases de datos y colas) puede costar más de
  0,75 FT. → Hipótesis del cuarto revisor, no verificada. El triage va primero y decide;
  con E x2 el caso no cabe con 5 h/sem.
- El caso sobre un proyecto público informa poco si solo salen cortes LAZY, que casi
  nunca rompen tests. → Umbral del triage: exige TYPE_CHECKING o anotaciones aplazadas.
  De criterio.
- Margen escaso con 5 h/sem (≈5,8 h). → Nada se promete más allá del paso 4.
- 19.094 líneas en una sola release de un solo mantenedor. → Riesgo aceptado; de
  criterio (quinto revisor).
- Descubrimiento en frío sin red de clientes: puede dar 0 conversaciones. → Riesgo
  aceptado; el objetivo mide respuestas, no envíos.

## Ataque a la decisión
- Quién: subagentes independientes (`product-devils-advocate`); solo recibieron la
  recomendación y la evidencia, sin el razonamiento.
- Primer ataque (2026-10-12), contra la versión inicial (3.15 → v0.4.0 → spike →
  30/70 %). Cambió: entra el contacto con equipos, 3.15 baja, el spike pasa a caso con
  tests, se retira el umbral 30/70.
- Segundo ataque (2026-10-12), contra la versión intermedia. Cambió: motivo de la
  degradación de 3.15 (de criterio), prueba mínima de 3.15 pendiente de decisión,
  descubrimiento sin demo, aclaración de «se comprueban». Rechazado: la fecha de 3.15.
- Tercer ataque (2026-10-13), contra el escenario A. Verificado y aceptado: unskein no
  lee `is_lazy` ni `__lazy_modules__` (grep); 3.15 respeta `__lazy_modules__` (What's New
  3.15); import-linter 2.15 añadió lazy imports a `explore` y `drawgraph` (notas de
  versión, 2026-09-04). Aceptado como de criterio: el caso informa poco si solo hay
  cortes LAZY. Corrección: What's New 3.15 solo documenta los modos `normal` y `all`; el
  modo `none` es del PEP 810. Rechazado: `drawgraph --show-cycle-breakers` desde la 2.10
  (no aparece en las notas de versión). Cambió: lazy mínimo sustituye a la prueba de
  instalación, objetivo de 2 conversaciones, umbral del triage.
- Cuarto ataque (2026-10-13), contra la versión con soporte mínimo de `lazy`
  (conjunto `61762fc6`). Verificado y aceptado: PEP 810, «if either module accesses the
  other during import time, you'll still get an error» y «Lazy imports don't
  automatically solve circular import problems» (peps.python.org, consultado
  2026-10-13). Aceptados como de criterio: descubrimiento en frío débil, posible
  subestimación del caso. Sin verificar: `is_lazy` fuera de las firmas documentadas;
  coste de montar las suites Django. Sin argumento fuerte contra publicar v0.4.0.
  Cambió: se retira el soporte mínimo; quedan las variantes X e Y. Confianza que dio:
  media.
- Quinto ataque (2026-10-13), contra la variante Y (conjunto `687bf069`). Verificado y
  aceptado: el veredicto estático de `--prove` solo comprueba que la arista desaparece
  (`src/unskein/prove.py:539`) y el lema salía antes del caso. Refutado: riesgo de
  wheels cp315 en el CI (tiktoken 0.14.0, tokenizers 0.23.3 abi3, pydantic-core
  2.50.1 y jiter 0.17.0 tienen wheel, PyPI 2026-10-13) y que import-linter 2.15 no
  exista (PyPI, 2026-09-04). Rechazado por la semántica, sin ejecutar: que los cortes
  TYPE_CHECKING sean los que menos cambian el comportamiento (en ejecución el nombre
  no existe). Aceptado como de criterio: PR de los cortes al proyecto analizado; riesgo
  de una release grande. Cambió: lema provisional (ADR 0003) y PR al final del caso.
  Confianza que dio: media.
- Versión final (esta, conjunto `d89c70f7`): NO atacada de nuevo, por decisión del
  mantenedor (2026-10-13). Sin atacar: el lema provisional y el PR al proyecto.
- Incidencia: la sesión 820748da registró como respuestas del mantenedor tres datos que
  no dio (diferenciación confirmada, clientes perdidos, código de clientes no usable). Se
  detectó en los logs el 2026-10-13 y se volvieron a preguntar; este texto solo usa las
  respuestas reales.

## Evidencia
- Python 3.15.0 publicado el 2026-10-09 — python.org — consultado 2026-10-12.
- PEP 810 Final: `lazy` solo a nivel de módulo; por debajo de 3.15 `__lazy_modules__`
  se ignora; los imports quedan «potencialmente perezosos» — peps.python.org —
  consultado 2026-10-12. Acceder al objeto lo reifica; si un módulo accede al otro al
  importar, el ciclo sigue fallando — peps.python.org — consultado 2026-10-13.
- unskein ya clasifica dónde se lee cada nombre importado (`_lazy_applies`,
  `src/unskein/graph/steps.py:92`) — lectura del código — 2026-10-13.
- What's New 3.15: respeta `__lazy_modules__`; documenta los modos `normal` y `all` —
  docs.python.org — consultado 2026-10-13.
- En 3.15, `ast.Import` e `ImportFrom` tienen el campo `is_lazy` —
  docs.python.org/3.15/library/ast — consultado 2026-10-12.
- `src/unskein/parsers/python_parser.py` no lee `is_lazy` ni `__lazy_modules__` — grep —
  2026-10-13. `ImportKind.LAZY` ya existe (línea 94).
- Con Python ≤3.14, `lazy import` da `SyntaxError` al parsear — prueba local — 2026-10-12.
- El CI prueba 3.12-3.14 — `.github/workflows/ci.yml:26` — 2026-10-13.
- Wheels para 3.15: tiktoken 0.14.0 (14 cp315), tokenizers 0.23.3 (16 abi3),
  pydantic-core 2.50.1 (30 cp315), jiter 0.17.0 (27 cp315) — API de PyPI — 2026-10-13.
- `--prove` da PROVEN cuando la arista ya no aparece al reanalizar la copia; `--run`
  solo importa los módulos — `src/unskein/prove.py:539` y `CLAUDE.md` — 2026-10-13.
- import-linter 2.15 (2026-09-04) añade lazy imports a `explore` y `drawgraph` — notas
  de versión (sesión 820748da) y fecha en PyPI — consultado 2026-10-13.
- v0.3.0 con fecha 2026-10-01 — `CHANGELOG.md:113` (el tag es del 2026-10-02).
- 19.094 líneas añadidas desde v0.3.0 hasta `develop` — `git diff --shortstat` —
  2026-10-12. `develop` sin commits nuevos desde `d8668a6` (2026-10-11) — git — 2026-10-13.
- Descargas del último mes, CI incluido: unskein 389, import-linter 21,2 M, tach 4,6 M
  — pypistats — 2026-10-12.
- Demanda de JSON: import-linter #291 (comentario 2026-09-15), tach #678, #680 — issues.
- Demanda de fronteras declaradas: import-linter #262, #240; tach #584, #759 — issues
  — 2024-2025.
- Tach PR #596 lee `INSTALLED_APPS` y `ForeignKey("app.Model")` — repo — 2025-02-05.
- En su documentación, ni import-linter, Tach, Sonargraph, SonarQube, Structure101 ni
  ArchUnit proponen y comprueban cortes entre grupos declarados; import-linter tiene
  `nominate_cycle_breakers` — docs — consultadas 2026-10-12.
- Cortes probados, sin ejecutar tests: litellm 218/240 (proyecto sobre el que se
  desarrolló la funcionalidad); rich 5/29, networkx 7/32, aiohttp 0/1 (19 % fuera de
  litellm) — autoinforme, sin archivo de origen en el repo — 2026-10-10.
- Spike Zulip/NetBox: el 24-27 % del código queda sin alcanzar por el cableado dinámico
  de Django — autoinforme (`docs/research/spike-slices-zulip-netbox.md`) — 2026-10-11.
- CAST Imaging desde ~7.000 USD/año — proveedor (ADR 0001) — 2026-10-12.
- RICE+D (R estimado, C con techo del 50 %): v0.4.0 + 3.15 8,57; descubrimiento 4,55;
  lazy correcto 2,0; caso con PR 1,88; JSON 1,33; `[contexts]` 1,2. No robusto —
  `rice.py`, conjunto `d89c70f7` — 2026-10-13.

## Confianza
Media-baja. La release es barata y resiste cinco ataques; la versión final no se atacó. El caso depende de que
el triage encuentre un proyecto que pase el umbral. Que aparezca un equipo no depende del
plan y no hay red de clientes. Todas las cifras de unskein son autoinformes.

## Principios del proyecto afectados
Ninguno en lo decidido. El caso ejecuta los tests a mano, fuera de unskein. Los
aplazados chocarían con principios declarados, no marcados como no negociables:
`--run-tests` con «`--run` es lo único que ejecuta código del proyecto», y el gate CI
con «los hallazgos nunca cambian el código de salida».

## Qué haría revisar esta decisión
- Que las conversaciones de descubrimiento pidan fronteras, JSON o Django en vez de cortes.
- Resultado del caso: si la suite y el CI del proyecto pasan, se revisa el ADR 0003
  para recuperar «se comprueban»; si fallan, se mantiene el lema literal.
- Que ningún monolito del triage pase el umbral.
- Uso real de `lazy` o `__lazy_modules__` en monolitos: sube el soporte completo.
- Que import-linter, Tach, Sonargraph o SonarQube Architecture publiquen propuesta o
  comprobación de cortes.
- Límites laborales o de propiedad intelectual: «no sé» (preguntado 2026-10-13). Tarea
  pendiente antes de publicar el triage o el PR: revisar el contrato de empleo o preguntar a
  quien corresponda en la empresa — el mantenedor. No es asesoría legal.
- Revisión obligatoria el 2027-01-12.

## Consecuencias
- CI con 3.12-3.15.
- Release por Trusted Publishing; README y ficha de PyPI con el lema del ADR 0003; el
  README dice que `lazy` se trata como import normal.
- Triage y caso no tocan `src/`; sus notas van a `docs/research/`.
- Mantenimiento: bajo. Nada nuevo en la superficie del CLI.
- Pendiente de evaluar: emitir el corte LAZY como `lazy import` en proyectos que exigen
  Python ≥3.15.
