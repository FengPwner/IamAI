"""Tests for iamai.stall_event.

Covers: StallEvent (construction, properties, severity, edge cases),
StallTracker (record, queries, severity, recovery, trend, health,
summarize, report_line, reset, error handling).
"""

import pytest
from iamai.stall_event import StallEvent, StallTracker


# ------------------------------------------------------------------
# StallEvent — construction
# ------------------------------------------------------------------


class TestStallEventConstruction:
    """StallEvent instantiation and validation."""

    def test_minimal(self):
        ev = StallEvent(gap_s=60)
        assert ev.gap_s == 60
        assert ev.recovery == "ongoing"
        assert ev.recovery_s == 0.0
        assert ev.commit_debt == 0

    def test_full_params(self):
        ev = StallEvent(
            gap_s=120, recovery="self", recovery_s=30, commit_debt=5
        )
        assert ev.gap_s == 120
        assert ev.recovery == "self"
        assert ev.recovery_s == 30
        assert ev.commit_debt == 5

    def test_zero_gap(self):
        ev = StallEvent(gap_s=0)
        assert ev.gap_s == 0
        assert ev.total_impact_s == 0.0

    def test_restart_recovery(self):
        ev = StallEvent(gap_s=300, recovery="restart", recovery_s=45)
        assert ev.recovery == "restart"
        assert ev.recovery_s == 45

    def test_negative_gap_rejected(self):
        with pytest.raises(ValueError, match="gap_s must be >= 0"):
            StallEvent(gap_s=-1)

    def test_negative_recovery_s_rejected(self):
        with pytest.raises(ValueError, match="recovery_s must be >= 0"):
            StallEvent(gap_s=60, recovery_s=-5)

    def test_negative_commit_debt_rejected(self):
        with pytest.raises(ValueError, match="commit_debt must be >= 0"):
            StallEvent(gap_s=60, commit_debt=-1)

    def test_invalid_recovery_rejected(self):
        with pytest.raises(ValueError, match="recovery must be one of"):
            StallEvent(gap_s=60, recovery="magic")

    def test_timestamp_auto(self):
        ev = StallEvent(gap_s=30)
        assert ev.timestamp is not None
        assert ev.timestamp > 0

    def test_timestamp_explicit(self):
        ev = StallEvent(gap_s=30, timestamp=1000.0)
        assert ev.timestamp == 1000.0


# ------------------------------------------------------------------
# StallEvent — properties
# ------------------------------------------------------------------


class TestStallEventProperties:
    """StallEvent computed properties."""

    def test_total_impact_s(self):
        ev = StallEvent(gap_s=100, recovery="self", recovery_s=20)
        assert ev.total_impact_s == 120

    def test_total_impact_s_no_recovery(self):
        ev = StallEvent(gap_s=100, recovery="ongoing")
        assert ev.total_impact_s == 100

    def test_lost_strokes(self):
        ev = StallEvent(gap_s=150)
        assert ev.lost_strokes(cadence_s=15) == 10.0

    def test_lost_strokes_zero_cadence(self):
        ev = StallEvent(gap_s=150)
        assert ev.lost_strokes(cadence_s=0) == 0.0

    def test_lost_strokes_fractional(self):
        ev = StallEvent(gap_s=22)
        result = ev.lost_strokes(cadence_s=15)
        assert abs(result - 22 / 15) < 1e-9

    def test_is_ongoing_true(self):
        ev = StallEvent(gap_s=60, recovery="ongoing")
        assert ev.is_ongoing() is True

    def test_is_ongoing_false_self(self):
        ev = StallEvent(gap_s=60, recovery="self")
        assert ev.is_ongoing() is False

    def test_is_ongoing_false_restart(self):
        ev = StallEvent(gap_s=60, recovery="restart")
        assert ev.is_ongoing() is False


# ------------------------------------------------------------------
# StallEvent — severity
# ------------------------------------------------------------------


