---
title: La lista de ciclos debe ser estable sin importar la semilla de hash
author: Miguel
date: 2026-11-02
standing: true
id: l-a19b747b
scope: repo
status: active
src: init-review
---

## Watch out
- Enumerar ciclos sobre conjuntos de cadenas cambiaba los ciclos reportados con PYTHONHASHSEED, contradiciendo el orden determinista prometido.
- In the code: Enumerar ciclos con etiquetas enteras (índice en nombres ordenados) y mapear de vuelta. El test ejecuta find_cycles con cuatro semillas de hash.

_From PR #28 here, Sep 30._
