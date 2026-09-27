import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class PerformanceStats:
    duration_seconds: float
    peak_memory_mb: float


def measure[T](fn: Callable[[], T]) -> tuple[T, PerformanceStats]:
    process = psutil.Process()
    start = time.perf_counter()
    result = fn()
    duration = time.perf_counter() - start
    peak_mb = process.memory_info().rss / (1024 * 1024)
    return result, PerformanceStats(duration, peak_mb)
