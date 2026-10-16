"""Tests for iamai.restart_overhead.

Covers: RestartRecord (construction, properties, edge cases),
RestartOverheadTracker (record, queries, health, trend, summarize,
reset, error handling).
"""

import pytest
from iamai.restart_overhead import (
    RestartOverheadTracker,
    RestartRecord,
)


# ------------------------------------------------------------------
# RestartRecord — construction
# ------------------------------------------------------------------


class TestRestartRecordConstruction:
    """RestartRecord instantiation and validation."""

    def test_minimal(self):
        r = RestartRecord(downtime_s=30)
        assert r.downtime_s == 30
        assert r.warmup_s == 0.0
        assert r.commit_debt == 0

    def test_full_params(self):
        r = RestartRecord(downtime_s=60, warmup_s=15, commit_debt=5)
        assert r.downtime_s == 60
        assert r.warmup_s == 15
        assert r.commit_debt == 5

    def test_zero_downtime(self):
        r = RestartRecord(downtime_s=0)
        assert r.downtime_s == 0
        assert r.total_overhead_s == 0.0

    def test_negative_downtime_rejected(self):
        with pytest.raises(ValueError, match="downtime_s must be >= 0"):
            RestartRecord(downtime_s=-1)

    def test_negative_warmup_rejected(self):
        with pytest.raises(ValueError, match="warmup_s must be >= 0"):
            RestartRecord(downtime_s=10, warmup_s=-5)

    def test_negative_commit_debt_rejected(self):
        with pytest.raises(ValueError, match="commit_debt must be >= 0"):
            RestartRecord(downtime_s=10, commit_debt=-1)

    def test_timestamp_auto(self):
        r = RestartRecord(downtime_s=10)
        assert r.timestamp is not None
        assert r.timestamp > 0

    def test_timestamp_explicit(self):
        r = RestartRecord(downtime_s=10, timestamp=1000.0)
        assert r.timestamp == 1000.0


# ------------------------------------------------------------------
# RestartRecord — properties
# ------------------------------------------------------------------


class TestRestartRecordProperties:
    """Computed properties on RestartRecord."""

    def test_total_overhead(self):
        r = RestartRecord(downtime_s=30, warmup_s=15)
        assert r.total_overhead_s == 45.0

    def test_total_overhead_no_warmup(self):
        r = RestartRecord(downtime_s=30)
        assert r.total_overhead_s == 30.0

    def test_lost_strokes(self):
        r = RestartRecord(downtime_s=45)
        assert r.lost_strokes(15.0) == 3.0

    def test_lost_strokes_fractional(self):
        r = RestartRecord(downtime_s=20)
        lost = r.lost_strokes(15.0)
        assert lost == pytest.approx(20 / 15)

    def test_lost_strokes_zero_cadence(self):
        r = RestartRecord(downtime_s=30)
        assert r.lost_strokes(0) == 0.0

    def test_lost_strokes_negative_cadence(self):
        r = RestartRecord(downtime_s=30)
        assert r.lost_strokes(-5) == 0.0

    def test_overhead_ratio_basic(self):
        # downtime=45, warmup=15 → overhead=60
        # lost_strokes(15) = 3 → ideal = 3*15 = 45
        # ratio = 60/45 = 1.333...
        r = RestartRecord(downtime_s=45, warmup_s=15)
        ratio = r.overhead_ratio(15.0)
        assert ratio == pytest.approx(60 / 45)

    def test_overhead_ratio_no_lost_strokes(self):
        # downtime=5, cadence=15 → lost=0.33 (< 1) → ratio=0
        r = RestartRecord(downtime_s=5)
        assert r.overhead_ratio(15.0) == 0.0

    def test_overhead_ratio_exact_one_stroke(self):
        # downtime=15, warmup=0 → overhead=15, lost=1 → ratio=1.0
        r = RestartRecord(downtime_s=15)
        assert r.overhead_ratio(15.0) == 1.0


# ------------------------------------------------------------------
# RestartOverheadTracker — construction
# ------------------------------------------------------------------


class TestTrackerConstruction:
    """Tracker instantiation and validation."""

    def test_defaults(self):
        t = RestartOverheadTracker()
        assert t.cadence_s == 15.0
        assert t.clean_threshold == 2.0
        assert t.heavy_threshold == 10.0
        assert t.max_history == 200
        assert t.restart_count == 0

    def test_custom_params(self):
        t = RestartOverheadTracker(
            cadence_s=30, clean_threshold=3, heavy_threshold=15
        )
        assert t.cadence_s == 30.0
        assert t.clean_threshold == 3.0
        assert t.heavy_threshold == 15.0

    def test_zero_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            RestartOverheadTracker(cadence_s=0)

    def test_negative_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            RestartOverheadTracker(cadence_s=-10)

    def test_zero_clean_threshold_rejected(self):
        with pytest.raises(ValueError, match="clean_threshold must be > 0"):
            RestartOverheadTracker(clean_threshold=0)

    def test_heavy_must_exceed_clean(self):
        with pytest.raises(ValueError, match="must exceed"):
            RestartOverheadTracker(clean_threshold=10, heavy_threshold=5)

    def test_zero_max_history_rejected(self):
        with pytest.raises(ValueError, match="max_history must be >= 1"):
            RestartOverheadTracker(max_history=0)


