"""Tests for iamai.restart_drift — restart frequency drift tracker.

covers:
  - RestartEvent parsing and defaults
  - recording single / many / count / latest / events-copy
  - intervals (empty, single pair, multiple)
  - mean / min / max interval
  - drift_direction (accelerating, stable, decelerating, edge cases)
  - instability_score (empty, healthy, strained, critical, accelerating penalty)
  - regime classification
  - projected_next_interval
  - report (empty, single event, multi-event, accelerating warning)
"""

import pytest

from iamai.restart_drift import (
    RestartDrift,
    RestartEvent,
    HEALTHY_INTERVAL_S,
    STRAINED_INTERVAL_S,
    CRITICAL_INTERVAL_S,
)


# ─── RestartEvent ──────────────────────────────────────────────────


class TestRestartEvent:
    def test_basic_fields(self):
        evt = RestartEvent(at="2026-10-19T06:00:00+08:00")
        assert evt.at == "2026-10-19T06:00:00+08:00"
        assert evt.visit is None
        assert evt.cause == "unknown"

    def test_all_fields(self):
        evt = RestartEvent(at="2026-10-19T12:00:00+08:00", visit=235,
                           cause="container_reclaim")
        assert evt.visit == 235
        assert evt.cause == "container_reclaim"

    def test_ts_parsing_offset(self):
        evt = RestartEvent(at="2026-10-19T06:00:00+08:00")
        dt = evt.ts()
        assert dt.hour == 6
        assert dt.minute == 0

    def test_ts_parsing_utc_z(self):
        evt = RestartEvent(at="2026-10-19T12:00:00Z")
        dt = evt.ts()
        assert dt.hour == 12

    def test_ts_parsing_no_offset(self):
        evt = RestartEvent(at="2026-10-19T15:30:00")
        dt = evt.ts()
        assert dt.hour == 15
        assert dt.minute == 30


# ─── Recording ─────────────────────────────────────────────────────


