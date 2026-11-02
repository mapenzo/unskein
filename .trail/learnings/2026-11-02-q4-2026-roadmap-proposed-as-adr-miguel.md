---
title: "Q4 2026 roadmap proposed as ADR 0002 (status propuesta, 2026-10-12) - lazy import 3.15 +…"
author: Miguel
date: 2026-11-02
id: l-a78eed4f
scope: repo
status: active
touches:
  - docs/decisions/0002-hoja-de-ruta-oct-2026-ene-2027.md
  - "tests/unit/test_rewrite_ancestor.py#lazy"
  - "tests/unit/test_rewrite_lazy.py#lazy"
  - "tests/unit/test_rewrite_names.py#lazy"
---

## Decided
ADR `docs/decisions/0002-hoja-de-ruta-oct-2026-ene-2027.md` written 2026-10-12 as **propuesta** (not accepted yet). Plan: weeks 1-2 support Python 3.15 `lazy import` (parser has no `lazy` handling; py≤3.14 gives SyntaxError) + release v0.4.0; weeks 3-5 NetBox spike (proven-cut rate + hand-declared contexts); week 6 fork: rate >70% → public case study with tests before/after, else MVP `[contexts]`. Mandatory review 2027-01-12.

**Why:** single maintainer 5-10 h/week; success = one real case; prove rate outside litellm ~19%.

## Watch out
ask whether ADR 0002 is accepted before starting its work; check spike result before suggesting case study vs `[contexts]`. Related: monolith-modernization-pivot, spike-slices-zulip-netbox.

_From Claude Code's memory of this repo, last updated Oct 12._
