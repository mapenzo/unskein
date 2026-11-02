# `untangle --prove` outside litellm: reproduction of the README figures

Date: 2026-11-02. Source of the figures: the author's own runs (self-reported, one
maintainer). Context: ADR 0004 requires every figure published in the README to carry a
version or commit and the command that reproduces it.

## Command

```bash
git clone --depth 1 <repository> <dir>
unskein untangle <dir> --prove          # static verdict only; no --run, no project tests
```

unskein at `d8668a6` (`develop`, 2026-10-11). Python 3.14 (`uv run`).

## Results

| Project | Commit (HEAD cloned 2026-11-02) | Cuts proven | Not proven | Broken |
|---|---|---|---|---|
| rich | `9d8f9a3` (2026-06-23) | 5 of 29 | 24 | 0 |
| networkx | `a325f6a` (2026-10-31) | 7 of 32 | 25 | 0 |
| aiohttp | `a2c6c92` (2026-11-01) | 0 of 1 | 1 | 0 |
| litellm | `a93c396a5c` (benchmark of the design specs; not rerun today) | 218 of 240 | 22 | 0 |

The first three match the figures reported on 2026-10-10 (rich 5/29, networkx 7/32,
aiohttp 0/1) on the current HEAD of each project. litellm is the project the feature was
developed against and was not rerun here: the 218/240 figure comes from
`CHANGELOG.md` (commit `a93c396a5c`, the benchmark of the design specs).

## What "proven" means here

The static verdict marks a cut as proven when the import edge is gone after re-analyzing a
temporary copy (`src/unskein/prove.py`, `_static_verdict`). Neither that verdict nor `--run`
runs the project's test suite; `--run` only imports the tangle's modules. On rich, the
5 proven cuts leave the tangle in place (tangles 1, cycles 100+ after applying them).
