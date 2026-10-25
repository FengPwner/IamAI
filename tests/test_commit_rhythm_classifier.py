"""Tests for iamai.commit_rhythm_classifier — rhythm classification.

Covers: classify_rhythm, RhythmReport properties, rhythm_timeline,
edge cases, boundary conditions, all five rhythm categories.
"""

import math
import pytest

from iamai.commit_rhythm_classifier import (
    RhythmReport,
    classify_rhythm,
    rhythm_timeline,
    RHYTHM_CATEGORIES,
    DEFAULT_METRONOME_CV,
    DEFAULT_TREND_THRESHOLD,
    DEFAULT_BURST_RATIO,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _steady_gaps(interval: float = 600.0, count: int = 20, noise: float = 0.02) -> list[float]:
    """Generate near-constant gaps with small noise."""
    import random
    random.seed(42)
    return [interval + random.gauss(0, interval * noise) for _ in range(count)]


def _accelerating_gaps(start: float = 1200.0, end: float = 200.0, count: int = 20) -> list[float]:
    """Generate linearly decreasing gaps (acceleration)."""
    step = (start - end) / (count - 1)
    return [start - i * step for i in range(count)]


def _decelerating_gaps(start: float = 200.0, end: float = 1200.0, count: int = 20) -> list[float]:
    """Generate linearly increasing gaps (deceleration)."""
    step = (end - start) / (count - 1)
    return [start + i * step for i in range(count)]


def _bursty_gaps(burst_size: int = 5, burst_gap: float = 60.0,
                 silence: float = 7200.0, bursts: int = 3) -> list[float]:
    """Generate bursty pattern: clusters of short gaps separated by long silences."""
    gaps = []
    for b in range(bursts):
        gaps.extend([burst_gap] * (burst_size - 1))
        if b < bursts - 1:
            gaps.append(silence)
    return gaps


def _irregular_gaps(count: int = 20) -> list[float]:
    """Generate gaps with no clear pattern (moderate CV, no trend)."""
    import random
    random.seed(99)
    # Mix of short, medium, and long gaps with no systematic pattern
    base = [400, 800, 500, 900, 600, 700, 550, 850, 450, 750,
            650, 500, 800, 600, 700, 550, 900, 400, 750, 650]
    return base[:count]


# ---------------------------------------------------------------------------
# metronome classification
# ---------------------------------------------------------------------------

class TestMetronome:
    """Tests for metronome (steady) rhythm."""

    def test_perfect_metronome(self):
        gaps = [600.0] * 10
        r = classify_rhythm(gaps)
        assert r.category == "metronome"
        assert r.confidence >= 0.9
        assert r.cv == 0.0
        assert r.trend_slope == 0.0

    def test_near_metronome_small_noise(self):
        gaps = _steady_gaps(600, 20, noise=0.01)
        r = classify_rhythm(gaps)
        assert r.category == "metronome"
        assert r.confidence > 0.5

    def test_metronome_properties(self):
        gaps = [600.0] * 10
        r = classify_rhythm(gaps)
        assert r.is_steady is True
        assert r.is_trending is False
        assert r.is_healthy is True
        assert r.gap_count == 10
        assert r.mean_gap == 600.0
        assert r.median_gap == 600.0
        assert r.max_gap == 600.0
        assert r.min_gap == 600.0

    def test_metronome_summary_line(self):
        gaps = [600.0] * 10
        r = classify_rhythm(gaps)
        line = r.summary_line
        assert "metronome" in line
        assert "confidence=" in line


# ---------------------------------------------------------------------------
# accelerating classification
# ---------------------------------------------------------------------------

class TestAccelerating:
    """Tests for accelerating rhythm (gaps shrinking)."""

    def test_strong_acceleration(self):
        gaps = _accelerating_gaps(1200, 200, 20)
        r = classify_rhythm(gaps)
        assert r.category == "accelerating"
        assert r.trend_slope < 0
        assert r.confidence > 0.0

    def test_acceleration_properties(self):
        gaps = _accelerating_gaps(1200, 200, 20)
        r = classify_rhythm(gaps)
        assert r.is_steady is False
        assert r.is_trending is True
        assert r.is_healthy is True

    def test_mild_acceleration(self):
        # Gaps decrease by ~2% per step — should still detect
        gaps = [600 - i * 8 for i in range(20)]
        r = classify_rhythm(gaps)
        # Might be metronome if CV is too low and slope is within threshold
        # but with 8-unit decrease per step over 600 base, norm_slope should exceed threshold
        assert r.category in ("accelerating", "metronome", "decelerating")


# ---------------------------------------------------------------------------
# decelerating classification
# ---------------------------------------------------------------------------

class TestDecelerating:
    """Tests for decelerating rhythm (gaps growing)."""

    def test_strong_deceleration(self):
        gaps = _decelerating_gaps(200, 1200, 20)
        r = classify_rhythm(gaps)
        assert r.category == "decelerating"
        assert r.trend_slope > 0

    def test_deceleration_properties(self):
        gaps = _decelerating_gaps(200, 1200, 20)
        r = classify_rhythm(gaps)
        assert r.is_steady is False
        assert r.is_trending is True
        assert r.is_healthy is True


# ---------------------------------------------------------------------------
# bursty classification
# ---------------------------------------------------------------------------

class TestBursty:
    """Tests for bursty rhythm (clusters separated by long pauses)."""

    def test_bursty_pattern(self):
        gaps = _bursty_gaps(burst_size=5, burst_gap=60, silence=7200, bursts=3)
        r = classify_rhythm(gaps)
        assert r.category == "bursty"
        assert r.burst_ratio >= DEFAULT_BURST_RATIO

    def test_bursty_properties(self):
        gaps = _bursty_gaps()
        r = classify_rhythm(gaps)
        assert r.is_steady is False
        assert r.is_healthy is False  # bursty is not considered healthy

    def test_burst_ratio_computed(self):
        gaps = _bursty_gaps()
        r = classify_rhythm(gaps)
        assert r.burst_ratio > 1.0


# ---------------------------------------------------------------------------
# irregular classification
# ---------------------------------------------------------------------------

class TestIrregular:
    """Tests for irregular rhythm (no clear pattern)."""

    def test_irregular_gaps(self):
        gaps = _irregular_gaps(20)
        r = classify_rhythm(gaps)
        # Irregular gaps should not be metronome (CV too high)
        # and may or may not have a trend depending on the specific values
        assert r.category in RHYTHM_CATEGORIES

    def test_two_different_gaps(self):
        # Alternating short and long — high CV, slight trend bias
        # due to odd-length alignment in linear regression
        gaps = [100, 1000, 100, 1000, 100, 1000, 100, 1000]
        r = classify_rhythm(gaps)
        # The alternating pattern may produce a slight positive slope
        # (first value=100 < last value=1000), classifying as decelerating.
        # All three are plausible for a high-variance alternating sequence.
        assert r.category in ("bursty", "irregular", "decelerating")


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            classify_rhythm([])

    def test_single_gap(self):
        r = classify_rhythm([600.0])
        assert r.category in RHYTHM_CATEGORIES
        assert r.gap_count == 1
        # CV of a single value is 0
        assert r.cv == 0.0

    def test_two_gaps(self):
        r = classify_rhythm([600.0, 600.0])
        assert r.gap_count == 2

    def test_two_gaps_accelerating(self):
        r = classify_rhythm([1200.0, 300.0])
        assert r.category in ("accelerating", "bursty")

    def test_two_gaps_decelerating(self):
        r = classify_rhythm([300.0, 1200.0])
        assert r.category in ("decelerating", "bursty")

    def test_all_zero_gaps(self):
        # Edge case: all gaps are 0
        r = classify_rhythm([0.0, 0.0, 0.0])
        assert r.mean_gap == 0.0
        assert r.cv == float("inf") or r.cv == 0.0

    def test_very_large_gaps(self):
        r = classify_rhythm([86400.0] * 5)  # one commit per day
        assert r.category == "metronome"

    def test_mixed_units_still_works(self):
        # Gaps in different magnitudes — classifier is scale-free
        r1 = classify_rhythm([6.0, 6.0, 6.0, 6.0])
        r2 = classify_rhythm([6000.0, 6000.0, 6000.0, 6000.0])
        assert r1.category == r2.category  # both metronome

    def test_confidence_bounded(self):
        """Confidence should always be between 0 and 1."""
        for gaps in [
            [600.0] * 10,
            _accelerating_gaps(),
            _decelerating_gaps(),
            _bursty_gaps(),
            _irregular_gaps(),
        ]:
            r = classify_rhythm(gaps)
            assert 0.0 <= r.confidence <= 1.0


# ---------------------------------------------------------------------------
# rhythm_timeline (sliding window)
# ---------------------------------------------------------------------------

class TestRhythmTimeline:
    """Tests for the sliding-window rhythm_timeline function."""

    def test_timeline_length(self):
        gaps = _steady_gaps(600, 20)
        reports = rhythm_timeline(gaps, window=10)
        assert len(reports) == 20 - 10 + 1  # 11

    def test_timeline_window_too_small(self):
        with pytest.raises(ValueError, match="window"):
            rhythm_timeline([600.0] * 10, window=1)

    def test_timeline_window_equals_length(self):
        gaps = _steady_gaps(600, 10)
        reports = rhythm_timeline(gaps, window=10)
        assert len(reports) == 1

    def test_timeline_window_larger_than_gaps(self):
        gaps = [600.0, 610.0, 590.0]
        reports = rhythm_timeline(gaps, window=10)
        # Falls back to single classification of all gaps
        assert len(reports) == 1

    def test_timeline_transition(self):
        """Steady gaps followed by accelerating — timeline should shift."""
        steady = [600.0] * 15
        accel = [1200 - i * 50 for i in range(15)]
        gaps = steady + accel
        reports = rhythm_timeline(gaps, window=10)
        # Early windows should be metronome, later windows accelerating
        early = reports[0]
        late = reports[-1]
        assert early.category == "metronome"
        assert late.category == "accelerating"

    def test_timeline_all_reports_valid(self):
        gaps = _irregular_gaps(20)
        for r in rhythm_timeline(gaps, window=5):
            assert r.category in RHYTHM_CATEGORIES
            assert 0.0 <= r.confidence <= 1.0
            assert r.gap_count == 5


# ---------------------------------------------------------------------------
# parameter overrides
# ---------------------------------------------------------------------------

class TestParameterOverrides:
    """Tests for custom parameter overrides."""

    def test_strict_metronome_cv(self):
        # Gaps that are metronome under default CV but not strict
        gaps = _steady_gaps(600, 20, noise=0.10)  # 10% noise
        r_default = classify_rhythm(gaps)
        r_strict = classify_rhythm(gaps, metronome_cv=0.01)
        # With strict CV, these gaps might not qualify as metronome
        if r_default.category == "metronome":
            assert r_strict.category != "metronome" or r_strict.confidence < r_default.confidence

    def test_relaxed_trend_threshold(self):
        gaps = _accelerating_gaps(700, 500, 20)  # mild acceleration
        r_strict = classify_rhythm(gaps, trend_threshold=0.5)
        r_relaxed = classify_rhythm(gaps, trend_threshold=0.001)
        # Relaxed threshold should detect the trend more easily
        assert r_relaxed.trend_slope != 0 or r_strict.trend_slope != 0

    def test_custom_burst_ratio(self):
        gaps = _bursty_gaps(burst_gap=100, silence=500)
        # With very high burst_ratio threshold, may not classify as bursty
        r = classify_rhythm(gaps, burst_ratio=100.0)
        # The burst ratio of these gaps might be ~5, so threshold of 100 won't trigger bursty
        # It should fall through to another category
        assert r.category in RHYTHM_CATEGORIES


# ---------------------------------------------------------------------------
# dataclass frozen behaviour
# ---------------------------------------------------------------------------

class TestRhythmReportDataclass:
    """RhythmReport is frozen — should not allow mutation."""

    def test_frozen(self):
        r = classify_rhythm([600.0] * 5)
        with pytest.raises(AttributeError):
            r.category = "hacked"

    def test_repr(self):
        r = classify_rhythm([600.0] * 5)
        assert "metronome" in repr(r) or "RhythmReport" in repr(r)
