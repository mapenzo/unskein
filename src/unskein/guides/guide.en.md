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

Monorepos need no configuration: every `pyproject.toml`, `setup.py` or `setup.cfg`
marks a distribution and its files are named the way Python imports them
(`enterprise/litellm_enterprise/x.py` is `litellm_enterprise.x`), so imports between
workspace members count as internal. Code that no distribution ships and nothing imports
(CI, examples, tooling) is listed apart as *scripts*: it does not count in Ca, metrics or
findings (except layers) and shows up as *consumers* of the modules it uses. To keep
folder-based naming, `[analysis] source_roots` turns the detection off.

## Reading the report

- **Summary**: modules, internal dependencies and cycles, the most coupled
  module and, if any, the tangles.
- **General metrics**: counts of modules, dependencies, cycles, tangles, hidden tangles and
  warnings.
- **Packages**: the same coupling measured between packages, which gives the overview a
  table of modules cannot (shown when the project has two or more). A module belongs to the
  package it sits in, named by at most the first `package_depth` segments of its name (`core.db`
  and `core.http` are both in `core`); modules that are in no package, such as a top-level
  single file, go to `(root)`. By default the depth is automatic: it starts at 1 and goes one
  level deeper when the whole project is a single top-level package; a number in
  `package_depth` fixes it. Ca and Ce count other packages, not modules, and imports inside
  one package do not count. Below the table, the largest dependencies between packages with
  their number of imports. Both are shown, and given to the AI, even with
  `[findings] enabled = false`.
- **Distributions**: only in monorepos with two or more named distributions (or when one
  imports code no distribution ships). Per distribution: its modules, which others it
  really imports and whether it can be installed alone, without extras, with no failing
  import; if not, the `file:line` that prevents it. Each import between distributions counts
  as *required* (at import time), *lazy* (inside a function) or *guarded* (in the body of a
  `try` that catches `ImportError`, `ModuleNotFoundError`, `Exception` or a bare `except:`
  and does not end in `raise`, or of `with contextlib.suppress(...)` for those errors); guarded imports are optional by
  contract and never prevent installing it. Declared dependencies are read from
  `[project] dependencies` and its extras, `[tool.poetry]` (dependencies and extras) and
  `setup.cfg`. A dependency listed only in a dependency group (`[dependency-groups]`, Poetry
  groups) counts as undeclared, since no installer installs groups with the package; the
  finding says which group lists it. With `dynamic = ["dependencies"]` or
  only `setup.py` they are unknown, and that distribution is never the source of an
  undeclared dependency. Two manifests with the same name give a warning, and only the
  shallower one keeps it. Each finding between
  distributions comes with a **Fix** you can copy (the line to add and the manifest it goes
  in). It is computed even with `[findings] enabled = false`.
- **Namespace packages**: a directory with code but no `__init__.py` (PEP 420) is a
  namespace package. When a module imports it, it appears in the graph with no file and
  Ce 0, marked *(namespace package)*, counted apart in the summary and the general
  metrics, and outside the module findings (it can still be the target of a layer
  violation). `import a.b` followed by `a.b.c.f()` depends on `a.b.c`. When the
  namespace has no regular package above it (`google/cloud/` with no `__init__.py`), other
  distributions can complete it: what the project lacks there stays a warning, never a
  finding.
- **Compiled extensions and stubs**: a module with no `.py` that exists as a binary
  (`.so`, `.pyd`), a Cython source (`.pyx`), a `[tool.maturin]` `module-name` or only a
  `.pyi` stub appears in the graph marked *(compiled extension)* or *(stub only)*, with
  its exact Ca and its Ce as `?`: what compiled code imports cannot be seen (the imports of
  a `.pyi` are types, not dependencies). `from pkg import _native` and
  `from pkg._native import X` reach the same node, with no warning. The **Native boundary**
  section says, per module, what proves it, how packaged code uses it (required / lazy /
  guarded / type-only) and whether it works without it; a binary nothing imports is not
  listed. `.gitignore` does not apply to stubs and binaries (a `.so` built in place is
  usually git-ignored, yet it exists); `.unskeinignore` and `--exclude` do. A name under
  compiled code is never reported as a missing module: the extension may provide it.
