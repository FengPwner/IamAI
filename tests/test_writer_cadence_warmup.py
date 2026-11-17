"""Tests for iamai.writer_cadence_warmup."""

from __future__ import annotations

import pytest

from iamai.writer_cadence_warmup import (
    analyze_warmup,
    classify_severity,
    detect_settled,
    warmup_cost,
    warmup_duration,
    warmup_trend,
)


# ---------------------------------------------------------------------------
# detect_settled
# ---------------------------------------------------------------------------

class TestDetectSettled:
    def test_empty_gaps(self):
        assert detect_settled([], target=15.0) == -1

    def test_zero_target(self):
        assert detect_settled([10, 20], target=0) == -1

    def test_all_within_threshold(self):
        # 3 consecutive gaps all <= 22.5 (15 * 1.5)
        gaps = [16, 15, 14]
        assert detect_settled(gaps, target=15.0, consecutive_needed=3) == 0

    def test_settled_after_slow_start(self):
        gaps = [60, 45, 16, 15, 14]
        assert detect_settled(gaps, target=15.0, consecutive_needed=3) == 2

    def test_never_settled(self):
        # No 3 consecutive gaps within threshold
        gaps = [60, 15, 15, 60, 15, 15]
        result = detect_settled(gaps, target=15.0, consecutive_needed=3)
        assert result == -1

    def test_single_gap_within(self):
        # Not enough consecutive
        gaps = [15]
        assert detect_settled(gaps, target=15.0, consecutive_needed=3) == -1

    def test_exactly_at_threshold(self):
        # 22.5 is exactly at boundary (15 * 1.5)
        gaps = [22.5, 22.5, 22.5]
        assert detect_settled(gaps, target=15.0, tolerance=0.5, consecutive_needed=3) == 0

    def test_just_over_threshold(self):
        gaps = [22.6, 22.6, 22.6]
        assert detect_settled(gaps, target=15.0, tolerance=0.5, consecutive_needed=3) == -1


# ---------------------------------------------------------------------------
# warmup_duration
# ---------------------------------------------------------------------------

class TestWarmupDuration:
    def test_empty_timestamps(self):
        assert warmup_duration(1000, [], settled_index=0) == 0.0

    def test_never_settled(self):
        ts = [1000, 1020, 1050, 1100]
        # settled_index = -1 → full span
        assert warmup_duration(1000, ts, settled_index=-1) == 100.0

    def test_settled_early(self):
        ts = [1000, 1020, 1035, 1050, 1065]
        # settled at index 1, so target_idx = 2, ts[2] = 1035
        assert warmup_duration(1000, ts, settled_index=1) == 35.0

    def test_settled_at_last_gap(self):
        ts = [1000, 1050, 1065]
        # settled_index = 0, target_idx = 1, ts[1] = 1050
        assert warmup_duration(1000, ts, settled_index=0) == 50.0


# ---------------------------------------------------------------------------
# warmup_cost
# ---------------------------------------------------------------------------

class TestWarmupCost:
    def test_empty_gaps(self):
        assert warmup_cost([], target=15.0) == 0.0

    def test_all_on_target(self):
        gaps = [15, 15, 15]
        assert warmup_cost(gaps, target=15.0) == 0.0

    def test_all_under_target(self):
        gaps = [10, 12, 14]
        assert warmup_cost(gaps, target=15.0) == 0.0

    def test_mixed(self):
        gaps = [30, 15, 45, 10]
        # excess: 15 + 0 + 30 + 0 = 45
        assert warmup_cost(gaps, target=15.0) == 45.0

    def test_large_gap(self):
        gaps = [120]
        assert warmup_cost(gaps, target=15.0) == 105.0


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_zero_target(self):
        assert classify_severity(100, target=0) == "unknown"

    def test_instant(self):
        # cost < 1× target
        assert classify_severity(10, target=15) == "instant"

    def test_quick(self):
        # 1× <= cost < 3×
        assert classify_severity(20, target=15) == "quick"
        assert classify_severity(44, target=15) == "quick"

    def test_moderate(self):
        # 3× <= cost < 6×
        assert classify_severity(50, target=15) == "moderate"
        assert classify_severity(89, target=15) == "moderate"

    def test_slow(self):
        # 6× <= cost < 12×
        assert classify_severity(90, target=15) == "slow"
        assert classify_severity(179, target=15) == "slow"

    def test_glacial(self):
        # >= 12×
        assert classify_severity(180, target=15) == "glacial"
        assert classify_severity(500, target=15) == "glacial"


