---
title: "Los cortes probados solo deshacen ciclos al importar, no separan contextos"
author: Miguel
date: 2026-11-02
standing: true
id: l-bc133435
scope: repo
status: active
src: init-review
---

## Tried and ruled out
- Se rechazó prometer 'medir fronteras y cortes que las separan' porque los cortes LAZY y TYPE_CHECKING solo aplazan el import y la función de contextos no existe.
- In the code: No documentar ni nombrar `[contexts]` como disponible. El segundo tiempo del lema exige validar `[contexts]` en un proyecto ajeno con tests iguales antes y después.

_From this repo's docs._
