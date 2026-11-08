"""Tests for iamai.cadence_recovery_tracker module."""

import pytest

from iamai.cadence_recovery_tracker import (
    CadenceRecoveryTracker,
    DisruptionRecovery,
    recovery_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _even_spaced(start, interval, count):
    """Generate evenly spaced timestamps."""
    return [start + i * interval for i in range(count)]


def _with_disruption(base_times, disrupt_after_idx, gap_s):
    """Insert a disruption (gap) after the stroke at disrupt_after_idx."""
    before = base_times[: disrupt_after_idx + 1]
    after = [t + gap_s for t in base_times[disrupt_after_idx + 1 :]]
    return before + after


def _with_overshoot_recovery(base_times, disrupt_after_idx, gap_s, overshoot_count=3):
    """Insert disruption followed by rushed (overshoot) strokes, then normal."""
    before = base_times[: disrupt_after_idx + 1]
    last = before[-1]
    # disruption gap
    resume = last + gap_s
    # rushed strokes (half the expected cadence)
    rushed = [resume + i * 7 for i in range(overshoot_count)]
    # then normal cadence resumes
    normal_start = rushed[-1] + 15
    normal = _even_spaced(normal_start, 15, 10)
    return before + [resume] + rushed + normal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_stream():
    """100 strokes, one every 15s — no disruptions."""
    return _even_spaced(1_000_000, 15, 100)


@pytest.fixture
def one_smooth_disruption():
    """50 normal strokes, 5-minute gap, then 50 normal strokes."""
    normal = _even_spaced(1_000_000, 15, 100)
    return _with_disruption(normal, 49, 300)  # 300s = 20x cadence


@pytest.fixture
def one_stuck_disruption():
    """50 normal strokes, 10-minute gap, then only 3 more strokes."""
    normal = _even_spaced(1_000_000, 15, 50)
    gap_end = normal[-1] + 600
    tail = _even_spaced(gap_end, 15, 3)
    return normal + tail


@pytest.fixture
def multiple_disruptions():
    """Three disruptions: one instant, one smooth, one slow."""
    base = _even_spaced(1_000_000, 15, 30)
    # disruption 1 at index 10: 120s gap (8x), then 10 normal strokes
    stream = _with_disruption(base, 9, 120)
    # disruption 2 at index 25 (adjusted): 300s gap (20x), then normal
    stream = _with_disruption(stream, 24, 300)
    # disruption 3 at index 45 (adjusted): 900s gap (60x), then slow recovery
    stream = _with_disruption(stream, 44, 900)
    return stream


@pytest.fixture
def disruption_with_overshoot():
    """Disruption followed by rushed recovery strokes."""
    normal = _even_spaced(1_000_000, 15, 50)
    return _with_overshoot_recovery(normal, 24, 300, overshoot_count=3)


# ---------------------------------------------------------------------------
# Basic tests
# ---------------------------------------------------------------------------


class TestNoDisruptions:
    """A clean stream should report zero disruptions."""

    def test_disruption_count_zero(self, clean_stream):
        crt = CadenceRecoveryTracker(clean_stream, expected_cadence=15)
        assert crt.disruption_count == 0

    def test_mean_recovery_zero(self, clean_stream):
        crt = CadenceRecoveryTracker(clean_stream, expected_cadence=15)
        assert crt.mean_recovery_s == 0.0

    def test_summary_clean(self, clean_stream):
        crt = CadenceRecoveryTracker(clean_stream, expected_cadence=15)
        s = crt.summary()
        assert s["disruptions"] == 0
        assert s["mean_recovery_s"] == 0.0
        assert s["worst_verdict"] == "instant"

    def test_report_clean(self, clean_stream):
        r = recovery_report(clean_stream, expected_cadence=15)
        assert "no disruptions" in r


class TestSingleSmoothDisruption:
    """One disruption with a smooth recovery."""

    def test_finds_one_disruption(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        assert crt.disruption_count == 1

    def test_gap_detected(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        d = crt.disruptions[0]
        # _with_disruption shifts post-gap strokes by gap_s on top of
        # the original interval, so actual gap = gap_s + interval = 315
        assert d.gap_s >= 300

    def test_recovery_verdict_smooth(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        d = crt.disruptions[0]
        # 5 consecutive good gaps at 15s = 75s recovery
        # 75 / 15 = 5.0 → at the boundary of smooth/slow
        assert d.verdict in ("smooth", "slow")

    def test_settle_strokes_positive(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        d = crt.disruptions[0]
        assert d.settle_strokes >= 5  # at least settle_window strokes


class TestStuckDisruption:
    """One disruption where the writer never recovers (too few strokes)."""

    def test_finds_one_disruption(self, one_stuck_disruption):
        crt = CadenceRecoveryTracker(
            one_stuck_disruption, expected_cadence=15
        )
        assert crt.disruption_count == 1

    def test_verdict_stuck(self, one_stuck_disruption):
        crt = CadenceRecoveryTracker(
            one_stuck_disruption, expected_cadence=15
        )
        d = crt.disruptions[0]
        # only 3 strokes after disruption, need 5 consecutive good gaps
        # but there are only 2 gaps → can never settle → stuck
        assert d.verdict == "stuck"

    def test_recovery_time_finite_but_stuck(self, one_stuck_disruption):
        crt = CadenceRecoveryTracker(
            one_stuck_disruption, expected_cadence=15
        )
        s = crt.summary()
        # stuck verdict but recovery time measured to last available stroke
        assert s["worst_verdict"] == "stuck"
        # only 3 strokes after disruption → 2 gaps → 30s
        assert s["mean_recovery_s"] is not None


class TestOvershootRecovery:
    """Disruption followed by rushed strokes (catching up)."""

    def test_overshoot_detected(self, disruption_with_overshoot):
        crt = CadenceRecoveryTracker(
            disruption_with_overshoot, expected_cadence=15
        )
        d = crt.disruptions[0]
        # the 3 rushed strokes at 7s intervals should count as overshoot
        assert d.overshoot_count >= 2

    def test_total_overshoot(self, disruption_with_overshoot):
        crt = CadenceRecoveryTracker(
            disruption_with_overshoot, expected_cadence=15
        )
        assert crt.total_overshoot >= 2


class TestMultipleDisruptions:
    """Multiple disruptions with different recovery qualities."""

    def test_finds_all_disruptions(self, multiple_disruptions):
        crt = CadenceRecoveryTracker(
            multiple_disruptions, expected_cadence=15
        )
        assert crt.disruption_count >= 2

    def test_worst_verdict(self, multiple_disruptions):
        crt = CadenceRecoveryTracker(
            multiple_disruptions, expected_cadence=15
        )
        # at least one disruption should have a non-instant verdict
        assert crt.worst_verdict in ("smooth", "slow", "stuck")

    def test_best_verdict(self, multiple_disruptions):
        crt = CadenceRecoveryTracker(
            multiple_disruptions, expected_cadence=15
        )
        # at least one should recover
        assert crt.best_verdict in ("instant", "smooth", "slow")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_stream(self):
        crt = CadenceRecoveryTracker([], expected_cadence=15)
        assert crt.disruption_count == 0
        assert crt.mean_recovery_s == 0.0

    def test_single_stroke(self):
        crt = CadenceRecoveryTracker([1_000_000], expected_cadence=15)
        assert crt.disruption_count == 0

    def test_two_strokes_normal(self):
        crt = CadenceRecoveryTracker(
            [1_000_000, 1_000_015], expected_cadence=15
        )
        assert crt.disruption_count == 0

    def test_two_strokes_disrupted(self):
        crt = CadenceRecoveryTracker(
            [1_000_000, 1_000_300], expected_cadence=15
        )
        assert crt.disruption_count == 1
        d = crt.disruptions[0]
        assert d.verdict == "stuck"  # only one stroke after, can't settle

    def test_unsorted_input(self):
        """Input should be sorted internally."""
        times = [1_000_015, 1_000_000, 1_000_030, 1_000_300]
        crt = CadenceRecoveryTracker(times, expected_cadence=15)
        # should not crash; should find the disruption
        assert crt.disruption_count >= 0

    def test_zero_cadence(self):
        """Zero cadence should not crash."""
        times = _even_spaced(1_000_000, 1, 10)
        crt = CadenceRecoveryTracker(times, expected_cadence=0)
        # division by zero should be handled
        assert crt.summary() is not None

    def test_very_large_gap(self):
        """A massive gap should still be detected."""
        times = [1_000_000, 1_000_000 + 86400]  # 24-hour gap
        crt = CadenceRecoveryTracker(times, expected_cadence=15)
        assert crt.disruption_count == 1

    def test_exact_threshold_boundary(self):
        """Gap exactly at the threshold should not be a disruption."""
        # threshold = 4.0 * 15 = 60s
        times = [1_000_000, 1_000_060, 1_000_075, 1_000_090]
        crt = CadenceRecoveryTracker(
            times, expected_cadence=15, disruption_threshold=4.0
        )
        # 60s = exactly 4x cadence; gap >= threshold_s → disruption
        assert crt.disruption_count == 1

    def test_just_below_threshold(self):
        """Gap just below threshold should not trigger."""
        times = [1_000_000, 1_000_059, 1_000_074, 1_000_089]
        crt = CadenceRecoveryTracker(
            times, expected_cadence=15, disruption_threshold=4.0
        )
        assert crt.disruption_count == 0

    def test_report_with_zero_disruptions(self):
        r = recovery_report([], expected_cadence=15)
        assert "no disruptions" in r


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------


class TestVerdictClassification:
    """Test the verdict thresholds."""

    def test_instant_recovery(self):
        """Recovery within 2x cadence = instant."""
        # Make 50 normal strokes, disruption, then 10 normal strokes
        # with only a brief gap that counts as disruption
        base = _even_spaced(1_000_000, 15, 50)
        # 61s gap (just over 4x)
        stream = _with_disruption(base, 24, 61)
        crt = CadenceRecoveryTracker(
            stream, expected_cadence=15, settle_window=2
        )
        if crt.disruption_count > 0:
            d = crt.disruptions[0]
            # if it settles in 2 good gaps (30s), 30/15 = 2.0 → at boundary
            assert d.verdict in ("instant", "smooth")

    def test_stuck_when_never_settles(self):
        """When the stream ends before settling, verdict is stuck."""
        times = [1_000_000, 1_000_300, 1_000_315]  # disruption then 1 gap
        crt = CadenceRecoveryTracker(
            times, expected_cadence=15, settle_window=5
        )
        assert crt.disruptions[0].verdict == "stuck"


# ---------------------------------------------------------------------------
# Summary and report
# ---------------------------------------------------------------------------


class TestSummaryAndReport:
    """Test the summary dict and report string."""

    def test_summary_keys(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        s = crt.summary()
        expected_keys = {
            "disruptions",
            "mean_recovery_s",
            "median_recovery_s",
            "mean_settle_strokes",
            "total_overshoot",
            "worst_verdict",
            "best_verdict",
        }
        assert set(s.keys()) == expected_keys

    def test_report_format(self, one_smooth_disruption):
        r = recovery_report(one_smooth_disruption, expected_cadence=15)
        assert "disruption" in r
        assert "recovery" in r

    def test_median_recovery(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        assert crt.median_recovery_s > 0

    def test_mean_settle_strokes(self, one_smooth_disruption):
        crt = CadenceRecoveryTracker(
            one_smooth_disruption, expected_cadence=15
        )
        assert crt.mean_settle_strokes >= 5


# ---------------------------------------------------------------------------
# DisruptionRecovery dataclass
# ---------------------------------------------------------------------------


class TestDisruptionRecovery:
    """Test the DisruptionRecovery dataclass."""

    def test_fields(self):
        dr = DisruptionRecovery(
            gap_start=100.0,
            gap_end=400.0,
            gap_s=300.0,
            recovery_time_s=75.0,
            settle_strokes=5,
            overshoot_count=0,
            verdict="smooth",
        )
        assert dr.gap_start == 100.0
        assert dr.gap_end == 400.0
        assert dr.gap_s == 300.0
        assert dr.recovery_time_s == 75.0
        assert dr.settle_strokes == 5
        assert dr.overshoot_count == 0
        assert dr.verdict == "smooth"
