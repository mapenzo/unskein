# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- AI interpretation: with a model configured, the report gains a summary, an
  architecture health rating and problems with severity, produced through LiteLLM (any
  provider, local Ollama or a LiteLLM Proxy). The AI only sees module names and
  metrics; its answer is checked against the dependency graph, so it cannot name a
  module that does not exist. If the call or the answer fails, the report is still
  produced with a notice saying why. `--min-severity` and exit code 2 now apply to it.
  Loosely written module names (quoted, with a trailing dot, or as file paths) are
  matched to the graph; problems that still name no real module are discarded, and the
  console and the report say how many.
- Initial project scaffold: `src/` layout, pipeline contracts, test fixtures, CI.
- Python import parser: absolute, relative and submodule imports, `is_external`
  detection, re-export detection in `__init__.py`, per-file warnings instead of crashes
  (syntax errors, undecodable files, oversized files, deeply nested code).
- Automatic `src/` layout detection and configurable `source_roots`.
- Test code excluded from analysis by default; `--include-tests` to opt back in.
- Re-export resolution: imports through `__init__.py` facades now point at the module
  that defines the symbol, so cycles hidden behind a package facade become visible.
  Re-export cycles produce a single warning per cycle.
- Dependency graph and coupling metrics: afferent/efferent coupling and instability per
  module, dependency cycles (capped at 100, deterministic order) and the most coupled
  modules by nearest-rank percentile of `Ca + Ce`.
- Configuration loading: `~/.config/unskein/config.toml` merged with the project's
  `.unskein.toml` (project wins), validated so typos and wrong types are reported with
  the file and field; env vars and CLI flags on top. API keys never appear in `repr`
  or error messages.
- `--no-include-tests` and `--no-follow-symlinks`, so a flag can override
  `.unskein.toml` in both directions.
- `unskein scan` works end to end: Markdown report in English or Spanish (terminal via
  rich, raw file with `-o`), warnings grouped by kind with paths relative to the
  project, `--verbose` stats and `--log-file`. The AI section explains why it is
  empty (disabled, not configured, or the call failed).
- Exit codes are enforced: usage errors now exit with 1 (click's default 2 collided with
  "high-severity problems found"), unexpected errors exit with 3 showing the traceback.
- Pylint configuration aligned with the Clean Code rules, for IDEs.
- Tangles: groups of mutually dependent modules (strongly connected components),
  exact and never truncated, shown before the cycle list with their size, so a
  "100+ cycles" report reveals it is really one knot of, say, 279 modules (#8).

### Fixed

- `--verbose` now reports the real peak memory of the run. It used to read the resident
  memory after the analysis, so memory freed before the end was invisible (a 200 MB
  spike showed as 21 MB) (#9).
- Printing the report to a Windows pipe (cp1252) no longer crashes with an internal
  error on symbols such as "→"; unencodable characters are replaced.

### Changed

- The placeholder notice about the AI arriving later is gone: the report now says
  either that the AI is disabled or not configured, or why the call failed.
- Precedence for non-secret options is now flag > env var > `.unskein.toml` (so
  `--lang` beats `UNSKEIN_LANG`); secrets keep env var > `.unskein.toml` > `--api-key`.
- Analysis warnings are now structured (`ParseWarning` with a `WarningCode`, file, line
  and language-neutral detail) instead of English strings, so reports can translate
  them and group them by kind.
- Clean Code is now a mandatory project convention: Google-style docstrings on every
  module, class and function (private ones included), enforced in CI with ruff's `D`
  rules plus an AST-based test that also covers private names.
- Parser data classes moved from `unskein.parsers.base` to `unskein.parsers.models`
  (still importable from `unskein.parsers`), removing an import cycle.
- LiteLLM is now required at `>=1.95.0,<2`. The AI client resolves how to call the
  model once (reasoning models get `temperature=1.0`, JSON-schema output when the model
  supports it, a 60 s limit for direct calls) and never lets LiteLLM download its price
  map or send telemetry.
