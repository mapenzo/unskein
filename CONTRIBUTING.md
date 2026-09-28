# Contributing to unskein

Thanks for your interest! Issues and pull requests are welcome in English or Spanish.

## Before you start

- Read [docs/architecture.md](docs/architecture.md). Design decisions listed there
  (deterministic graph vs. interpretive AI, LiteLLM only, no symlink following by
  default, etc.) should not be changed without an issue discussing it first.
- For anything beyond a small fix, open an issue before writing code.

## Setup

```bash
uv sync
uv run pytest --cov
uv run ruff check . && uv run ruff format --check .
```

Supported Python: 3.12, 3.13, 3.14 (CI runs all three).

## Clean Code (mandatory)

Every PR must follow the Clean Code rules in [CLAUDE.md](CLAUDE.md#clean-code-obligatorio).
In short:

- **Docstrings on every module, class, function and method, private ones included.**
  [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings),
  in English: an imperative one-line summary ending with a period, then `Args:`,
  `Returns:` and `Raises:` when they add information. Constructor arguments go in the
  class docstring; dataclass fields in `Attributes:`.
- Tests don't need docstrings: the test name describes the behavior.
- CI enforces this twice: ruff's `D` rules check public docstrings and their format,
  and `tests/integration/test_docstrings.py` fails if any module, class or function in
  `src/` or `scripts/` lacks a docstring, private ones included.
- Intention-revealing names, small single-purpose functions, at most 3 positional
  parameters, named constants instead of magic numbers, comments only for *why*,
  no dead or commented-out code, and leave touched code cleaner than you found it.

## Guidelines

- Tests are required for every change. Synthetic fixture projects live in
  `tests/fixtures/`.
- Dataclasses for pipeline data; Pydantic only for validating external I/O (LLM output).
- Plain loops or comprehensions in hot paths, not `map`/`filter` chains with lambdas.
- Never log API keys, at any level.
- Do not add provider-specific AI SDKs; everything goes through LiteLLM.
- User-facing strings go through `unskein.i18n` with both `es` and `en` entries.
- Add an entry under `[Unreleased]` in `CHANGELOG.md`.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, ...).
