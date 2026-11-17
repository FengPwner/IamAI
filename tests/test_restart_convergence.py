#!/usr/bin/env python3
"""Tests for iamai/restart_convergence.py — post-restart convergence tracking."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.restart_convergence import ConvergenceTracker, DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tracker() -> ConvergenceTracker:
    """Fresh tracker with a fixed clock at t=1000."""
    return ConvergenceTracker(now=1000.0)


@pytest.fixture
def tracker_custom_thresholds() -> ConvergenceTracker:
    """Tracker with tight thresholds for boundary testing."""
    return ConvergenceTracker(
        thresholds={"stroke_s": 10.0, "push_s": 20.0, "backlog_s": 15.0, "total_s": 25.0},
        now=1000.0,
    )


# ---------------------------------------------------------------------------
# initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_not_restarted(self, tracker: ConvergenceTracker) -> None:
        assert not tracker.restarted

    def test_not_converged(self, tracker: ConvergenceTracker) -> None:
        assert not tracker.converged

    def test_elapsed_is_none(self, tracker: ConvergenceTracker) -> None:
        assert tracker.elapsed_since_restart() is None

    def test_report_no_restart(self, tracker: ConvergenceTracker) -> None:
        r = tracker.report()
        assert r["restarted"] is False
        assert r["converged"] is False
        assert r["healthy"] is None
        assert r["detail"] == "no restart recorded"


# ---------------------------------------------------------------------------
# mark_restart
# ---------------------------------------------------------------------------


class TestMarkRestart:
    def test_sets_restart_time(self, tracker: ConvergenceTracker) -> None:
        t = tracker.mark_restart()
        assert t == 1000.0
        assert tracker.restarted

    def test_elapsed_after_restart(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=990.0)
        assert tracker.elapsed_since_restart(now=1000.0) == pytest.approx(10.0)

    def test_restart_resets_milestones(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=900.0)
        tracker.mark_first_stroke(t=910.0)
        tracker.mark_first_push(t=920.0)
        tracker.mark_backlog_clear(t=930.0)
        assert tracker.converged

        # Second restart clears downstream marks.
        tracker.mark_restart(t=1000.0)
        assert not tracker.converged
        assert tracker._stroke_t is None
        assert tracker._push_t is None
        assert tracker._backlog_t is None

    def test_mark_restart_with_explicit_time(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=500.0)
        assert tracker._restart_t == 500.0


# ---------------------------------------------------------------------------
# milestone marking
# ---------------------------------------------------------------------------


class TestMilestones:
    def test_first_stroke(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        t = tracker.mark_first_stroke(t=1012.0)
        assert t == 1012.0

    def test_first_push(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        t = tracker.mark_first_push(t=1060.0)
        assert t == 1060.0

    def test_backlog_clear(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        t = tracker.mark_backlog_clear(t=1045.0)
        assert t == 1045.0

    def test_idempotent_stroke(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.0)
        tracker.mark_first_stroke(t=1020.0)  # should be ignored
        assert tracker._stroke_t == 1010.0

    def test_idempotent_push(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_push(t=1050.0)
        tracker.mark_first_push(t=1070.0)
        assert tracker._push_t == 1050.0

    def test_idempotent_backlog(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_backlog_clear(t=1030.0)
        tracker.mark_backlog_clear(t=1040.0)
        assert tracker._backlog_t == 1030.0


# ---------------------------------------------------------------------------
# convergence
# ---------------------------------------------------------------------------


class TestConvergence:
    def test_converged_when_all_marked(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.0)
        tracker.mark_first_push(t=1050.0)
        tracker.mark_backlog_clear(t=1030.0)
        assert tracker.converged

    def test_not_converged_partial(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.0)
        assert not tracker.converged


# ---------------------------------------------------------------------------
# report — healthy convergence
# ---------------------------------------------------------------------------


class TestHealthyReport:
    def test_all_within_thresholds(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1015.0)   # 15s < 60s
        tracker.mark_first_push(t=1060.0)     # 60s < 660s
        tracker.mark_backlog_clear(t=1045.0)  # 45s < 300s

        r = tracker.report(now=1100.0)
        assert r["converged"] is True
        assert r["restarted"] is True
        assert r["healthy"] is True
        assert r["stroke_s"] == pytest.approx(15.0)
        assert r["push_s"] == pytest.approx(60.0)
        assert r["backlog_s"] == pytest.approx(45.0)
        assert r["total_s"] == pytest.approx(60.0)  # max of all latencies
        assert "all within thresholds" in r["detail"]

    def test_elapsed_is_now_minus_restart(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.0)
        tracker.mark_first_push(t=1050.0)
        tracker.mark_backlog_clear(t=1030.0)

        r = tracker.report(now=1200.0)
        assert r["elapsed_s"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# report — unhealthy convergence
# ---------------------------------------------------------------------------


class TestUnhealthyReport:
    def test_slow_stroke(self, tracker_custom_thresholds: ConvergenceTracker) -> None:
        t = tracker_custom_thresholds
        t.mark_restart(t=1000.0)
        t.mark_first_stroke(t=1025.0)   # 25s > 10s threshold
        t.mark_first_push(t=1015.0)     # 15s < 20s
        t.mark_backlog_clear(t=1012.0)  # 12s < 15s

        r = t.report(now=1100.0)
        assert r["converged"] is True
        assert r["healthy"] is False
        assert "stroke_s" in r["detail"]

    def test_slow_push(self, tracker_custom_thresholds: ConvergenceTracker) -> None:
        t = tracker_custom_thresholds
        t.mark_restart(t=1000.0)
        t.mark_first_stroke(t=1005.0)   # 5s < 10s
        t.mark_first_push(t=1030.0)     # 30s > 20s
        t.mark_backlog_clear(t=1010.0)  # 10s < 15s

        r = t.report(now=1100.0)
        assert r["healthy"] is False
        assert "push_s" in r["detail"]

    def test_total_exceeds_threshold(self, tracker_custom_thresholds: ConvergenceTracker) -> None:
        t = tracker_custom_thresholds
        t.mark_restart(t=1000.0)
        t.mark_first_stroke(t=1005.0)   # 5s
        t.mark_first_push(t=1018.0)     # 18s
        t.mark_backlog_clear(t=1030.0)  # 30s > 25s total threshold

        r = t.report(now=1100.0)
        assert r["healthy"] is False
        assert "total_s" in r["detail"]

    def test_all_slow(self, tracker_custom_thresholds: ConvergenceTracker) -> None:
        t = tracker_custom_thresholds
        t.mark_restart(t=1000.0)
        t.mark_first_stroke(t=1050.0)   # 50s > 10s
        t.mark_first_push(t=1080.0)     # 80s > 20s
        t.mark_backlog_clear(t=1060.0)  # 60s > 15s

        r = t.report(now=1200.0)
        assert r["healthy"] is False
        assert r["total_s"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# report — partial convergence
# ---------------------------------------------------------------------------


class TestPartialReport:
    def test_missing_push(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.0)
        tracker.mark_backlog_clear(t=1030.0)

        r = tracker.report(now=1100.0)
        assert r["converged"] is False
        assert r["healthy"] is None
        assert r["stroke_s"] == pytest.approx(10.0)
        assert r["push_s"] is None
        assert r["backlog_s"] == pytest.approx(30.0)
        assert "first_push" in r["detail"]
        assert "100s elapsed" in r["detail"]

    def test_missing_all_milestones(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        r = tracker.report(now=1050.0)
        assert r["converged"] is False
        assert r["stroke_s"] is None
        assert r["push_s"] is None
        assert r["backlog_s"] is None
        assert "first_stroke" in r["detail"]
        assert "first_push" in r["detail"]
        assert "backlog_clear" in r["detail"]


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_latency(self, tracker: ConvergenceTracker) -> None:
        """All milestones at restart time — instant convergence."""
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1000.0)
        tracker.mark_first_push(t=1000.0)
        tracker.mark_backlog_clear(t=1000.0)

        r = tracker.report(now=1000.0)
        assert r["converged"] is True
        assert r["healthy"] is True
        assert r["stroke_s"] == pytest.approx(0.0)
        assert r["push_s"] == pytest.approx(0.0)
        assert r["backlog_s"] == pytest.approx(0.0)
        assert r["total_s"] == pytest.approx(0.0)

    def test_custom_thresholds_merge(self) -> None:
        """Partial threshold override merges with defaults."""
        t = ConvergenceTracker(thresholds={"stroke_s": 5.0}, now=1000.0)
        assert t._thresholds["stroke_s"] == 5.0
        assert t._thresholds["push_s"] == DEFAULT_THRESHOLDS["push_s"]

    def test_report_rounding(self, tracker: ConvergenceTracker) -> None:
        tracker.mark_restart(t=1000.0)
        tracker.mark_first_stroke(t=1010.567)
        tracker.mark_first_push(t=1050.123)
        tracker.mark_backlog_clear(t=1030.789)

        r = tracker.report(now=1100.0)
        assert r["stroke_s"] == pytest.approx(10.6)
        assert r["push_s"] == pytest.approx(50.1)
        assert r["backlog_s"] == pytest.approx(30.8)

    def test_elapsed_without_restart(self, tracker: ConvergenceTracker) -> None:
        assert tracker.elapsed_since_restart(now=2000.0) is None
