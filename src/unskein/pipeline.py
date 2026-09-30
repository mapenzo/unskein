"""Choose between sequential and parallel parsing of the discovered files.

The parallel path keeps the adapter and the shared parsing data in module
globals of each worker process, set once by the pool initializer.
"""

import logging
import os
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from unskein.config import AnalysisConfig
from unskein.parsers.base import LanguageAdapter
from unskein.parsers.models import (
    FileParseResult,
    ParseResult,
    ParseTask,
    ParseWarning,
    WarningCode,
)

logger = logging.getLogger("unskein")

BATCHES_PER_WORKER = 4
MAX_BATCH_SIZE = 32

_worker_adapter: LanguageAdapter | None = None
_worker_shared: Any = None


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


def batch_size(task_count: int, workers: int, queue_maxsize: int) -> int:
    """Choose how many files travel to a worker in one message.

    One file per message costs about a millisecond of inter-process overhead
    each; batches amortize it. Several batches per worker keep the load balanced
    when file costs are uneven.

    Args:
        task_count: Number of files to parse.
        workers: Number of worker processes.
        queue_maxsize: Most files allowed in flight at once.

    Returns:
        A batch size between 1 and ``MAX_BATCH_SIZE``, never above ``queue_maxsize``.
    """
    balanced = task_count // (workers * BATCHES_PER_WORKER)
    return max(1, min(balanced, MAX_BATCH_SIZE, queue_maxsize))


def _init_worker(adapter: LanguageAdapter, shared: Any) -> None:
    """Store the adapter and shared data in the worker process, once.

    Args:
        adapter: Language adapter whose ``parse_task`` the worker runs.
        shared: The plan's shared data, sent once per worker instead of per file.
    """
    # pylint: disable-next=global-statement  # per-process state, set once by the pool initializer
    global _worker_adapter, _worker_shared
    _worker_adapter = adapter
    _worker_shared = shared


def _parse_batch(batch: list[ParseTask]) -> list[FileParseResult]:
    """Parse a batch of files inside a worker process.

    Args:
        batch: Files and module names to parse.

    Returns:
        One result per file, in the order given.
    """
    assert _worker_adapter is not None, "the pool initializer did not run"
    return [_worker_adapter.parse_task(task, _worker_shared) for task in batch]


def _timeout_result(task: ParseTask, timeout_seconds: int) -> FileParseResult:
    """Build the result of a file whose parsing did not finish in time.

    Args:
        task: The file that timed out.
        timeout_seconds: The per-file limit that was exceeded.

    Returns:
        A skipped-file result carrying a ``PARSE_TIMEOUT`` warning.
    """
    warning = ParseWarning(WarningCode.PARSE_TIMEOUT, task[0], None, str(timeout_seconds))
    return FileParseResult(None, warnings=[warning])


def _collect_batch(
    pool: ProcessPoolExecutor, batch: list[ParseTask], future: Future, timeout_seconds: int
) -> list[FileParseResult]:
    """Wait for a batch; on timeout, retry its files one by one to find the culprit.

    A timeout only stops waiting: the worker keeps running the stuck file, and
    closing the pool waits for it (see ``docs/architecture.md``).

    Args:
        pool: Pool the batch was submitted to.
        batch: Files of the batch.
        future: Pending result of the batch.
        timeout_seconds: Per-file limit; a batch may take that long per file.

    Returns:
        One result per file, in the order given.
    """
    try:
        return future.result(timeout=timeout_seconds * len(batch))
    except TimeoutError:
        if len(batch) == 1:
            return [_timeout_result(batch[0], timeout_seconds)]
        results: list[FileParseResult] = []
        for task in batch:
            single = [task]
            results += _collect_batch(
                pool, single, pool.submit(_parse_batch, single), timeout_seconds
            )
        return results


def _parse_in_pool(
    pool: ProcessPoolExecutor, batches: list[list[ParseTask]], config: AnalysisConfig
) -> list[FileParseResult]:
    """Submit batches keeping a bounded window in flight; collect them in order.

    Args:
        pool: Worker pool, already initialized.
        batches: Batches of files, in the order results must come back.
        config: Analysis settings (window size, per-file timeout).

    Returns:
        One result per file, in the order of the tasks.
    """
    max_pending = max(1, config.queue_maxsize // len(batches[0]))
    pending: deque[tuple[list[ParseTask], Future]] = deque()
    results: list[FileParseResult] = []
    for batch in batches:
        if len(pending) >= max_pending:
            results += _collect_batch(pool, *pending.popleft(), config.per_file_timeout_seconds)
        pending.append((batch, pool.submit(_parse_batch, batch)))
    while pending:
        results += _collect_batch(pool, *pending.popleft(), config.per_file_timeout_seconds)
    return results


def _parse_parallel(
    files: list[Path], adapter: LanguageAdapter, root: Path, config: AnalysisConfig
) -> ParseResult:
    """Parse files in a ProcessPoolExecutor fed with a bounded window of batches.

    Results are combined in the order of the files, so the outcome equals the
    sequential one. The shared data goes to each worker once, through the pool
    initializer. A file that exceeds ``per_file_timeout_seconds`` is skipped
    with a warning; a pool that dies falls back to sequential parsing.

    Args:
        files: Source files to parse.
        adapter: Language adapter that knows how to parse them.
        root: Project root the files belong to.
        config: Analysis settings (workers, queue size, per-file limits).

    Returns:
        The combined parse result for all files.
    """
    plan = adapter.plan_parse(files, root)
    workers = config.max_workers or os.cpu_count() or 1
    size = batch_size(len(plan.tasks), workers, config.queue_maxsize)
    batches = [plan.tasks[start : start + size] for start in range(0, len(plan.tasks), size)]
    try:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=(adapter, plan.shared)
        ) as pool:
            file_results = _parse_in_pool(pool, batches, config)
    except BrokenProcessPool:
        logger.warning("A parsing worker died; parsing again sequentially")
        return adapter.parse(files, root)
    return ParseResult.from_file_results(adapter.language_name, file_results)
