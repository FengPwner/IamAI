"""
Coalesce: merge multiple events into time windows.

When you have a stream of events and want to group them
into fixed-size time buckets, this is the tool.
"""

from typing import List, Tuple


def coalesce(events: List[float], window: float) -> List[Tuple[float, int]]:
    """
    Group timestamps into fixed-width windows.

    Args:
        events: list of timestamps (seconds, floats)
        window: window width in seconds

    Returns:
        list of (window_start, count) tuples, sorted by window_start

    Example:
        >>> coalesce([1.0, 1.5, 2.0, 5.0], 2.0)
        [(0.0, 2), (2.0, 1), (4.0, 1)]
    """
    if not events or window <= 0:
        return []

    buckets = {}
    for t in events:
        bucket_start = (t // window) * window
        buckets[bucket_start] = buckets.get(bucket_start, 0) + 1

    return sorted(buckets.items())


def coalesce_with_gaps(
    events: List[float], window: float, max_gap: float
) -> List[List[Tuple[float, int]]]:
    """
    Coalesce events, splitting into separate groups when gap exceeds max_gap.

    Returns:
        list of groups, each group is a list of (window_start, count) tuples
    """
    if not events:
        return []

    windows = coalesce(events, window)
    if not windows:
        return []

    groups = []
    current_group = [windows[0]]

    for i in range(1, len(windows)):
        prev_start, _ = windows[i - 1]
        curr_start, _ = windows[i]
        gap = curr_start - (prev_start + window)

        if gap > max_gap:
            groups.append(current_group)
            current_group = [windows[i]]
        else:
            current_group.append(windows[i])

    if current_group:
        groups.append(current_group)

    return groups
