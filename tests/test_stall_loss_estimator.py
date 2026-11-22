"""Tests for iamai.stall_loss_estimator.

Covers StallEvent properties, LossReport aggregations, the core
estimate_losses algorithm across normal, edge, and multi-stall
scenarios, recovery measurement, and severity classification.
"""

import pytest

from iamai.stall_loss_estimator import (
    LossReport,
    StallEvent,
    estimate_losses,
)


# ---------------------------------------------------------------------------
# StallEvent
# ---------------------------------------------------------------------------

class TestStallEvent:
    """StallEvent dataclass and derived properties."""

    def test_loss_severity_minor(self):
        s = StallEvent(index=0, gap_seconds=600, expected_strokes=40,
                       recovery_seconds=30, cadence=15)
        assert s.loss_severity == "minor"

    def test_loss_severity_moderate_low_boundary(self):
        s = StallEvent(index=0, gap_seconds=1500, expected_strokes=100,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "moderate"

    def test_loss_severity_moderate_high_boundary(self):
        s = StallEvent(index=0, gap_seconds=7500, expected_strokes=500,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "moderate"

    def test_loss_severity_severe(self):
        s = StallEvent(index=0, gap_seconds=9000, expected_strokes=600,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "severe"

    def test_loss_severity_zero_expected(self):
        s = StallEvent(index=0, gap_seconds=1, expected_strokes=0,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "minor"

    def test_as_dict_rounding(self):
        s = StallEvent(index=3, gap_seconds=3269.456, expected_strokes=217,
                       recovery_seconds=45.789, cadence=15)
        d = s.as_dict()
        assert d == {
            "index": 3,
            "gap_seconds": 3269.5,
            "expected_strokes": 217,
            "recovery_seconds": 45.8,
            "loss_severity": "moderate",
        }

    def test_frozen(self):
        s = StallEvent(index=0, gap_seconds=100, expected_strokes=6,
                       recovery_seconds=15, cadence=15)
        with pytest.raises(AttributeError):
            s.gap_seconds = 200


# ---------------------------------------------------------------------------
# LossReport
# ---------------------------------------------------------------------------

class TestLossReport:
    """LossReport aggregations and properties."""

    def test_empty_report(self):
        r = LossReport()
        assert r.stall_count == 0
        assert r.worst_severity is None
        assert r.health_score == 1.0

    def test_stall_count(self):
        stalls = [
            StallEvent(index=0, gap_seconds=1500, expected_strokes=100,
                       recovery_seconds=0, cadence=15),
            StallEvent(index=5, gap_seconds=3000, expected_strokes=200,
                       recovery_seconds=0, cadence=15),
        ]
        r = LossReport(stalls=stalls, total_strokes=300,
                       total_gap_seconds=4500, total_expected_lost=300)
        assert r.stall_count == 2

    def test_worst_severity_single_minor(self):
        stalls = [StallEvent(index=0, gap_seconds=600, expected_strokes=10,
                             recovery_seconds=0, cadence=15)]
        r = LossReport(stalls=stalls, total_strokes=100,
                       total_gap_seconds=600, total_expected_lost=10)
        assert r.worst_severity == "minor"

    def test_worst_severity_mixed(self):
        stalls = [
            StallEvent(index=0, gap_seconds=600, expected_strokes=10,
                       recovery_seconds=0, cadence=15),
            StallEvent(index=5, gap_seconds=9000, expected_strokes=600,
                       recovery_seconds=0, cadence=15),
        ]
        r = LossReport(stalls=stalls, total_strokes=700,
                       total_gap_seconds=9600, total_expected_lost=610)
        assert r.worst_severity == "severe"

    def test_health_score_no_strokes(self):
        r = LossReport(total_strokes=0, total_expected_lost=0)
        assert r.health_score == 1.0

    def test_health_score_no_loss(self):
        r = LossReport(total_strokes=100, total_expected_lost=0)
        assert r.health_score == 0.0

    def test_health_score_partial_loss(self):
        r = LossReport(total_strokes=90, total_expected_lost=10)
        expected = round(10 / (90 + 10), 4)
        assert r.health_score == expected

    def test_health_score_capped_at_one(self):
        # Edge case: more lost than total shouldn't exceed 1.0
        r = LossReport(total_strokes=5, total_expected_lost=100)
        assert r.health_score <= 1.0

    def test_as_dict(self):
        stalls = [StallEvent(index=0, gap_seconds=1500, expected_strokes=100,
                             recovery_seconds=30, cadence=15)]
        r = LossReport(stalls=stalls, total_strokes=200,
                       total_gap_seconds=1500.0, total_expected_lost=100)
        d = r.as_dict()
        assert d["stall_count"] == 1
        assert d["total_strokes"] == 200
        assert d["total_gap_seconds"] == 1500.0
        assert d["total_expected_lost"] == 100
        assert d["worst_severity"] == "moderate"
        assert isinstance(d["health_score"], float)


# ---------------------------------------------------------------------------
# estimate_losses — core algorithm
# ---------------------------------------------------------------------------

class TestEstimateLosses:
    """Core scanning algorithm."""

    def test_empty_timestamps(self):
        r = estimate_losses([])
        assert r.stall_count == 0
        assert r.total_strokes == 0

    def test_single_timestamp(self):
        r = estimate_losses([1000.0])
        assert r.stall_count == 0
        assert r.total_strokes == 1

    def test_two_timestamps_no_gap(self):
        r = estimate_losses([1000.0, 1015.0], cadence=15, gap_threshold=1200)
        assert r.stall_count == 0
        assert r.total_strokes == 2

    def test_two_timestamps_with_gap(self):
        r = estimate_losses([1000.0, 4000.0], cadence=15, gap_threshold=1200)
        assert r.stall_count == 1
        assert r.total_strokes == 2
        stall = r.stalls[0]
        assert stall.gap_seconds == 3000.0
        assert stall.expected_strokes == 200  # 3000 / 15
        assert stall.index == 0

    def test_gap_at_threshold_not_flagged(self):
        # Exactly at threshold should not count as a stall
        r = estimate_losses([0.0, 1200.0], cadence=15, gap_threshold=1200)
        assert r.stall_count == 0

    def test_gap_just_above_threshold(self):
        r = estimate_losses([0.0, 1201.0], cadence=15, gap_threshold=1200)
        assert r.stall_count == 1
        assert r.stalls[0].gap_seconds == 1201.0

    def test_multiple_stalls(self):
        # Normal run → stall → normal run → stall → normal run
        ts = (
            [i * 15 for i in range(10)]  # 0..135s: 10 strokes
            + [135 + 3000]                 # stall: 3000s gap
            + [135 + 3000 + i * 15 for i in range(1, 6)]  # 5 more strokes
            + [135 + 3000 + 75 + 2000]     # stall: 2000s gap
            + [135 + 3000 + 75 + 2000 + i * 15 for i in range(1, 4)]  # 3 more
        )
        r = estimate_losses(ts, cadence=15, gap_threshold=1200)
        assert r.stall_count == 2
        assert r.total_strokes == len(ts)
        # First stall: 3000s gap
        assert r.stalls[0].gap_seconds == 3000.0
        assert r.stalls[0].expected_strokes == 200
        # Second stall: 2000s gap
        assert r.stalls[1].gap_seconds == 2000.0
        assert r.stalls[1].expected_strokes == pytest.approx(133, abs=1)

    def test_total_gap_accumulation(self):
        ts = [0, 2000, 2015, 5000, 5015]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200)
        assert r.stall_count == 2
        assert r.total_gap_seconds == (2000 + (5000 - 2015))

    def test_total_expected_lost_accumulation(self):
        ts = [0, 2000, 2015, 5000, 5015]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200)
        expected = int(2000 / 15) + int((5000 - 2015) / 15)
        assert r.total_expected_lost == expected

    def test_custom_cadence(self):
        # With cadence=60, a 1200s gap only loses 20 strokes
        r = estimate_losses([0, 1200], cadence=60, gap_threshold=1200)
        # gap == threshold → not flagged
        assert r.stall_count == 0

        r = estimate_losses([0, 1201], cadence=60, gap_threshold=1200)
        assert r.stall_count == 1
        assert r.stalls[0].expected_strokes == 20  # 1201 // 60

    def test_custom_gap_threshold(self):
        r = estimate_losses([0, 300, 315], cadence=15, gap_threshold=200)
        assert r.stall_count == 1
        assert r.stalls[0].gap_seconds == 300

    def test_realistic_overnight_stall(self):
        """Simulate the common pattern: evening strokes, overnight gap,
        morning recovery."""
        base = 1700000000
        # 20 strokes at 15s intervals before stall
        before = [base + i * 15 for i in range(20)]
        # 3269s gap (matches the observed longest gap)
        gap_end = before[-1] + 3269
        # 10 strokes after recovery
        after = [gap_end + i * 15 for i in range(10)]
        ts = before + after
        r = estimate_losses(ts, cadence=15, gap_threshold=1200)
        assert r.stall_count == 1
        stall = r.stalls[0]
        assert stall.gap_seconds == 3269
        assert stall.expected_strokes == pytest.approx(217, abs=1)
        assert stall.loss_severity == "moderate"


# ---------------------------------------------------------------------------
# Recovery measurement
# ---------------------------------------------------------------------------

class TestRecovery:
    """Recovery time calculation after a stall."""

    def test_instant_recovery(self):
        # Post-stall strokes are at normal cadence → recovery = 0
        ts = [0, 3000, 3015, 3030, 3045, 3060, 3075]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200,
                            recovery_window=5)
        assert r.stalls[0].recovery_seconds == 0.0

    def test_slow_recovery(self):
        # Post-stall strokes are slow initially
        ts = [0, 3000, 3100, 3150, 3200, 3250, 3265, 3280]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200,
                            recovery_window=5)
        stall = r.stalls[0]
        # recovery accumulates intervals > 2*cadence from the first
        # post-gap stroke
        assert stall.recovery_seconds > 0

    def test_recovery_window_boundary(self):
        # Only 2 strokes after the gap (fewer than recovery_window)
        ts = [0, 3000, 3015]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200,
                            recovery_window=5)
        # No recovery measurement possible with only one post-gap interval
        assert r.stalls[0].recovery_seconds == 0.0

    def test_recovery_with_no_post_strokes(self):
        # Only the pre-gap stroke and the first post-gap stroke
        ts = [0, 5000]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200,
                            recovery_window=5)
        assert r.stalls[0].recovery_seconds == 0.0

    def test_recovery_window_respected(self):
        """Recovery window limits how many post-gap intervals are examined."""
        # 10 post-gap strokes, all slow, but window=3
        ts = [0, 3000,
              3100, 3200, 3300, 3400, 3500,
              3515, 3530, 3545, 3560, 3575]
        r = estimate_losses(ts, cadence=15, gap_threshold=1200,
                            recovery_window=3)
        stall = r.stalls[0]
        # Only the first 3 post-gap intervals are examined
        # interval 3000→3100=100 (>30, counts), 3100→3200=100 (>30, counts),
        # 3200→3300=100 (>30, counts) — window exhausted
        assert stall.recovery_seconds == pytest.approx(300, abs=1)


