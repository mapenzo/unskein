# unskein {version} — usage guide

## What unskein does

unskein reads the imports of a Python project and builds a graph of its modules.
From that graph it measures how coupled each module is, finds dependency cycles
and tangles, and writes a Markdown report. With an AI model configured, the
report also gets a short interpretation: a summary, a health rating and the
problems worth looking at.

The graph and the metrics never depend on the AI: they are computed the same
way on every run. The AI only interprets numbers the graph already produced.

This version analyzes **Python only**, at **module level** (one node per
`.py` file). It does not look inside classes or functions, check for
vulnerabilities or draw an architecture map.

## Installation and first scan

```bash
pip install unskein          # or: uv tool install unskein / pipx install unskein
unskein scan path/to/project --no-ai
```

`--no-ai` gives the full deterministic report without calling any model. No
config file is needed: every setting has a default.

## Reading the report

- **Summary**: modules, internal dependencies and cycles, the most coupled
  module and, if any, the tangles.
- **General metrics**: counts of modules, dependencies, cycles, tangles and
  warnings.
- **Packages**: the same coupling measured between packages, which gives the overview a
  table of modules cannot (shown when the project has two or more). A package is named by the
  first `package_depth` segments of its modules' names (default 1: `core.db` and `core.http`
  are both in `core`); plain modules above that depth go to `(root)`. Ca and Ce count other
  packages, not modules, and imports inside one package do not count. Below the table, the
  largest dependencies between packages with their number of imports.
- **Most coupled modules**: the top 10% by `Ca + Ce` (up to 15 rows).
  - **Ca** (afferent coupling): how many modules import this one. High Ca
    means many modules break if it changes.
  - **Ce** (efferent coupling): how many modules this one imports. High Ce
    means it breaks when any of them changes.
  - **Instability** = `Ce / (Ca + Ce)`, from 0 (stable, others depend on it)
    to 1 (unstable, it depends on others).
  - **Impact**: how many modules depend on this one, directly or indirectly: what a change
    to it can reach. Shown for the modules listed and for bottlenecks.
- **Dependency cycles**: modules that end up importing themselves.
  - **Tangles** come first: groups where every module reaches every other one.
    Their size is exact, even when the cycle list is cut short.
  - **Cycles** are then listed as example loops, at most 100; the report says
    when the search stopped at that limit.
- **Findings**: rules computed from the graph, shown also with `--no-ai`. Each kind has
  one explanation and one recommendation, then its modules with the numbers behind
  them (at most 10 per kind):
  - **Unstable dependency**: a module others rely on imports a much more unstable one.
  - **Bottleneck**: high Ca and high Ce at once, so changes flow in and out.
  - **Orchestrator with many dependencies**: far more imports than the rest; normal for
    entry points and use cases.
  - **Orphan module**: imports no project module and is imported by none: dead code or an
    entry point run from outside the code.

  Thresholds are relative to the project (percentiles, with an absolute minimum) and can
  be tuned in `[findings]`. Findings never change the exit code.
- **Problems flagged (AI)**: only with a model configured. Each problem has a
  severity (`low`, `medium`, `high`), the modules involved and a
  recommendation. Problems naming modules that do not exist are discarded, and
  the report says how many.
- **Analysis warnings**: files skipped or imports that could not be resolved
  (star imports, relative imports beyond the top package, files too large,
  unparseable or too slow to parse, re-export cycles or chains too long). A
  warning never stops the analysis.

Imports through a package's `__init__.py` are followed to the module that
defines the name, so a cycle hidden behind a facade still shows up.

## `scan` options

```bash
unskein scan [PATH] [options]
```

| Option | What it does |
|---|---|
| `PATH` | Folder to analyze (default: current folder). |
| `--no-ai` | Skip the AI interpretation. |
| `--exclude PATTERN` | Skip more paths, gitignore syntax (repeatable). |
| `--min-severity low\|medium\|high` | Lowest AI problem severity to show. |
| `--include-tests` / `--no-include-tests` | Also analyze test code (off by default). |
| `--findings` / `--no-findings` | Show or hide the findings section (shown by default). |
| `--follow-symlinks` / `--no-follow-symlinks` | Follow symlinked folders (off by default). |
| `--encoding NAME` | Fallback encoding for files that declare none. |
| `--lang es\|en` | Report language. |
| `-o`, `--output FILE` | Also save the Markdown report to a file. |
| `-v`, `--verbose` | Show progress, duration and peak memory. |
| `--log-file FILE` | Also write debug logs to a file. |
| `--api-key KEY` | Only for quick tests: it stays in your shell history. |

