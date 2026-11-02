---
title: No registrar como respuestas del usuario cosas que no dijo
author: Miguel
date: 2026-11-02
standing: true
id: l-4db3a1be
scope: repo
status: active
src: init-sessions
touches:
  - docs/product-context.md
---

## Watch out
- Un plan anterior anotó tres respuestas que el usuario nunca dio, y otro mensaje llegó con una plantilla sin rellenar. Esto contaminó ADR y contexto hasta que se auditó.
- In the code: Antes de escribir en `docs/product-context.md` o en un ADR, comprobar que cada respuesta existe en la conversación. Si llega un texto como «Elijo [A o B]», tratarlo como sin responder y volver a preguntar.

_From past Claude sessions here, Oct 13._
