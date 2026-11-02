---
title: Unskein branching model
author: Miguel
date: 2026-11-02
id: l-e40a3272
scope: repo
status: active
touches:
  - "src/unskein/cli.py#main"
---

## Decided
Remote: https://github.com/mapenzo/unskein (public). Since 2026-09-27: `develop` (created from `main`) is the working/integration branch; `main` receives PRs. The initial scaffold landed via PR #1 (merge commit, old `master` branch deleted).

**Why:** user set up a develop/main split after merging the scaffold PR.

## Watch out
start feature work from `develop` (feature branches → PR into `develop` unless told otherwise); never commit directly to `main`. Local graft tooling (`.claude/`, `.mcp.json`, `.ignore`) is the user's personal setup — gitignored via PR #3 (2026-09-27), never force-add it. Small changes also go branch → PR into `develop` (user accepted this flow for PRs #2 and #3).
…

_From Claude Code's memory of this repo, last updated Sep 28._
