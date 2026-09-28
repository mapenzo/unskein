import psutil

from unskein.perf import measure, peak_rss_bytes

MIB = 1024 * 1024
ALLOCATION = 200 * MIB


def allocate_and_release() -> int:
    """Touch a large block of memory and release it before returning.

    Returns:
        Size of the block that was allocated.
    """
    block = b"x" * ALLOCATION
    return len(block)


def test_peak_includes_memory_freed_before_the_run_ended() -> None:
    before = psutil.Process().memory_info().rss
    size, stats = measure(allocate_and_release)
    assert size == ALLOCATION
    assert stats.peak_memory_mb * MIB >= before + ALLOCATION * 0.9


def test_peak_is_never_below_current_memory() -> None:
    assert peak_rss_bytes() >= psutil.Process().memory_info().rss * 0.99
