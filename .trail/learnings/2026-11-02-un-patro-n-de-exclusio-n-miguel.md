---
title: Un patrón de exclusión con barra en medio solo vale desde la raíz
author: Miguel
date: 2026-11-02
standing: true
id: l-62a55c74
scope: repo
status: active
src: init-review
touches:
  - tests/unit/test_discovery.py
---

## Watch out
- El README sugería excluir migraciones con un patrón anclado a la raíz, que no alcanzaba las migraciones anidadas de Django.
- In the code: Usar `--exclude "migrations/"` (cualquier profundidad) o `**/migrations/**`, no `migrations/**`. Test en tests/unit/test_discovery.py.

_From PR #27 here, Sep 30._
