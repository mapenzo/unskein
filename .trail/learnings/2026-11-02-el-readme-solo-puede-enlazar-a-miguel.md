---
title: El README solo puede enlazar a archivos versionados; las notas de investigación locales no cuentan
author: Miguel
date: 2026-11-02
branch: docs/readme-pypi-v0.4.0
cost: { minutes: 1, tokens: 1343 }
id: l-2bdaf9a8
scope: repo
status: active
src: agent
touches:
  - docs/prove-outside-litellm.md
  - README.md
---

## Decided
La nota que reproduce las cifras del README (cortes comprobados en litellm, rich, networkx, aiohttp) vive en una ruta versionada, because un enlace a una carpeta local queda roto en GitHub y en PyPI.

## Tried and ruled out
Guardar la nota en la carpeta de investigación y enlazarla desde el README. Se descartó because esa carpeta (y la de specs) está excluida en el clon y no se sube; otherwise el enlace fallaba para cualquier lector.

## Watch out
- Antes de enlazar un archivo desde el README, comprobar que está versionado; otherwise the link fails con un 404.
- Un agente de revisión puede apoyarse en recuerdos de planes ya retirados; contrastar con el estado final del plan, because si no se reabren decisiones cerradas.

In the code:
- `docs/prove-outside-litellm.md` (versionado), enlazado desde `README.md`.
- Exclusión local: `.git/info/exclude` (`docs/research/`); `git ls-files docs` solo lista `architecture.md` y `assets/`.
- Comando de las cifras: `unskein untangle <dir> --prove` con unskein `d8668a6`.
