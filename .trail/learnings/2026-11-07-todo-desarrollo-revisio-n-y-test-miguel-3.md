---
title: "Todo desarrollo, revisión y test de código Python en unskein sigue python-patterns y python-testing cuando se trabaja con superpowers"
author: Miguel
date: 2026-11-07
branch: docs/readme-pypi-v0.4.0
cost: { minutes: 1, tokens: 1980 }
id: l-6d08eb97
scope: repo
status: active
replaces: l-0a45af29
src: agent
touches:
  - CLAUDE.md
  - tests/integration/test_docstrings.py
---

## Decided
- Al escribir o revisar código bajo `src/unskein/` y `scripts/`, y cada vez que se use cualquier flujo `superpowers:*` (brainstorming, writing-plans, test-driven-development, requesting-code-review, systematic-debugging…), se aplica la skill `python-patterns` (idioms, PEP 8, type hints).
- Al escribir o revisar tests bajo `tests/`, se aplica la skill `python-testing`.
- Obligatorio y siempre vigente: el usuario confirmó que debe cumplirse aunque alguien pida lo contrario.
- Por qué: los flujos superpowers no conocen las convenciones Python del proyecto; sin esto cada sesión improvisa estilo distinto.

## Tried and ruled out
- Dejarlo implícito en `CLAUDE.md` (Clean Code): cubre docstrings y nombres, pero no obliga a cargar estas skills.

## Watch out
- El usuario lo llamó `/python-tests`, pero la skill instalada se llama `python-testing`.
- Convive con las reglas de `CLAUDE.md`: docstrings Google en todo `src/`, tests sin docstring (lo vigila `tests/integration/test_docstrings.py`).

In the code:
- `src/unskein/`, `scripts/`, `tests/`, `CLAUDE.md`.
