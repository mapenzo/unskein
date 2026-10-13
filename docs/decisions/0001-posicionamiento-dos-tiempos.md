# 0001. Posicionamiento en dos tiempos para equipos con monolito

- **Estado:** aceptada; lema de hoy sustituido provisionalmente por 0003
- **Fecha:** 2026-10-12
- **Tipo:** posicionamiento

## Contexto
El público objetivo son equipos con un monolito Python que quieren desacoplarlo,
strangularlo o modernizarlo. Se compararon import-linter, Tach, Sonargraph /
SonarQube Architecture y CAST Imaging. Ninguno de los hallazgos verificados muestra
una herramienta gratuita y offline que, para Python, agrupe los ciclos al importar y
dé un paso comprobado por corte; no se afirma que sea único (ver "No verificado").
`[contexts]` aún no existe y el descubrimiento de contextos no quedó establecido.

## Decisión
Dos tiempos. Hoy: «Antes de cortar tu monolito Python, mira qué lo ata: tus ciclos
de import, qué cortes los deshacen y cuáles se comprueban sobre una copia. Gratis,
offline, sin telemetría.» Solo tras validar `[contexts]` en un proyecto ajeno:
«Declara tus fronteras y mide qué las cruza y qué cortes hacen falta para separarlas.»

## Alternativas consideradas
- Solo el lema de ciclos — se queda corto para el público de monolitos.
- Prometer ya «medir fronteras y cortes que las separan» — `[contexts]` no existe y
  los cortes probados (LAZY, TYPE_CHECKING) deshacen ciclos al importar, no separan contextos.
- Descubrir bounded contexts por clustering — el spike en Zulip/NetBox no lo estableció.
- Posicionarse como linter de arquitectura — terreno de import-linter y Tach.

## Argumentos en contra y respuesta
- Los cortes probados solo aplazan el import → el lema de hoy solo promete ciclos al
  importar; el segundo tiempo exige evidencia de aristas eliminadas.
- La medición básica ya existe gratis en Tach e import-linter → se posiciona como
  complemento (plan de cortes), no como sustituto.
- El público grande pide JSON, CI y Django → declarado como suposición abierta; el
  caso real contrastará qué exigen.

## Evidencia
- import-linter: contratos declarados, `acyclic_siblings` sugiere cortes mínimos, sin JSON (#291), imports de función en #230 — repo/doc — 2026-10-12
- Tach: módulos declarados, mantenido hoy por un voluntario tras abandono de los autores (2025-06), ciclos sin camino (#476) — repo — 2026-10-12
- Sonargraph: Python 3 listado; cortes y refactorings virtuales de pago (Team 60 EUR/usuario/mes, mín. 5); offline y aplicación a Python no verificados — proveedor — 2026-10-12
- SonarQube Architecture: Python, ediciones de pago, directivas humanas, sin plan automático documentado — proveedor — 2026-10
- CAST Imaging: desde ~7.000 USD/año, 32 GB RAM, profundidad en Python no clara; «450+ lenguajes / 90.000 reglas» sin fuente — proveedor — 2026-10-12
- Proof en litellm: 218/240, 0 rotos; rich 5/29, networkx 7/32, aiohttp 0/1; sin ejecución de tests — autoinforme — 2026-10-10

## Confianza
Media-baja. Los datos sobre unskein son autoinformes sobre proyectos elegidos por el
mantenedor, sin usuarios externos. El ataque independiente dio baja confianza a la
versión inicial; esta la estrecha a lo respaldado.

## Principios del proyecto afectados
Ninguno. No hay principios marcados como no negociables (confirmado 2026-10-12).

## Qué haría revisar esta decisión
- `[contexts]` implementado y probado en un monolito ajeno (idealmente Django) con
  tests del proyecto iguales antes y después.
- Desglose de las 218 de litellm por tipo de corte con una parte relevante de
  BYPASS_FACADE.
- Sonargraph o SonarQube Architecture con cortes comprobados para Python.
- Un equipo externo que diga que import-linter o `tach report` no le bastan.

## Consecuencias
- El README y la ficha de PyPI deben usar solo el lema de hoy; nada de «separa contextos»
  hasta la revisión.
- Prioridad del caso real: conseguir un equipo con monolito y hacer el experimento de tests antes/después.
- Salida JSON y código de salida por hallazgos del grafo, a decidir con ese caso.
- Coste de mantenimiento: ninguno nuevo.

## No verificado
- Que no exista una herramienta con esa combinación: solo se buscó en estos competidores.
