---
title: Quitar imports de módulo no es seguro si otros módulos leen esos nombres a través de él
author: Miguel
date: 2026-11-02
standing: true
id: l-9d624ad4
scope: repo
status: active
src: init-review
---

## Watch out
- Los pasos lazy y TYPE_CHECKING quitan del módulo los nombres que el import enlaza, y se bloqueaban solo si otro los importaba por nombre. Eso ocultaba lectores como `import pkg.a; pkg.a.Thing`, `getattr(a, ...)` o estrellas.
- In the code: Antes de ofrecer LAZY o TYPE_CHECKING usar `parsers/usage.collect_names_read_from`, que recorre acceso por atributos y re-lee importadores. Un importador ilegible cuenta como lector de todo.

_From PR #46 here, Oct 1._
