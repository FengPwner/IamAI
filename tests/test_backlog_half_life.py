"""Tests for iamai.backlog_half_life."""

from datetime import datetime, timedelta, timezone

import pytest

from iamai.backlog_half_life import (
    BacklogReport,
    _classify,
    _empirical_half_life,
    _to_seconds,
    compute_half_life,
    report_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 22, 8, 0, 0, tzinfo=timezone.utc)


def _dt(minutes: float) -> datetime:
    """Helper: T0 + minutes."""
    return T0 + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# _to_seconds
# ---------------------------------------------------------------------------

class TestToSeconds:
    def test_aware_datetime(self):
        s = _to_seconds(T0)
        assert isinstance(s, float)
        assert s > 0

    def test_naive_gets_utc(self):
        naive = datetime(2026, 10, 22, 8, 0, 0)
        aware = datetime(2026, 10, 22, 8, 0, 0, tzinfo=timezone.utc)
        assert _to_seconds(naive) == _to_seconds(aware)


# ---------------------------------------------------------------------------
# _empirical_half_life
# ---------------------------------------------------------------------------

class TestEmpiricalHalfLife:
    def test_empty(self):
        assert _empirical_half_life([]) is None

    def test_single(self):
        assert _empirical_half_life([5.0]) is None

    def test_two_values(self):
        assert _empirical_half_life([10.0, 20.0]) == 15.0

    def test_odd_count(self):
        assert _empirical_half_life([10.0, 20.0, 30.0]) == 20.0

    def test_even_count(self):
        result = _empirical_half_life([10.0, 20.0, 30.0, 40.0])
        assert result == 25.0

    def test_unsorted_input(self):
        result = _empirical_half_life([40.0, 10.0, 30.0, 20.0])
        assert result == 25.0


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_draining(self):
        assert _classify(300.0, 500.0, 0, 600.0) == "draining"

    def test_stagnant(self):
        assert _classify(1200.0, 1500.0, 0, 600.0) == "stagnant"

    def test_accumulating(self):
        assert _classify(2000.0, 2500.0, 5, 600.0) == "accumulating"

    def test_none_half_life_with_pending(self):
        assert _classify(None, 0.0, 3, 600.0) == "accumulating"

    def test_none_half_life_no_pending(self):
        assert _classify(None, 0.0, 0, 600.0) == "draining"

    def test_boundary_drain(self):
        # exactly 1.5 * interval, max within 3x
        assert _classify(900.0, 1800.0, 0, 600.0) == "draining"

    def test_boundary_stagnant(self):
        # exactly 3.0 * interval
        assert _classify(1800.0, 1800.0, 0, 600.0) == "stagnant"


# ---------------------------------------------------------------------------
# compute_half_life
# ---------------------------------------------------------------------------

class TestComputeHalfLife:
    def test_empty_events(self):
        report = compute_half_life([], batch_interval=600.0)
        assert report.total_files == 0
        assert report.resolved == 0
        assert report.pending == 0
        assert report.half_life is None
        assert report.verdict == "draining"

    def test_all_resolved_fast(self):
        events = [
            (_dt(0), _dt(5)),
            (_dt(2), _dt(7)),
            (_dt(4), _dt(9)),
            (_dt(6), _dt(10)),
        ]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(15))
        assert report.total_files == 4
        assert report.resolved == 4
        assert report.pending == 0
        assert report.half_life is not None
        assert report.half_life == 300.0  # 5 minutes = 300s
        assert report.verdict == "draining"

    def test_all_pending(self):
        events = [
            (_dt(0), None),
            (_dt(5), None),
        ]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(20))
        assert report.total_files == 2
        assert report.resolved == 0
        assert report.pending == 2
        assert report.half_life is None
        assert report.verdict == "accumulating"

    def test_mixed_resolved_pending(self):
        events = [
            (_dt(0), _dt(5)),    # resolved, 300s residence
            (_dt(2), _dt(10)),   # resolved, 480s residence
            (_dt(4), _dt(8)),    # resolved, 240s residence
            (_dt(6), None),      # pending
            (_dt(8), None),      # pending
        ]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(15))
        assert report.total_files == 5
        assert report.resolved == 3
        assert report.pending == 2
        assert report.half_life is not None
        # residence times: [300, 480, 240] sorted: [240, 300, 480], median=300
        assert report.half_life == 300.0
        assert report.median_residence == 300.0
        assert report.max_residence == 480.0

    def test_drain_rate_computed(self):
        events = [
            (_dt(0), _dt(10)),
            (_dt(5), _dt(10)),
        ]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(20))
        assert report.drain_rate_per_min > 0
        # 2 resolved over 20 minutes = 0.1/min
        assert abs(report.drain_rate_per_min - 0.1) < 0.01

    def test_negative_residence_clamped(self):
        # resolved before appeared (clock skew) → clamped to 0
        events = [
            (_dt(10), _dt(5)),
            (_dt(0), _dt(10)),
        ]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(15))
        assert all(t >= 0 for t in report.residence_times)

    def test_single_resolved_file(self):
        events = [(_dt(0), _dt(5))]
        report = compute_half_life(events, batch_interval=600.0, now=_dt(10))
        assert report.total_files == 1
        assert report.half_life is None  # need ≥2 for half-life


# ---------------------------------------------------------------------------
# report_summary
# ---------------------------------------------------------------------------

class TestReportSummary:
    def test_basic(self):
        report = BacklogReport(
            total_files=5,
            resolved=3,
            pending=2,
            half_life=300.0,
            drain_rate_per_min=0.15,
            verdict="draining",
        )
        s = report_summary(report)
        assert "5 files" in s
        assert "3 resolved" in s
        assert "2 pending" in s
        assert "300s" in s
        assert "draining" in s

    def test_none_half_life(self):
        report = BacklogReport(
            total_files=2,
            resolved=0,
            pending=2,
            half_life=None,
            drain_rate_per_min=0.0,
            verdict="accumulating",
        )
        s = report_summary(report)
        assert "n/a" in s
        assert "accumulating" in s
