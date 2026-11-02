---
title: User wants unskein to stand out in the GitHub landscape
author: Miguel
date: 2026-11-02
id: l-789622d1
scope: repo
status: active
touches:
  - CLAUDE.md
  - docs/research/2026-10-01-grafo-dependencias-almacenamiento-visualizacion.md
  - docs/research/2026-10-01-plan-de-desenredo.md
  - docs/research/2026-10-01-diff-de-arquitectura.md
  - docs/superpowers/specs/2026-10-01-cycle-precision-untangle-design.md
  - docs/superpowers/plans/2026-10-01-cycle-precision-alias-access.md
  - docs/superpowers/plans/2026-10-01-untangle.md
  - "src/unskein/parsers/rewrite.py#_ReadScanner._mentions"
  - "src/unskein/parsers/usage.py#_mentions"
---

## Decided
On 2026-10-01 the user asked me to act as researcher/innovator beside them: unskein must not be "one more tool" on GitHub, it must stand out with **killer** features.

**Why:** the dependency-analysis space is crowded (pydeps, import-linter, tach, dependency-cruiser, emerge); parity features won't get adoption.

## Watch out
when proposing features, benchmark against those tools and lead with what none of them do (unskein's edge = deterministic graph + AI interpretation, offline, ES/EN). Flag when an idea is merely parity. Still respect CLAUDE.md design rules (graph vs AI separation, zero telemetry, offline). First research output: docs/research/2026-10-01-grafo-dependencias-almacenamiento-visualizacion.md (JSON contract + Mermaid + offline HTML/DSM). Related: project-v02-adaptive-semaphore.
…

_From Claude Code's memory of this repo, last updated Oct 1._
