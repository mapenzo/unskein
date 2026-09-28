"""Configuration dataclasses, ``.unskein.toml`` loading and precedence resolution."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from unskein.errors import ConfigError

ENV_AI_MODEL = "UNSKEIN_AI_MODEL"
ENV_API_KEY = "UNSKEIN_API_KEY"
ENV_AI_API_BASE = "UNSKEIN_AI_API_BASE"
ENV_LANG = "UNSKEIN_LANG"

PROJECT_CONFIG_NAME = ".unskein.toml"
USER_CONFIG_PATH = Path.home() / ".config" / "unskein" / "config.toml"


@dataclass
class StageConfig:
    """Concurrency settings for one pipeline stage.

    Attributes:
        max_workers: Worker count for the stage; None means ``os.cpu_count()``.
        queue_maxsize: Bound of the stage's input queue (backpressure).
    """

    max_workers: int | None = None
    queue_maxsize: int = 200


@dataclass
class PipelineConfig:
    """Per-stage concurrency settings, sized by how CPU-bound each stage is.

    Attributes:
        parse: Parsing stage, CPU-bound, one worker per core by default.
        resolve: Re-export resolution stage, lightweight.
        metrics: Metrics stage, single worker since NetworkX does not parallelize well.
    """

    parse: StageConfig = field(default_factory=lambda: StageConfig(max_workers=None))
    resolve: StageConfig = field(default_factory=lambda: StageConfig(max_workers=2))
    metrics: StageConfig = field(default_factory=lambda: StageConfig(max_workers=1))


@dataclass
class AnalysisConfig:
    """Settings that control discovery, parsing and parallelization.

    Attributes:
        parallel_threshold: File count from which parsing runs in parallel.
        max_workers: Worker processes for parsing; None means ``os.cpu_count()``.
        queue_maxsize: Maximum number of files in flight at once.
        max_file_size_bytes: Files larger than this are skipped unread, with a warning.
        per_file_timeout_seconds: Time limit to parse one file before skipping it.
        default_encoding: Fallback encoding only when a file declares none and
            detection fails; never overrides a PEP 263 cookie.
        follow_symlinks: Whether discovery follows symlinked directories.
        exclude: Extra exclude patterns (gitignore syntax).
        source_roots: Directories module names are relative to; None auto-detects
            a ``src/`` layout. The project root is always the last fallback.
        include_tests: Whether test code is analyzed (excluded by default).
        pipeline: Per-stage concurrency settings.
    """

    parallel_threshold: int = 50
    max_workers: int | None = None
    queue_maxsize: int = 200
    max_file_size_bytes: int = 5 * 1024 * 1024
    per_file_timeout_seconds: int = 30
    default_encoding: str | None = None
    follow_symlinks: bool = False
    exclude: list[str] = field(default_factory=list)
    source_roots: list[str] | None = None
    include_tests: bool = False
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


@dataclass
class AIConfig:
    """Settings passed to LiteLLM; fallback and retries are LiteLLM's job.

    Attributes:
        model: LiteLLM model string, e.g. ``ollama/qwen2.5-coder:7b``.
        api_key: Provider API key; excluded from ``repr`` so it never reaches logs.
        api_base: Custom endpoint, e.g. a local Ollama server.
    """

    model: str
    api_key: str | None = field(default=None, repr=False)
    api_base: str | None = None


class _TomlTable(BaseModel):
    """Base for TOML tables: unknown keys and implicit type coercion are errors."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TomlGeneral(_TomlTable):
    """The ``[general]`` table.

    Attributes:
        lang: Output language.
    """

    lang: Literal["es", "en"] | None = None


class TomlAI(_TomlTable):
    """The ``[ai]`` table; None means "not set in any file".

    Attributes:
        model: LiteLLM model string.
        api_key: Provider API key (prefer the ``UNSKEIN_API_KEY`` env var).
        api_base: Custom endpoint.
    """

    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    api_base: str | None = None


class TomlAnalysis(_TomlTable):
    """The ``[analysis]`` table; None means "not set", so defaults still apply.

    Attributes:
        parallel_threshold: See ``AnalysisConfig``.
        max_workers: See ``AnalysisConfig``.
        queue_maxsize: See ``AnalysisConfig``.
        max_file_size_bytes: See ``AnalysisConfig``.
        per_file_timeout_seconds: See ``AnalysisConfig``.
        default_encoding: See ``AnalysisConfig``.
        follow_symlinks: See ``AnalysisConfig``.
        exclude: Extra exclude patterns, added to the CLI ones.
        source_roots: See ``AnalysisConfig``.
        include_tests: See ``AnalysisConfig``.
    """

    parallel_threshold: int | None = None
    max_workers: int | None = None
    queue_maxsize: int | None = None
    max_file_size_bytes: int | None = None
    per_file_timeout_seconds: int | None = None
    default_encoding: str | None = None
    follow_symlinks: bool | None = None
    exclude: list[str] | None = None
    source_roots: list[str] | None = None
    include_tests: bool | None = None


