"""Tests for iamai.commit_pipeline_latency — stroke-to-commit latency tracking.

Covers: pairing logic, latency statistics (median/p95/max/mean),
orphan detection, verdict tiers, empty/malformed inputs,
the convenience wrapper, and edge cases (zero-gap, negative gap,
multiple commits consuming from one stroke batch).
"""

from __future__ import annotations

import pytest

from iamai.commit_pipeline_latency import (
    HEALTHY_P95_S,
    WARN_P95_S,
    PipelineLatency,
    latency_from_epochs,
    pair,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = 1_696_636_800.0  # arbitrary epoch anchor


def _strokes(*offsets: float) -> list[dict]:
    """Build stroke dicts from relative offsets (seconds from BASE)."""
    return [{"at": BASE + o} for o in offsets]


def _commit(offset: float, covered: int = 0) -> dict:
    """Build a commit dict from a relative offset."""
    return {"at": BASE + offset, "strokes_covered": covered}


# ---------------------------------------------------------------------------
# Basic pairing
# ---------------------------------------------------------------------------

class TestPairing:
    def test_empty_strokes(self):
        result = pair([], [_commit(100, 0)])
        assert result.latencies == []
        assert result.orphan_count == 0
        assert result.stroke_count == 0

    def test_empty_commits(self):
        strokes = _strokes(0, 15, 30)
        result = pair(strokes, [])
        assert result.latencies == []
        assert result.orphan_count == 3

    def test_both_empty(self):
        result = pair([], [])
        assert result.latencies == []
        assert result.orphan_count == 0
        assert result.stroke_count == 0

    def test_single_stroke_single_commit(self):
        strokes = _strokes(0)
        commits = [_commit(60, 1)]
        result = pair(strokes, commits)
        assert result.latencies == [60.0]
        assert result.orphan_count == 0

    def test_multiple_strokes_one_commit(self):
        strokes = _strokes(0, 15, 30, 45)
        commits = [_commit(60, 4)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 4
        assert result.latencies[0] == 60.0   # stroke at +0 → commit at +60
        assert result.latencies[1] == 45.0   # stroke at +15
        assert result.latencies[2] == 30.0   # stroke at +30
        assert result.latencies[3] == 15.0   # stroke at +45
        assert result.orphan_count == 0

    def test_multiple_commits(self):
        strokes = _strokes(0, 15, 30, 45, 60, 75)
        commits = [_commit(30, 3), _commit(90, 3)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 6
        assert result.orphan_count == 0

    def test_zero_latency(self):
        """Stroke and commit at exactly the same timestamp."""
        strokes = _strokes(50)
        commits = [_commit(50, 1)]
        result = pair(strokes, commits)
        assert result.latencies == [0.0]

    def test_negative_gap_clamped_to_zero(self):
        """Commit timestamp before stroke timestamp (clock skew) → 0."""
        strokes = _strokes(100)
        commits = [_commit(90, 1)]
        result = pair(strokes, commits)
        # Stroke at +100 > commit at +90, so stroke is NOT consumed
        assert result.orphan_count == 1
        assert result.latencies == []


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

class TestOrphans:
    def test_all_orphaned(self):
        """All strokes after the last commit."""
        strokes = _strokes(100, 115, 130)
        commits = [_commit(50, 0)]
        result = pair(strokes, commits)
        assert result.orphan_count == 3
        assert result.latencies == []

    def test_partial_orphans(self):
        strokes = _strokes(0, 15, 30, 100, 115)
        commits = [_commit(45, 3)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 3
        assert result.orphan_count == 2

    def test_orphan_count_matches_unconsumed(self):
        strokes = _strokes(*range(0, 200, 15))  # 14 strokes
        commits = [_commit(60, 5), _commit(120, 4)]
        result = pair(strokes, commits)
        assert result.orphan_count == 14 - len(result.latencies)


# ---------------------------------------------------------------------------
# Latency statistics
# ---------------------------------------------------------------------------

class TestStatistics:
    def test_median(self):
        result = PipelineLatency(latencies=[10, 20, 30, 40, 50])
        assert result.median_latency_s == 30.0

    def test_p95(self):
        # 20 values: 10, 20, ..., 200
        vals = [i * 10 for i in range(1, 21)]
        result = PipelineLatency(latencies=vals)
        # 95th percentile index = int(20 * 95 / 100) = 19 → vals[19] = 200
        assert result.p95_latency_s == 200.0

    def test_max(self):
        result = PipelineLatency(latencies=[5, 500, 100])
        assert result.max_latency_s == 500.0

    def test_mean(self):
        result = PipelineLatency(latencies=[10, 20, 30])
        assert result.mean_latency_s == 20.0

    def test_empty_stats(self):
        result = PipelineLatency()
        assert result.median_latency_s == 0.0
        assert result.p95_latency_s == 0.0
        assert result.max_latency_s == 0.0
        assert result.mean_latency_s == 0.0


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

class TestVerdicts:
    def test_healthy(self):
        """All latencies well under HEALTHY_P95_S."""
        result = PipelineLatency(latencies=[10, 20, 30, 40, 50])
        assert result.healthy is True
        assert result.verdict == "healthy"

    def test_degraded(self):
        """P95 between HEALTHY and WARN thresholds."""
        # p95 of these 20 values should be > 900 but < 1800
        vals = [100] * 18 + [1000, 1200]
        result = PipelineLatency(latencies=vals)
        assert result.healthy is False
        assert result.verdict == "degraded"

    def test_broken(self):
        """P95 above WARN_P95_S."""
        vals = [100] * 18 + [2000, 3000]
        result = PipelineLatency(latencies=vals)
        assert result.healthy is False
        assert result.verdict == "broken"

    def test_no_data_verdict(self):
        result = PipelineLatency()
        assert result.healthy is False
        assert result.verdict == "no-data"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_no_data(self):
        result = PipelineLatency(stroke_count=5, commit_count=2, orphan_count=5)
        s = result.summary()
        assert "no paired data" in s
        assert "5 strokes" in s
        assert "5 orphaned" in s

    def test_summary_with_data(self):
        result = PipelineLatency(
            latencies=[10, 20, 30],
            stroke_count=3,
            commit_count=1,
            orphan_count=0,
        )
        s = result.summary()
        assert "healthy" in s
        assert "median" in s
        assert "p95" in s


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

class TestConvenienceWrapper:
    def test_latency_from_epochs_basic(self):
        stroke_ts = [BASE, BASE + 15, BASE + 30, BASE + 45]
        commit_ts = [BASE + 60]
        result = latency_from_epochs(stroke_ts, commit_ts, strokes_per_commit=4)
        assert len(result.latencies) == 4
        assert result.orphan_count == 0

    def test_latency_from_epochs_with_orphans(self):
        stroke_ts = [BASE, BASE + 15, BASE + 30, BASE + 100]
        commit_ts = [BASE + 60]
        result = latency_from_epochs(stroke_ts, commit_ts, strokes_per_commit=3)
        assert len(result.latencies) == 3
        assert result.orphan_count == 1

    def test_latency_from_epochs_custom_threshold(self):
        stroke_ts = [BASE, BASE + 15]
        commit_ts = [BASE + 120]
        result = latency_from_epochs(
            stroke_ts, commit_ts,
            strokes_per_commit=2,
            threshold_s=200.0,
        )
        assert result.threshold_s == 200.0

    def test_latency_from_epochs_empty(self):
        result = latency_from_epochs([], [])
        assert result.latencies == []
        assert result.stroke_count == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unsorted_strokes_handled(self):
        """Strokes given out of order should still pair correctly."""
        strokes = _strokes(30, 0, 45, 15)
        commits = [_commit(60, 4)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 4
        assert result.orphan_count == 0

    def test_unsorted_commits_handled(self):
        """Commits given out of order should still pair correctly."""
        strokes = _strokes(0, 15, 60, 75)
        commits = [_commit(90, 2), _commit(30, 2)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 4

    def test_commit_with_zero_covered_consumes_all_pending(self):
        """strokes_covered=0 means 'consume everything pending'."""
        strokes = _strokes(0, 15, 30)
        commits = [_commit(45, 0)]
        result = pair(strokes, commits)
        assert len(result.latencies) == 3
        assert result.orphan_count == 0

    def test_large_latency_values(self):
        """Handles very large timestamps without overflow."""
        strokes = [{"at": 1e12}]
        commits = [{"at": 1e12 + 600, "strokes_covered": 1}]
        result = pair(strokes, commits)
        assert result.latencies == [600.0]

    def test_frozen_dataclass(self):
        """PipelineLatency should be immutable."""
        result = PipelineLatency(latencies=[10, 20])
        with pytest.raises(AttributeError):
            result.latencies = [30]  # type: ignore[misc]
