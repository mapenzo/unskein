"""Choose between sequential and parallel parsing of the discovered files."""

from pathlib import Path

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.models import ParseResult


def should_parallelize(file_count: int, config: AnalysisConfig) -> bool:
    """Decide whether parsing is worth spreading across worker processes.

    Isolated on purpose: the extension point for adaptive logic (cores, total
    bytes, past timings) without touching the rest of the pipeline.

    Args:
        file_count: Number of files to parse.
        config: Analysis settings holding ``parallel_threshold``.

    Returns:
        True when ``file_count`` reaches the configured threshold.
    """
    return file_count >= config.parallel_threshold


def parse_all(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig
) -> ParseResult:
    """Parse every file, sequentially or in parallel depending on project size.

    Args:
        files: Source files to parse.
        adapter: Language adapter that knows how to parse them.
        root: Project root the files belong to.
        config: Analysis settings, including the parallelization threshold.

    Returns:
        The combined parse result for all files.
    """
    if not should_parallelize(len(files), config):
        return adapter.parse(files, root)
    return _parse_parallel(files, adapter, root, config)


def _parse_parallel(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig
) -> ParseResult:
    """Parse files in a ProcessPoolExecutor fed by one bounded shared queue.

    One shared queue (backpressure, no hash-sharding) self-balances uneven file
    costs. Enforces max_file_size_bytes and per_file_timeout_seconds as
    warnings, never crashes.

    Args:
        files: Source files to parse.
        adapter: Language adapter that knows how to parse them.
        root: Project root the files belong to.
        config: Analysis settings (workers, queue size, per-file limits).

    Returns:
        The combined parse result for all files.

    Raises:
        NotImplementedError: Not implemented yet.
    """
    raise NotImplementedError
