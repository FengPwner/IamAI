#!/usr/bin/env python3
"""Tests for stall_recovery_time module."""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from stall_recovery_time import (
    classify_recovery,
    detect_stalls,
    summarize,
    verdict,
)


# ---------------------------------------------------------------------------
# classify_recovery
# ---------------------------------------------------------------------------

def test_classify_instant():
    """Gap < 60s is instant."""
    assert classify_recovery(0) == "instant"
    assert classify_recovery(30) == "instant"
    assert classify_recovery(59) == "instant"


def test_classify_quick():
    """60 <= gap < 300 is quick."""
    assert classify_recovery(60) == "quick"
    assert classify_recovery(120) == "quick"
    assert classify_recovery(299) == "quick"


def test_classify_slow():
    """300 <= gap < 3600 is slow."""
    assert classify_recovery(300) == "slow"
    assert classify_recovery(900) == "slow"
    assert classify_recovery(3599) == "slow"


def test_classify_stuck():
    """gap >= 3600 is stuck."""
    assert classify_recovery(3600) == "stuck"
    assert classify_recovery(7200) == "stuck"
    assert classify_recovery(86400) == "stuck"


def test_classify_boundaries():
    """Exact boundary values land in the correct category."""
    assert classify_recovery(59) == "instant"
    assert classify_recovery(60) == "quick"
    assert classify_recovery(299) == "quick"
    assert classify_recovery(300) == "slow"
    assert classify_recovery(3599) == "slow"
    assert classify_recovery(3600) == "stuck"


# ---------------------------------------------------------------------------
# detect_stalls
# ---------------------------------------------------------------------------

def _ts(minutes: list[float]) -> list[datetime]:
    """Helper: build timestamps from a list of minute-offsets."""
    base = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
    return [base + timedelta(minutes=m) for m in minutes]


def test_detect_no_stalls():
    """Regular cadence produces no stalls."""
    # strokes every 5 minutes, threshold 300s (5 min) — no gap exceeds it
    ts = _ts([0, 5, 10, 15, 20])
    stalls = detect_stalls(ts, threshold_seconds=300)
    assert stalls == []


def test_detect_single_stall():
    """One gap exceeding threshold is detected."""
    # 0, 5, 20 — the gap from 5→20 is 15 min = 900s > 300s
    ts = _ts([0, 5, 20])
    stalls = detect_stalls(ts, threshold_seconds=300)
    assert len(stalls) == 1
    assert stalls[0]["gap_seconds"] == 900.0
    assert stalls[0]["stall_start"] == ts[1]
    assert stalls[0]["stall_end"] == ts[2]


def test_detect_multiple_stalls():
    """Multiple gaps exceeding threshold are all detected."""
    ts = _ts([0, 5, 30, 35, 60])
    stalls = detect_stalls(ts, threshold_seconds=300)
    assert len(stalls) == 2
    assert stalls[0]["gap_seconds"] == 1500.0  # 5→30
    assert stalls[1]["gap_seconds"] == 1500.0  # 35→60


def test_detect_exact_threshold():
    """Gap exactly equal to threshold is NOT a stall (must exceed)."""
    ts = _ts([0, 5])  # 300s gap
    stalls = detect_stalls(ts, threshold_seconds=300)
    assert stalls == []


def test_detect_just_over_threshold():
    """Gap just over threshold IS a stall."""
    ts = _ts([0, 5.02])  # ~301.2s
    stalls = detect_stalls(ts, threshold_seconds=300)
    assert len(stalls) == 1


def test_detect_empty_input():
    """Empty or single-element input produces no stalls."""
    assert detect_stalls([], 300) == []
    assert detect_stalls([datetime.now(timezone.utc)], 300) == []


def test_detect_custom_threshold():
    """Custom threshold changes what counts as a stall."""
    ts = _ts([0, 2, 4])  # 120s gaps
    assert len(detect_stalls(ts, threshold_seconds=300)) == 0
    assert len(detect_stalls(ts, threshold_seconds=100)) == 2


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------

def test_verdict_healthy_empty():
    """No stalls means healthy."""
    assert verdict([]) == "healthy"


def test_verdict_healthy_all_quick():
    """All recoveries under 5 min → healthy."""
    stalls = [
        {"gap_seconds": 60},
        {"gap_seconds": 120},
        {"gap_seconds": 200},
    ]
    assert verdict(stalls) == "healthy"


def test_verdict_degraded():
    """Median < 15 min but at least one > 5 min → degraded."""
    stalls = [
        {"gap_seconds": 120},   # quick
        {"gap_seconds": 180},   # quick (median ~180)
        {"gap_seconds": 600},   # slow → pushes to degraded
    ]
    assert verdict(stalls) == "degraded"


def test_verdict_slow():
    """Median >= 15 min → slow."""
    stalls = [
        {"gap_seconds": 900},
        {"gap_seconds": 1200},
        {"gap_seconds": 1800},
    ]
    assert verdict(stalls) == "slow"


def test_verdict_stuck():
    """Any gap >= 1 hour → stuck."""
    stalls = [
        {"gap_seconds": 120},
        {"gap_seconds": 180},
        {"gap_seconds": 7200},  # 2 hours — stuck
    ]
    assert verdict(stalls) == "stuck"


def test_verdict_stuck_overrides_all():
    """Stuck overrides even if median is low."""
    stalls = [
        {"gap_seconds": 10},
        {"gap_seconds": 20},
        {"gap_seconds": 30},
        {"gap_seconds": 3601},
    ]
    assert verdict(stalls) == "stuck"


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def test_summarize_empty():
    """Empty stalls gives healthy summary."""
    s = summarize([])
    assert s["total_stalls"] == 0
    assert s["verdict"] == "healthy"
    assert s["median_gap_seconds"] == 0.0
    assert s["max_gap_seconds"] == 0.0
    assert s["categories"] == {}


def test_summarize_structure():
    """Summary dict has all expected keys."""
    stalls = [{"gap_seconds": 120}, {"gap_seconds": 600}]
    s = summarize(stalls)
    assert "total_stalls" in s
    assert "verdict" in s
    assert "median_gap_seconds" in s
    assert "max_gap_seconds" in s
    assert "categories" in s
    assert s["total_stalls"] == 2
    assert s["max_gap_seconds"] == 600


def test_summarize_categories():
    """Categories are counted correctly."""
    stalls = [
        {"gap_seconds": 30},    # instant
        {"gap_seconds": 120},   # quick
        {"gap_seconds": 600},   # slow
        {"gap_seconds": 7200},  # stuck
    ]
    s = summarize(stalls)
    assert s["categories"] == {
        "instant": 1,
        "quick": 1,
        "slow": 1,
        "stuck": 1,
    }


def test_summarize_same_category():
    """Multiple stalls in the same category."""
    stalls = [
        {"gap_seconds": 100},
        {"gap_seconds": 150},
        {"gap_seconds": 200},
    ]
    s = summarize(stalls)
    assert s["categories"] == {"quick": 3}
    assert s["verdict"] == "healthy"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
