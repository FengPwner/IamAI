"""Tests for caretaker_process_correlator module.

Covers:
- ProcessEvent / StrokeSample / Correlation / CorrelationSummary dataclasses
- estimate_lost_strokes: normal, zero duration, zero cadence, negative
- recovery_time: stable, never stable, not enough data, immediate
- classify_impact: all three buckets + boundary values
- correlate_events: empty, single event, multiple events, no strokes
- summarize: empty, single, mixed impacts, all negligible
"""

import pytest

from iamai.caretaker_process_correlator import (
    Correlation,
    CorrelationSummary,
    ProcessEvent,
    StrokeSample,
    classify_impact,
    correlate_events,
    estimate_lost_strokes,
    recovery_time,
    summarize,
)


# ===========================================================================
# dataclasses
# ===========================================================================


class TestProcessEvent:
    def test_minimal(self):
        e = ProcessEvent(timestamp=1000.0, event_type="restart")
        assert e.timestamp == 1000.0
        assert e.event_type == "restart"
        assert e.pid is None
        assert e.duration is None

    def test_full(self):
        e = ProcessEvent(timestamp=1000.0, event_type="crash", pid=1234, duration=60.0)
        assert e.pid == 1234
        assert e.duration == 60.0


class TestStrokeSample:
    def test_defaults(self):
        s = StrokeSample(timestamp=500.0)
        assert s.category == ""
        assert s.word_count == 0

    def test_full(self):
        s = StrokeSample(timestamp=500.0, category="devlog", word_count=42)
        assert s.category == "devlog"
        assert s.word_count == 42


class TestCorrelation:
    def test_defaults(self):
        e = ProcessEvent(timestamp=1000.0, event_type="restart")
        c = Correlation(event=e)
        assert c.strokes_before == 0
        assert c.strokes_after == 0
        assert c.lost_strokes == 0.0
        assert c.recovery_seconds == 0.0
        assert c.impact == "unknown"

    def test_summary_format(self):
        e = ProcessEvent(timestamp=1000.0, event_type="restart")
        c = Correlation(
            event=e, strokes_before=10, strokes_after=8,
            lost_strokes=3.5, recovery_seconds=45.0, impact="moderate",
        )
        text = c.summary()
        assert "restart" in text
        assert "10 before" in text
        assert "8 after" in text
        assert "3.5 lost" in text
        assert "45s" in text
        assert "moderate" in text


class TestCorrelationSummary:
    def test_defaults(self):
        s = CorrelationSummary()
        assert s.total_events == 0
        assert s.worst_impact == "unknown"

    def test_summary_format(self):
        s = CorrelationSummary(
            total_events=3, total_lost_strokes=12.0,
            mean_recovery_seconds=30.0, worst_impact="severe",
        )
        text = s.summary()
        assert "3 events" in text
        assert "12.0 strokes lost" in text
        assert "30s" in text
        assert "severe" in text


# ===========================================================================
# estimate_lost_strokes
# ===========================================================================


class TestEstimateLostStrokes:
    def test_normal(self):
        assert estimate_lost_strokes(300, 15) == 20.0

    def test_zero_duration(self):
        assert estimate_lost_strokes(0, 15) == 0.0

    def test_zero_cadence(self):
        assert estimate_lost_strokes(60, 0) == 0.0

    def test_negative_duration(self):
        assert estimate_lost_strokes(-10, 15) == 0.0

    def test_negative_cadence(self):
        assert estimate_lost_strokes(100, -5) == 0.0

    def test_fractional_result(self):
        assert estimate_lost_strokes(20, 15) == pytest.approx(1.333, rel=1e-2)


# ===========================================================================
# recovery_time
# ===========================================================================


class TestRecoveryTime:
    @staticmethod
    def _strokes(timestamps):
        return [StrokeSample(timestamp=t) for t in timestamps]

    def test_not_enough_post_strokes(self):
        ev = ProcessEvent(timestamp=100.0, event_type="restart")
        strokes = self._strokes([100, 115])  # only 2 post-event
        assert recovery_time(ev, strokes, cadence=15) == 0.0

    def test_immediately_stable(self):
        ev = ProcessEvent(timestamp=100.0, event_type="restart")
        # 7 strokes at perfect 15s intervals starting at event time
        strokes = self._strokes([100, 115, 130, 145, 160, 175, 190])
        recov = recovery_time(ev, strokes, cadence=15, settle_window=5)
        # stable at stroke index 5 (175), so recovery = 175 - 100 = 75
        assert recov == pytest.approx(75.0, abs=1.0)

    def test_never_stable(self):
        ev = ProcessEvent(timestamp=100.0, event_type="restart")
        # wildly irregular intervals, none ≤ 30s threshold
        timestamps = [100, 200, 500, 900, 1400, 2000, 2700, 3500]
        strokes = self._strokes(timestamps)
        recov = recovery_time(ev, strokes, cadence=15, settle_window=5)
        # never stabilises → returns span of all post-event data
        assert recov == pytest.approx(3400.0, abs=1.0)

    def test_event_with_no_matching_strokes(self):
        ev = ProcessEvent(timestamp=9999.0, event_type="restart")
        strokes = self._strokes([100, 200, 300])
        assert recovery_time(ev, strokes, cadence=15) == 0.0


