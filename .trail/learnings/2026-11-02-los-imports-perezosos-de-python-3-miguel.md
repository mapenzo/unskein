---
title: "Los imports perezosos de Python 3.15 se tratan como imports normales, no como ciclos ocultos"
author: Miguel
date: 2026-11-02
standing: true
id: l-ba945cae
scope: repo
status: active
src: init-review
---

## Tried and ruled out
- Se descartó clasificar 'lazy import' como perezoso: según PEP 810 si un módulo accede al otro al importar, el ciclo sigue fallando. Eso ocultaría ciclos reales (falso negativo).
- In the code: Tratar `lazy import` y `__lazy_modules__` como arista MODULE (ImportKind.MODULE). Con Python ≤3.14 da SyntaxError: saltar el archivo con aviso explícito. No usar LAZY para ellos.

_From this repo's docs._