- **Most coupled modules**: the top 10% by `Ca + Ce` (up to 15 rows).
  - **Ca** (afferent coupling): how many modules import this one. High Ca
    means many modules break if it changes.
  - **Ce** (efferent coupling): how many modules this one imports. High Ce
    means it breaks when any of them changes.
  - **Instability** = `Ce / (Ca + Ce)`, from 0 (stable, others depend on it)
    to 1 (unstable, it depends on others).
  - **Impact**: how many modules depend on this one, directly or indirectly: what a change
    to it can reach. Shown for the modules listed and for bottlenecks.
- **Dependency cycles**: modules that end up importing themselves when the code is
  imported (imports at module level).
  - **Tangles** come first: groups where every module reaches every other one.
    Their size is exact, even when the cycle list is cut short.
  - **Cycles** are then listed as example loops, at most 100; the report says
    when the search stopped at that limit.
  - **Hidden coupling** lists groups that depend on each other, or groups larger than a
    tangle above, only once imports inside functions or under `TYPE_CHECKING` are counted.
    Those imports do not fail at import time, but they are still design coupling, and
    they count in every other number of the report.
- **Findings**: rules computed from the graph, shown also with `--no-ai`. Each kind has
  one explanation and one recommendation, then its modules with the numbers behind
  them (at most 10 per kind):
  - **Unstable dependency**: a module others rely on imports a much more unstable one.
  - **Bottleneck**: high Ca and high Ce at once, so changes flow in and out.
  - **Orchestrator with many dependencies**: far more imports than the rest; normal for
    entry points and use cases.
  - **Orphan module**: imports no project module and is imported by none: dead code or an
    entry point run from outside the code.
  - **Layer violation**: only when you declare `[layers]`: a module of a lower layer
    imports one of a higher layer.
  - **Undeclared dependency**: a distribution in the repository imports another one its
    manifest does not declare; installed alone, it fails on import.
  - **Optional dependency used as required**: declared only in an extra, but imported at
    load time without `try`/`except ImportError`.
  - **Import of unpackaged code**: imports code that no distribution ships (it only exists
    in the repository).
  - **Import of a module that does not exist**: packaged code imports, at load time or in
    a function and unguarded, a project module that does not exist; it raises `ImportError`
    when it runs. `TYPE_CHECKING`, guarded and test imports stay warnings. The fix names the
    module that defines the symbol, or says that none does.
  - **Optional extension used as required**: the code guards the import of a compiled (or
    stub-only) module in one place, because it expects it can be missing, and imports it
    unguarded elsewhere, where it raises `ImportError` when it is missing. It lists the
    unguarded `path:line` (up to five, with the total); the fix is to guard them the same
    way or to drop the fallback. A name taken from a facade that imports it in such a `try`
    counts as guarded too.
    It does not follow control flow: an earlier check (`if available():`) is not seen.
  - **Wildcard import**: one finding per module imported with `from x import *` outside a
    package facade. For each statement it gives the explicit import to write, with the
    names it needs computed with the whole project: those the module reads, those other
    analyzed modules import from it or read as its attributes, and those that pass on to
    modules that star-import it. When in doubt a name is kept. A statement that needs
    nothing can be removed (the line loads the module when imported, so removing it also
    drops its load-time effects). A star whose names cannot be known (a computed `__all__`,
    a cycle of star imports) stays a warning. Tests only count when they are analyzed: run
    with `--include-tests` before applying the fixes.
  - **Cycle between distributions**: distributions that import each other; it says which
    edge to cut.

  Thresholds are relative to the project (percentiles, with an absolute minimum) and can
  be tuned in `[findings]`. Findings never change the exit code.
- **Problems flagged (AI)**: only with a model configured. Each problem has a
  severity (`low`, `medium`, `high`), the modules involved and a
  recommendation. Problems naming modules that do not exist are discarded, and
  the report says how many.
- **Analysis warnings**: files skipped or imports that could not be resolved
  (star imports outside package facades whose names cannot be known, because the module
  was not parsed or computes its `__all__`; relative
  imports beyond the top package, files too large, unparseable or too slow to parse,
  re-export cycles or chains too long). A warning never stops the analysis.

