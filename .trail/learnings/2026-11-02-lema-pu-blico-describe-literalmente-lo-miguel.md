---
title: "Lema público describe literalmente lo que se comprueba, no promete que el corte funciona"
author: Miguel
date: 2026-11-02
standing: true
id: l-c25e3104
scope: repo
status: active
src: init-review
touches:
  - docs/decisions/0003-lema-provisional-literal.md
---

## Decided
- El veredicto de prueba da Proven cuando la arista desaparece al reanalizar la copia, y --run solo comprueba que los módulos importan. Ninguno ejecuta tests, así que 'se comprueban' se leería como 'funciona'.
- In the code: README y ficha de PyPI de v0.4.0 usan el lema del ADR 0003 (docs/decisions/0003-lema-provisional-literal.md). No escribir 'separa contextos' ni 'cortes comprobados' hasta el caso con tests. Revisión obligatoria 2027-01-12.

_From this repo's docs._
