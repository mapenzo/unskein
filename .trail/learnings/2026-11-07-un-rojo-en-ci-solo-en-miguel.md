---
title: "Un rojo en CI solo en Python 3.14 puede venir del parche del runner, no del PR"
author: Miguel
date: 2026-11-07
branch: docs/readme-pypi-v0.4.0
cost: { minutes: 20, tokens: 129930 }
id: l-e0c558f7
scope: repo
status: active
src: agent
touches:
  - docs/decisions/0004-readme-y-ficha-pypi-v0.4.0.md
  - tests/unit/test_python_parse.py
  - src/unskein/parsers/python_parser.py
---

## Decided
Cuando un check falla en todos los PR a la vez (incluido uno solo de docs) y solo en una versión de Python, primero se compara el parche exacto del runner con el local antes de culpar al código. Se arregla en una rama aparte contra develop, para no depender de PRs externos.

## Tried and ruled out
Fijar 3.14.2 en la matriz de CI: oculta el problema en vez de arreglar el test.

## Watch out
CPython 3.14.2 lanza RecursionError al parsear 100.000 sumas encadenadas y 3.14.4 las parsea, así que el test pasaba en local y fallaba en el runner. El test debe aceptar ambos resultados (parseado, o saltado con un PARSE_ERROR). Los jobs de 3.15 fallan aparte porque maturin no compila pyo3-ffi; no añadir el classifier de 3.15 hasta que pasen.

In the code: tests/unit/test_python_parse.py::test_deeply_nested_expression_is_warned_not_raised; parser captura RecursionError en src/unskein/parsers/python_parser.py:674; PR #66.