# ---------------------------------------------------------------------------
# Severity classification edge cases
# ---------------------------------------------------------------------------

class TestSeverityEdges:
    """Boundary values for loss_severity."""

    def test_exactly_99_is_minor(self):
        s = StallEvent(index=0, gap_seconds=0, expected_strokes=99,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "minor"

    def test_exactly_100_is_moderate(self):
        s = StallEvent(index=0, gap_seconds=0, expected_strokes=100,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "moderate"

    def test_exactly_500_is_moderate(self):
        s = StallEvent(index=0, gap_seconds=0, expected_strokes=500,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "moderate"

    def test_exactly_501_is_severe(self):
        s = StallEvent(index=0, gap_seconds=0, expected_strokes=501,
                       recovery_seconds=0, cadence=15)
        assert s.loss_severity == "severe"


# ---------------------------------------------------------------------------
# Integration: end-to-end scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end scenario matching real overnight stall patterns."""

    def test_full_overnight_scenario(self):
        base = 1700000000
        cadence = 15

        # Phase 1: 40 normal strokes (10 minutes of writing)
        normal_before = [base + i * cadence for i in range(40)]

        # Phase 2: overnight stall — 2945s gap (observed in visit 785)
        gap_start = normal_before[-1]
        gap_duration = 2945
        gap_end = gap_start + gap_duration

        # Phase 3: 30 normal strokes after restart
        normal_after = [gap_end + i * cadence for i in range(30)]

        ts = normal_before + normal_after
        r = estimate_losses(ts, cadence=cadence, gap_threshold=1200)

        # Structural checks
        assert r.total_strokes == 70
        assert r.stall_count == 1

        stall = r.stalls[0]
        assert stall.gap_seconds == 2945
        assert stall.expected_strokes == pytest.approx(196, abs=1)
        assert stall.loss_severity == "moderate"
        assert stall.recovery_seconds == 0.0  # post-stall intervals are normal

        # Aggregate checks
        assert r.total_expected_lost == stall.expected_strokes
        assert r.total_gap_seconds == 2945
        assert r.worst_severity == "moderate"

        # Health score: lost / (total + lost) = 196 / (70 + 196)
        expected_health = round(196 / (70 + 196), 4)
        assert r.health_score == pytest.approx(expected_health, abs=0.01)

        # Serialization
        d = r.as_dict()
        assert d["stall_count"] == 1
        assert d["worst_severity"] == "moderate"
        assert isinstance(d["health_score"], float)

    def test_multi_stall_degradation(self):
        """Two stalls of increasing severity."""
        base = 1700000000
        c = 15

        # 20 normal strokes
        p1 = [base + i * c for i in range(20)]

        # Stall 1: 1500s (moderate)
        s1_end = p1[-1] + 1500
        p2 = [s1_end + i * c for i in range(10)]

        # Stall 2: 8000s (severe)
        s2_end = p2[-1] + 8000
        p3 = [s2_end + i * c for i in range(10)]

        ts = p1 + p2 + p3
        r = estimate_losses(ts, cadence=c, gap_threshold=1200)

        assert r.stall_count == 2
        assert r.stalls[0].loss_severity == "moderate"
        assert r.stalls[1].loss_severity == "severe"
        assert r.worst_severity == "severe"