Imports through a package's `__init__.py` are followed to the module that
defines the name, so a cycle hidden behind a facade still shows up. That includes
`import pkg as p` followed by `p.name`: the dependency goes to the module that defines
`name`, unless the way `p` is used cannot be followed (it is passed around,
reassigned or written to), in which case it stays on the package. `from x import *` inside a package's
`__init__.py` is followed too.

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

Other commands: `unskein init` and `unskein config save` (see Configuration), `unskein guide` (this
guide, `--lang` to pick its language; `unskein guide > guide.md` saves it) and
`unskein --version`.

## Untangling: `untangle`

`unskein untangle [PATH]` plans which imports to cut to undo each tangle. For every
tangle it lists the imports to cut, the cheapest refactoring step for each one and the
evidence behind it (file, line and imported symbols), then simulates the result:
tangles, cycles and the coupling of the affected modules before and after.

The steps, cheapest first: move under `TYPE_CHECKING` (names only used in annotations),
import from the defining module (the import goes through a package's `__init__.py` that
does not define the name itself), lazy import (names only used inside functions, or in
annotations too when the module has `from __future__ import annotations`), move the
symbol (one or two symbols imported), extract a shared module, and review the package
structure (a package importing its own submodule, only when nothing else breaks the
cycle). With `--all-edges` only the structural steps are offered, since a lazy or
`TYPE_CHECKING` import keeps the coupling. Neither is offered when another module reads
one of the names through the source module (`from a import Thing`, `a.Thing`, `from a
import *`): the name would no longer exist there. The cuts come from a heuristic and the
simulation is optimistic: read it as a plan to review.

Like `scan`, `untangle` honors the `exclude` and `include_tests` settings of
`.unskein.toml`. When some file could not be parsed, the plan says how many analysis
warnings there were; `unskein scan` shows them in detail.

- `--all-edges`: also untangle hidden coupling (imports inside functions or under
  `TYPE_CHECKING`).
- `--max-tangles N`: how many tangles to detail, largest first (default 5).
- `--output FILE` / `-o FILE`: also save the Markdown plan.
- `--lang es|en`: output language.

Exit codes: 0 when the plan was built (with or without tangles), 1 for usage errors,
3 for internal errors. `untangle` never calls the AI.

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

unskein reads two files, both optional:

- **Project file**: `.unskein.toml` (with the leading dot) in the folder you
  **analyze**, not the folder you run the command from. `unskein scan ~/code/app`
  reads `~/code/app/.unskein.toml`.
- **User file**: `~/.config/unskein/config.toml`, used for every project you
  analyze. The place for your AI model when you scan projects that are not
  yours.

```bash
unskein init                # writes ./.unskein.toml
unskein init --user         # writes ~/.config/unskein/config.toml (creates the folder)
unskein init --force        # replaces an existing file
unskein config save         # checks ./.unskein.toml and saves it as the user file
```

`init` takes a folder (`PATH`, default: current folder), `--user`, `--force`
and `--lang` for its messages. It writes a file where every setting is commented out at its default,
with a line explaining it. Uncomment only what you want to change. It never
overwrites an existing file without `--force`.

`config save` takes a file (`SOURCE`, default: `./.unskein.toml`), `--force`
and `--lang`. It validates the file first, so a typo stops it before anything
is written, then copies it as it is, comments included, to
`~/.config/unskein/config.toml`, creating the folder if needed. It never
replaces an existing user file without `--force`. A usual path: `unskein init`
in any folder, edit the file, try it with `unskein scan`, then
`unskein config save`. If the file holds `[ai] api_key`, it is saved readable
only by you and you get a warning: prefer the `UNSKEIN_API_KEY` variable.

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

To check your architecture's layers, list them from the highest to the lowest as
package prefixes:

```toml
[layers]
order = ["app.web", "app.services", "app.core"]
```

A module belongs to the layer with the longest matching prefix; an import from a lower
layer into a higher one is reported as a layer violation. Modules in no layer are not
checked, and without `[layers]` there is no layer rule.

## AI interpretation

The AI step is optional and goes through LiteLLM, so it works with a local
model, a cloud provider or a LiteLLM Proxy. Three settings drive it:

