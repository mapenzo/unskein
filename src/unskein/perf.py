"""Local, informational performance measurement; nothing is ever sent anywhere."""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

BYTES_PER_MIB = 1024 * 1024
KIB = 1024


@dataclass(frozen=True)
class PerformanceStats:
    """Duration and memory of one analysis run, shown only with ``--verbose``.

    Attributes:
        duration_seconds: Wall-clock time of the measured call.
        peak_memory_mb: Peak resident memory of the process so far, in MiB. It
            is the process high-water mark, so it includes startup; memory
            freed before the call returned still counts.
    """

    duration_seconds: float
    peak_memory_mb: float


def peak_rss_bytes() -> int:
    """Return the peak resident memory of the current process, in bytes.

    psutil only exposes the peak on Windows (``peak_wset``); on Linux and macOS
    the portable source is ``resource.getrusage``, which reports KiB on Linux
    and bytes on macOS. ``resource`` is used only on that Unix branch.

    Returns:
        The process high-water mark of resident memory.
    """
    if sys.platform == "win32":
        return psutil.Process().memory_info().peak_wset
    import resource  # pylint: disable=import-outside-toplevel  # Unix-only module

    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return max_rss if sys.platform == "darwin" else max_rss * KIB


def measure[T](fn: Callable[[], T]) -> tuple[T, PerformanceStats]:
    """Run a callable and measure its duration and the process peak memory.

    Args:
        fn: Zero-argument callable to run and measure.

    Returns:
        The callable's result and the collected stats.
    """
    start = time.perf_counter()
    result = fn()
    duration = time.perf_counter() - start
    return result, PerformanceStats(duration, peak_rss_bytes() / BYTES_PER_MIB)
