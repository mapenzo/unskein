# Contexto de producto: unskein
Última revisión: 2026-10-13

## Qué es
CLI open source (MIT) de análisis estático de imports en Python a nivel módulo:
grafo, acoplamiento Ca/Ce, ciclos al importar, plan de cortes (`untangle`) y
comprobación de cortes sobre una copia (`--prove`). — [leído de CLAUDE.md, 2026-10-12]

## Estado actual
v0.3.0 publicada (alpha, CHANGELOG 2026-10-01); `develop` (`d8668a6`, 2026-10-11) con
`untangle --prove`, API leaks, star imports, módulos nativos, sin publicar. Sin salida
JSON; `[contexts]` solo propuesto; sin soporte de `lazy import` (Python 3.15). — [leído
de CHANGELOG, git y código, 2026-10-13]

## Usuario objetivo y problema
- Usuario y dolor: equipos con un monolito que quieren desacoplarlo, strangularlo,
  crear microservicios o modernizarlo. — [dicho por el developer, 2026-10-12]
- Cómo lo resuelve hoy: con una herramienta de pago, import-linter o Tach. — [dicho
  por el developer, 2026-10-13]
- Qué probó el mantenedor: CAST Imaging; los clientes no quisieron pagar ese precio. Por
  eso crea una herramienta que «radiografíe» un proyecto y demuestre con evidencias cómo
  desacoplarlo para modernizarlo. — [dicho por el developer, 2026-10-13]

## Diferenciación buscada
Radiografiar un monolito Python y aportar evidencias comprobadas de cómo desacoplarlo,
sin el coste de CAST Imaging. — [confirmada por el developer, 2026-10-13]

## Principios del proyecto
No negociables (marcados por el developer): ninguno marcado (confirmado por el
developer, 2026-10-12).
Declarados, no marcados: separación grafo determinista / IA; cero telemetría; offline;
LiteLLM sin SDKs de proveedores; `--prove` nunca toca el proyecto; `--run` es lo único
que ejecuta código del proyecto; los hallazgos nunca cambian el código de salida — [leído
de CLAUDE.md, 2026-10-12]

## Restricciones
- Tiempo disponible: 5-10 h/semana. — [dicho por el developer, 2026-10-13]
- Equipo: un único mantenedor. — [dicho por el developer, 2026-10-12]
- Presupuesto: 0 €. — [dicho por el developer, 2026-10-13]
- Límites laborales o de propiedad intelectual: no sé (preguntado 2026-10-13). Corrige
  el registro anterior («sin límites»), que venía de una pregunta compuesta.

## Éxito
- A 6 y 12 meses: un caso real (un equipo con un monolito Python que use unskein). —
  [dicho por el developer, 2026-10-12]
- Cuál de los dos horizontes: no sé (preguntado 2026-10-12).

## Suposiciones abiertas
- Sin clientes ni ex-clientes a quienes preguntar (dicho 2026-10-13): el descubrimiento
  es en frío y puede no dar conversaciones.
- Qué exigiría ese caso real (JSON, CI, Django) no está contrastado con ningún equipo.
- Si los cortes comprobados sobreviven a la suite de tests de un proyecto Django: sin
  medir; lo mide el caso del ADR 0002.
- Lo que unskein hace mejor que import-linter o Tach fuera de litellm no está medido.
- Sonargraph/SonarQube Architecture: no verificado si ofrecen cortes comprobados para Python.
- Límites laborales o de propiedad intelectual: desconocidos; condicionan publicar casos
  o cobrar.
  Tarea: revisar el contrato de empleo o preguntar a quien corresponda en la empresa — el
  mantenedor (antes de publicar el triage o el PR del ADR 0002). Plazo: esta semana (hasta
  2026-10-18) — [dicho por el developer, 2026-10-13].

## Fuentes leídas
CLAUDE.md, README, CHANGELOG, docs/research/*, código (`prove.py`, `python_parser.py`),
git (rama develop), ADR 0001-0002 y borrador, 2026-10-13; respuestas del developer en las
sesiones del 2026-10-12 y 2026-10-13.
