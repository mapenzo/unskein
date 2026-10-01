# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Layer check: declare your layers in `[layers] order` of `.unskein.toml` (highest first,
  as package prefixes) and the findings report every import that goes from a lower layer
  up into a higher one. A module belongs to the layer with the longest matching prefix
  (whole name segments); modules in no layer are not checked. Shown also with `--no-ai`,
  given to the AI, and it never changes the exit code. Invalid or repeated layer names
  are a configuration error; a declared layer that matches no module is warned about.
- Findings section in the report: four deterministic rules over the graph (unstable
  dependency, bottleneck, growing orchestrator, orphan module), each with an explanation
  and a recommendation. Thresholds are relative (percentiles of the project) with
  absolute minimums, so a small project is not flooded; package `__init__.py` facades are
  excluded. Tune them in the `[findings]` table of `.unskein.toml`, or switch the
  section off with `--no-findings` (`--findings` to override a config that disables it).
  Entry points are never reported as orphans: `__main__`, the targets of
  `[project.scripts]` and `[project.gui-scripts]` in `pyproject.toml`, and the
  `entry_points` setting. The section is shown also with `--no-ai`, the AI receives the
  findings as facts already computed, and they never change the exit code.
- Packages section in the report: modules grouped by the package they sit in, named by at
  most the first `package_depth` segments of their names (`[findings]`), with Ca, Ce and
  instability measured between packages and the largest dependencies between them. Modules
  in no package, such as a top-level single file, go to `(root)`. The depth is automatic by
  default: it starts at 1 and goes one level deeper when the whole project is a single
  top-level package; a number in `package_depth` fixes it. It is omitted when the project
  has fewer than two packages, and it is shown, and given to the AI, even with
  `[findings] enabled = false`.
- Impact column in the most coupled modules table, and `impact N` on bottleneck lines: how
  many modules depend on a module directly or indirectly, shown for the listed modules and
  the bottlenecks. The AI receives the package dependencies and the bottleneck impact as
  facts already computed.

### Changed

- The most coupled modules table now says what it lists (the top 10% of modules by
  Ca + Ce) and what Ca, Ce and instability mean. The note under a cut table reads
  "Showing the 15 most coupled of the 31 modules in the top 10% by Ca + Ce" instead of
  "Showing 15 of 31", which looked like an unfinished scan.
- The usage guide (`unskein guide`) explains how to set up the AI step: what the model,
  key and endpoint settings are, a recipe per provider (Ollama, OpenAI, Claude, Gemini,
  Azure OpenAI, AWS Bedrock, Mistral, Groq, DeepSeek, LiteLLM Proxy, OpenAI-compatible
  servers), how to check the setup and what each AI error means. The README,
  `.env.example` and the `unskein init` template point to it, and say that unskein reads
  environment variables, not `.env` files.

### Fixed

- Reasoning models behind a LiteLLM Proxy alias that does not name the real model (for
  example "GPT 5.6 Luna") failed with `BadRequestError`, because they were sent
  temperature 0.2. For `litellm_proxy/` models unskein now asks the proxy's
  `/model/info` whether the alias is a reasoning model, and falls back to LiteLLM's own
  model map when the proxy cannot say.

## [0.1.1] - 2026-09-30

### Added

- `unskein init` writes a commented `.unskein.toml` with every setting at its default,
  so a fresh install does not start from an empty file. `--user` writes
  `~/.config/unskein/config.toml` instead, and `--force` overwrites an existing file,
  which is otherwise kept (exit code 1). The template ships inside the package; the
  generated file changes nothing until a line is uncommented.
- `unskein guide` shows the usage guide of the installed version, in Spanish or English
  (`--lang`, `UNSKEIN_LANG` or the system locale): what the report means, every option,
  excludes, configuration, AI and privacy, exit codes and troubleshooting. Rendered in a
  terminal, raw Markdown when piped (`unskein guide > guide.md`). Tests fail if a
  command or option is missing from either guide.

### Removed

- `.unskein.toml.example` in the repository root, replaced by `unskein init`. It was not
  in the installed package, and its uncommented `parallel_threshold = 50` overrode the
  calibrated default of 500.

## [0.1.0] - 2026-09-30

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

- Parallel parsing: projects with 500 files or more are parsed in a process pool
  (`parallel_threshold`, `max_workers`, `queue_maxsize` in `.unskein.toml`), up to
  2.9x faster on large projects (1.0-2.6x where processes are spawned, as on Windows), with the same result and order as the sequential parser. A
  file that exceeds `per_file_timeout_seconds` is skipped with a warning; a worker that
  dies makes the parser fall back to sequential. The timeout only stops waiting: a
  worker stuck on a pathological file still delays closing the pool.

### Fixed

- The list of dependency cycles (and which ones survived the 100-cycle limit) changed
  between runs because networkx follows the string hash seed. Cycles are now enumerated
  over integer labels, so the report is identical on every run.
- The README example `--exclude "migrations/**"` only skipped a `migrations/` folder at
  the project root, not the ones inside each app. It now reads `--exclude "migrations/"`,
  which matches at any depth (a pattern with a slash in the middle is anchored to the
  root, as in `.gitignore`).
- `--verbose` now reports the real peak memory of the run. It used to read the resident
  memory after the analysis, so memory freed before the end was invisible (a 200 MB
  spike showed as 21 MB) (#9).
- Printing the report to a Windows pipe (cp1252) no longer crashes with an internal
  error on symbols such as "→"; unencodable characters are replaced.

### Changed

- The default `parallel_threshold` is now 500 files (was 50) and `max_workers` defaults to
  the core count capped at 8. Measured, a pool at 50 files was 2-40x slower than
  sequential parsing because starting it costs 130-300 ms.
- `LanguageAdapter.parse` is now concrete, built on the new `plan_parse` and `parse_task`
  that language adapters implement, so the parallel and sequential paths share one code
  path. `FileParseResult` moved to `unskein.parsers.models`.
- File discovery no longer enters excluded directories (`.venv/`, `build/`,
  `node_modules/`, `tests/`…), so its cost no longer grows with ignored content. As in
  git, a negated pattern (`!build/keep.py`) cannot re-include a file inside an excluded
  directory: such a file is no longer analyzed.
- Import collection walks only statement lists instead of every AST node, making parsing
  1.3-1.5x faster on large projects (networkx, Django, sympy) with the same graph.
  Imports are now visited depth-first in code order, so a file's warnings come out in
  line order and the report may show different examples per warning kind.
- When a package `__init__.py` re-exports the same symbol more than once (for example a
  `try/except ImportError` fallback), the first one in the code now wins; before, the
  last one did.
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

[Unreleased]: https://github.com/mapenzo/unskein/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/mapenzo/unskein/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mapenzo/unskein/releases/tag/v0.1.0