Examples:

```bash
unskein scan . --no-ai -o report.md          # save the report
unskein scan . --exclude "migrations/"       # skip every migrations/ folder
unskein scan . --min-severity high           # only high-severity AI problems
```

Other commands: `unskein init` (see Configuration), `unskein guide` (this
guide, `--lang` to pick its language; `unskein guide > guide.md` saves it) and
`unskein --version`.

## Excluding paths

Three sources are combined; none replaces the others:

1. The `.gitignore` at the project root.
2. A `.unskeinignore` at the project root, same syntax, for code that is in
   git but should not be analyzed (generated code, vendored packages).
3. `--exclude` flags and `exclude` in `.unskein.toml`.

Test code (`tests/`, `test/`, `test_*.py`, `*_test.py`, `conftest.py`) is skipped
unless you pass `--include-tests`.

A pattern with a slash in the middle is anchored to the root:
`migrations/**` only skips the top-level folder, while `migrations/` or
`**/migrations/**` skip it at any depth.

## Configuration

```bash
unskein init                # writes ./.unskein.toml
unskein init --user         # writes ~/.config/unskein/config.toml
unskein init --force        # replaces an existing file
```

`init` takes a folder (`PATH`, default: current folder), `--user`, `--force`
and `--lang` for its messages. It writes a file where every setting is commented out at its default,
with a line explaining it. Uncomment only what you want to change. It never
overwrites an existing file without `--force`.

Precedence, highest first:

- **Most settings**: flag > environment variable > `.unskein.toml` > default.
  The only documented environment variable here is `UNSKEIN_LANG`.
- **AI model and secrets**: `UNSKEIN_AI_MODEL`, `UNSKEIN_API_KEY`,
  `UNSKEIN_AI_API_BASE` > `.unskein.toml` > `--api-key`.

The project's `.unskein.toml` wins over the user file key by key, and
excludes from both are added together. A typo or a wrong type in either file
stops the scan with exit code 1 and names the file and the key.

If your packages live somewhere other than the root or `src/`, set
`source_roots` in `[analysis]`.

The `[findings]` table tunes the findings; modules that are run from outside the
code can be listed in `entry_points` (scripts in `pyproject.toml` and `__main__`
modules are detected on their own). The `package_depth` setting changes how
packages are named.

## AI interpretation

Any model supported by LiteLLM works: a local Ollama model, a cloud provider
or a LiteLLM Proxy.

```bash
# Local Ollama
export UNSKEIN_AI_MODEL="ollama/qwen2.5-coder:7b"
export UNSKEIN_AI_API_BASE="http://localhost:11434"

# Cloud provider
export UNSKEIN_AI_MODEL="gpt-4o-mini"
export UNSKEIN_API_KEY="sk-..."
```

What leaves your machine: module names and their metrics (coupling, cycles,
tangles). Never source code. With `--no-ai` or a local model, nothing does.
unskein has no telemetry of any kind.

If the model fails, times out (60 s for direct calls) or answers in the wrong
format, the report is still produced without the AI section and says why.
The answer comes in the report language.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Analysis done, no `high` severity problem. |
| `1` | Usage error: bad path, no `.py` files, invalid config, existing file in `init`. |
| `2` | Analysis done and the AI flagged a `high` severity problem. |
| `3` | Internal error (a bug): the full traceback is shown. Please report it. |

`--min-severity` only filters what is shown; it does not change the exit code.

## Performance

From 500 files, parsing runs in parallel with up to 8 processes (tune
`parallel_threshold` and `max_workers` in `.unskein.toml`). Files of 5 MB or more
are skipped with a warning, and in parallel parsing a file that takes more
than 30 s is skipped too. `--verbose` prints the duration and the peak memory
of the run, measured locally and never sent anywhere.

## Troubleshooting

- **"No .py files found"**: check the path, and that `.gitignore`,
  `.unskeinignore` or `--exclude` are not excluding everything. Tests are
  skipped by default.
- **Imports reported as unresolved**: your packages may live outside the root
  and `src/`; set `source_roots`.
- **No AI section**: no model is configured, or `--no-ai` was passed. The
  report says which.
- **Wrong language**: pass `--lang`, or set `UNSKEIN_LANG` or
  `[general] lang`.
- **A bug**: open an issue at https://github.com/mapenzo/unskein/issues with
  the output of `--verbose`.
