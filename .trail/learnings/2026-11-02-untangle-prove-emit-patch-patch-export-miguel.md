---
title: Untangle --prove --emit-patch (patch export of PROVEN cuts) was dropped on 2026-10-11…
author: Miguel
date: 2026-11-02
id: l-82573fe2
scope: repo
status: active
touches:
  - docs/research/killer-features.md
---

## Decided
`untangle --prove --emit-patch` (rank 1 of docs/research/killer-features.md, local-only, git-excluded) is out of scope. The user chose not to ship it without conclusive data.

**Why:** PROVEN only means the analyzer no longer sees the import-time edge (`--run` only checks that modules still import). Nobody ran a project's test suite before/after the patch. The attempt on litellm `tests/unit` (37,543 tests) was killed by the system for low memory, so there is no result. Proof rate also does not generalize: litellm 218/240, rich 5/29, networkx 7/32, aiohttp 0/1; a tangle remains in every project. Moving imports into functions changes when side effects run and where ImportError appears. Subset re-prove stayed 100% PROVEN on litellm, rich, networkx (static only, no `--run`).

## Watch out
do not propose or build a patch/diff export, or the GitHub suggestion-block variant, unless the user brings behavioral evidence (test suite equal before/after on real projects). If revisited, run the suite in chunks with `-n 4` and repeat the baseline once to separate flaky tests. See litellm-review-roadmap.

_From Claude Code's memory of this repo, last updated Oct 11._
