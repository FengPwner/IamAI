"""Tests for heartbeat.cadence -- measuring stroke regularity.

The stall detector answers 'did it stop?'. Cadence answers 'is it limping?'.
A process that takes 45 seconds between strokes instead of 15 is still technically
writing, but something is wrong. These tests ensure the gradient is measured
correctly before the binary stall check fires.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from iamai.heartbeat import cadence


def _stamps(intervals: list[int], start: str = "2026-10-04T00:00:00+00:00") -> list[dict]:
    """Build a history list from a sequence of intervals (seconds)."""
    at = datetime.fromisoformat(start)
    entries = [{"at": at.isoformat(), "kind": "thought"}]
    for gap in intervals:
        at = at + timedelta(seconds=gap)
        entries.append({"at": at.isoformat(), "kind": "thought"})
    return entries


# --- base cases -----------------------------------------------------------


def test_empty_history_is_not_degraded():
    result = cadence([], every=15)
    assert result["count"] == 0
    assert result["degraded"] is False
    assert result["jitter"] == 0.0


def test_single_stroke_is_not_degraded():
    history = [{"at": "2026-10-04T00:00:00+00:00", "kind": "thought"}]
    result = cadence(history, every=15)
    assert result["count"] == 1
    assert result["mean_interval"] == 0.0


# --- perfect cadence ------------------------------------------------------


def test_perfect_cadence_has_zero_jitter():
    # 10 strokes, exactly 15 seconds apart
    history = _stamps([15] * 9)
    result = cadence(history, every=15)
    assert result["count"] == 10
    assert result["mean_interval"] == 15.0
    assert result["std_interval"] == 0.0
    assert result["jitter"] == 0.0
    assert result["degraded"] is False


# --- degraded cadence -----------------------------------------------------


def test_slow_cadence_is_degraded():
    # Each interval is 35s instead of 15s -- more than 2x the expected cadence
    history = _stamps([35] * 5)
    result = cadence(history, every=15)
    assert result["mean_interval"] == 35.0
    assert result["degraded"] is True


def test_jittery_cadence_is_degraded():
    # Intervals swing wildly: 2s, 40s, 2s, 40s -- mean is 21, std is ~19
    # jitter = std / every = ~1.27, which exceeds 1.0
    history = _stamps([2, 40, 2, 40])
    result = cadence(history, every=15)
    assert result["jitter"] > 1.0
    assert result["degraded"] is True


# --- pure arithmetic ------------------------------------------------------


def test_cadence_ignores_non_dict_entries():
    history = [
        {"at": "2026-10-04T00:00:00+00:00", "kind": "thought"},
        "garbage",
        42,
        None,
        {"at": "2026-10-04T00:00:15+00:00", "kind": "thought"},
    ]
    result = cadence(history, every=15)
    assert result["count"] == 2
    assert result["mean_interval"] == 15.0


def test_cadence_skips_entries_without_parseable_timestamps():
    history = [
        {"at": "2026-10-04T00:00:00+00:00", "kind": "thought"},
        {"at": "not-a-date", "kind": "thought"},
        {"at": "2026-10-04T00:00:15+00:00", "kind": "thought"},
    ]
    result = cadence(history, every=15)
    assert result["count"] == 2


def test_cadence_handles_unsorted_input():
    """Timestamps arrive in order from the log, but the function sorts anyway."""
    history = [
        {"at": "2026-10-04T00:00:30+00:00", "kind": "thought"},
        {"at": "2026-10-04T00:00:00+00:00", "kind": "thought"},
        {"at": "2026-10-04T00:00:15+00:00", "kind": "thought"},
    ]
    result = cadence(history, every=15)
    assert result["mean_interval"] == 15.0
    assert result["std_interval"] == 0.0


def test_cadence_preserves_every_parameter():
    result = cadence([], every=30)
    assert result["every"] == 30


def test_cadence_std_is_nonnegative():
    history = _stamps([10, 20, 15, 12, 18])
    result = cadence(history, every=15)
    assert result["std_interval"] >= 0.0