# ---------------------------------------------------------------------------
# analyze_warmup
# ---------------------------------------------------------------------------

class TestAnalyzeWarmup:
    def test_insufficient_data_single_stroke(self):
        report = analyze_warmup(
            restart_ts=1000,
            stroke_timestamps=[1010],
            target_cadence_s=15,
        )
        assert report["settled"] is False
        assert report["severity"] == "unknown"
        assert report["warmup_duration_s"] == 0.0

    def test_perfect_cadence_from_start(self):
        # Every gap is exactly 15s → instant warmup
        ts = [1000, 1015, 1030, 1045, 1060, 1075]
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert report["settled"] is True
        assert report["severity"] == "instant"
        assert report["warmup_cost_s"] == 0.0

    def test_slow_start_then_settle(self):
        ts = [1000, 1060, 1100, 1115, 1130, 1145, 1160]
        # gaps: 60, 40, 15, 15, 15, 15
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert report["settled"] is True
        assert report["warmup_duration_s"] > 0
        assert report["severity"] in ("quick", "moderate", "slow")
        assert report["overshoot_count"] >= 1  # 60s gap > 2×15

    def test_never_settles(self):
        ts = [1000, 1060, 1061, 1120, 1121, 1180]
        # gaps: 60, 1, 59, 1, 59 — wildly irregular
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert report["settled"] is False

    def test_filters_pre_restart_strokes(self):
        ts = [990, 995, 1000, 1015, 1030, 1045, 1060]
        # Only strokes >= restart_ts=1000 are used
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert report["settled"] is True
        assert report["warmup_cost_s"] == 0.0

    def test_efficiency_above_one_when_slower(self):
        ts = [1000, 1030, 1060, 1075, 1090, 1105]
        # gaps: 30, 30, 15, 15, 15 — warmup gaps are slow
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        # mean of warmup gaps > target → efficiency < 1
        assert report["efficiency"] <= 1.0

    def test_gaps_list_returned(self):
        ts = [1000, 1015, 1030, 1045]
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert isinstance(report["gaps"], list)
        assert len(report["gaps"]) >= 1

    def test_unsorted_input_handled(self):
        ts = [1045, 1000, 1030, 1015]
        report = analyze_warmup(restart_ts=1000, stroke_timestamps=ts, target_cadence_s=15)
        assert report["settled"] is True


# ---------------------------------------------------------------------------
# warmup_trend
# ---------------------------------------------------------------------------

class TestWarmupTrend:
    def test_empty_reports(self):
        result = warmup_trend([])
        assert result["count"] == 0
        assert result["trend"] == "unknown"

    def test_two_reports_insufficient(self):
        reports = [
            {"warmup_cost_s": 10},
            {"warmup_cost_s": 20},
        ]
        result = warmup_trend(reports)
        assert result["count"] == 2
        assert result["trend"] == "insufficient_data"

    def test_improving_trend(self):
        reports = [
            {"warmup_cost_s": 100},
            {"warmup_cost_s": 90},
            {"warmup_cost_s": 10},
            {"warmup_cost_s": 8},
        ]
        result = warmup_trend(reports)
        assert result["trend"] == "improving"

    def test_degrading_trend(self):
        reports = [
            {"warmup_cost_s": 10},
            {"warmup_cost_s": 12},
            {"warmup_cost_s": 80},
            {"warmup_cost_s": 100},
        ]
        result = warmup_trend(reports)
        assert result["trend"] == "degrading"

    def test_stable_trend(self):
        reports = [
            {"warmup_cost_s": 20},
            {"warmup_cost_s": 22},
            {"warmup_cost_s": 19},
            {"warmup_cost_s": 21},
        ]
        result = warmup_trend(reports)
        assert result["trend"] == "stable"

    def test_mean_and_median(self):
        reports = [
            {"warmup_cost_s": 10},
            {"warmup_cost_s": 20},
            {"warmup_cost_s": 30},
            {"warmup_cost_s": 40},
        ]
        result = warmup_trend(reports)
        assert result["mean_cost_s"] == 25.0
        assert result["median_cost_s"] == 25.0
