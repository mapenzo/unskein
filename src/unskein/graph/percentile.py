"""Nearest-rank percentile shared by the coupling selection and the findings."""

import math


def nearest_rank_percentile(values: list[int], percentile: int) -> int:
    """Return the nearest-rank percentile of a non-empty list of numbers.

    The value is the ``ceil(percentile / 100 * n)``-th smallest one, with no
    interpolation, so it is always a real score and easy to explain.

    Args:
        values: Numbers to rank, in any order; must not be empty.
        percentile: Percentile to take, from 1 to 100.

    Returns:
        The percentile value.

    Raises:
        IndexError: If ``values`` is empty.
    """
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]
