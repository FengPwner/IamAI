"""Tests for tools/push_gap_analyzer.py — push timing gap analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from push_gap_analyzer import (  # noqa: E402
    compute_gaps,
    classify_trend,
    classify_pattern,
    health_score,
    analyze,
)


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------


class TestComputeGaps:
    def test_empty(self):
        assert compute_gaps([]) == []

    def test_single(self):
        assert compute_gaps([1000.0]) == []

    def test_two(self):
        assert compute_gaps([1000.0, 1060.0]) == [60.0]

    def test_multiple(self):
        ts = [0.0, 10.0, 30.0, 60.0]
        assert compute_gaps(ts) == [10.0, 20.0, 30.0]

    def test_negative_gaps_skipped(self):
        """Clock going backwards should be silently dropped."""
        ts = [100.0, 50.0, 200.0]
        gaps = compute_gaps(ts)
        assert gaps == [150.0]

    def test_zero_gaps_skipped(self):
        """Duplicate timestamps produce no gap entry."""
        ts = [100.0, 100.0, 200.0]
        gaps = compute_gaps(ts)
        assert gaps == [100.0]


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------


class TestClassifyTrend:
    def test_flat(self):
        gaps = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        assert classify_trend(gaps) == "flat"

    def test_increasing(self):
        gaps = [10.0, 10.0, 10.0, 100.0, 100.0, 100.0]
        assert classify_trend(gaps) == "increasing"

    def test_decreasing(self):
        gaps = [100.0, 100.0, 100.0, 10.0, 10.0, 10.0]
        assert classify_trend(gaps) == "decreasing"

    def test_insufficient_data(self):
        assert classify_trend([10.0, 20.0]) == "flat"
        assert classify_trend([]) == "flat"

    def test_three_items(self):
        """Three gaps is still 'flat' (needs ≥4)."""
        assert classify_trend([10.0, 20.0, 30.0]) == "flat"

    def test_first_half_zero(self):
        """Edge case: all first-half gaps are zero."""
        gaps = [0.0, 0.0, 50.0, 50.0]
        # first_half mean = 0 → returns 'increasing' if second_half > 0
        assert classify_trend(gaps) == "increasing"

    def test_all_zero(self):
        gaps = [0.0, 0.0, 0.0, 0.0]
        assert classify_trend(gaps) == "flat"


# ---------------------------------------------------------------------------
# classify_pattern
# ---------------------------------------------------------------------------


class TestClassifyPattern:
    def test_steady(self):
        gaps = [100.0, 100.0, 100.0, 100.0, 100.0]
        assert classify_pattern(gaps) == "steady"

    def test_bursty(self):
        gaps = [10.0, 100.0, 20.0, 80.0, 15.0, 90.0]
        assert classify_pattern(gaps) in ("bursty", "erratic")

    def test_erratic(self):
        # Extremely high variance: mostly tiny with one massive gap
        gaps = [1.0, 1.0, 1.0, 10000.0]
        assert classify_pattern(gaps) == "erratic"

    def test_unknown_single(self):
        assert classify_pattern([100.0]) == "unknown"

    def test_unknown_empty(self):
        assert classify_pattern([]) == "unknown"

    def test_steady_with_minor_jitter(self):
        """Small jitter around the mean should still be steady."""
        gaps = [100.0, 102.0, 98.0, 101.0, 99.0]
        assert classify_pattern(gaps) == "steady"


# ---------------------------------------------------------------------------
# health_score
# ---------------------------------------------------------------------------


class TestHealthScore:
    def test_excellent(self):
        """10+ pushes, steady rhythm, flat trend → high score."""
        gaps = [600.0] * 12  # every 10 min, 12 times
        score = health_score(gaps, 13, "flat", 24)
        # 40 (count) + 20 (steady) + 20 (flat) = 80
        # max_gap = 600s = 0.167h → -1 (int(1.67)) → 79
        assert 70 <= score <= 100

    def test_zero_pushes(self):
        score = health_score([], 0, "flat", 24)
        assert score == 0

    def test_few_pushes(self):
        gaps = [3600.0, 3600.0]
        score = health_score(gaps, 3, "flat", 24)
        assert 0 <= score <= 50

    def test_long_gap_penalty(self):
        """A single massive gap should heavily penalize."""
        gaps = [86400.0] * 5  # 24h gaps
        score = health_score(gaps, 6, "flat", 24)
        # 20 (≥5 pushes) + 20 (steady) + 20 (flat) = 60
        # max_gap = 86400s = 24h → -40 (capped) → 20
        assert score <= 30

    def test_score_bounds(self):
        """Score is always within [0, 100]."""
        for count in range(0, 20):
            gaps = [float(i * 100) for i in range(max(count - 1, 0))]
            score = health_score(gaps, count, "increasing", 24)
            assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# analyze (integration — may return empty on CI without reflog)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_returns_dict(self):
        result = analyze()
        assert isinstance(result, dict)
        assert "push_count" in result
        assert "trend" in result
        assert "pattern" in result
        assert "health_score" in result
        assert "window_hours" in result

    def test_score_in_range(self):
        result = analyze()
        assert 0 <= result["health_score"] <= 100

    def test_window_propagated(self):
        result = analyze(hours=48)
        assert result["window_hours"] == 48

    def test_gaps_present_when_count_sufficient(self):
        result = analyze()
        if result["push_count"] >= 2:
            assert "gaps_s" in result
            assert isinstance(result["gaps_s"], list)
