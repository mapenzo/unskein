"""Local, informational performance measurement; nothing is ever sent anywhere."""

import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class PerformanceStats:
    """Duration and memory of one analysis run, shown only with ``--verbose``.

    Attributes:
        duration_seconds: Wall-clock time of the measured call.
        peak_memory_mb: Resident memory of the process after the call, in MiB.
    """

    duration_seconds: float
    peak_memory_mb: float


def measure[T](fn: Callable[[], T]) -> tuple[T, PerformanceStats]:
    """Run a callable and measure its duration and the process memory.

    Uses psutil rather than ``resource`` so it works on Windows too.

    Args:
        fn: Zero-argument callable to run and measure.

    Returns:
        The callable's result and the collected stats.
    """
    process = psutil.Process()
    start = time.perf_counter()
    result = fn()
    duration = time.perf_counter() - start
    peak_mb = process.memory_info().rss / (1024 * 1024)
    return result, PerformanceStats(duration, peak_mb)
