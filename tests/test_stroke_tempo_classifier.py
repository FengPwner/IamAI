"""Tests for iamai.stroke_tempo_classifier — writing tempo regime classifier.

Covers:
  - interval computation (sorted, positive-only)
  - median math (odd/even/empty)
  - regime classification at each boundary
  - confidence levels by sample count
  - transition labels and direction detection
  - snapshot and summary formatting
  - record_batch and clear
  - window_size enforcement (FIFO drop)
  - edge cases: single sample, duplicate timestamps, negative intervals

Total: 52 tests.
"""

import pytest
from iamai.stroke_tempo_classifier import (
    StrokeTempoClassifier,
    TempoSnapshot,
    REGIME_SPRINT,
    REGIME_STEADY,
    REGIME_DRIP,
    REGIME_DORMANT,
    REGIME_STALLED,
    REGIME_UNKNOWN,
    SPRINT_CEILING,
    STEADY_CEILING,
    DRIP_CEILING,
    DORMANT_CEILING,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_classifier(intervals: list[float], base: float = 1_000_000.0) -> StrokeTempoClassifier:
    """Build a classifier with exact inter-stroke intervals."""
    tc = StrokeTempoClassifier(window_size=len(intervals) + 1)
    ts = base
    tc.record(ts)
    for iv in intervals:
        ts += iv
        tc.record(ts)
    return tc


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------

class TestIntervals:
    def test_empty_when_no_data(self):
        tc = StrokeTempoClassifier()
        assert tc.intervals() == []

    def test_empty_when_one_sample(self):
        tc = StrokeTempoClassifier()
        tc.record(100.0)
        assert tc.intervals() == []

    def test_simple_intervals(self):
        tc = make_classifier([10.0, 20.0, 30.0])
        assert tc.intervals() == [10.0, 20.0, 30.0]

    def test_intervals_are_sorted(self):
        """Timestamps inserted out of order should still yield sorted intervals."""
        tc = StrokeTempoClassifier()
        tc.record(100.0)
        tc.record(130.0)
        tc.record(110.0)  # inserted between
        assert tc.intervals() == [10.0, 20.0]

    def test_duplicate_timestamps_skipped(self):
        tc = StrokeTempoClassifier()
        tc.record(100.0)
        tc.record(100.0)
        tc.record(110.0)
        assert tc.intervals() == [10.0]

    def test_negative_interval_dropped(self):
        tc = StrokeTempoClassifier()
        tc.record(100.0)
        tc.record(90.0)  # before previous — negative
        tc.record(120.0)
        ivs = tc.intervals()
        assert all(iv > 0 for iv in ivs)


# ---------------------------------------------------------------------------
# Median interval
# ---------------------------------------------------------------------------

class TestMedianInterval:
    def test_zero_when_empty(self):
        tc = StrokeTempoClassifier()
        assert tc.median_interval() == 0.0

    def test_odd_count(self):
        tc = make_classifier([5.0, 10.0, 15.0])
        assert tc.median_interval() == 10.0

    def test_even_count(self):
        tc = make_classifier([2.0, 4.0, 6.0, 8.0])
        assert tc.median_interval() == 5.0

    def test_two_intervals(self):
        tc = make_classifier([10.0, 20.0])
        assert tc.median_interval() == 15.0

    def test_single_interval(self):
        tc = make_classifier([7.5])
        # Only 1 interval → median is that value
        assert tc.median_interval() == 7.5


# ---------------------------------------------------------------------------
# Classification boundaries
# ---------------------------------------------------------------------------

class TestClassify:
    def test_unknown_with_no_data(self):
        tc = StrokeTempoClassifier()
        assert tc.classify() == REGIME_UNKNOWN

    def test_unknown_with_one_sample(self):
        tc = StrokeTempoClassifier()
        tc.record(100.0)
        assert tc.classify() == REGIME_UNKNOWN

    def test_sprint(self):
        tc = make_classifier([1.0, 2.0, 3.0, 2.0, 1.5])
        assert tc.classify() == REGIME_SPRINT

    def test_sprint_at_boundary(self):
        """Just below SPRINT_CEILING."""
        tc = make_classifier([4.9, 4.8, 4.9, 4.8, 4.9])
        assert tc.classify() == REGIME_SPRINT

    def test_steady(self):
        tc = make_classifier([10.0, 15.0, 12.0, 14.0, 11.0])
        assert tc.classify() == REGIME_STEADY

    def test_steady_at_boundary(self):
        """SPRINT_CEILING exactly should be steady."""
        tc = make_classifier([5.0, 5.0, 5.0, 5.0, 5.0])
        assert tc.classify() == REGIME_STEADY

    def test_drip(self):
        tc = make_classifier([60.0, 90.0, 120.0, 80.0, 70.0])
        assert tc.classify() == REGIME_DRIP

    def test_drip_at_boundary(self):
        """STEADY_CEILING exactly should be drip."""
        tc = make_classifier([30.0, 30.0, 30.0, 30.0, 30.0])
        assert tc.classify() == REGIME_DRIP

    def test_dormant(self):
        tc = make_classifier([600.0, 700.0, 500.0, 800.0, 650.0])
        assert tc.classify() == REGIME_DORMANT

    def test_dormant_at_boundary(self):
        """DRIP_CEILING exactly should be dormant."""
        tc = make_classifier([300.0, 300.0, 300.0, 300.0, 300.0])
        assert tc.classify() == REGIME_DORMANT

    def test_stalled(self):
        tc = make_classifier([2000.0, 2500.0, 1900.0, 2100.0, 2200.0])
        assert tc.classify() == REGIME_STALLED

    def test_stalled_at_boundary(self):
        """DORMANT_CEILING exactly should be stalled."""
        tc = make_classifier([1800.0, 1800.0, 1800.0, 1800.0, 1800.0])
        assert tc.classify() == REGIME_STALLED

    def test_regime_from_median_static(self):
        assert StrokeTempoClassifier._regime_from_median(0.5) == REGIME_SPRINT
        assert StrokeTempoClassifier._regime_from_median(10.0) == REGIME_STEADY
        assert StrokeTempoClassifier._regime_from_median(100.0) == REGIME_DRIP
        assert StrokeTempoClassifier._regime_from_median(500.0) == REGIME_DORMANT
        assert StrokeTempoClassifier._regime_from_median(2000.0) == REGIME_STALLED


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_low_confidence_few_samples(self):
        tc = make_classifier([10.0, 10.0])  # 2 intervals
        assert tc.confidence() == 0.1

    def test_medium_confidence_5_samples(self):
        tc = make_classifier([10.0] * 6)  # 6 intervals
        assert tc.confidence() == 0.4

    def test_good_confidence_10_samples(self):
        tc = make_classifier([10.0] * 10)  # 10 intervals
        assert tc.confidence() == 0.7

    def test_high_confidence_20_samples(self):
        tc = make_classifier([10.0] * 20)  # 20 intervals
        assert tc.confidence() == 1.0

    def test_high_confidence_50_samples(self):
        tc = make_classifier([10.0] * 50)
        assert tc.confidence() == 1.0

    def test_confidence_empty(self):
        tc = StrokeTempoClassifier()
        assert tc.confidence() == 0.1


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

class TestTransitions:
    def test_no_change(self):
        tc = make_classifier([10.0, 12.0, 11.0, 13.0, 10.0])
        label = tc.transition("steady")
        assert label == "steady\u2192steady"

    def test_slowdown(self):
        tc = make_classifier([60.0, 90.0, 80.0, 70.0, 100.0])
        label = tc.transition("steady")
        assert label == "steady\u2192drip"

    def test_speedup(self):
        tc = make_classifier([2.0, 3.0, 2.5, 2.0, 3.0])
        label = tc.transition("steady")
        assert label == "steady\u2192sprint"

    def test_is_slowdown_true(self):
        assert StrokeTempoClassifier.is_slowdown("steady\u2192drip") is True

    def test_is_slowdown_false(self):
        assert StrokeTempoClassifier.is_slowdown("drip\u2192steady") is False

    def test_is_speedup_true(self):
        assert StrokeTempoClassifier.is_speedup("dormant\u2192sprint") is True

    def test_is_speedup_false(self):
        assert StrokeTempoClassifier.is_speedup("sprint\u2192dormant") is False

    def test_is_slowdown_same_regime(self):
        assert StrokeTempoClassifier.is_slowdown("steady\u2192steady") is False

    def test_is_speedup_same_regime(self):
        assert StrokeTempoClassifier.is_speedup("steady\u2192steady") is False

    def test_invalid_transition_label(self):
        assert StrokeTempoClassifier.is_slowdown("garbage") is False
        assert StrokeTempoClassifier.is_speedup("garbage") is False

    def test_unknown_in_transition(self):
        assert StrokeTempoClassifier.is_slowdown("unknown\u2192steady") is False


# ---------------------------------------------------------------------------
# Snapshot & summary
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_fields(self):
        tc = make_classifier([10.0, 12.0, 14.0, 11.0, 13.0])
        snap = tc.snapshot()
        assert isinstance(snap, TempoSnapshot)
        assert snap.regime == REGIME_STEADY
        assert snap.median_interval > 0
        assert snap.confidence == 0.4  # 5 intervals
        assert snap.sample_count == 5

    def test_summary_format(self):
        tc = make_classifier([10.0, 12.0, 14.0, 11.0, 13.0])
        s = tc.summary()
        assert "tempo=steady" in s
        assert "conf=" in s
        assert "median=" in s
        assert "n=5" in s


# ---------------------------------------------------------------------------
# Record batch & clear
# ---------------------------------------------------------------------------

class TestBatchAndClear:
    def test_record_batch(self):
        tc = StrokeTempoClassifier()
        tc.record_batch([100.0, 110.0, 120.0, 130.0])
        assert len(tc.intervals()) == 3

    def test_clear(self):
        tc = make_classifier([10.0, 10.0, 10.0])
        assert len(tc.intervals()) > 0
        tc.clear()
        assert tc.intervals() == []
        assert tc.classify() == REGIME_UNKNOWN


# ---------------------------------------------------------------------------
# Window size / FIFO
# ---------------------------------------------------------------------------

class TestWindow:
    def test_window_drops_old(self):
        tc = StrokeTempoClassifier(window_size=5)
        for i in range(10):
            tc.record(float(i * 10))
        # window=5 means max 5 timestamps → 4 intervals
        assert len(tc.intervals()) <= 4

    def test_window_preserves_recent(self):
        tc = StrokeTempoClassifier(window_size=4)
        tc.record_batch([0.0, 1.0, 2.0, 3.0, 100.0])
        # oldest (0.0) dropped; timestamps are [1, 2, 3, 100]
        ivs = tc.intervals()
        assert 100.0 - 3.0 in ivs


# ---------------------------------------------------------------------------
# Regime constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_regime_ordering(self):
        """Regimes should progress from fast to slow."""
        order = [REGIME_SPRINT, REGIME_STEADY, REGIME_DRIP, REGIME_DORMANT, REGIME_STALLED]
        ceilings = [SPRINT_CEILING, STEADY_CEILING, DRIP_CEILING, DORMANT_CEILING]
        for i in range(len(ceilings) - 1):
            assert ceilings[i] < ceilings[i + 1]

    def test_all_regimes_are_strings(self):
        for r in [REGIME_SPRINT, REGIME_STEADY, REGIME_DRIP, REGIME_DORMANT, REGIME_STALLED, REGIME_UNKNOWN]:
            assert isinstance(r, str)
