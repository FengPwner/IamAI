"""Tests for tools/commit_rhythm_health.py — commit timing pattern analysis."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from commit_rhythm_health import (  # noqa: E402
    compute_intervals,
    extract_features,
    classify,
    health_score,
    analyze,
)


# ---------------------------------------------------------------------------
# compute_intervals
# ---------------------------------------------------------------------------


class TestComputeIntervals:
    def test_empty(self):
        assert compute_intervals([]) == []

    def test_single(self):
        assert compute_intervals([100]) == []

    def test_two(self):
        assert compute_intervals([200, 100]) == [100]

    def test_newest_first(self):
        """Timestamps arrive newest-first from git log; intervals are positive."""
        result = compute_intervals([300, 200, 100])
        assert result == [100, 100]

    def test_unsorted_still_works(self):
        """Even if input is jumbled, we sort internally."""
        result = compute_intervals([100, 300, 200])
        assert sorted(result) == [100, 100]

    def test_large_gap(self):
        result = compute_intervals([10000, 100])
        assert result == [9900]

    def test_same_timestamps(self):
        """Two commits at the same second → zero interval."""
        result = compute_intervals([500, 500])
        assert result == [0]

    def test_many(self):
        ts = [500, 400, 300, 200, 100]
        result = compute_intervals(ts)
        assert result == [100, 100, 100, 100]


# ---------------------------------------------------------------------------
# extract_features
# ---------------------------------------------------------------------------


class TestExtractFeatures:
    def test_empty_intervals(self):
        f = extract_features([])
        assert f["count"] == 0
        assert f["median_interval"] is None
        assert f["coefficient_of_variation"] is None

    def test_single_interval(self):
        f = extract_features([600])
        assert f["count"] == 1
        assert f["median_interval"] == 600
        assert f["coefficient_of_variation"] == 0.0  # no variance

    def test_uniform_intervals(self):
        """All intervals the same → CV = 0, no thrash, no stall."""
        f = extract_features([600, 600, 600, 600])
        assert f["coefficient_of_variation"] == 0.0
        assert f["thrash_ratio"] == 0.0
        assert f["stall_ratio"] == 0.0
        assert f["median_interval"] == 600.0

    def test_thrash_detected(self):
        """Intervals under the thrash threshold."""
        f = extract_features([10, 20, 30, 600, 600], thrash_threshold=60)
        assert f["thrash_ratio"] > 0
        assert f["thrash_ratio"] == pytest.approx(3 / 5)  # 3 out of 5

    def test_stall_detected(self):
        """Intervals over the stall threshold."""
        f = extract_features([600, 600, 3600, 600], stall_threshold=1800)
        assert f["stall_ratio"] == pytest.approx(1 / 4)

    def test_custom_thresholds(self):
        f = extract_features([100, 100, 100], thrash_threshold=200, stall_threshold=50)
        assert f["thrash_ratio"] == pytest.approx(1.0)  # all under 200
        assert f["stall_ratio"] == pytest.approx(1.0)  # all over 50

    def test_min_max(self):
        f = extract_features([10, 500, 3600])
        assert f["min_interval"] == 10
        assert f["max_interval"] == 3600

    def test_mean_and_median_differ(self):
        """Skewed distribution: mean > median."""
        f = extract_features([100, 100, 100, 10000])
        assert f["mean_interval"] > f["median_interval"]


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_unknown_when_no_data(self):
        f = extract_features([])
        assert classify(f) == "unknown"

    def test_steady(self):
        """Low CV, no thrash, no stall → steady."""
        f = extract_features([600, 600, 600, 600, 600])
        assert classify(f) == "steady"

    def test_irregular(self):
        """High CV but no dangerous thrash or stall."""
        f = extract_features([200, 400, 800, 1200, 1600])
        label = classify(f, cv_steady=0.3)
        assert label == "irregular"

    def test_thrashing(self):
        """Many short intervals → thrashing."""
        f = extract_features([5, 5, 5, 10, 600, 600], thrash_threshold=60)
        label = classify(f, thrash_danger=0.25)
        assert label == "thrashing"

    def test_stalled(self):
        """Many long intervals → stalled."""
        f = extract_features([3600, 3600, 600, 600], stall_threshold=1800)
        label = classify(f, stall_danger=0.25)
        assert label == "stalled"

    def test_erratic(self):
        """Both thrashing and stalling → erratic."""
        f = extract_features([5, 5, 5, 7200, 7200, 600], thrash_threshold=60, stall_threshold=1800)
        label = classify(f, thrash_danger=0.25, stall_danger=0.25)
        assert label == "erratic"

    def test_threshold_boundary_thrash(self):
        """Exactly at the thrash_danger boundary."""
        # 1 out of 4 = 0.25 → should be thrashing (>= threshold)
        f = extract_features([5, 600, 600, 600], thrash_threshold=60)
        label = classify(f, thrash_danger=0.25)
        assert label == "thrashing"

    def test_threshold_boundary_stall(self):
        """Exactly at the stall_danger boundary."""
        f = extract_features([3600, 600, 600, 600], stall_threshold=1800)
        label = classify(f, stall_danger=0.25)
        assert label == "stalled"

    def test_custom_cv_threshold(self):
        """With a very high CV threshold, even varied data looks steady."""
        f = extract_features([100, 500, 900])
        label = classify(f, cv_steady=5.0, thrash_danger=0.0, stall_danger=0.0)
        # With thrash/stall danger at 0.0, everything triggers both → erratic
        assert label == "erratic"


# ---------------------------------------------------------------------------
# health_score
# ---------------------------------------------------------------------------


class TestHealthScore:
    def test_unknown_is_zero(self):
        f = extract_features([])
        assert health_score(f, "unknown") == 0

    def test_steady_perfect(self):
        """Perfectly steady → 100."""
        f = extract_features([600, 600, 600, 600])
        label = classify(f)
        score = health_score(f, label)
        assert score == 100

    def test_steady_with_thrash_penalty(self):
        """Steady but with some thrash → less than 100."""
        f = extract_features([5, 600, 600, 600, 600, 600, 600, 600], thrash_threshold=60)
        # force steady label but with thrash_ratio > 0
        score = health_score(f, "steady")
        assert 70 <= score < 100

    def test_thrashing_low(self):
        f = extract_features([5, 5, 5, 5], thrash_threshold=60)
        label = classify(f)
        score = health_score(f, label)
        assert 0 <= score <= 40

    def test_stalled_low(self):
        f = extract_features([7200, 7200, 7200], stall_threshold=1800)
        label = classify(f)
        score = health_score(f, label)
        assert 0 <= score <= 40

    def test_erratic_very_low(self):
        f = extract_features([5, 5, 7200, 7200], thrash_threshold=60, stall_threshold=1800)
        label = classify(f)
        score = health_score(f, label)
        assert 0 <= score <= 20

    def test_irregular_moderate(self):
        f = extract_features([200, 400, 800, 1200])
        score = health_score(f, "irregular")
        assert 40 <= score <= 70

    def test_clamped_to_zero(self):
        """Even with absurd ratios, score never goes below 0."""
        f = {"count": 1, "coefficient_of_variation": 10.0,
             "thrash_ratio": 1.0, "stall_ratio": 1.0}
        score = health_score(f, "erratic")
        assert score >= 0

    def test_clamped_to_hundred(self):
        """Score never exceeds 100."""
        f = {"count": 5, "coefficient_of_variation": 0.0,
             "thrash_ratio": 0.0, "stall_ratio": 0.0}
        score = health_score(f, "steady")
        assert score <= 100

    def test_all_labels_produce_valid_scores(self):
        """Every label produces a score in [0, 100]."""
        f = {"count": 5, "coefficient_of_variation": 0.5,
             "thrash_ratio": 0.3, "stall_ratio": 0.3}
        for label in ["steady", "irregular", "thrashing", "stalled", "erratic", "unknown"]:
            score = health_score(f, label)
            assert 0 <= score <= 100, f"{label} produced score {score}"


# ---------------------------------------------------------------------------
# analyze (integration)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_nonexistent_repo(self):
        """Analyzing a bogus path returns unknown / 0 gracefully."""
        result = analyze(repo_path="/nonexistent/path/for/sure")
        assert result["label"] == "unknown"
        assert result["health"] == 0
        assert result["commits_analyzed"] == 0

    def test_real_repo(self):
        """Run against the actual repo we live in."""
        repo = str(Path(__file__).resolve().parent.parent)
        result = analyze(repo_path=repo, window=10)
        assert result["commits_analyzed"] > 0
        assert result["label"] in ("steady", "irregular", "thrashing", "stalled", "erratic", "unknown")
        assert 0 <= result["health"] <= 100
        assert result["features"]["count"] > 0

    def test_window_respected(self):
        """Analyzing with window=3 looks at most 3 commits."""
        repo = str(Path(__file__).resolve().parent.parent)
        result = analyze(repo_path=repo, window=3)
        assert result["commits_analyzed"] <= 3

    def test_custom_thresholds(self):
        """Custom thresholds propagate through the pipeline."""
        repo = str(Path(__file__).resolve().parent.parent)
        result = analyze(
            repo_path=repo,
            window=10,
            thrash_threshold=1,
            stall_threshold=2,
        )
        # With a 2-second stall threshold, most real commits look stalled.
        assert result["features"]["stall_ratio"] is not None

    def test_result_keys(self):
        result = analyze(repo_path="/nonexistent")
        assert "commits_analyzed" in result
        assert "features" in result
        assert "label" in result
        assert "health" in result


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_one_commit(self):
        """A single commit → no intervals → unknown."""
        # We can't inject timestamps directly through analyze(),
        # so test the pipeline components.
        intervals = compute_intervals([1000])
        assert intervals == []
        features = extract_features(intervals)
        assert classify(features) == "unknown"
        assert health_score(features, "unknown") == 0

    def test_zero_interval(self):
        """Two commits at the same second."""
        intervals = compute_intervals([500, 500])
        assert intervals == [0]
        features = extract_features(intervals, thrash_threshold=60)
        assert features["thrash_ratio"] == 1.0

    def test_very_large_intervals(self):
        intervals = [86400, 86400, 86400]  # one per day
        features = extract_features(intervals, stall_threshold=1800)
        assert features["stall_ratio"] == 1.0
        assert classify(features) == "stalled"

    def test_mixed_with_zero(self):
        intervals = [0, 0, 600, 600, 3600]
        features = extract_features(intervals, thrash_threshold=60, stall_threshold=1800)
        assert features["thrash_ratio"] > 0
        assert features["stall_ratio"] > 0

    def test_feature_count_matches_intervals(self):
        intervals = [100, 200, 300, 400]
        features = extract_features(intervals)
        assert features["count"] == len(intervals)

    def test_cv_zero_for_identical(self):
        features = extract_features([42, 42, 42, 42])
        assert features["coefficient_of_variation"] == 0.0

    def test_deterministic(self):
        """Same input always gives same output."""
        intervals = [100, 300, 500, 200, 400]
        f1 = extract_features(intervals)
        f2 = extract_features(intervals)
        assert f1 == f2
        l1 = classify(f1)
        l2 = classify(f2)
        assert l1 == l2