class TestRecording:
    def test_record_single(self):
        drift = RestartDrift()
        evt = drift.record("2026-10-19T06:00:00+08:00")
        assert drift.count() == 1
        assert isinstance(evt, RestartEvent)

    def test_record_with_visit(self):
        drift = RestartDrift()
        evt = drift.record("2026-10-19T06:00:00+08:00", visit=235,
                           cause="manual")
        assert evt.visit == 235
        assert evt.cause == "manual"

    def test_record_many(self):
        drift = RestartDrift()
        ts_list = [
            "2026-10-19T06:00:00+08:00",
            "2026-10-19T12:00:00+08:00",
            "2026-10-19T18:00:00+08:00",
        ]
        added = drift.record_many(ts_list)
        assert added == 3
        assert drift.count() == 3

    def test_latest_empty(self):
        drift = RestartDrift()
        assert drift.latest() is None

    def test_latest(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        latest = drift.latest()
        assert latest.at == "2026-10-19T12:00:00+08:00"

    def test_events_returns_copy(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        events = drift.events()
        events.clear()
        assert drift.count() == 1  # original not affected


# ─── Intervals ─────────────────────────────────────────────────────


class TestIntervals:
    def test_empty(self):
        drift = RestartDrift()
        assert drift.intervals() == []

    def test_single_event(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        assert drift.intervals() == []

    def test_two_events(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        ivs = drift.intervals()
        assert len(ivs) == 1
        assert ivs[0] == 6 * 3600  # 6 hours in seconds

    def test_multiple_events(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        drift.record("2026-10-19T16:00:00+08:00")
        ivs = drift.intervals()
        assert len(ivs) == 2
        assert ivs[0] == 6 * 3600   # 6h
        assert ivs[1] == 4 * 3600   # 4h

    def test_mean_interval_empty(self):
        drift = RestartDrift()
        assert drift.mean_interval() is None

    def test_mean_interval(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        drift.record("2026-10-19T16:00:00+08:00")
        mean = drift.mean_interval()
        assert mean == 5 * 3600  # (6h + 4h) / 2 = 5h

    def test_min_interval_empty(self):
        drift = RestartDrift()
        assert drift.min_interval() is None

    def test_min_interval(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        drift.record("2026-10-19T16:00:00+08:00")
        assert drift.min_interval() == 4 * 3600

    def test_max_interval_empty(self):
        drift = RestartDrift()
        assert drift.max_interval() is None

    def test_max_interval(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        drift.record("2026-10-19T16:00:00+08:00")
        assert drift.max_interval() == 6 * 3600


# ─── Drift Direction ───────────────────────────────────────────────


class TestDriftDirection:
    def test_empty(self):
        drift = RestartDrift()
        assert drift.drift_direction() == "stable"

    def test_single_interval(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        # only 1 interval → can't detect drift
        assert drift.drift_direction() == "stable"

    def test_accelerating(self):
        """Gaps shrinking: 8h, 6h, 4h, 2h → clearly accelerating."""
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T08:00:00+08:00")  # 8h
        drift.record("2026-10-18T14:00:00+08:00")  # 6h
        drift.record("2026-10-18T18:00:00+08:00")  # 4h
        drift.record("2026-10-18T20:00:00+08:00")  # 2h
        assert drift.drift_direction() == "accelerating"

    def test_decelerating(self):
        """Gaps growing: 2h, 4h, 6h, 8h → decelerating."""
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T02:00:00+08:00")  # 2h
        drift.record("2026-10-18T06:00:00+08:00")  # 4h
        drift.record("2026-10-18T12:00:00+08:00")  # 6h
        drift.record("2026-10-18T20:00:00+08:00")  # 8h
        assert drift.drift_direction() == "decelerating"

    def test_stable(self):
        """Constant 6h gaps → stable."""
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T06:00:00+08:00")
        drift.record("2026-10-18T12:00:00+08:00")
        drift.record("2026-10-18T18:00:00+08:00")
        drift.record("2026-10-19T00:00:00+08:00")
        assert drift.drift_direction() == "stable"

    def test_near_stable(self):
        """Small variation within 20% threshold → stable."""
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T06:00:00+08:00")   # 6h
        drift.record("2026-10-18T11:30:00+08:00")   # 5.5h
        drift.record("2026-10-18T17:00:00+08:00")   # 5.5h
        drift.record("2026-10-18T22:30:00+08:00")   # 5.5h
        assert drift.drift_direction() == "stable"


# ─── Instability Score ─────────────────────────────────────────────


class TestInstabilityScore:
    def test_empty(self):
        drift = RestartDrift()
        assert drift.instability_score() == 0.0

    def test_single_event(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        assert drift.instability_score() == 0.0

    def test_healthy_score(self):
        """8h intervals → healthy."""
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T08:00:00+08:00")
        drift.record("2026-10-18T16:00:00+08:00")
        score = drift.instability_score()
        assert 0.0 <= score <= 0.3

    def test_strained_score(self):
        """3h intervals → strained."""
        drift = RestartDrift()
        drift.record("2026-10-19T00:00:00+08:00")
        drift.record("2026-10-19T03:00:00+08:00")
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T09:00:00+08:00")
        score = drift.instability_score()
        assert 0.3 < score < 0.8

    def test_critical_score(self):
        """30min intervals → critical."""
        drift = RestartDrift()
        drift.record("2026-10-19T00:00:00+08:00")
        drift.record("2026-10-19T00:30:00+08:00")
        drift.record("2026-10-19T01:00:00+08:00")
        drift.record("2026-10-19T01:30:00+08:00")
        score = drift.instability_score()
        assert score >= 0.7

    def test_score_bounded(self):
        """Score never exceeds 1.0."""
        drift = RestartDrift()
        # Extremely frequent restarts every 5 minutes
        for h in range(24):
            for m in range(0, 60, 5):
                drift.record(f"2026-10-19T{h:02d}:{m:02d}:00+08:00")
        score = drift.instability_score()
        assert 0.0 <= score <= 1.0

    def test_accelerating_penalty(self):
        """Accelerating restarts score higher than stable same-mean."""
        # Stable: constant 4h
        stable = RestartDrift()
        for i in range(6):
            stable.record(f"2026-10-18T{i * 4:02d}:00:00+08:00")

        # Accelerating: 6h, 5h, 4h, 3h, 2h (mean ~4h)
        accel = RestartDrift()
        accel.record("2026-10-18T00:00:00+08:00")
        accel.record("2026-10-18T06:00:00+08:00")
        accel.record("2026-10-18T11:00:00+08:00")
        accel.record("2026-10-18T15:00:00+08:00")
        accel.record("2026-10-18T18:00:00+08:00")
        accel.record("2026-10-18T20:00:00+08:00")

        assert accel.instability_score() > stable.instability_score()


# ─── Regime ────────────────────────────────────────────────────────


class TestRegime:
    def test_empty(self):
        drift = RestartDrift()
        assert drift.regime() == "healthy"

    def test_healthy(self):
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T08:00:00+08:00")
        drift.record("2026-10-18T16:00:00+08:00")
        assert drift.regime() == "healthy"

    def test_strained(self):
        drift = RestartDrift()
        drift.record("2026-10-19T00:00:00+08:00")
        drift.record("2026-10-19T03:00:00+08:00")
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T09:00:00+08:00")
        assert drift.regime() == "strained"

    def test_critical(self):
        drift = RestartDrift()
        drift.record("2026-10-19T00:00:00+08:00")
        drift.record("2026-10-19T00:30:00+08:00")
        drift.record("2026-10-19T01:00:00+08:00")
        drift.record("2026-10-19T01:30:00+08:00")
        assert drift.regime() == "critical"


# ─── Projected Next ────────────────────────────────────────────────


class TestProjectedNext:
    def test_empty(self):
        drift = RestartDrift()
        assert drift.projected_next_interval() is None

    def test_single_pair(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        assert drift.projected_next_interval() == 6 * 3600

    def test_uses_recent_three(self):
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T10:00:00+08:00")  # 10h
        drift.record("2026-10-18T18:00:00+08:00")  # 8h
        drift.record("2026-10-19T02:00:00+08:00")  # 8h
        drift.record("2026-10-19T08:00:00+08:00")  # 6h
        # last 3 intervals: 8h, 8h, 6h → mean ~7.33h
        proj = drift.projected_next_interval()
        expected = (8 * 3600 + 8 * 3600 + 6 * 3600) / 3
        assert abs(proj - expected) < 1


# ─── Report ────────────────────────────────────────────────────────


class TestReport:
    def test_empty(self):
        drift = RestartDrift()
        report = drift.report()
        assert "no restart events" in report

    def test_single_event(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        report = drift.report()
        assert "1 event" in report
        assert "cannot compute" in report

    def test_multi_event(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        drift.record("2026-10-19T18:00:00+08:00")
        report = drift.report()
        assert "3 event" in report
        assert "mean interval" in report
        assert "drift direction" in report
        assert "instability" in report

    def test_accelerating_warning(self):
        drift = RestartDrift()
        drift.record("2026-10-18T00:00:00+08:00")
        drift.record("2026-10-18T08:00:00+08:00")
        drift.record("2026-10-18T14:00:00+08:00")
        drift.record("2026-10-18T18:00:00+08:00")
        drift.record("2026-10-18T20:00:00+08:00")
        report = drift.report()
        assert "accelerating" in report.lower() or "⚠" in report

    def test_report_has_projected(self):
        drift = RestartDrift()
        drift.record("2026-10-19T06:00:00+08:00")
        drift.record("2026-10-19T12:00:00+08:00")
        report = drift.report()
        assert "projected next" in report
