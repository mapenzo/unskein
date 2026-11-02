---
title: "Borrar el borrador al escribir el ADR numerado, para no tener dos planes"
author: Miguel
date: 2026-11-02
standing: true
id: l-a1457def
scope: repo
status: active
src: init-sessions
touches:
  - docs/decisions/0002-hoja-de-ruta-oct-2026-ene-2027.md
---

## Decided
- Había un borrador en `drafts/` y un ADR 0002 antiguo en el repo con contenidos distintos, y las sesiones se confundían sobre cuál valía. Se decidió dejar una sola versión.
- In the code: Al aceptar o escribir `docs/decisions/0002-hoja-de-ruta-oct-2026-ene-2027.md`, eliminar `docs/decisions/drafts/2026-10-12-hoja-de-ruta-oct-ene.md`. Los datos de la puntuación RICE van en `docs/decisions/data/` y se reproducen con `rice.py`.

_From past Claude sessions here, Oct 13._
