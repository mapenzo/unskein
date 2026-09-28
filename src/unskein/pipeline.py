from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.models import ParseResult


def should_parallelize(file_count: int, config: AnalysisConfig) -> bool:
    return file_count >= config.parallel_threshold


def parse_all(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig
) -> ParseResult:
    if not should_parallelize(len(files), config):
        return adapter.parse(files, root)
    return _parse_parallel(files, adapter, root, config)


def _parse_parallel(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig
) -> ParseResult:
    """ProcessPoolExecutor fed by one bounded shared queue (backpressure, no hash-sharding).

    Enforces max_file_size_bytes and per_file_timeout_seconds as warnings, never crashes.
    """
    raise NotImplementedError
