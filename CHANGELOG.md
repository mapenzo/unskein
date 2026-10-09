# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Namespace packages (PEP 420, directories without `__init__.py`): importing one is no
  longer an "internal import not found" warning. They appear in the graph as marked
  nodes with no file, counted apart from modules and left out of the module findings.
- Finding: import of a module that does not exist. It fires when packaged code imports it
  at load time or in a function, unguarded, so it raises `ImportError` when it runs. The
  fix names the module that defines the symbol, or says that none does.
  `TYPE_CHECKING`, guarded and test imports stay warnings, and so do names under a
  namespace package that other distributions can complete (`google.*`).
- Compiled extensions and stubs: a module that exists as a `.so`/`.pyd` binary, a Cython
  `.pyx`, a `[tool.maturin]` `module-name` or only a `.pyi` stub is a marked node of the
  graph (*compiled extension* or *stub only*) with its exact Ca and an unknown Ce. Imports
  of it are exact and no longer "internal import not found" warnings, whether written
  `from pkg import _native` or `from pkg._native import X`.
- Native boundary section: for each compiled or stub-only module, what proves it exists,
  how packaged code uses it (required, lazy, guarded, type-only) and whether it works
  without it.
- Finding: optional extension used as required. The code guards the import of a compiled
  module in one place and imports it unguarded elsewhere, where it raises `ImportError`
  when the extension is missing. It lists the unguarded lines (up to five, with the total);
  the fix is to guard them the same way or to drop the fallback.
- Monorepos without configuration: every `pyproject.toml`, `setup.py` or `setup.cfg`
  marks a distribution, and its files take the name Python imports them by (uv,
  maturin, hatch, poetry and setuptools declarations are read; `setup.py` is never
  run). Imports between workspace members are internal now.
- Scripts: code no distribution ships and nothing imports (CI, examples, tooling) is
  listed in its own report section and counts as *consumers* of the modules it uses,
  not in Ca, metrics or findings (except layers).
- Warnings for unreadable manifests, declared packages that do not exist and repeated
  module names.
- Findings between the distributions of a monorepo, each with a copyable fix:
  undeclared dependencies, dependencies declared only in an extra but imported at load
  time, imports of code that no distribution ships, and cycles between distributions
  (each edge marked required, optional, undeclared or unknown, with the edges to cut).
  Imports inside a `try` that catches import errors (and does not re-raise), or
  `contextlib.suppress`, count as optional by contract.
  A dependency listed only in a dependency group counts as undeclared: groups are never
  installed with the package. Poetry manifests are read too.
- A Distributions section: what each distribution really imports from the others and
  whether it can be installed alone.
- Warnings for declared dependencies without a valid name and for two manifests that
  declare the same distribution name.

### Changed

- The module count of the report and of the AI context counts parsed `.py` modules only;
  namespace packages, compiled extensions and stubs are counted apart.
- `discover_files` also yields `.pyi`, `.so`, `.pyd` and `.pyx` files (they are named, never
  parsed). `.gitignore` does not apply to them (an in-place build is usually git-ignored);
  `.unskeinignore` and `--exclude` do.
- A name taken from a package facade that imports it inside a `try` for import errors now
  counts as a guarded import for its users too (the facade falls back instead of failing).
- `import a.b` followed by `a.b.c.x` now depends on `a.b.c`, the module really used,
  and `import a` plus `import a.b` are analyzed together (they bind the same `a`).
- In projects with nested manifests, module names follow the distribution that ships
  each file (`enterprise/litellm_enterprise/x.py` is `litellm_enterprise.x`). Set
  `[analysis] source_roots` to keep the previous naming.
- Entry points are read from the scripts of every distribution, not only the root one.

## [0.3.0] - 2026-10-01

### Added

- `unskein untangle [PATH]`: for each tangle, the imports to cut, the cheapest
  refactoring step for each one (move under `TYPE_CHECKING`, import from the defining
  module, lazy import, move the symbol, extract a shared module, review the package
  structure) with its evidence, and a simulation of tangles, cycles and coupling before
  and after. `--all-edges` includes hidden coupling. The `scan` summary points to it
  when there are tangles. The lazy and `TYPE_CHECKING` steps are never offered when
  another module reads one of the names through the importing module (by name, by
  attribute, by a star import or by using the module by itself), since the name would
  no longer exist there.
- Hidden coupling: the report lists groups of modules that depend on each other only
  through imports inside functions or under `TYPE_CHECKING`, with their own summary
  line and a "Hidden tangles" metric. The AI context receives them too (largest first,
  with their total), rated medium severity since they do not fail at import time.
- `unskein config save [SOURCE]`: validates a config file (default `./.unskein.toml`)
  and copies it, comments included, to `~/.config/unskein/config.toml`, creating the
  folder. It never replaces an existing user file without `--force`, writes it readable
  only by its owner, and warns when the file holds `[ai] api_key`.

### Changed

- Dependency cycles and tangles now count only imports that run when the code is
  imported (module level). Imports inside functions or under `TYPE_CHECKING` no
  longer create cycles or tangles in the report, the AI context or the summary; they
  still count for coupling, findings, layers and impact. Projects that reported tangles
  made only of such imports now report them as hidden coupling.
- The "no AI model configured" notice names both places a model can be set: the
  `.unskein.toml` of the analyzed folder and `~/.config/unskein/config.toml`
  (`unskein init --user`). `unskein init` points to `unskein config save`, and the
  guide explains where each config file is read from.
- `import pkg as p` followed by `p.name` (also `import pkg` and `from pkg import sub`
  when `sub` is a package) now counts as a dependency on the module that defines `name`
  instead of on the package's `__init__.py`. Uses that cannot be followed (the name is
  passed around, reassigned or never used) still point at the package. Measured on copies
  of installed packages: in networkx, modules depending on the package's `__init__.py`
  drop from 253 to 5 (of 288); in litellm, from 618 to 454 (of 2469); in pydantic, from
  9 to 1. Import-time tangles change little (networkx 278 to 273 modules), and in litellm
  the largest one grows from 493 to 601 modules because dependencies that used to stop at
  the facade now reach the modules that define each name, which shows dependencies that
  were hidden behind the facade. Analysis time in litellm goes from 1.4 s to 1.6 s.
- `from x import *` inside a package `__init__.py` is followed too: it re-exports `x`'s
  literal `__all__`, or its public module-level names. Outside a package `__init__.py`,
  or from a module that is not part of the project, it still warns.

### Fixed

- Tests no longer read the developer's real `~/.config/unskein/config.toml`:
  `load_toml_config` looks the user file up at call time.

## [0.2.0] - 2026-10-01

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
- With `--verbose`, the provider's error message hid only the key given to unskein
  (`UNSKEIN_API_KEY`, `[ai] api_key`, `--api-key`). A key LiteLLM read from the
  provider's own variable (`ANTHROPIC_API_KEY`, AWS credentials...) could show in clear.
  Those values are now hidden too.

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

[Unreleased]: https://github.com/mapenzo/unskein/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mapenzo/unskein/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mapenzo/unskein/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/mapenzo/unskein/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/mapenzo/unskein/releases/tag/v0.1.0
