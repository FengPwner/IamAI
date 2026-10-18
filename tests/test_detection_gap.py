"""Tests for iamai.detection_gap — detection-to-recovery gap tracker."""

from __future__ import annotations

import time

import pytest

from iamai.detection_gap import (
    DetectionEvent,
    DetectionGapTracker,
    classify_detection_gap,
    gap_advice,
)


# ------------------------------------------------------------------
# classify_detection_gap
# ------------------------------------------------------------------


class TestClassify:
    """Standalone classification function."""

    def test_prompt(self):
        assert classify_detection_gap(0) == "prompt"
        assert classify_detection_gap(30) == "prompt"
        assert classify_detection_gap(119) == "prompt"

    def test_timely(self):
        assert classify_detection_gap(120) == "timely"
        assert classify_detection_gap(300) == "timely"
        assert classify_detection_gap(599) == "timely"

    def test_delayed(self):
        assert classify_detection_gap(600) == "delayed"
        assert classify_detection_gap(900) == "delayed"
        assert classify_detection_gap(1799) == "delayed"

    def test_neglected(self):
        assert classify_detection_gap(1800) == "neglected"
        assert classify_detection_gap(3600) == "neglected"
        assert classify_detection_gap(86400) == "neglected"

    def test_boundary_values(self):
        # Exactly at boundaries
        assert classify_detection_gap(120) == "timely"
        assert classify_detection_gap(600) == "delayed"
        assert classify_detection_gap(1800) == "neglected"

    def test_fractional_values(self):
        assert classify_detection_gap(119.5) == "prompt"
        assert classify_detection_gap(120.5) == "timely"


# ------------------------------------------------------------------
# gap_advice
# ------------------------------------------------------------------


class TestAdvice:
    """Human-readable advice strings."""

    def test_prompt_advice(self):
        a = gap_advice("prompt")
        assert "immediate" in a.lower()

    def test_timely_advice(self):
        a = gap_advice("timely")
        assert "10 minutes" in a

    def test_delayed_advice(self):
        a = gap_advice("delayed")
        assert "30 minutes" in a or "automat" in a.lower()

    def test_neglected_advice(self):
        a = gap_advice("neglected")
        assert "unaddressed" in a.lower() or "recovery" in a.lower()

    def test_unknown_verdict(self):
        a = gap_advice("unknown_verdict_xyz")
        assert "unknown" in a.lower()


# ------------------------------------------------------------------
# DetectionEvent
# ------------------------------------------------------------------


class TestDetectionEvent:
    """Single detection-to-recovery event."""

    def test_unresolved_gap_grows(self):
        base = 1000.0
        e = DetectionEvent(detected_at=base, detected_by="stall_probe")
        assert not e.resolved
        # Gap is measured from now when unresolved
        assert e.gap_seconds >= 0

    def test_resolved_gap_fixed(self):
        e = DetectionEvent(
            detected_at=1000.0,
            detected_by="stall_probe",
            recovered_at=1045.0,
            recovered_by="caretaker_restart",
        )
        assert e.resolved
        assert e.gap_seconds == pytest.approx(45.0)

    def test_classify_resolved(self):
        e = DetectionEvent(
            detected_at=1000.0,
            detected_by="test",
            recovered_at=1030.0,
            recovered_by="restart",
        )
        assert e.classify() == "prompt"

    def test_classify_delayed(self):
        e = DetectionEvent(
            detected_at=1000.0,
            detected_by="test",
            recovered_at=1700.0,
            recovered_by="restart",
        )
        assert e.classify() == "delayed"


# ------------------------------------------------------------------
# DetectionGapTracker — basic operations
# ------------------------------------------------------------------