# ------------------------------------------------------------------
# RestartOverheadTracker — recording
# ------------------------------------------------------------------


class TestTrackerRecording:
    """Recording restart events."""

    def test_record_returns_record(self):
        t = RestartOverheadTracker()
        rec = t.record(downtime_s=30)
        assert isinstance(rec, RestartRecord)
        assert rec.downtime_s == 30

    def test_record_increments_count(self):
        t = RestartOverheadTracker()
        assert t.restart_count == 0
        t.record(downtime_s=10)
        assert t.restart_count == 1
        t.record(downtime_s=20)
        assert t.restart_count == 2

    def test_record_with_all_params(self):
        t = RestartOverheadTracker()
        t.record(downtime_s=30, warmup_s=15, commit_debt=5)
        assert t.total_downtime_s == 30
        assert t.total_warmup_s == 15
        assert t.total_commit_debt == 5

    def test_max_history_enforced(self):
        t = RestartOverheadTracker(max_history=3)
        for i in range(10):
            t.record(downtime_s=float(i))
        assert t.restart_count == 3
        # should keep the last 3: 7, 8, 9
        assert t.total_downtime_s == 7 + 8 + 9

    def test_max_history_one(self):
        t = RestartOverheadTracker(max_history=1)
        t.record(downtime_s=10)
        t.record(downtime_s=20)
        assert t.restart_count == 1
        assert t.total_downtime_s == 20


# ------------------------------------------------------------------
# RestartOverheadTracker — queries
# ------------------------------------------------------------------


class TestTrackerQueries:
    """Aggregate queries on tracker."""

    def _seeded_tracker(self):
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=30, warmup_s=10, commit_debt=3)
        t.record(downtime_s=60, warmup_s=20, commit_debt=7)
        t.record(downtime_s=15, warmup_s=5, commit_debt=1)
        return t

    def test_total_downtime(self):
        t = self._seeded_tracker()
        assert t.total_downtime_s == 105

    def test_total_warmup(self):
        t = self._seeded_tracker()
        assert t.total_warmup_s == 35

    def test_total_commit_debt(self):
        t = self._seeded_tracker()
        assert t.total_commit_debt == 11

    def test_mean_downtime(self):
        t = self._seeded_tracker()
        assert t.mean_downtime() == pytest.approx(35.0)

    def test_mean_warmup(self):
        t = self._seeded_tracker()
        assert t.mean_warmup() == pytest.approx(35 / 3)

    def test_mean_overhead(self):
        t = self._seeded_tracker()
        # overheads: 40, 80, 20 → mean = 140/3 ≈ 46.67
        assert t.mean_overhead() == pytest.approx(140 / 3)

    def test_worst_overhead(self):
        t = self._seeded_tracker()
        assert t.worst_overhead() == 80.0

    def test_total_lost_strokes(self):
        t = self._seeded_tracker()
        # 30/15 + 60/15 + 15/15 = 2 + 4 + 1 = 7
        assert t.total_lost_strokes() == pytest.approx(7.0)

    def test_mean_lost_strokes(self):
        t = self._seeded_tracker()
        assert t.mean_lost_strokes() == pytest.approx(7 / 3)

    def test_empty_queries(self):
        t = RestartOverheadTracker()
        assert t.total_downtime_s == 0
        assert t.total_warmup_s == 0
        assert t.total_commit_debt == 0
        assert t.mean_downtime() == 0.0
        assert t.mean_warmup() == 0.0
        assert t.mean_overhead() == 0.0
        assert t.worst_overhead() == 0.0
        assert t.total_lost_strokes() == 0.0
        assert t.mean_lost_strokes() == 0.0


# ------------------------------------------------------------------
# RestartOverheadTracker — health
# ------------------------------------------------------------------


