# 0004. README y ficha de PyPI de la v0.4.0: edición mínima más ejemplo nuevo

- **Estado:** propuesta
- **Fecha:** 2026-11-02 (memo del 2026-10-13, guardado hoy)
- **Tipo:** posicionamiento

## Contexto
El ADR 0002 (propuesta), punto 2, manda publicar la v0.4.0 con README y ficha de PyPI
que usen el lema provisional del ADR 0003 (propuesta). Falta decidir qué se cambia en
esos dos textos. El README actual abre con «tells you … which knots are worth cutting
first» (`README.md:24`), su único ejemplo es el informe v0.1 con «Problems flagged (AI)»
(`README.md:38-62`), la nota de estado dice «alpha (v0.3.0)» (`README.md:31`) y afirma que
ninguna herramienta open source revisada propone cortes (`README.md:123-125`), cosa que
el propio repo contradice (`docs/research/gap-analysis.md:332`). El resumen de PyPI
empieza por «AI-assisted» (`pyproject.toml:4`), pero la IA es opcional.

## Decisión
Edición mínima del README y de la ficha de PyPI, más el cambio del ejemplo:

1. **Encabezado.** Lema corto arriba («See what ties your Python monolith together, and
   which import cuts undo it.») y el lema del ADR 0003, en inglés, como primer párrafo,
   con el aviso de que `--run` ejecuta los módulos del proyecto en subprocesos aislados y
   de que nada ejecuta sus tests. El lema corto es texto nuevo, de criterio.
2. **Frase sobre la competencia.** Sustituir «ninguna herramienta propone cortes» por: import-linter
   (vía grimp) puede nominar un conjunto mínimo de imports a quitar; unskein elige además
   un paso concreto de Python por import y reanaliza una copia. Sin «único», «primero» ni
   «ninguno».
3. **Cifras.** Tabla con litellm 218/240, rich 5/29, networkx 7/32 y aiohttp 0/1, cada
   cifra con versión o commit y el comando que la reproduce. Las tres de fuera de litellm
   no tienen archivo de origen: se reejecutan y se guardan en `docs/research/`, o no se
   publican. litellm se presenta como el proyecto sobre el que se desarrolló la función.
4. **Ejemplo.** Sustituir el informe v0.1 por una captura real de `untangle --prove` con
   la build de la v0.4.0 (por ejemplo sobre rich); no se escribe a mano.
5. **Python 3.15.** Badge y classifier solo con 3.15 en verde en el CI. El README dice que
   `lazy import` se trata como import normal (puede marcar un ciclo que en ejecución no
   ocurre, nunca oculta uno) y que con Python ≤3.14 el archivo se salta con un aviso;
   antes se comprueba que el aviso exista en `python_parser.py`.
6. **PyPI.** Resumen que encabece con lo determinista, palabras clave `circular-imports`,
   `import-cycles`, `monolith`, `refactoring`, banner con URL absoluta (comprobar con
   `curl -I` el tipo de contenido del SVG en `raw.githubusercontent.com`) y nota de estado
   «alpha (v0.4.0)».
7. **Sin promesas** de separar contextos o fronteras (`[contexts]` no existe), ni «único»
   ni «probado».
8. **Orden.** CI con 3.15 en verde, README, ficha, versión 0.4.0 y `[0.4.0]` fechado en el
   CHANGELOG, guías `guide.{es,en}.md` al día, y render con `readme-renderer[md]` antes de
   publicar.

Resumen de PyPI propuesto: «Map the import cycles in your Python monolith, plan the cuts
that undo them, and check each cut on a copy. Free, works offline, no telemetry.»
«Offline» es cierto con `--no-ai` o con Ollama local; con un modelo en la nube sale la
llamada al LLM y el README ya lo dice en Privacy.

## Alternativas consideradas
- Edición mínima sin cambiar el ejemplo — retirada por el ataque: un lema determinista
  sobre una demo de IA se contradice.
- Reescritura completa del README — descartada por capacidad (5-10 h/semana) y porque la
  evidencia del caso con tests aún no existe.
- Encabezar con el diagnóstico (ciclos, acoplamiento oculto, frontera nativa) en vez de
  con los cortes — queda como alternativa si el triage de Django da una tasa cercana al
  19 %.
- Lema largo solo, sin lema corto — el lema del ADR 0003 tiene unas 40 palabras.

