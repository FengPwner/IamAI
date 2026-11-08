"""Tests for iamai.stroke_rhythm_monitor — rhythm health scoring.

The rhythm monitor is the caretaker's stethoscope: a single number
that says whether the writer's heartbeat is healthy.  These tests
ensure that number is trustworthy across normal, degraded, and
pathological inputs.
"""

import math
import time

import pytest

from iamai.stroke_rhythm_monitor import (
    StrokeRhythmMonitor,
    RhythmReport,
    rhythm_check,
    _cadence_component,
    _regularity_component,
    _freshness_component,
    _score_to_grade,
    _dominant_issue,
)


# ---------------------------------------------------------------------------
# Component tests
# ---------------------------------------------------------------------------


class TestCadenceComponent:
    def test_perfect_cadence(self):
        gaps = [15.0, 15.0, 15.0, 15.0]
        assert _cadence_component(15.0, gaps) == pytest.approx(1.0)

    def test_double_expected(self):
        # median 30s vs expected 15s → ratio=2 → score=0
        gaps = [30.0, 30.0, 30.0]
        assert _cadence_component(15.0, gaps) == pytest.approx(0.0)

    def test_half_expected(self):
        # median 7.5s vs expected 15s → ratio=0.5 → score=0.5
        gaps = [7.5, 7.5, 7.5]
        assert _cadence_component(15.0, gaps) == pytest.approx(0.5)

    def test_150_percent(self):
        # median 22.5s vs expected 15s → ratio=1.5 → score=0.5
        gaps = [22.5, 22.5, 22.5]
        assert _cadence_component(15.0, gaps) == pytest.approx(0.5)

    def test_empty_gaps(self):
        assert _cadence_component(15.0, []) == 0.0

    def test_zero_expected(self):
        assert _cadence_component(0, [15.0]) == 0.0

    def test_mixed_gaps(self):
        # median of [10, 15, 20] = 15 → perfect
        gaps = [10.0, 15.0, 20.0]
        assert _cadence_component(15.0, gaps) == pytest.approx(1.0)


class TestRegularityComponent:
    def test_perfectly_regular(self):
        gaps = [15.0, 15.0, 15.0, 15.0]
        assert _regularity_component(gaps) == pytest.approx(1.0)

    def test_single_gap(self):
        # single gap → trivially consistent
        assert _regularity_component([42.0]) == 1.0

    def test_empty(self):
        # no data → no regularity signal
        assert _regularity_component([]) == 0.0

    def test_high_variance(self):
        # CV = stdev([1, 100]) / mean([1, 100]) ≈ 70 / 50.5 ≈ 1.39
        # score = max(0, 1 - 1.39) = 0
        gaps = [1.0, 100.0]
        assert _regularity_component(gaps) == pytest.approx(0.0, abs=0.01)

    def test_moderate_variance(self):
        # gaps of 12, 15, 18 → mean=15, stdev=3, CV=0.2 → score=0.8
        gaps = [12.0, 15.0, 18.0]
        result = _regularity_component(gaps)
        assert 0.7 < result < 0.9

    def test_zero_mean(self):
        # all zero gaps → mean=0 → score=0
        gaps = [0.0, 0.0, 0.0]
        assert _regularity_component(gaps) == 0.0


class TestFreshnessComponent:
    def test_fresh(self):
        # last gap = expected → ratio=1 → score=1
        assert _freshness_component(15.0, 15.0) == 1.0

    def test_very_fresh(self):
        # last gap < expected → score=1
        assert _freshness_component(15.0, 5.0) == 1.0

    def test_stale_10x(self):
        # last gap = 150s, expected 15s → ratio=10 → log10(10)=1 → score=0
        assert _freshness_component(15.0, 150.0) == pytest.approx(0.0)

    def test_moderately_stale(self):
        # last gap = 47.1s (~3.14× expected) → log10(3.14)≈0.497 → score≈0.503
        result = _freshness_component(15.0, 47.1)
        assert 0.4 < result < 0.6

    def test_zero_expected(self):
        assert _freshness_component(0, 15.0) == 0.0

    def test_negative_last_gap(self):
        assert _freshness_component(15.0, -1.0) == 0.0


class TestScoreToGrade:
    def test_a(self):
        assert _score_to_grade(0.95) == "A"
        assert _score_to_grade(0.90) == "A"

    def test_b(self):
        assert _score_to_grade(0.89) == "B"
        assert _score_to_grade(0.75) == "B"

    def test_c(self):
        assert _score_to_grade(0.74) == "C"
        assert _score_to_grade(0.55) == "C"

    def test_d(self):
        assert _score_to_grade(0.54) == "D"
        assert _score_to_grade(0.35) == "D"

    def test_f(self):
        assert _score_to_grade(0.34) == "F"
        assert _score_to_grade(0.0) == "F"

    def test_perfect(self):
        assert _score_to_grade(1.0) == "A"


class TestDominantIssue:
    def test_all_healthy(self):
        assert _dominant_issue(0.9, 0.9, 0.9) is None

    def test_cadence_drift(self):
        assert _dominant_issue(0.5, 0.9, 0.9) == "cadence_drift"

    def test_irregularity(self):
        assert _dominant_issue(0.9, 0.4, 0.9) == "irregularity"

    def test_staleness(self):
        assert _dominant_issue(0.9, 0.9, 0.3) == "staleness"

    def test_multiple_weak(self):
        # weakest wins
        assert _dominant_issue(0.6, 0.5, 0.7) == "irregularity"

    def test_boundary(self):
        # exactly 0.8 → no issue
        assert _dominant_issue(0.8, 0.8, 0.8) is None


