"""Configuration dataclasses and the env var -> .unskein.toml -> CLI flag hierarchy."""

from dataclasses import dataclass, field
from pathlib import Path

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


def load_toml_config(root: Path) -> dict:
    """Merge ~/.config/unskein/config.toml with <root>/.unskein.toml (project wins).

    Args:
        root: Project root where ``.unskein.toml`` may live.

    Returns:
        The merged configuration tables.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def load_analysis_config(root: Path, **cli_overrides: object) -> AnalysisConfig:
    """Build AnalysisConfig from the env var -> .unskein.toml -> CLI flag hierarchy.

    Args:
        root: Project root where ``.unskein.toml`` may live.
        **cli_overrides: Values given as CLI flags, keyed by field name.

    Returns:
        The resolved analysis settings.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError


def load_ai_config(root: Path, cli_api_key: str | None = None) -> AIConfig | None:
    """Build AIConfig from env var -> .unskein.toml -> --api-key.

    Args:
        root: Project root where ``.unskein.toml`` may live.
        cli_api_key: Key passed with the insecure ``--api-key`` flag, if any.

    Returns:
        The AI settings, or None when no model is configured in any layer.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
