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
    max_workers: int | None = None
    queue_maxsize: int = 200


@dataclass
class PipelineConfig:
    parse: StageConfig = field(default_factory=lambda: StageConfig(max_workers=None))
    resolve: StageConfig = field(default_factory=lambda: StageConfig(max_workers=2))
    metrics: StageConfig = field(default_factory=lambda: StageConfig(max_workers=1))


@dataclass
class AnalysisConfig:
    parallel_threshold: int = 50
    max_workers: int | None = None
    queue_maxsize: int = 200
    max_file_size_bytes: int = 5 * 1024 * 1024
    per_file_timeout_seconds: int = 30
    default_encoding: str | None = None
    follow_symlinks: bool = False
    exclude: list[str] = field(default_factory=list)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


@dataclass
class AIConfig:
    model: str
    api_key: str | None = field(default=None, repr=False)
    api_base: str | None = None


def load_toml_config(root: Path) -> dict:
    """Merge ~/.config/unskein/config.toml with <root>/.unskein.toml (project wins)."""
    raise NotImplementedError


def load_analysis_config(root: Path, **cli_overrides: object) -> AnalysisConfig:
    """Env var -> .unskein.toml -> CLI flag hierarchy for AnalysisConfig."""
    raise NotImplementedError


def load_ai_config(root: Path, cli_api_key: str | None = None) -> AIConfig | None:
    """Env var -> .unskein.toml -> --api-key. Returns None when no model is configured."""
    raise NotImplementedError