class TestStallEventSeverity:
    """StallEvent severity classification."""

    def test_minor(self):
        ev = StallEvent(gap_s=30)
        assert ev.severity(cadence_s=15) == "minor"  # 2x

    def test_minor_boundary(self):
        ev = StallEvent(gap_s=59)
        assert ev.severity(cadence_s=15) == "minor"  # <4x

    def test_moderate(self):
        ev = StallEvent(gap_s=60)
        assert ev.severity(cadence_s=15) == "moderate"  # 4x

    def test_moderate_mid(self):
        ev = StallEvent(gap_s=120)
        assert ev.severity(cadence_s=15) == "moderate"  # 8x

    def test_severe(self):
        ev = StallEvent(gap_s=150)
        assert ev.severity(cadence_s=15) == "severe"  # 10x

    def test_severe_beyond(self):
        ev = StallEvent(gap_s=600)
        assert ev.severity(cadence_s=15) == "severe"  # 40x

    def test_severity_zero_cadence(self):
        ev = StallEvent(gap_s=600)
        assert ev.severity(cadence_s=0) == "minor"


# ------------------------------------------------------------------
# StallTracker — construction
# ------------------------------------------------------------------


class TestStallTrackerConstruction:
    """StallTracker instantiation and validation."""

    def test_defaults(self):
        t = StallTracker()
        assert t.cadence_s == 15.0
        assert t.minor_threshold == 4.0
        assert t.severe_threshold == 10.0
        assert t.max_history == 500
        assert t.event_count == 0

    def test_custom(self):
        t = StallTracker(
            cadence_s=30,
            minor_threshold=3.0,
            severe_threshold=8.0,
            max_history=100,
        )
        assert t.cadence_s == 30
        assert t.minor_threshold == 3.0

    def test_zero_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            StallTracker(cadence_s=0)

    def test_negative_cadence_rejected(self):
        with pytest.raises(ValueError, match="cadence_s must be > 0"):
            StallTracker(cadence_s=-5)

    def test_zero_minor_threshold_rejected(self):
        with pytest.raises(ValueError, match="minor_threshold must be > 0"):
            StallTracker(minor_threshold=0)

    def test_severe_below_minor_rejected(self):
        with pytest.raises(ValueError, match="severe_threshold"):
            StallTracker(minor_threshold=10, severe_threshold=5)

    def test_severe_equals_minor_rejected(self):
        with pytest.raises(ValueError, match="severe_threshold"):
            StallTracker(minor_threshold=4, severe_threshold=4)

    def test_zero_max_history_rejected(self):
        with pytest.raises(ValueError, match="max_history must be >= 1"):
            StallTracker(max_history=0)


# ------------------------------------------------------------------
# StallTracker — recording
# ------------------------------------------------------------------


class TestStallTrackerRecording:
    """StallTracker record method."""

    def test_record_basic(self):
        t = StallTracker()
        ev = t.record(gap_s=60)
        assert t.event_count == 1
        assert ev.gap_s == 60

    def test_record_multiple(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10)
        t.record(gap_s=120, recovery="restart", recovery_s=45)
        t.record(gap_s=300, recovery="ongoing")
        assert t.event_count == 3

    def test_record_returns_event(self):
        t = StallTracker()
        ev = t.record(gap_s=90, recovery="self", recovery_s=15)
        assert isinstance(ev, StallEvent)
        assert ev.gap_s == 90
        assert ev.recovery == "self"

    def test_history_cap(self):
        t = StallTracker(max_history=3)
        for i in range(10):
            t.record(gap_s=float(i + 1))
        assert t.event_count == 3
        # should keep the last 3
        assert t._events[0].gap_s == 8.0
        assert t._events[1].gap_s == 9.0
        assert t._events[2].gap_s == 10.0

    def test_record_explicit_timestamp(self):
        t = StallTracker()
        ev = t.record(gap_s=30, timestamp=999.0)
        assert ev.timestamp == 999.0


# ------------------------------------------------------------------
# StallTracker — queries
# ------------------------------------------------------------------


