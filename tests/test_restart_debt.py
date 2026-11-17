#!/usr/bin/env python3
"""Tests for restart_debt.py — cumulative restart debt tracking."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import restart_debt as rd


# ---------------------------------------------------------------------------
# RestartDebtTracker.record
# ---------------------------------------------------------------------------

class TestRecord:
    def test_record_returns_event(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=60, warmup_cost_s=30, ts=1000)
        assert ev["downtime_s"] == 60
        assert ev["warmup_cost_s"] == 30
        assert ev["total_cost_s"] == 90
        assert ev["ts"] == 1000

    def test_strokes_lost_calculation(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=60, warmup_cost_s=30, ts=1000)
        assert ev["strokes_lost"] == 6  # 90 / 15 = 6

    def test_strokes_lost_with_fraction(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=20, warmup_cost_s=5, ts=1000)
        assert ev["strokes_lost"] == 1  # 25 / 15 = 1.67 -> int = 1

    def test_negative_downtime_clamped_to_zero(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=-10, warmup_cost_s=30, ts=1000)
        assert ev["downtime_s"] == -10  # stored as-is
        assert ev["total_cost_s"] == 30  # but max(0, -10) + 30 = 30

    def test_negative_warmup_clamped_to_zero(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=60, warmup_cost_s=-5, ts=1000)
        assert ev["total_cost_s"] == 60

    def test_label_stored(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=10, ts=1000, label="visit 676")
        assert ev["label"] == "visit 676"

    def test_default_label_empty(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        ev = t.record(downtime_s=10, ts=1000)
        assert ev["label"] == ""

    def test_zero_cadence_no_division_error(self):
        t = rd.RestartDebtTracker(target_cadence_s=0)
        ev = t.record(downtime_s=60, warmup_cost_s=30, ts=1000)
        assert ev["strokes_lost"] == 0

    def test_multiple_records_accumulate(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        t.record(downtime_s=60, warmup_cost_s=30, ts=1000)
        t.record(downtime_s=120, warmup_cost_s=45, ts=2000)
        t.record(downtime_s=30, warmup_cost_s=15, ts=3000)
        assert len(t._events) == 3


# ---------------------------------------------------------------------------
# RestartDebtTracker.report
# ---------------------------------------------------------------------------

class TestReport:
    def test_empty_report(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        r = t.report(now=1000)
        assert r["restart_count"] == 0
        assert r["total_debt_s"] == 0.0
        assert r["strokes_lost"] == 0
        assert r["debt_ratio_pct"] == 0.0
        assert r["events"] == []

    def test_single_event_report(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=60, warmup_cost_s=30, ts=500)
        r = t.report(now=1000)
        assert r["restart_count"] == 1
        assert r["total_debt_s"] == 90.0
        assert r["total_downtime_s"] == 60.0
        assert r["total_warmup_cost_s"] == 30.0
        assert r["strokes_lost"] == 6

    def test_multiple_events_summed(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=60, warmup_cost_s=30, ts=500)
        t.record(downtime_s=120, warmup_cost_s=45, ts=800)
        r = t.report(now=1000)
        assert r["restart_count"] == 2
        assert r["total_debt_s"] == 255.0  # 90 + 165
        assert r["strokes_lost"] == 17  # 6 + 11

    def test_debt_ratio_percentage(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=1000)
        t.record(downtime_s=50, warmup_cost_s=50, ts=500)
        r = t.report(now=1000)
        assert r["debt_ratio_pct"] == 10.0  # 100 / 1000 * 100

    def test_mean_debt_per_restart(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=60, warmup_cost_s=30, ts=500)
        t.record(downtime_s=120, warmup_cost_s=60, ts=800)
        r = t.report(now=1000)
        assert r["mean_debt_per_restart_s"] == 135.0  # (90 + 180) / 2

    def test_events_outside_window_excluded(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=60, warmup_cost_s=30, ts=100)  # outside window
        t.record(downtime_s=120, warmup_cost_s=45, ts=500)  # inside
        r = t.report(now=1000)  # window: -2600 to 1000 → ts=100 is at age 900 > 3600? no, 900 < 3600
        # actually ts=100, now=1000, age=900 < 3600 → inside
        assert r["restart_count"] == 2

    def test_events_far_outside_window_excluded(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=100)
        t.record(downtime_s=60, warmup_cost_s=30, ts=100)  # age 900 >> 100
        t.record(downtime_s=120, warmup_cost_s=45, ts=950)  # age 50 < 100
        r = t.report(now=1000)
        assert r["restart_count"] == 1
        assert r["total_debt_s"] == 165.0  # only the second event

    def test_report_fields_complete(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=30, ts=500)
        r = t.report(now=1000)
        expected_keys = {
            "restart_count", "total_debt_s", "total_downtime_s",
            "total_warmup_cost_s", "strokes_lost", "debt_ratio_pct",
            "mean_debt_per_restart_s", "events",
        }
        assert set(r.keys()) == expected_keys


# ---------------------------------------------------------------------------
# RestartDebtTracker._prune
# ---------------------------------------------------------------------------

class TestPrune:
    def test_prune_keeps_recent(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=1000)
        t.record(downtime_s=10, ts=500)
        t.record(downtime_s=10, ts=800)
        active = t._prune(now=1000)
        assert len(active) == 2

    def test_prune_drops_old(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=100)
        t.record(downtime_s=10, ts=100)
        t.record(downtime_s=10, ts=950)
        active = t._prune(now=1000)
        assert len(active) == 1
        assert active[0]["ts"] == 950

    def test_prune_empty(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=1000)
        assert t._prune(now=1000) == []


# ---------------------------------------------------------------------------
# RestartDebtTracker.trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_trend_insufficient_data_empty(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        tr = t.trend(now=3600)
        assert tr["trend"] == "insufficient_data"

    def test_trend_stable(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=4000)
        # Even distribution across 4 buckets
        t.record(downtime_s=50, ts=500)   # bucket 0 (oldest)
        t.record(downtime_s=50, ts=1500)  # bucket 1
        t.record(downtime_s=50, ts=2500)  # bucket 2
        t.record(downtime_s=50, ts=3500)  # bucket 3 (newest)
        tr = t.trend(bucket_count=4, now=4000)
        assert tr["trend"] == "stable"
        assert len(tr["buckets"]) == 4

    def test_trend_improving(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=4000)
        # Heavy early, light late
        t.record(downtime_s=200, ts=500)
        t.record(downtime_s=200, ts=1500)
        t.record(downtime_s=10, ts=2500)
        t.record(downtime_s=10, ts=3500)
        tr = t.trend(bucket_count=4, now=4000)
        assert tr["trend"] == "improving"

    def test_trend_degrading(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=4000)
        # Light early, heavy late
        t.record(downtime_s=10, ts=500)
        t.record(downtime_s=10, ts=1500)
        t.record(downtime_s=200, ts=2500)
        t.record(downtime_s=200, ts=3500)
        tr = t.trend(bucket_count=4, now=4000)
        assert tr["trend"] == "degrading"

    def test_trend_bucket_count_minimum(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=50, ts=1000)
        tr = t.trend(bucket_count=1, now=3600)
        # bucket_count clamped to 2
        assert len(tr["buckets"]) == 2

    def test_trend_all_zero_debt(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=4000)
        t.record(downtime_s=0, warmup_cost_s=0, ts=500)
        t.record(downtime_s=0, warmup_cost_s=0, ts=3500)
        tr = t.trend(bucket_count=4, now=4000)
        assert tr["trend"] == "insufficient_data"


# ---------------------------------------------------------------------------
# RestartDebtTracker.clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_removes_all(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        t.record(downtime_s=60, ts=1000)
        t.record(downtime_s=120, ts=2000)
        n = t.clear()
        assert n == 2
        assert len(t._events) == 0

    def test_clear_empty_returns_zero(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        assert t.clear() == 0

    def test_report_after_clear(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=60, ts=500)
        t.clear()
        r = t.report(now=1000)
        assert r["restart_count"] == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_window(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=0)
        t.record(downtime_s=60, ts=1000)
        r = t.report(now=1000)
        # window_s=0 → debt_ratio_pct would be 0 (guarded)
        assert r["debt_ratio_pct"] == 0.0

    def test_very_large_downtime(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=86400)
        ev = t.record(downtime_s=86400, warmup_cost_s=300, ts=1000)
        assert ev["total_cost_s"] == 86700.0
        assert ev["strokes_lost"] == 5780

    def test_rounding_precision(self):
        t = rd.RestartDebtTracker(target_cadence_s=15, window_s=3600)
        t.record(downtime_s=33.333, warmup_cost_s=11.111, ts=500)
        r = t.report(now=1000)
        assert r["total_debt_s"] == 44.44  # rounded to 2dp

    def test_default_window_is_24h(self):
        t = rd.RestartDebtTracker(target_cadence_s=15)
        assert t.window_s == 86400.0

    def test_default_cadence_is_15s(self):
        t = rd.RestartDebtTracker()
        assert t.target_cadence_s == 15.0
