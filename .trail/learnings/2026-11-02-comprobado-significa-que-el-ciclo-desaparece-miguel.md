---
title: "\"Comprobado\" significa que el ciclo desaparece al reanalizar, no que los tests pasen"
author: Miguel
date: 2026-11-02
standing: true
id: l-92a89c18
scope: repo
status: active
src: init-sessions
touches:
  - src/unskein/prove.py
  - "src/unskein/prove.py#_static_verdict"
---

## Watch out
- La revisión adversarial mostró que el lema sobrepromete: la comprobación solo reanaliza la copia y `--run` solo verifica que los módulos importan. Ninguna ejecuta los tests del usuario.
- In the code: En README y mensajes de `--prove` aclarar el alcance de "se comprueban". La lógica está en `_static_verdict` de `src/unskein/prove.py`. No afirmar que los tests pasan hasta tener el caso con tests antes y después.

_From past Claude sessions here, Oct 13._