class TestStallTrackerQueries:
    """StallTracker query properties and methods."""

    def _populated(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10, commit_debt=2)
        t.record(gap_s=120, recovery="restart", recovery_s=45, commit_debt=8)
        t.record(gap_s=300, recovery="ongoing", commit_debt=12)
        return t

    def test_event_count(self):
        assert self._populated().event_count == 3

    def test_ongoing_count(self):
        assert self._populated().ongoing_count == 1

    def test_resolved_count(self):
        assert self._populated().resolved_count == 2

    def test_total_gap_s(self):
        assert self._populated().total_gap_s == 450

    def test_total_recovery_s(self):
        assert self._populated().total_recovery_s == 55

    def test_total_impact_s(self):
        assert self._populated().total_impact_s == 505

    def test_total_commit_debt(self):
        assert self._populated().total_commit_debt == 22

    def test_mean_gap(self):
        assert self._populated().mean_gap() == 150.0

    def test_mean_recovery_s(self):
        # only resolved: (10 + 45) / 2
        assert self._populated().mean_recovery_s() == 27.5

    def test_mean_impact(self):
        # (40 + 165 + 300) / 3
        t = self._populated()
        assert abs(t.mean_impact() - 505 / 3) < 1e-9

    def test_worst_gap(self):
        assert self._populated().worst_gap() == 300

    def test_total_lost_strokes(self):
        # 30/15 + 120/15 + 300/15 = 2 + 8 + 20 = 30
        assert self._populated().total_lost_strokes() == 30.0

    def test_empty_queries(self):
        t = StallTracker()
        assert t.event_count == 0
        assert t.ongoing_count == 0
        assert t.resolved_count == 0
        assert t.total_gap_s == 0
        assert t.total_recovery_s == 0
        assert t.total_impact_s == 0
        assert t.total_commit_debt == 0
        assert t.mean_gap() == 0.0
        assert t.mean_recovery_s() == 0.0
        assert t.mean_impact() == 0.0
        assert t.worst_gap() == 0.0
        assert t.total_lost_strokes() == 0.0


# ------------------------------------------------------------------
# StallTracker — severity
# ------------------------------------------------------------------


class TestStallTrackerSeverity:
    """StallTracker severity analysis."""

    def test_severity_counts(self):
        t = StallTracker()
        t.record(gap_s=30)   # minor (2x)
        t.record(gap_s=50)   # minor (3.3x)
        t.record(gap_s=75)   # moderate (5x)
        t.record(gap_s=200)  # severe (13.3x)
        counts = t.severity_counts()
        assert counts == {"minor": 2, "moderate": 1, "severe": 1}

    def test_severity_counts_empty(self):
        t = StallTracker()
        assert t.severity_counts() == {"minor": 0, "moderate": 0, "severe": 0}

    def test_dominant_severity_minor(self):
        t = StallTracker()
        t.record(gap_s=10)
        t.record(gap_s=20)
        t.record(gap_s=70)
        assert t.dominant_severity() == "minor"

    def test_dominant_severity_moderate(self):
        t = StallTracker()
        t.record(gap_s=10)
        t.record(gap_s=70)
        t.record(gap_s=80)
        assert t.dominant_severity() == "moderate"

    def test_dominant_severity_severe(self):
        t = StallTracker()
        t.record(gap_s=200)
        t.record(gap_s=300)
        assert t.dominant_severity() == "severe"

    def test_dominant_severity_tie_severe_wins(self):
        t = StallTracker()
        t.record(gap_s=20)   # minor
        t.record(gap_s=70)   # moderate
        t.record(gap_s=200)  # severe
        assert t.dominant_severity() == "severe"

    def test_dominant_severity_empty(self):
        t = StallTracker()
        assert t.dominant_severity() == "minor"


# ------------------------------------------------------------------
# StallTracker — recovery analysis
# ------------------------------------------------------------------