class TestTrackerBasic:
    """Core tracker operations."""

    def test_initial_state(self):
        t = DetectionGapTracker()
        assert not t.pending
        assert t.pending_gap == 0.0
        assert t.event_count == 0
        assert t.latest_gap() == 0.0
        assert t.latest_verdict() == "no_events"

    def test_mark_detected_creates_pending(self):
        t = DetectionGapTracker()
        t.mark_detected("stall_probe", at=1000.0)
        assert t.pending

    def test_mark_recovered_resolves_pending(self):
        t = DetectionGapTracker()
        t.mark_detected("stall_probe", at=1000.0)
        result = t.mark_recovered("restart", at=1045.0)
        assert result is True
        assert not t.pending
        assert t.event_count == 1

    def test_mark_recovered_without_detection(self):
        t = DetectionGapTracker()
        result = t.mark_recovered("restart", at=1000.0)
        assert result is False
        assert t.event_count == 0

    def test_multiple_events(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        t.mark_detected("probe", at=2000.0)
        t.mark_recovered("restart", at=2600.0)
        assert t.event_count == 2

    def test_overwrite_pending_detection(self):
        t = DetectionGapTracker()
        t.mark_detected("probe_a", at=1000.0)
        t.mark_detected("probe_b", at=1100.0)
        t.mark_recovered("restart", at=1130.0)
        # Only the latest detection should be resolved
        assert t.event_count == 1
        assert t.latest_gap() == pytest.approx(30.0)


# ------------------------------------------------------------------
# DetectionGapTracker — metrics
# ------------------------------------------------------------------


class TestTrackerMetrics:
    """Metric calculations across multiple events."""

    @pytest.fixture
    def tracker_with_events(self):
        t = DetectionGapTracker()
        # Event 1: 30s gap (prompt)
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        # Event 2: 300s gap (timely)
        t.mark_detected("probe", at=2000.0)
        t.mark_recovered("restart", at=2300.0)
        # Event 3: 900s gap (delayed)
        t.mark_detected("probe", at=3000.0)
        t.mark_recovered("restart", at=3900.0)
        return t

    def test_gaps_list(self, tracker_with_events):
        assert tracker_with_events.gaps() == [30.0, 300.0, 900.0]

    def test_mean_gap(self, tracker_with_events):
        assert tracker_with_events.mean_gap == pytest.approx(410.0)

    def test_max_gap(self, tracker_with_events):
        assert tracker_with_events.max_gap == pytest.approx(900.0)

    def test_min_gap(self, tracker_with_events):
        assert tracker_with_events.min_gap == pytest.approx(30.0)

    def test_latest_gap(self, tracker_with_events):
        assert tracker_with_events.latest_gap() == pytest.approx(900.0)

    def test_latest_verdict(self, tracker_with_events):
        assert tracker_with_events.latest_verdict() == "delayed"

    def test_verdict_distribution(self, tracker_with_events):
        dist = tracker_with_events.verdict_distribution()
        assert dist == {"prompt": 1, "timely": 1, "delayed": 1, "neglected": 0}

    def test_empty_tracker_metrics(self):
        t = DetectionGapTracker()
        assert t.mean_gap == 0.0
        assert t.max_gap == 0.0
        assert t.min_gap == 0.0
        assert t.gaps() == []


# ------------------------------------------------------------------
# DetectionGapTracker — pending gap
# ------------------------------------------------------------------


class TestTrackerPending:
    """Pending gap behavior."""

    def test_pending_gap_with_detection(self):
        t = DetectionGapTracker()
        now = time.monotonic()
        t.mark_detected("probe", at=now - 60)
        # Pending gap should be approximately 60 seconds
        assert 59 <= t.pending_gap <= 62

    def test_pending_gap_after_resolution(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        assert t.pending_gap == 0.0

    def test_pending_gap_with_no_detection(self):
        t = DetectionGapTracker()
        assert t.pending_gap == 0.0


# ------------------------------------------------------------------
# DetectionGapTracker — summarize and report
# ------------------------------------------------------------------


class TestTrackerSummary:
    """Summary and reporting."""

    def test_summarize_empty(self):
        t = DetectionGapTracker()
        s = t.summarize()
        assert s["resolved_events"] == 0
        assert s["pending"] is False
        assert s["pending_gap_s"] == 0.0
        assert s["mean_gap_s"] == 0.0
        assert s["latest_verdict"] == "no_events"

    def test_summarize_with_events(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        s = t.summarize()
        assert s["resolved_events"] == 1
        assert s["mean_gap_s"] == 30.0
        assert s["latest_verdict"] == "prompt"
        assert s["distribution"]["prompt"] == 1

    def test_summarize_with_pending(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=time.monotonic() - 120)
        s = t.summarize()
        assert s["pending"] is True
        assert s["pending_gap_s"] >= 119.0

    def test_report_line_no_events(self):
        t = DetectionGapTracker()
        line = t.report_line()
        assert "0 events" in line

    def test_report_line_with_events(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        line = t.report_line()
        assert "1 events" in line
        assert "prompt" in line

    def test_report_line_with_pending(self):
        t = DetectionGapTracker()
        now = time.monotonic()
        t.mark_detected("probe", at=now - 200)
        line = t.report_line()
        assert "pending" in line


# ------------------------------------------------------------------
# DetectionGapTracker — reset
# ------------------------------------------------------------------


class TestTrackerReset:
    """Reset clears all state."""

    def test_reset_clears_events(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        t.reset()
        assert t.event_count == 0
        assert t.gaps() == []
        assert t.latest_verdict() == "no_events"

    def test_reset_clears_pending(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        assert t.pending
        t.reset()
        assert not t.pending
        assert t.pending_gap == 0.0

    def test_reset_allows_fresh_start(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1030.0)
        t.reset()
        t.mark_detected("probe", at=2000.0)
        t.mark_recovered("restart", at=2600.0)
        assert t.event_count == 1
        assert t.latest_gap() == pytest.approx(600.0)
        assert t.latest_verdict() == "delayed"


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and edge cases."""

    def test_zero_gap(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        t.mark_recovered("restart", at=1000.0)
        assert t.latest_gap() == 0.0
        assert t.latest_verdict() == "prompt"

    def test_very_large_gap(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=0.0)
        t.mark_recovered("restart", at=86400.0)
        assert t.latest_gap() == 86400.0
        assert t.latest_verdict() == "neglected"

    def test_rapid_detect_recover_cycles(self):
        t = DetectionGapTracker()
        for i in range(100):
            base = i * 100.0
            t.mark_detected("probe", at=base)
            t.mark_recovered("restart", at=base + 5)
        assert t.event_count == 100
        assert t.mean_gap == pytest.approx(5.0)
        dist = t.verdict_distribution()
        assert dist["prompt"] == 100

    def test_detect_without_recover_then_reset(self):
        t = DetectionGapTracker()
        t.mark_detected("probe", at=1000.0)
        # Never recovered — pending forever
        assert t.pending
        assert t.event_count == 0
        # Reset clears the orphan
        t.reset()
        assert not t.pending