class TestTrackerHealth:
    """Health verdicts for latest and overall."""

    def test_empty_health_is_clean(self):
        t = RestartOverheadTracker()
        assert t.health() == "clean"
        assert t.overall_health() == "clean"

    def test_clean_restart(self):
        # overhead 20 < 2*15=30 → clean
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=15, warmup_s=5)
        assert t.health() == "clean"

    def test_tolerable_restart(self):
        # overhead 45 >= 30 but < 150 → tolerable
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=30, warmup_s=15)
        assert t.health() == "tolerable"

    def test_heavy_restart(self):
        # overhead 200 >= 150 → heavy
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=150, warmup_s=50)
        assert t.health() == "heavy"

    def test_overall_health_averaged(self):
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=5, warmup_s=5)    # overhead 10 (clean)
        t.record(downtime_s=5, warmup_s=5)    # overhead 10 (clean)
        t.record(downtime_s=5, warmup_s=5)    # overhead 10 (clean)
        assert t.overall_health() == "clean"
        # Now add a big one
        t.record(downtime_s=200, warmup_s=100)  # overhead 300 (heavy)
        # mean overhead = (10+10+10+300)/4 = 82.5
        # 82.5 >= 30 → tolerable (but not >= 150)
        assert t.overall_health() == "tolerable"

    def test_latest_vs_overall_differ(self):
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=50, warmup_s=30)     # overhead 80 → heavy (>=150? no, 80<150 → tolerable)
        t.record(downtime_s=5, warmup_s=5)        # overhead 10 → clean
        assert t.health() == "clean"              # latest
        # avg overhead = (80+10)/2 = 45, >= 30 (2*15) → tolerable
        assert t.overall_health() == "tolerable"


# ------------------------------------------------------------------
# RestartOverheadTracker — trend
# ------------------------------------------------------------------


class TestTrackerTrend:
    """Trend analysis across restart history."""

    def test_stable_when_few_records(self):
        t = RestartOverheadTracker()
        t.record(downtime_s=10)
        t.record(downtime_s=20)
        assert t.trend() == "stable"

    def test_stable_with_three(self):
        t = RestartOverheadTracker()
        for _ in range(3):
            t.record(downtime_s=10)
        assert t.trend() == "stable"

    def test_worsening_trend(self):
        t = RestartOverheadTracker(cadence_s=15)
        # first half: small overheads
        t.record(downtime_s=5, warmup_s=0)
        t.record(downtime_s=5, warmup_s=0)
        # second half: large overheads (delta > cadence_s)
        t.record(downtime_s=100, warmup_s=50)
        t.record(downtime_s=100, warmup_s=50)
        assert t.trend() == "worsening"

    def test_improving_trend(self):
        t = RestartOverheadTracker(cadence_s=15)
        # first half: large overheads
        t.record(downtime_s=100, warmup_s=50)
        t.record(downtime_s=100, warmup_s=50)
        # second half: small overheads (delta < -cadence_s)
        t.record(downtime_s=5, warmup_s=0)
        t.record(downtime_s=5, warmup_s=0)
        assert t.trend() == "improving"

    def test_stable_trend_equal(self):
        t = RestartOverheadTracker(cadence_s=15)
        for _ in range(6):
            t.record(downtime_s=20, warmup_s=5)
        assert t.trend() == "stable"


# ------------------------------------------------------------------
# RestartOverheadTracker — summarize
# ------------------------------------------------------------------


class TestTrackerSummarize:
    """JSON-serializable summary."""

    def test_empty_summary(self):
        t = RestartOverheadTracker()
        s = t.summarize()
        assert s["restart_count"] == 0
        assert s["health_latest"] == "clean"
        assert s["health_overall"] == "clean"
        assert s["trend"] == "stable"

    def test_populated_summary(self):
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=30, warmup_s=10, commit_debt=3)
        t.record(downtime_s=60, warmup_s=20, commit_debt=7)
        s = t.summarize()
        assert s["restart_count"] == 2
        assert s["total_downtime_s"] == 90
        assert s["total_warmup_s"] == 30
        assert s["total_commit_debt"] == 10
        assert "mean_overhead_s" in s
        assert "worst_overhead_s" in s
        assert "health_latest" in s
        assert "health_overall" in s
        assert "trend" in s

    def test_report_line_format(self):
        t = RestartOverheadTracker(cadence_s=15)
        t.record(downtime_s=30, warmup_s=10, commit_debt=3)
        line = t.report_line()
        assert "restart_overhead:" in line
        assert "restarts" in line
        assert "avg overhead" in line


# ------------------------------------------------------------------
# RestartOverheadTracker — reset
# ------------------------------------------------------------------


class TestTrackerReset:
    """Reset clears all state."""

    def test_reset(self):
        t = RestartOverheadTracker()
        t.record(downtime_s=30)
        t.record(downtime_s=60)
        assert t.restart_count == 2
        t.reset()
        assert t.restart_count == 0
        assert t.total_downtime_s == 0
        assert t.health() == "clean"
        assert t.summarize()["restart_count"] == 0