| Setting | Environment variable | `.unskein.toml` | What it is |
|---|---|---|---|
| Model | `UNSKEIN_AI_MODEL` | `[ai] model` | `provider/model`, as LiteLLM names it. Without it, no AI. |
| API key | `UNSKEIN_API_KEY` | `[ai] api_key` | Optional: if unset, LiteLLM reads the provider's own variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`...). |
| Endpoint | `UNSKEIN_AI_API_BASE` | `[ai] api_base` | Only for local servers, Azure and proxies. |

Environment variables win over `.unskein.toml`. Keep keys in environment
variables: a key written in `.unskein.toml` can end up in git.

unskein reads environment variables, not `.env` files. To use one, load it
in your shell first (`set -a; source .env; set +a`) or with a tool such as
direnv. `.env.example` in the repository lists the variables.

### Providers

| Provider | `model` | Key and endpoint |
|---|---|---|
| Ollama (local) | `ollama/qwen2.5-coder:7b` | `api_base` `http://localhost:11434`; no key |
| OpenAI | `openai/<model>` | `OPENAI_API_KEY` |
| Claude (Anthropic) | `anthropic/<model>` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini/<model>` | `GEMINI_API_KEY` |
| Azure OpenAI | `azure/<deployment>` | `AZURE_API_KEY`, `AZURE_API_VERSION`, and `api_base` (your resource URL) |
| AWS Bedrock | `bedrock/<model id>` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |
| Mistral | `mistral/<model>` | `MISTRAL_API_KEY` |
| Groq | `groq/<model>` | `GROQ_API_KEY` |
| DeepSeek | `deepseek/<model>` | `DEEPSEEK_API_KEY` |
| LiteLLM Proxy | `litellm_proxy/<alias>` | `api_base` (the proxy URL) and your virtual key |
| OpenAI-compatible server (LM Studio, vLLM) | `openai/<model>` | `api_base` (e.g. `http://localhost:1234/v1`); any non-empty key (e.g. `sk-local`) if the server checks none |

Replace `<model>` with a current model of the provider; the LiteLLM
documentation lists the names. `UNSKEIN_API_KEY` can replace any of the keys
above, except the AWS credentials. Some examples:

```bash
# Claude
export UNSKEIN_AI_MODEL="anthropic/<model>"
export ANTHROPIC_API_KEY="sk-ant-..."

# Azure OpenAI
export UNSKEIN_AI_MODEL="azure/my-deployment"
export UNSKEIN_AI_API_BASE="https://my-resource.openai.azure.com"
export AZURE_API_KEY="..."
export AZURE_API_VERSION="2024-10-21"

# LiteLLM Proxy
export UNSKEIN_AI_MODEL="litellm_proxy/my-alias"
export UNSKEIN_AI_API_BASE="https://litellm.example.com"
export UNSKEIN_API_KEY="sk-..."
```

Or, for a model without a secret, in `.unskein.toml`:

```toml
[ai]
model = "ollama/qwen2.5-coder:7b"
api_base = "http://localhost:11434"
```

Reasoning models only accept temperature 1, and unskein picks it from what
LiteLLM knows about the model. A proxy alias can be any name, so for
`litellm_proxy/` models unskein first asks the proxy (`/model/info`, with the
same key) whether the alias is a reasoning model.

To check the setup, run `unskein scan . --verbose`: a line with the tokens
used means the model answered. If the report has no AI section, it says why.

What leaves your machine: module names and their metrics (coupling, cycles,
tangles). Never source code. With `--no-ai` or a local model, nothing does.
unskein has no telemetry of any kind.

If the model fails, times out (60 s for direct calls; behind a proxy, the
proxy decides) or answers in the wrong format, the report is still produced
without the AI section and says why. The answer comes in the report language.

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
- **"The model could not be reached (AuthenticationError)"**: the key is
  missing or wrong. Check `UNSKEIN_API_KEY` or the provider's variable.
- **"...(NotFoundError)" or "(BadRequestError)"**: the model name is wrong or
  the provider prefix is missing (`anthropic/`, `azure/`...). `--verbose`
  shows the provider's message.
- **"The model did not answer in time"**: try a faster model; for a large
  local model, a smaller one.
- **"The model's answer does not follow the expected format"**: common with
  small local models. Try again or use a larger model.
- **Wrong language**: pass `--lang`, or set `UNSKEIN_LANG` or
  `[general] lang`.
- **A bug**: open an issue at https://github.com/mapenzo/unskein/issues with
  the output of `--verbose`.
