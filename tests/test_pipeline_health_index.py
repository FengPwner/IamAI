"""Tests for iamai.pipeline_health_index."""

from __future__ import annotations

import pytest

from iamai.pipeline_health_index import (
    PipelineHealthIndex,
    _linear_score,
    _verdict,
    WEIGHTS,
)


# ---------------------------------------------------------------------------
# _linear_score
# ---------------------------------------------------------------------------

class TestLinearScore:
    def test_at_perfect(self):
        assert _linear_score(30, 30, 600) == 1.0

    def test_below_perfect(self):
        assert _linear_score(0, 30, 600) == 1.0

    def test_at_zero(self):
        assert _linear_score(600, 30, 600) == 0.0

    def test_above_zero(self):
        assert _linear_score(1000, 30, 600) == 0.0

    def test_midpoint(self):
        score = _linear_score(315, 30, 600)  # midpoint = 315
        assert 0.49 <= score <= 0.51

    def test_negative_value(self):
        assert _linear_score(-10, 30, 600) == 1.0

    def test_equal_perfect_and_zero(self):
        # degenerate: perfect == zero → anything at or below is 1.0
        assert _linear_score(50, 50, 50) == 1.0
        assert _linear_score(51, 50, 50) == 0.0


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------

class TestVerdict:
    @pytest.mark.parametrize("idx,expected", [
        (1.0, "healthy"),
        (0.80, "healthy"),
        (0.79, "warn"),
        (0.50, "warn"),
        (0.49, "critical"),
        (0.20, "critical"),
        (0.19, "down"),
        (0.0, "down"),
    ])
    def test_boundaries(self, idx, expected):
        assert _verdict(idx) == expected


# ---------------------------------------------------------------------------
# WEIGHTS
# ---------------------------------------------------------------------------

class TestWeights:
    def test_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_all_positive(self):
        for v in WEIGHTS.values():
            assert v > 0


# ---------------------------------------------------------------------------
# PipelineHealthIndex.compute
# ---------------------------------------------------------------------------

class TestCompute:
    def test_perfect_health(self):
        idx = PipelineHealthIndex()
        r = idx.compute(
            writer_freshness_s=5,
            commit_freshness_s=30,
            uncommitted_files=0,
            unpushed_commits=0,
        )
        assert r["index"] == 1.0
        assert r["verdict"] == "healthy"

    def test_all_zero(self):
        idx = PipelineHealthIndex()
        r = idx.compute(
            writer_freshness_s=9999,
            commit_freshness_s=9999,
            uncommitted_files=100,
            unpushed_commits=50,
        )
        assert r["index"] == 0.0
        assert r["verdict"] == "down"

    def test_mixed_signals(self):
        idx = PipelineHealthIndex()
        r = idx.compute(
            writer_freshness_s=15,     # perfect
            commit_freshness_s=600,    # mid-range
            uncommitted_files=10,      # half
            unpushed_commits=0,        # perfect
        )
        assert 0.0 < r["index"] < 1.0
        # sub-scores should reflect individual conditions
        assert r["sub_scores"]["writer_freshness"] == 1.0
        assert r["sub_scores"]["push_lag"] == 1.0
        assert r["sub_scores"]["commit_freshness"] < 1.0
        assert r["sub_scores"]["backlog_ratio"] == 0.5

    def test_index_clamped(self):
        idx = PipelineHealthIndex()
        r = idx.compute(
            writer_freshness_s=-100,
            commit_freshness_s=-100,
            uncommitted_files=-5,
            unpushed_commits=-3,
        )
        assert 0.0 <= r["index"] <= 1.0

    def test_result_structure(self):
        idx = PipelineHealthIndex()
        r = idx.compute(10, 100, 3, 1)
        assert "index" in r
        assert "verdict" in r
        assert "sub_scores" in r
        assert "inputs" in r
        assert len(r["sub_scores"]) == 4
        assert r["inputs"]["writer_freshness_s"] == 10

    def test_inputs_recorded(self):
        idx = PipelineHealthIndex()
        r = idx.compute(
            writer_freshness_s=42,
            commit_freshness_s=300,
            uncommitted_files=7,
            unpushed_commits=2,
        )
        assert r["inputs"]["writer_freshness_s"] == 42
        assert r["inputs"]["commit_freshness_s"] == 300
        assert r["inputs"]["uncommitted_files"] == 7
        assert r["inputs"]["unpushed_commits"] == 2


# ---------------------------------------------------------------------------
# PipelineHealthIndex.trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_insufficient_data(self):
        idx = PipelineHealthIndex()
        assert idx.trend() == "insufficient_data"
        idx.compute(5, 5, 0, 0)
        assert idx.trend() == "insufficient_data"
        idx.compute(5, 5, 0, 0)
        assert idx.trend() == "insufficient_data"

    def test_improving(self):
        idx = PipelineHealthIndex()
        # First half: bad scores
        for _ in range(3):
            idx.compute(9999, 9999, 100, 50)
        # Second half: good scores
        for _ in range(3):
            idx.compute(5, 5, 0, 0)
        assert idx.trend() == "improving"

    def test_declining(self):
        idx = PipelineHealthIndex()
        # First half: good scores
        for _ in range(3):
            idx.compute(5, 5, 0, 0)
        # Second half: bad scores
        for _ in range(3):
            idx.compute(9999, 9999, 100, 50)
        assert idx.trend() == "declining"

    def test_flat(self):
        idx = PipelineHealthIndex()
        for _ in range(6):
            idx.compute(15, 100, 2, 0)
        assert idx.trend() == "flat"


# ---------------------------------------------------------------------------
# PipelineHealthIndex.history
# ---------------------------------------------------------------------------

class TestHistory:
    def test_returns_copy(self):
        idx = PipelineHealthIndex()
        idx.compute(5, 5, 0, 0)
        h1 = idx.history()
        h2 = idx.history()
        assert h1 == h2
        assert h1 is not h2  # different objects

    def test_ring_buffer(self):
        idx = PipelineHealthIndex(history_size=3)
        for i in range(5):
            idx.compute(5, 5, 0, 0)
        assert len(idx.history()) == 3

    def test_empty_initially(self):
        idx = PipelineHealthIndex()
        assert idx.history() == []


# ---------------------------------------------------------------------------
# PipelineHealthIndex.summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_contains_verdict(self):
        idx = PipelineHealthIndex()
        s = idx.summary(5, 30, 0, 0)
        assert "healthy" in s or "warn" in s or "critical" in s or "down" in s

    def test_contains_index(self):
        idx = PipelineHealthIndex()
        s = idx.summary(5, 30, 0, 0)
        assert "index=" in s

    def test_contains_trend(self):
        idx = PipelineHealthIndex()
        s = idx.summary(5, 30, 0, 0)
        assert "trend=" in s

    def test_perfect_case(self):
        idx = PipelineHealthIndex()
        s = idx.summary(5, 30, 0, 0)
        assert "healthy" in s
