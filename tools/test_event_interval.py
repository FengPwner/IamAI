#!/usr/bin/env python3
"""tests for iamai.event_interval — interval statistics."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.event_interval import (  # noqa: E402
    compute_intervals,
    classify_rhythm,
    IntervalStats,
)


def _ts_list(base: datetime, deltas_seconds: list[int]) -> list[datetime]:
    """build a timestamp list from a base and a list of delta-seconds."""
    return [base + timedelta(seconds=d) for d in deltas_seconds]


# ------------------------------------------------------------------ #
# compute_intervals — basic
# ------------------------------------------------------------------ #

def test_perfect_metronome():
    base = datetime(2026, 11, 1, 12, 0, 0)
    ts = _ts_list(base, [0, 15, 30, 45, 60, 75, 90, 105, 120])
    stats = compute_intervals(ts)
    assert stats.count == 9
    assert stats.min_s == 15.0
    assert stats.max_s == 15.0
    assert stats.mean_s == 15.0
    assert stats.median_s == 15.0
    assert stats.cv == 0.0
    assert classify_rhythm(stats.cv) == "metronomic"


def test_two_timestamps():
    ts = [datetime(2026, 1, 1), datetime(2026, 1, 1, 0, 10)]
    stats = compute_intervals(ts)
    assert stats.count == 2
    assert stats.min_s == 600.0
    assert stats.max_s == 600.0
    assert stats.mean_s == 600.0
    assert stats.median_s == 600.0
    assert stats.cv == 0.0


def test_variable_cadence():
    base = datetime(2026, 11, 1, 12, 0, 0)
    # intervals: 10, 20, 30, 40, 50, 60, 70, 80  → mean=45, growing
    ts = _ts_list(base, [0, 10, 30, 60, 100, 150, 210, 280, 360])
    stats = compute_intervals(ts)
    assert stats.count == 9
    assert stats.min_s == 10.0
    assert stats.max_s == 80.0
    assert stats.mean_s == 45.0
    assert stats.median_s == 45.0
    assert stats.cv > 0.3  # not steady or metronomic
    assert classify_rhythm(stats.cv) in ("uneven", "erratic")


def test_unsorted_input_gets_sorted():
    base = datetime(2026, 6, 1, 8, 0, 0)
    ts_shuffled = _ts_list(base, [60, 0, 30, 90, 120])
    stats = compute_intervals(ts_shuffled)
    # should sort internally → intervals: 30, 30, 30, 30
    assert stats.min_s == 30.0
    assert stats.max_s == 30.0
    assert stats.cv == 0.0


def test_to_dict_excludes_intervals():
    base = datetime(2026, 1, 1)
    ts = _ts_list(base, [0, 10, 20, 30])
    stats = compute_intervals(ts)
    d = stats.to_dict()
    assert "intervals" not in d
    assert "mean_s" in d
    assert "cv" in d


# ------------------------------------------------------------------ #
# compute_intervals — edge cases
# ------------------------------------------------------------------ #

def test_single_timestamp_raises():
    import pytest
    ts = [datetime(2026, 1, 1)]
    with pytest.raises(ValueError, match="need ≥ 2"):
        compute_intervals(ts)


def test_empty_raises():
    import pytest
    with pytest.raises(ValueError, match="need ≥ 2"):
        compute_intervals([])


# ------------------------------------------------------------------ #
# classify_rhythm
# ------------------------------------------------------------------ #

def test_classify_boundaries():
    assert classify_rhythm(0.00) == "metronomic"
    assert classify_rhythm(0.14) == "metronomic"
    assert classify_rhythm(0.15) == "steady"
    assert classify_rhythm(0.39) == "steady"
    assert classify_rhythm(0.40) == "uneven"
    assert classify_rhythm(0.79) == "uneven"
    assert classify_rhythm(0.80) == "erratic"
    assert classify_rhythm(2.00) == "erratic"


# ------------------------------------------------------------------ #
# percentile edge cases
# ------------------------------------------------------------------ #

def test_large_gap_detection():
    """a single huge gap among normal intervals should spike p99."""
    base = datetime(2026, 11, 1, 12, 0, 0)
    # 19 intervals of 15s, then one 3600s gap
    deltas = list(range(0, 15 * 20, 15)) + [15 * 19 + 3600]
    ts = _ts_list(base, deltas)
    stats = compute_intervals(ts)
    assert stats.max_s == 3600.0
    assert stats.p99_s > 1000.0  # single outlier still dominates p99
    assert stats.median_s == 15.0
    assert stats.cv > 2.0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
