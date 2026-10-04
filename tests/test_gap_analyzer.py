"""Tests for snippets/gap_analyzer: stroke gap severity classification.

born from the seventh reclamation — if we can tell a 30-second pause
from a 30-minute stall, a future caretaker can act without guessing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from snippets.gap_analyzer import GapReport, analyze_gaps


UTC = timezone.utc


def _ts(*offsets: float) -> list[datetime]:
    """Build timestamps from a base + list of second-offsets."""
    base = datetime(2026, 10, 4, 16, 0, 0, tzinfo=UTC)
    return [base + timedelta(seconds=s) for s in offsets]


# --- edge cases ----------------------------------------------------------


def test_empty_timestamps():
    r = analyze_gaps([], cadence=15)
    assert r.total_gaps == 0
    assert r.health == "healthy"
    assert r.longest_gap_at is None


def test_single_timestamp():
    r = analyze_gaps([datetime(2026, 10, 4, tzinfo=UTC)], cadence=15)
    assert r.total_gaps == 0
    assert r.mean_gap_seconds == 0.0


def test_two_identical_timestamps():
    t = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    r = analyze_gaps([t, t], cadence=15)
    assert r.total_gaps == 1
    assert r.ok == 1
    assert r.max_gap_seconds == 0.0


# --- bucket classification -----------------------------------------------


def test_all_ok_gaps():
    # cadence=15, OK threshold = 30s; all gaps are 15s
    ts = _ts(0, 15, 30, 45, 60)
    r = analyze_gaps(ts, cadence=15)
    assert r.total_gaps == 4
    assert r.ok == 4
    assert r.warning == 0
    assert r.critical == 0
    assert r.health == "healthy"


def test_warning_gap():
    # cadence=15, warn > 30s, crit > 150s; gap of 60s = warning
    ts = _ts(0, 15, 75)  # 15s ok, 60s warning
    r = analyze_gaps(ts, cadence=15)
    assert r.ok == 1
    assert r.warning == 1
    assert r.critical == 0
    assert r.health == "degraded"


def test_critical_gap():
    # cadence=15, crit > 150s; gap of 300s = critical
    ts = _ts(0, 15, 315)  # 15s ok, 300s critical
    r = analyze_gaps(ts, cadence=15)
    assert r.ok == 1
    assert r.critical == 1
    assert r.health == "critical"


def test_mixed_severities():
    # 15s (ok), 50s (warn), 200s (crit), 15s (ok)
    ts = _ts(0, 15, 65, 265, 280)
    r = analyze_gaps(ts, cadence=15)
    assert r.total_gaps == 4
    assert r.ok == 2
    assert r.warning == 1
    assert r.critical == 1


# --- statistics ----------------------------------------------------------


def test_max_gap_tracking():
    ts = _ts(0, 10, 20, 120, 130)
    r = analyze_gaps(ts, cadence=10)
    assert r.max_gap_seconds == 100.0
    # longest gap ends at offset 120
    assert r.longest_gap_at == datetime(2026, 10, 4, 16, 2, 0, tzinfo=UTC)


def test_mean_gap():
    ts = _ts(0, 10, 30, 60)  # gaps: 10, 20, 30 → mean 20
    r = analyze_gaps(ts, cadence=10)
    assert r.mean_gap_seconds == pytest.approx(20.0)


# --- custom cadence ------------------------------------------------------


def test_custom_cadence():
    # cadence=60: warn > 120s, crit > 600s
    ts = _ts(0, 60, 200, 900)  # 60s ok, 140s warn, 700s crit
    r = analyze_gaps(ts, cadence=60)
    assert r.ok == 1
    assert r.warning == 1
    assert r.critical == 1


# --- boundary conditions -------------------------------------------------


def test_exactly_at_warning_threshold_is_ok():
    # gap == 2*cadence → not > threshold → OK
    ts = _ts(0, 30)  # cadence=15, gap=30 = exactly 2x
    r = analyze_gaps(ts, cadence=15)
    assert r.ok == 1
    assert r.warning == 0


def test_just_above_warning_threshold():
    # gap = 30.001 > 30 → warning
    ts = _ts(0, 30.001)
    r = analyze_gaps(ts, cadence=15)
    assert r.warning == 1
    assert r.ok == 0


def test_exactly_at_critical_threshold_is_warning():
    # gap == 10*cadence → not > threshold → warning (not critical)
    ts = _ts(0, 150)  # cadence=15, gap=150 = exactly 10x
    r = analyze_gaps(ts, cadence=15)
    assert r.warning == 1
    assert r.critical == 0


def test_real_stall_scenario():
    """simulate the 2930s gap from the seventh reclamation."""
    ts = _ts(0, 15, 30, 45, 2975)  # three ok gaps, one 2930s gap
    r = analyze_gaps(ts, cadence=15)
    assert r.ok == 3
    assert r.critical == 1
    assert r.max_gap_seconds == 2930.0
    assert r.health == "critical"