class TestStallTrackerRecovery:
    """StallTracker recovery analysis."""

    def test_self_recovery_pct(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10)
        t.record(gap_s=60, recovery="self", recovery_s=15)
        t.record(gap_s=120, recovery="restart", recovery_s=45)
        t.record(gap_s=200, recovery="ongoing")
        # resolved: 3, self: 2 → 66.67%
        assert abs(t.self_recovery_pct() - 66.67) < 0.1

    def test_restart_recovery_pct(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10)
        t.record(gap_s=120, recovery="restart", recovery_s=45)
        # resolved: 2, restart: 1 → 50%
        assert abs(t.restart_recovery_pct() - 50.0) < 0.1

    def test_recovery_pct_empty(self):
        t = StallTracker()
        assert t.self_recovery_pct() == 0.0
        assert t.restart_recovery_pct() == 0.0

    def test_recovery_pct_all_ongoing(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="ongoing")
        t.record(gap_s=60, recovery="ongoing")
        assert t.self_recovery_pct() == 0.0
        assert t.restart_recovery_pct() == 0.0

    def test_mean_self_recovery_s(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10)
        t.record(gap_s=60, recovery="self", recovery_s=20)
        t.record(gap_s=120, recovery="restart", recovery_s=45)
        assert t.mean_self_recovery_s() == 15.0

    def test_mean_self_recovery_s_none(self):
        t = StallTracker()
        t.record(gap_s=120, recovery="restart", recovery_s=45)
        assert t.mean_self_recovery_s() == 0.0

    def test_mean_restart_recovery_s(self):
        t = StallTracker()
        t.record(gap_s=120, recovery="restart", recovery_s=40)
        t.record(gap_s=200, recovery="restart", recovery_s=60)
        assert t.mean_restart_recovery_s() == 50.0

    def test_mean_restart_recovery_s_none(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10)
        assert t.mean_restart_recovery_s() == 0.0


# ------------------------------------------------------------------
# StallTracker — trend
# ------------------------------------------------------------------


class TestStallTrackerTrend:
    """StallTracker trend analysis."""

    def test_stable_few_events(self):
        t = StallTracker()
        t.record(gap_s=30)
        t.record(gap_s=60)
        assert t.trend() == "stable"

    def test_stable_three_events(self):
        t = StallTracker()
        t.record(gap_s=30)
        t.record(gap_s=60)
        t.record(gap_s=45)
        assert t.trend() == "stable"

    def test_worsening(self):
        t = StallTracker()
        t.record(gap_s=10)
        t.record(gap_s=10)
        t.record(gap_s=100)
        t.record(gap_s=100)
        assert t.trend() == "worsening"

    def test_improving(self):
        t = StallTracker()
        t.record(gap_s=200)
        t.record(gap_s=200)
        t.record(gap_s=10)
        t.record(gap_s=10)
        assert t.trend() == "improving"

    def test_stable_similar(self):
        t = StallTracker()
        t.record(gap_s=50)
        t.record(gap_s=50)
        t.record(gap_s=55)
        t.record(gap_s=55)
        assert t.trend() == "stable"

    def test_empty_trend(self):
        t = StallTracker()
        assert t.trend() == "stable"


# ------------------------------------------------------------------
# StallTracker — health
# ------------------------------------------------------------------


class TestStallTrackerHealth:
    """StallTracker health classification."""

    def test_clean_empty(self):
        t = StallTracker()
        assert t.health() == "clean"

    def test_clean_minor_only(self):
        t = StallTracker()
        t.record(gap_s=10)
        t.record(gap_s=20)
        assert t.health() == "clean"

    def test_degraded_moderate(self):
        t = StallTracker()
        t.record(gap_s=70)  # moderate (4.67x)
        assert t.health() == "degraded"

    def test_critical_severe(self):
        t = StallTracker()
        t.record(gap_s=200)  # severe (13.3x)
        assert t.health() == "critical"

    def test_critical_high_mean_gap(self):
        t = StallTracker()
        # all moderate but mean gap >= 10x cadence (150)
        t.record(gap_s=140)  # 9.33x = moderate
        t.record(gap_s=140)
        # mean gap = 140, < 150, not critical by mean
        # but both moderate → degraded
        assert t.health() == "degraded"

    def test_critical_by_mean_gap(self):
        t = StallTracker()
        t.record(gap_s=140)  # moderate
        t.record(gap_s=140)
        t.record(gap_s=200)  # severe
        assert t.health() == "critical"


# ------------------------------------------------------------------
# StallTracker — reporting
# ------------------------------------------------------------------


