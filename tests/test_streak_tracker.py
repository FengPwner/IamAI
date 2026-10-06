"""Tests for iamai.streak_tracker"""

from __future__ import annotations

import pytest

from iamai.streak_tracker import StreakTracker, analyze_gaps


# ---------------------------------------------------------------------------
# StreakTracker basics
# ---------------------------------------------------------------------------

class TestStreakTrackerBasic:
    def test_initial_state(self):
        t = StreakTracker(cadence_seconds=15)
        assert t.current == 0
        assert t.best == 0
        s = t.summary()
        assert s["current_streak"] == 0
        assert s["best_streak"] == 0
        assert s["total_events"] == 0

    def test_threshold(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        assert t.threshold == 30.0

    def test_single_on_time(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        result = t.record(gap_seconds=14)
        assert result["current"] == 1
        assert t.current == 1
        assert t.best == 1

    def test_single_late(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        result = t.record(gap_seconds=60)
        assert result["current"] == 0
        assert t.current == 0
        assert t.best == 0

    def test_streak_builds(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        for gap in [10, 12, 15, 14, 16]:
            t.record(gap)
        assert t.current == 5
        assert t.best == 5

    def test_streak_breaks_and_resets(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        for gap in [10, 12, 15]:  # 3 on-time
            t.record(gap)
        assert t.current == 3
        t.record(gap_seconds=120)  # break
        assert t.current == 0
        assert t.best == 3  # historical best preserved

    def test_streak_resumes_after_break(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        # Build a streak of 3
        for gap in [10, 12, 15]:
            t.record(gap)
        t.record(gap_seconds=120)  # break
        # Build a new streak of 4
        for gap in [14, 13, 15, 16]:
            t.record(gap)
        assert t.current == 4
        assert t.best == 4  # new best

    def test_multiple_breaks(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        t.record(10)   # streak 1
        t.record(120)  # break 1
        t.record(10)   # streak 1
        t.record(120)  # break 2
        t.record(10)   # streak 1
        assert t._total_breaks == 2
        assert t.current == 1
        assert t.best == 1

    def test_total_events(self):
        t = StreakTracker(cadence_seconds=15)
        for gap in [10, 12, 120, 14, 15]:
            t.record(gap)
        assert t._total_events == 5

    def test_boundary_exactly_at_threshold(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        # Exactly at threshold (30s) should count as on-time
        t.record(gap_seconds=30.0)
        assert t.current == 1

    def test_boundary_just_over_threshold(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        t.record(gap_seconds=30.1)
        assert t.current == 0


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    def test_record_stroke(self):
        t = StreakTracker(cadence_seconds=15)
        result = t.record_stroke(12)
        assert result["current"] == 1

    def test_record_commit(self):
        t = StreakTracker(cadence_seconds=600)
        result = t.record_commit(500)
        assert result["current"] == 1


# ---------------------------------------------------------------------------
# Summary and reset
# ---------------------------------------------------------------------------

class TestSummaryAndReset:
    def test_summary_fields(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        t.record(10)
        t.record(12)
        t.record(120)
        s = t.summary()
        assert s["current_streak"] == 0
        assert s["best_streak"] == 2
        assert s["total_breaks"] == 1
        assert s["total_events"] == 3
        assert s["cadence_seconds"] == 15
        assert s["tolerance"] == 2.0
        assert s["threshold_seconds"] == 30.0

    def test_reset_clears_everything(self):
        t = StreakTracker(cadence_seconds=15)
        for gap in [10, 12, 15, 120, 14]:
            t.record(gap)
        t.reset()
        assert t.current == 0
        assert t.best == 0
        assert t._total_breaks == 0
        assert t._total_events == 0


# ---------------------------------------------------------------------------
# analyze_gaps (one-shot batch analysis)
# ---------------------------------------------------------------------------

class TestAnalyzeGaps:
    def test_empty_gaps(self):
        result = analyze_gaps([], cadence_seconds=15)
        assert result["best_streak"] == 0
        assert result["streaks"] == []
        assert result["on_time_ratio"] == 0.0

    def test_all_on_time(self):
        gaps = [10, 12, 14, 15, 13]
        result = analyze_gaps(gaps, cadence_seconds=15, tolerance=2.0)
        assert result["best_streak"] == 5
        assert result["total_breaks"] == 0
        assert result["on_time_ratio"] == 1.0

    def test_all_late(self):
        gaps = [60, 120, 90]
        result = analyze_gaps(gaps, cadence_seconds=15, tolerance=2.0)
        assert result["best_streak"] == 0
        assert result["streaks"] == []
        assert result["on_time_ratio"] == 0.0

    def test_mixed_pattern(self):
        # 3 on-time, 1 late, 2 on-time
        gaps = [10, 12, 15, 120, 14, 13]
        result = analyze_gaps(gaps, cadence_seconds=15, tolerance=2.0)
        assert result["streaks"] == [3, 2]
        assert result["best_streak"] == 3
        assert result["total_breaks"] == 1
        assert abs(result["on_time_ratio"] - 5 / 6) < 0.01

    def test_streak_at_end_flushed(self):
        # All on-time, final streak should be captured
        gaps = [10, 12]
        result = analyze_gaps(gaps, cadence_seconds=15)
        assert result["streaks"] == [2]
        assert result["best_streak"] == 2

    def test_single_event_on_time(self):
        result = analyze_gaps([10], cadence_seconds=15)
        assert result["streaks"] == [1]
        assert result["best_streak"] == 1

    def test_single_event_late(self):
        result = analyze_gaps([120], cadence_seconds=15)
        assert result["streaks"] == []
        assert result["best_streak"] == 0

    def test_custom_tolerance(self):
        gaps = [20, 22, 25]
        # With tolerance=1.0, threshold=15 -> all late
        result = analyze_gaps(gaps, cadence_seconds=15, tolerance=1.0)
        assert result["best_streak"] == 0
        # With tolerance=2.0, threshold=30 -> all on-time
        result = analyze_gaps(gaps, cadence_seconds=15, tolerance=2.0)
        assert result["best_streak"] == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_cadence(self):
        # Degenerate: threshold = 0, so nothing can be on-time
        t = StreakTracker(cadence_seconds=0, tolerance=2.0)
        t.record(gap_seconds=0)
        assert t.current == 1  # 0 <= 0 is True

    def test_very_large_gap(self):
        t = StreakTracker(cadence_seconds=15)
        t.record(gap_seconds=1_000_000)
        assert t.current == 0

    def test_fractional_gaps(self):
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        t.record(gap_seconds=14.999)
        assert t.current == 1
        t.record(gap_seconds=30.001)
        assert t.current == 0

    def test_consecutive_breaks_do_not_double_count(self):
        """Two late events in a row should count as one break (first one breaks,
        second one is already at zero)."""
        t = StreakTracker(cadence_seconds=15, tolerance=2.0)
        t.record(10)   # streak 1
        t.record(120)  # break -> total_breaks = 1
        t.record(120)  # still zero, should NOT increment breaks
        assert t._total_breaks == 1
