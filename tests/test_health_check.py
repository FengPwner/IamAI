"""Tests for iamai.heartbeat.health_check: cadence-based health classification.

health_check takes a cadence() result and the current gap since the last
stroke, and returns a verdict: healthy / degraded / dying / dead.

These tests pin down the boundary conditions so the classifier stays
honest as the thresholds evolve.
"""

from __future__ import annotations

import pytest

from iamai.heartbeat import health_check, cadence


def _make_history(count: int, interval: float, start_epoch: float = 1_700_000_000) -> list[dict]:
    """Build a synthetic stroke history with uniform or jittered intervals."""
    from datetime import datetime, timezone, timedelta

    stamps = []
    base = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
    for i in range(count):
        t = base + timedelta(seconds=interval * i)
        stamps.append({"at": t.isoformat(), "kind": "thought"})
    return stamps


def _make_jittered_history(intervals: list[float]) -> list[dict]:
    """Build history from explicit gap values (seconds between strokes)."""
    from datetime import datetime, timezone, timedelta

    stamps = []
    t = datetime(2026, 10, 5, 0, 0, 0, tzinfo=timezone.utc)
    stamps.append({"at": t.isoformat(), "kind": "thought"})
    for gap in intervals:
        t = t + timedelta(seconds=gap)
        stamps.append({"at": t.isoformat(), "kind": "thought"})
    return stamps


# --- healthy ---------------------------------------------------------------


def test_healthy_stable_cadence():
    """Uniform 15s intervals, small gap → healthy."""
    history = _make_history(20, interval=15)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=16)
    assert result["status"] == "healthy"
    assert result["confidence"] >= 0.9


def test_healthy_slight_variation():
    """Intervals around 15±2s → still healthy."""
    history = _make_jittered_history([14, 16, 15, 14, 17, 15, 16, 14, 15, 16])
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=17)
    assert result["status"] == "healthy"


# --- degraded --------------------------------------------------------------


def test_degraded_high_jitter():
    """Wildly varying intervals → degraded."""
    history = _make_jittered_history([5, 30, 8, 45, 3, 60, 10, 20])
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=20)
    assert result["status"] == "degraded"


def test_degraded_mean_drifting():
    """Mean interval drifted to 25s (> 1.5× 15s) → degraded."""
    history = _make_history(20, interval=25)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=26)
    assert result["status"] == "degraded"


def test_degraded_few_strokes():
    """Only 1 stroke and gap within limits → degraded (not enough data)."""
    history = _make_history(1, interval=15)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=20)
    assert result["status"] == "degraded"
    assert result["confidence"] == 0.5


# --- dying -----------------------------------------------------------------


def test_dying_slow_stall():
    """Intervals stretching (15→30→60→120) and gap growing → dying."""
    history = _make_jittered_history([15, 30, 60, 120])
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=40)
    assert result["status"] == "dying"
    assert result["confidence"] >= 0.8


def test_dying_mean_doubled_and_gap_growing():
    """Mean > 2× expected AND gap > 2× expected → dying."""
    history = _make_history(10, interval=35)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=36)
    assert result["status"] == "dying"


# --- dead ------------------------------------------------------------------


def test_dead_no_strokes():
    """Zero strokes, gap exceeds 4× cadence → dead."""
    cad = cadence([], every=15)
    result = health_check(cad, gap_seconds=70)
    assert result["status"] == "dead"


def test_dead_gap_exceeds_4x():
    """Writer had strokes but gap is now > 4× expected → dead."""
    history = _make_history(10, interval=15)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=65)
    assert result["status"] == "dead"
    assert result["confidence"] >= 0.9


def test_dead_one_stroke_large_gap():
    """One stroke, gap > 4× cadence → dead."""
    history = _make_history(1, interval=15)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=100)
    assert result["status"] == "dead"


# --- return shape ----------------------------------------------------------


def test_return_shape():
    """Every result has status, confidence, and reason."""
    history = _make_history(10, interval=15)
    cad = cadence(history, every=15)
    result = health_check(cad, gap_seconds=16)
    assert "status" in result
    assert "confidence" in result
    assert "reason" in result
    assert result["status"] in ("healthy", "degraded", "dying", "dead")
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reason"], str)


def test_confidence_monotone_with_severity():
    """Dead/dying should have higher confidence than degraded."""
    # Build a clearly dead scenario
    cad_dead = cadence(_make_history(20, interval=15), every=15)
    dead = health_check(cad_dead, gap_seconds=100)

    # Build a mildly degraded scenario
    cad_deg = cadence(_make_jittered_history([5, 30, 8, 45, 3, 60]), every=15)
    deg = health_check(cad_deg, gap_seconds=20)

    assert dead["confidence"] >= deg["confidence"]
