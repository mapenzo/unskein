---
title: "Strategic pivot (2026-10-11) - unskein targets monolith modernization (understand app,…"
author: Miguel
date: 2026-11-02
id: l-6fee228e
scope: repo
status: active
touches:
  - CLAUDE.md
  - "src/unskein/cli.py#untangle"
  - "tests/unit/test_prove.py#prove"
---

## Decided
User pivot, own words: wants unskein for **modernizing monolithic applications**: (1) understand how the app is built, (2) steps to split the monolith (Strangler Fig pattern), (3) an external companion tool, to be created together with Claude, to run **EventStorming**. User asked Claude to act as innovator/domain expert on this.

**Why:** after dropping `--emit-patch` (emit-patch-shelved) and a differentiation/audience discussion, the user wants a clear niche beyond cycle-cutting (cut-set is not novel, see competitor-cycle-measurements).

**Working thesis (corrected after spike):** unskein must NOT promise to discover bounded contexts. Code lacks that information. EventStorming workshop supplies domain intent; unskein supplies structural evidence and extraction readiness for boundaries humans declare.
Defensible half = "verify declared boundaries":
1. `[contexts]` contract (modelled on `[layers]`): measure what crosses declared boundaries - edges, cycles, shared kernel, provable cuts needed to separate them.
2. Map of shared kernel vs private parts per slice (entry-point closures).
3. Django adapter for dynamic wiring (include("app.urls") strings, webhooks discovery, templatetags, registries) that the import graph cannot see.
4. JSON export for the EventStorming companion tool.

## Watch out
- Next step proposed, NOT yet approved: cheap spike using NetBox Django apps as declared contexts (e.g. dcim vs ipam): cross-app edges, cuts the planner proposes, how many provable. Reuses `untangle`/`prove`. Ask user before starting it or any design work.
- Nothing in `src/` changed for this pivot. CLAUDE.md scope (module level, Python only, "full architecture map" = phase 2) not reopened; needs user's OK first.
- Companion EventStorming tool: user wants to build it together; not started.
- Spike evidence: spike-slices-zulip-netbox.

_From Claude Code's memory of this repo, last updated Oct 11._