class TomlConfig(_TomlTable):
    """A validated, merged ``.unskein.toml`` (all tables optional).

    Attributes:
        general: The ``[general]`` table.
        ai: The ``[ai]`` table.
        analysis: The ``[analysis]`` table.
    """

    general: TomlGeneral = TomlGeneral()
    ai: TomlAI = TomlAI()
    analysis: TomlAnalysis = TomlAnalysis()


def _read_toml(path: Path) -> dict:
    """Read and validate one TOML file; a missing file is an empty config.

    Validating each file on its own lets errors name the file at fault.

    Args:
        path: TOML file to read.

    Returns:
        The file's raw tables, already checked against ``TomlConfig``.

    Raises:
        ConfigError: If the file is not valid TOML or does not match the schema.
    """
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError("invalid_toml", {"file": str(path), "detail": str(e)}) from None
    try:
        TomlConfig.model_validate(data)
    except ValidationError as e:
        raise _config_error(path, e) from None
    return data


def _config_error(path: Path, error: ValidationError) -> ConfigError:
    """Turn the first Pydantic error into a ConfigError without the input value.

    Args:
        path: File that failed validation.
        error: Pydantic validation error.

    Returns:
        ``unknown_key`` for unexpected keys, ``invalid_value`` otherwise.
    """
    first = error.errors()[0]
    field_name = ".".join(str(part) for part in first["loc"])
    params = {"file": str(path), "field": field_name}
    if first["type"] == "extra_forbidden":
        return ConfigError("unknown_key", params)
    return ConfigError("invalid_value", params | {"detail": first["msg"]})


def load_toml_config(root: Path, user_config: Path = USER_CONFIG_PATH) -> TomlConfig:
    """Merge the user config with ``<root>/.unskein.toml``; the project wins key by key.

    Args:
        root: Project root where ``.unskein.toml`` may live.
        user_config: User-wide config file (``~/.config/unskein/config.toml``).

    Returns:
        The validated, merged configuration.

    Raises:
        ConfigError: If either file is invalid TOML or has unknown keys or wrong types.
    """
    merged: dict[str, dict] = {}
    for path in (user_config, root / PROJECT_CONFIG_NAME):
        for table, values in _read_toml(path).items():
            merged.setdefault(table, {}).update(values)
    return TomlConfig.model_validate(merged)


@dataclass(frozen=True)
class AnalysisFlags:
    """Analysis options given on the command line; None means "flag not given".

    Attributes:
        exclude: ``--exclude`` patterns (always added to the TOML ones).
        include_tests: ``--include-tests`` / ``--no-include-tests``.
        follow_symlinks: ``--follow-symlinks`` / ``--no-follow-symlinks``.
        encoding: ``--encoding`` fallback encoding.
    """

    exclude: tuple[str, ...] = ()
    include_tests: bool | None = None
    follow_symlinks: bool | None = None
    encoding: str | None = None


def resolve_analysis_config(toml: TomlConfig, flags: AnalysisFlags) -> AnalysisConfig:
    """Resolve analysis settings with precedence flag > .unskein.toml > default.

    Exclude patterns are the exception: TOML and flag patterns are combined,
    like every other exclude source.

    Args:
        toml: Validated, merged TOML configuration.
        flags: Options given on the command line.

    Returns:
        The resolved analysis settings.
    """
    from_toml = toml.analysis.model_dump(exclude_none=True, exclude={"exclude"})
    from_flags = {
        "include_tests": flags.include_tests,
        "follow_symlinks": flags.follow_symlinks,
        "default_encoding": flags.encoding,
    }
    overrides = from_toml | {name: value for name, value in from_flags.items() if value is not None}
    exclude = [*(toml.analysis.exclude or []), *flags.exclude]
    return AnalysisConfig(**overrides, exclude=exclude)


def resolve_ai_config(
    toml: TomlConfig, env: Mapping[str, str], cli_api_key: str | None
) -> AIConfig | None:
    """Resolve AI settings; secrets follow env > .unskein.toml > ``--api-key``.

    The API key flag comes last because it leaks into shell history. Model and
    API base have no flag: env var, then TOML.

    Args:
        toml: Validated, merged TOML configuration.
        env: Environment variables (``os.environ`` in production).
        cli_api_key: Key passed with the insecure ``--api-key`` flag, if any.

    Returns:
        The AI settings, or None when no model is configured in any layer.
    """
    model = env.get(ENV_AI_MODEL) or toml.ai.model
    if not model:
        return None
    return AIConfig(
        model=model,
        api_key=env.get(ENV_API_KEY) or toml.ai.api_key or cli_api_key,
        api_base=env.get(ENV_AI_API_BASE) or toml.ai.api_base,
    )