class TestStallTrackerReporting:
    """StallTracker summarize and report_line."""

    def test_summarize_empty(self):
        t = StallTracker()
        s = t.summarize()
        assert s["event_count"] == 0
        assert s["ongoing"] == 0
        assert s["health"] == "clean"
        assert s["trend"] == "stable"

    def test_summarize_populated(self):
        t = StallTracker()
        t.record(gap_s=30, recovery="self", recovery_s=10, commit_debt=2)
        t.record(gap_s=200, recovery="restart", recovery_s=45, commit_debt=8)
        s = t.summarize()
        assert s["event_count"] == 2
        assert s["ongoing"] == 0
        assert s["total_gap_s"] == 230
        assert s["total_recovery_s"] == 55
        assert s["total_impact_s"] == 285
        assert s["worst_gap_s"] == 200
        assert s["total_commit_debt"] == 10
        assert s["health"] == "critical"

    def test_report_line_returns_string(self):
        t = StallTracker()
        t.record(gap_s=60, recovery="self", recovery_s=15)
        line = t.report_line()
        assert isinstance(line, str)
        assert "stall_events:" in line
        assert "1 events" in line

    def test_report_line_empty(self):
        t = StallTracker()
        line = t.report_line()
        assert "0 events" in line
        assert "clean" in line

    def test_summarize_all_fields_present(self):
        t = StallTracker()
        t.record(gap_s=50, recovery="self", recovery_s=10)
        s = t.summarize()
        expected_keys = {
            "event_count", "ongoing", "cadence_s",
            "total_gap_s", "total_recovery_s", "total_impact_s",
            "mean_gap_s", "worst_gap_s", "mean_impact_s",
            "total_lost_strokes", "total_commit_debt",
            "severity_counts", "dominant_severity",
            "self_recovery_pct", "restart_recovery_pct",
            "mean_self_recovery_s", "mean_restart_recovery_s",
            "health", "trend",
        }
        assert set(s.keys()) == expected_keys


# ------------------------------------------------------------------
# StallTracker — reset
# ------------------------------------------------------------------


class TestStallTrackerReset:
    """StallTracker reset method."""

    def test_reset_clears(self):
        t = StallTracker()
        t.record(gap_s=60)
        t.record(gap_s=120)
        assert t.event_count == 2
        t.reset()
        assert t.event_count == 0
        assert t.total_gap_s == 0
        assert t.health() == "clean"


# ------------------------------------------------------------------
# Integration-style scenarios
# ------------------------------------------------------------------


class TestStallEventIntegration:
    """End-to-end scenarios combining StallEvent and StallTracker."""

    def test_caretaker_visit_scenario(self):
        """Simulate a typical caretaker visit with mixed stalls."""
        t = StallTracker(cadence_s=15)
        # Two minor self-recovered stalls
        t.record(gap_s=25, recovery="self", recovery_s=5)
        t.record(gap_s=40, recovery="self", recovery_s=8)
        # One moderate restart-recovered stall
        t.record(gap_s=90, recovery="restart", recovery_s=30, commit_debt=5)
        # One severe ongoing stall
        t.record(gap_s=500, recovery="ongoing", commit_debt=12)

        assert t.event_count == 4
        assert t.ongoing_count == 1
        assert t.resolved_count == 3
        assert t.worst_gap() == 500
        assert t.health() == "critical"

        counts = t.severity_counts()
        assert counts["minor"] == 2
        assert counts["moderate"] == 1
        assert counts["severe"] == 1

        # self: 2/3 resolved ≈ 66.7%
        assert abs(t.self_recovery_pct() - 66.67) < 0.1

        s = t.summarize()
        assert s["health"] == "critical"
        assert s["dominant_severity"] == "minor"  # 2 minor > 1 each

    def test_all_clean_scenario(self):
        """All stalls are minor and self-recovered."""
        t = StallTracker(cadence_s=15)
        t.record(gap_s=20, recovery="self", recovery_s=3)
        t.record(gap_s=25, recovery="self", recovery_s=5)
        t.record(gap_s=30, recovery="self", recovery_s=4)
        assert t.health() == "clean"
        assert t.self_recovery_pct() == 100.0
        assert t.restart_recovery_pct() == 0.0