# ---------------------------------------------------------------------------
# Integration tests — StrokeRhythmMonitor
# ---------------------------------------------------------------------------


class TestStrokeRhythmMonitor:
    def _make_timestamps(self, count, interval=15.0, start=1000.0):
        return [start + i * interval for i in range(count)]

    def test_perfect_rhythm(self):
        ts = self._make_timestamps(50, interval=15.0)
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check(ts)

        assert report.rhythm_grade == "A"
        assert report.rhythm_score > 0.9
        assert report.cadence_component == pytest.approx(1.0)
        assert report.regularity_component == pytest.approx(1.0)
        assert report.freshness_component == pytest.approx(1.0)
        assert report.dominant_issue is None
        assert report.sample_count == 49

    def test_slow_writer(self):
        # writer at 30s cadence vs expected 15s
        ts = self._make_timestamps(50, interval=30.0)
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check(ts)

        # cadence_component: ratio=2 → 0.0
        assert report.cadence_component == pytest.approx(0.0)
        # freshness survives at ~0.7 (30/15=2, log10(2)≈0.3), regularity=1.0
        # total ≈ 0.35 + 0.175 ≈ 0.525
        assert report.rhythm_score < 0.6
        assert report.dominant_issue == "cadence_drift"

    def test_irregular_writer(self):
        # alternating 5s and 25s gaps → median=15 but high variance
        base = 1000.0
        ts = [base]
        for i in range(50):
            ts.append(ts[-1] + (5.0 if i % 2 == 0 else 25.0))
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check(ts)

        # cadence is fine (median ≈ 15), but regularity is poor
        assert report.cadence_component > 0.8
        assert report.regularity_component < 0.5
        assert report.dominant_issue == "irregularity"

    def test_stale_writer(self):
        # Uniform slow cadence (45s) → cadence degrades moderately,
        # freshness degrades more.  cadence_drift wins the race.
        ts = self._make_timestamps(50, interval=45.0)  # 3× expected
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check(ts)

        # ratio=3 → cadence = max(0, 1-(3-1)) = 0.0
        assert report.cadence_component == pytest.approx(0.0)
        # freshness: log10(3)≈0.477 → ~0.52
        assert 0.4 < report.freshness_component < 0.6
        # regularity perfect (all gaps identical)
        assert report.regularity_component == pytest.approx(1.0)
        assert report.dominant_issue == "cadence_drift"

    def test_empty_input(self):
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check([])

        assert report.rhythm_score == 0.0
        assert report.rhythm_grade == "F"
        assert report.sample_count == 0
        assert report.last_gap_s == -1.0

    def test_single_timestamp(self):
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0)
        report = monitor.check([1000.0])

        assert report.sample_count == 0
        assert report.rhythm_grade == "F"

    def test_window_size(self):
        # 200 timestamps but window=50 → only last 50 gaps used
        ts = self._make_timestamps(200, interval=15.0)
        monitor = StrokeRhythmMonitor(expected_cadence_s=15.0, window_size=50)
        report = monitor.check(ts)

        assert report.sample_count == 50

    def test_is_healthy(self):
        ts = self._make_timestamps(50, interval=15.0)
        report = StrokeRhythmMonitor(expected_cadence_s=15.0).check(ts)
        assert report.is_healthy() is True

    def test_is_unhealthy(self):
        ts = self._make_timestamps(50, interval=120.0)
        report = StrokeRhythmMonitor(expected_cadence_s=15.0).check(ts)
        assert report.is_healthy() is False


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


class TestRhythmCheck:
    def test_basic(self):
        ts = [1000.0 + i * 15.0 for i in range(30)]
        report = rhythm_check(ts, expected_cadence_s=15.0)
        assert isinstance(report, RhythmReport)
        assert report.rhythm_grade == "A"

    def test_custom_window(self):
        ts = [1000.0 + i * 15.0 for i in range(30)]
        report = rhythm_check(ts, expected_cadence_s=15.0, window_size=10)
        assert report.sample_count == 10


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


class TestRhythmReport:
    def test_frozen(self):
        report = RhythmReport(
            rhythm_score=0.9,
            rhythm_grade="A",
            cadence_component=1.0,
            regularity_component=0.9,
            freshness_component=0.8,
            median_gap_s=15.0,
            p95_gap_s=18.0,
            last_gap_s=15.0,
            sample_count=49,
            dominant_issue=None,
        )
        with pytest.raises(AttributeError):
            report.rhythm_score = 0.5  # type: ignore[misc]

    def test_is_healthy_grades(self):
        base = dict(
            cadence_component=1.0,
            regularity_component=1.0,
            freshness_component=1.0,
            median_gap_s=15.0,
            p95_gap_s=18.0,
            last_gap_s=15.0,
            sample_count=49,
            dominant_issue=None,
        )
        assert RhythmReport(rhythm_score=0.95, rhythm_grade="A", **base).is_healthy()
        assert RhythmReport(rhythm_score=0.80, rhythm_grade="B", **base).is_healthy()
        assert not RhythmReport(rhythm_score=0.60, rhythm_grade="C", **base).is_healthy()
        assert not RhythmReport(rhythm_score=0.40, rhythm_grade="D", **base).is_healthy()
        assert not RhythmReport(rhythm_score=0.10, rhythm_grade="F", **base).is_healthy()
