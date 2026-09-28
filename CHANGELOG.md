# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project scaffold: `src/` layout, pipeline contracts, test fixtures, CI.
- Python import parser: absolute, relative and submodule imports, `is_external`
  detection, re-export detection in `__init__.py`, per-file warnings instead of crashes
  (syntax errors, undecodable files, oversized files, deeply nested code).
- Automatic `src/` layout detection and configurable `source_roots`.
- Test code excluded from analysis by default; `--include-tests` to opt back in.
- Re-export resolution: imports through `__init__.py` facades now point at the module
  that defines the symbol, so cycles hidden behind a package facade become visible.
  Re-export cycles produce a single warning per cycle.

### Changed

- Clean Code is now a mandatory project convention: Google-style docstrings on every
  module, class and function (private ones included), enforced in CI with ruff's `D`
  rules plus an AST-based test that also covers private names.
- Parser data classes moved from `unskein.parsers.base` to `unskein.parsers.models`
  (still importable from `unskein.parsers`), removing an import cycle.
