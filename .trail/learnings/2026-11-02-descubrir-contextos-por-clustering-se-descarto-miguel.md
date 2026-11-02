---
title: "Descubrir contextos por clustering se descartó: el spike no lo demostró"
author: Miguel
date: 2026-11-02
standing: true
id: l-bd566019
scope: repo
status: active
src: init-review
---

## Tried and ruled out
- Un spike en Zulip y NetBox no estableció que el clustering encuentre bounded contexts fiables.
- In the code: No implementar descubrimiento automático de contextos por clustering. Cualquier función de fronteras parte de contextos declarados por el usuario en `[contexts]`.

_From this repo's docs._
