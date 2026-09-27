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
