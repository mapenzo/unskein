# 0003. Lema provisional literal hasta tener el caso con tests

- **Estado:** propuesta
- **Fecha:** 2026-10-13
- **Tipo:** posicionamiento

## Contexto
El ADR 0001 (aceptado) fija el lema de hoy: «… qué cortes los deshacen y cuáles se
comprueban sobre una copia». El quinto ataque a la hoja de ruta (ADR 0002) mostró que
el veredicto estático de `untangle --prove` da PROVEN cuando la arista ya no aparece al
reanalizar la copia (`src/unskein/prove.py:539`), y que `--run` solo comprueba que los
módulos importan. Ninguno ejecuta tests. «Se comprueban» se lee como «funciona», y la
v0.4.0 se publicaría antes del caso con tests que podría respaldarlo.

## Decisión
Sustituir el lema de hoy del ADR 0001, solo hasta tener el resultado del caso con tests
del ADR 0002, por:

«Antes de cortar tu monolito Python, mira qué lo ata: tus ciclos de import, qué cortes
los deshacen, cuáles desaparecen al reanalizar una copia y cuáles importan sin error
con `--run`. Gratis, offline, sin telemetría.»

El segundo tiempo del ADR 0001 (`[contexts]`) no cambia.

## Alternativas consideradas
- Mantener el lema del ADR 0001 con una aclaración — la aclaración se lee menos que el
  lema; se publicaría antes de la evidencia.
- Quitar del lema cualquier mención a comprobar — pierde lo que distingue a unskein de
  import-linter y Tach según la evidencia del ADR 0001.

## Argumentos en contra y respuesta
- El lema literal es más largo y menos vendedor. → Es provisional; si el caso sale
  bien, se recupera «se comprueban» con la evidencia del caso.
- «Importan sin error con `--run`» puede leerse también como «funciona». → Dice
  exactamente lo que `--run` hace; el caso con tests mide lo demás.

## Ataque a la decisión
- Versión atacada: ninguna como ADR propio. La decisión nace del quinto ataque a la
  hoja de ruta (subagente independiente `product-devils-advocate`, 2026-10-13, que solo
  recibió la recomendación y la evidencia).
- El texto del lema provisional no se atacó, por decisión del mantenedor (2026-10-13).

## Evidencia
- `_static_verdict` da PROVEN si la arista ya no está en el grafo reanalizado —
  `src/unskein/prove.py:539` — 2026-10-13.
- `--run` importa los módulos de la maraña antes y después en subprocesos aislados —
  `CLAUDE.md`, sección de decisiones de diseño — 2026-10-13.
- Cortes comprobados sin ejecutar tests: litellm 218/240; fuera de litellm ≈19 % —
  autoinforme — 2026-10-10.

## Confianza
Media. El texto describe lo que el código hace; no hay datos de cómo lo leen usuarios.

## Principios del proyecto afectados
Ninguno.

## Qué haría revisar esta decisión
- Resultado del caso con tests y PR del ADR 0002: si la suite y el CI del proyecto pasan
  con los cortes, recuperar «se comprueban»; si fallan, mantener el lema literal.
- Que `--prove` pase a ejecutar tests.
- Revisión obligatoria el 2027-01-12, con el ADR 0002.

## Consecuencias
- README y ficha de PyPI de la v0.4.0 usan este lema.
- El ADR 0001 pasa a «aceptada; lema de hoy sustituido provisionalmente por 0003».
- Mantenimiento: ninguno.