## Argumentos en contra y respuesta
- El lema encabeza con la función con menos respaldo fuera de litellm (≈19 %, cifras del
  mantenedor, autoinforme sin archivo de origen). → Se muestran ambas cifras y el lema
  es provisional (ADR 0003). Riesgo aceptado.
- «Antes de cortar tu monolito» puede atraer a quien busca fronteras, que unskein no
  ofrece. → Sin promesas de contextos (punto 7). La demanda observada en competidores es
  de JSON y fronteras (import-linter #291, #262, #240; tach #584, #678, #680, #759).
- Publicar sin soporte completo de `lazy` la semana de Python 3.15. → Decisión del
  mantenedor en el ADR 0002 (variante Y, 2026-10-13); el README lo documenta.
- El lema pone `--run` junto a «offline, sin telemetría» sin decir que ejecuta código.
  → Aceptado: se añade el aviso (punto 1).

## Ataque a la decisión
- Versión atacada: la inicial, de seis cambios. La final (con el ejemplo nuevo, el aviso de
  `--run` y el lema corto) no se atacó de nuevo.
- Quién: subagente independiente (`product-devils-advocate`), 2026-10-13.
- Qué recibió el revisor: solo la recomendación y la evidencia.
- Qué cambió por el ataque: «mínima» pasa a «mínima más ejemplo nuevo»; se añade el aviso
  de `--run` en el lema. Rechazado: el subagente usó una memoria anterior al ADR 0002
  final (umbral NetBox 70 %, soporte de `lazy` en las semanas 1-2); ambos están retirados
  o decididos.
- Sin verificar por el revisor: versión de `nominate_cycle_breakers` en grimp.

## Evidencia
- README sin ejemplo de `--prove`, nota «alpha (v0.3.0)», frase «ninguna herramienta
  propone cortes» — lectura del repo — 2026-10-13.
- import-linter/grimp `nominate_cycle_breakers`, `drawgraph --show-cycle-breakers` —
  `docs/research/gap-analysis.md:332` y documentación de import-linter — 2026-10-13.
- readme-renderer deja relativo `docs/assets/banner.svg`, así que PyPI no lo mostrará —
  ejecución local — 2026-10-13. Mermaid y la alerta `[!NOTE]` sin renderizar en PyPI —
  inferido, no verificado.
- CI con 3.12-3.14 (`.github/workflows/ci.yml:26`), `develop` en `d8668a6`, PyPI en 0.3.0
  — git y API de PyPI — 2026-11-02. Sin cambios desde el 2026-10-13.
- `_static_verdict` da PROVEN si la arista ya no está al reanalizar —
  `src/unskein/prove.py:539` — 2026-10-13.
- Cifras de cortes: litellm 218/240; rich 5/29, networkx 7/32, aiohttp 0/1 — autoinforme
  — 2026-10-10.

## Confianza
Media. La corrección de los datos es sólida. El lema es una apuesta: ningún usuario
externo lo ha leído y fuera de litellm el acierto es del 19 %.

## Principios del proyecto afectados
Ninguno. Ninguna restricción marcada como no negociable.

## Qué haría revisar esta decisión
- Triage de Django del ADR 0002 con una tasa de cortes comprobados claramente mejor:
  justifica el lema largo; cercana al 19 %: encabezar con el diagnóstico.
- Resultado del caso con tests: recuperar «se comprueban» (ADR 0003).
- Que alguien externo pida «dime qué import cortar», o que un competidor publique cortes
  comprobados (import-linter, Tach, Sonargraph, SonarQube Architecture).
- Tarea pendiente de límites laborales o de propiedad intelectual («no sé», preguntado
  2026-10-13; plazo 2026-10-18, ya vencido; sin respuesta registrada): revisar el contrato
  o preguntar a quien corresponda en la empresa — el mantenedor. No bloquea el README;
  sí el triage y el PR. No es asesoría legal.
- Revisión obligatoria el 2027-01-12, con los ADR 0002 y 0003.

## Consecuencias
- Cambian `README.md`, `pyproject.toml`, `CHANGELOG.md`, `ci.yml` y las guías; nada en
  `src/`.
- Hasta 2026-11-02, 20 días sin commits en `develop`: el calendario de 1,4-2,8 semanas
  para la v0.4.0 del ADR 0002 ya se ha agotado.
- Mantenimiento: bajo; hay que reproducir las cifras al cambiar la versión.