# ===========================================================================
# classify_impact
# ===========================================================================


class TestClassifyImpact:
    def test_negligible(self):
        assert classify_impact(1.0, 30, 15) == "negligible"

    def test_negligible_boundary(self):
        assert classify_impact(1.9, 59, 15) == "negligible"

    def test_moderate(self):
        assert classify_impact(5.0, 200, 15) == "moderate"

    def test_moderate_boundary(self):
        assert classify_impact(9.9, 299, 15) == "moderate"

    def test_severe_by_lost(self):
        assert classify_impact(10.0, 0, 15) == "severe"

    def test_severe_by_recovery(self):
        assert classify_impact(0, 500, 15) == "severe"

    def test_both_bad(self):
        assert classify_impact(50.0, 1000, 15) == "severe"


# ===========================================================================
# correlate_events
# ===========================================================================


class TestCorrelateEvents:
    def test_empty(self):
        assert correlate_events([], [], cadence=15) == []

    def test_single_event_no_strokes(self):
        ev = ProcessEvent(timestamp=1000.0, event_type="restart", duration=60.0)
        results = correlate_events([ev], [], cadence=15)
        assert len(results) == 1
        assert results[0].strokes_before == 0
        assert results[0].strokes_after == 0
        assert results[0].lost_strokes == pytest.approx(4.0)

    def test_single_event_with_strokes(self):
        ev = ProcessEvent(timestamp=1000.0, event_type="restart", duration=30.0)
        strokes = [
            StrokeSample(timestamp=900 + i * 15, category="note")
            for i in range(20)
        ]
        results = correlate_events([ev], strokes, cadence=15, window=300)
        assert len(results) == 1
        r = results[0]
        # strokes in [700, 1000): timestamps 900..1275 → those < 1000: 900,915,...,990 = 7
        assert r.strokes_before == 7
        # strokes in [1000, 1300): 1005, 1020, ..., 1185 = 13
        assert r.strokes_after == 13
        assert r.lost_strokes == pytest.approx(2.0)

    def test_multiple_events(self):
        events = [
            ProcessEvent(timestamp=1000.0, event_type="crash", duration=120.0),
            ProcessEvent(timestamp=2000.0, event_type="restart", duration=10.0),
        ]
        strokes = [
            StrokeSample(timestamp=900 + i * 15)
            for i in range(100)
        ]
        results = correlate_events(events, strokes, cadence=15, window=300)
        assert len(results) == 2
        assert results[0].lost_strokes > results[1].lost_strokes

    def test_event_with_no_duration(self):
        ev = ProcessEvent(timestamp=500.0, event_type="stall")
        results = correlate_events([ev], [], cadence=15)
        assert results[0].lost_strokes == 0.0


# ===========================================================================
# summarize
# ===========================================================================


class TestSummarize:
    def test_empty(self):
        s = summarize([])
        assert s.total_events == 0
        assert s.worst_impact == "unknown"

    def test_single(self):
        ev = ProcessEvent(timestamp=1000.0, event_type="restart")
        c = Correlation(event=ev, lost_strokes=3.0, recovery_seconds=45, impact="moderate")
        s = summarize([c])
        assert s.total_events == 1
        assert s.total_lost_strokes == 3.0
        assert s.mean_recovery_seconds == 45.0
        assert s.worst_impact == "moderate"
        assert s.moderate_count == 1

    def test_mixed(self):
        ev1 = ProcessEvent(timestamp=1000.0, event_type="restart")
        ev2 = ProcessEvent(timestamp=2000.0, event_type="crash")
        ev3 = ProcessEvent(timestamp=3000.0, event_type="stall")
        correlations = [
            Correlation(event=ev1, lost_strokes=1.0, recovery_seconds=30, impact="negligible"),
            Correlation(event=ev2, lost_strokes=20.0, recovery_seconds=600, impact="severe"),
            Correlation(event=ev3, lost_strokes=5.0, recovery_seconds=120, impact="moderate"),
        ]
        s = summarize(correlations)
        assert s.total_events == 3
        assert s.total_lost_strokes == 26.0
        assert s.worst_impact == "severe"
        assert s.negligible_count == 1
        assert s.moderate_count == 1
        assert s.severe_count == 1
        assert s.mean_recovery_seconds == pytest.approx(250.0)

    def test_all_negligible(self):
        correlations = [
            Correlation(
                event=ProcessEvent(timestamp=i * 1000.0, event_type="restart"),
                impact="negligible",
            )
            for i in range(5)
        ]
        s = summarize(correlations)
        assert s.worst_impact == "negligible"
        assert s.negligible_count == 5
        assert s.severe_count == 0
