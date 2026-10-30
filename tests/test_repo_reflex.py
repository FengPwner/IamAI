"""Tests for iamai.repo_reflex — reflex-arc measurement."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from iamai.repo_reflex import (
    ReflexResult,
    SegmentScore,
    _classify,
    _recommend,
    _score_effector,
    _score_motor,
    _score_sensory,
    measure_reflex,
)


# ===========================================================================
# SegmentScore
# ===========================================================================


class TestSegmentScore:
    def test_is_areflexic_when_zero(self):
        s = SegmentScore(name="x", latency_s=9999, score=0.0)
        assert s.is_areflexic

    def test_is_areflexic_at_boundary(self):
        s = SegmentScore(name="x", latency_s=100, score=5.0)
        assert s.is_areflexic

    def test_not_areflexic(self):
        s = SegmentScore(name="x", latency_s=10, score=50.0)
        assert not s.is_areflexic


# ===========================================================================
# Sensory scoring
# ===========================================================================


class TestScoreSensory:
    def test_instant(self):
        assert _score_sensory(0) == 100.0

    def test_just_under_30(self):
        assert _score_sensory(29) == 100.0

    def test_at_30(self):
        assert _score_sensory(30) == 80.0

    def test_5_minutes(self):
        assert _score_sensory(300) == 50.0

    def test_15_minutes(self):
        assert _score_sensory(900) == 20.0

    def test_1_hour(self):
        assert _score_sensory(3600) == 0.0

    def test_monotone_decreasing(self):
        points = [0, 10, 30, 100, 300, 500, 900, 1800, 3600, 7200]
        scores = [_score_sensory(t) for t in points]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]


# ===========================================================================
# Motor scoring
# ===========================================================================


class TestScoreMotor:
    def test_instant(self):
        assert _score_motor(0) == 100.0

    def test_just_under_60(self):
        assert _score_motor(59) == 100.0

    def test_10_minutes(self):
        assert _score_motor(600) == 30.0

    def test_30_minutes(self):
        assert _score_motor(1800) == 0.0

    def test_monotone_decreasing(self):
        points = [0, 30, 60, 300, 600, 1200, 1800, 3600]
        scores = [_score_motor(t) for t in points]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]


# ===========================================================================
# Effector scoring
# ===========================================================================


class TestScoreEffector:
    def test_instant(self):
        assert _score_effector(0) == 100.0

    def test_2_minutes(self):
        assert _score_effector(120) == 75.0

    def test_10_minutes(self):
        assert _score_effector(600) == 30.0

    def test_1_hour(self):
        assert _score_effector(3600) == 0.0

    def test_monotone_decreasing(self):
        points = [0, 60, 120, 300, 600, 1800, 3600, 7200]
        scores = [_score_effector(t) for t in points]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]


# ===========================================================================
# Classification
# ===========================================================================


class TestClassify:
    def test_sharp(self):
        assert _classify(100) == "sharp"
        assert _classify(80) == "sharp"

    def test_adequate(self):
        assert _classify(79) == "adequate"
        assert _classify(50) == "adequate"

    def test_sluggish(self):
        assert _classify(49) == "sluggish"
        assert _classify(20) == "sluggish"

    def test_areflexic(self):
        assert _classify(19) == "areflexic"
        assert _classify(0) == "areflexic"


# ===========================================================================
# Recommendations
# ===========================================================================


class TestRecommend:
    def test_sharp_has_no_action(self):
        rec = _recommend("sharp", None)
        assert "healthy" in rec.lower() or "responsive" in rec.lower()

    def test_sluggish_effector_mentions_push(self):
        seg = SegmentScore(name="effector", latency_s=600, score=30)
        rec = _recommend("sluggish", seg)
        assert "push" in rec.lower() or "credential" in rec.lower()

    def test_sluggish_sensory_mentions_writer(self):
        seg = SegmentScore(name="sensory", latency_s=2000, score=20)
        rec = _recommend("sluggish", seg)
        assert "writer" in rec.lower() or "stall" in rec.lower()

    def test_areflexic_mentions_intervention(self):
        rec = _recommend("areflexic", None)
        assert "intervention" in rec.lower() or "broken" in rec.lower()


# ===========================================================================
# ReflexResult
# ===========================================================================


class TestReflexResult:
    def test_empty_total_latency(self):
        r = ReflexResult()
        assert r.total_latency_s == 0.0

    def test_total_latency_sums(self):
        r = ReflexResult(segments=[
            SegmentScore("a", 10, 50),
            SegmentScore("b", 20, 50),
        ])
        assert r.total_latency_s == 30.0

    def test_weakest_segment(self):
        r = ReflexResult(segments=[
            SegmentScore("a", 10, 80),
            SegmentScore("b", 100, 10),
            SegmentScore("c", 50, 50),
        ])
        assert r.weakest_segment.name == "b"

    def test_weakest_empty(self):
        assert ReflexResult().weakest_segment is None

    def test_to_dict_keys(self):
        r = ReflexResult(segments=[SegmentScore("sensory", 5, 100)])
        d = r.to_dict()
        assert "segments" in d
        assert "composite_score" in d
        assert "classification" in d
        assert "recommendation" in d
        assert "total_latency_s" in d
        assert "weakest_segment" in d

    def test_to_dict_weakest_none(self):
        r = ReflexResult()
        assert r.to_dict()["weakest_segment"] is None


# ===========================================================================
# measure_reflex (mocked git)
# ===========================================================================


class TestMeasureReflex:
    """Integration-level tests with mocked git helpers."""

    @patch("iamai.repo_reflex._has_unpushed_commits", return_value=False)
    @patch("iamai.repo_reflex._latest_commit_time", return_value=1000.0)
    @patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=None)
    def test_clean_repo_sharp(self, mock_mtime, mock_commit, mock_unpushed, tmp_path):
        # Simulate "now" shortly after last commit
        result = measure_reflex(repo=tmp_path, now=1060.0)
        assert result.classification in ("sharp", "adequate")
        assert len(result.segments) == 3

    @patch("iamai.repo_reflex._has_unpushed_commits", return_value=True)
    @patch("iamai.repo_reflex._latest_commit_push_time", return_value=500.0)
    @patch("iamai.repo_reflex._latest_commit_time", return_value=1000.0)
    @patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=990.0)
    def test_unpushed_degrades_effector(
        self, mock_mtime, mock_commit, mock_push, mock_unpushed, tmp_path
    ):
        # effector latency = commit_time - push_time = 500s → score 75
        result = measure_reflex(repo=tmp_path, now=1010.0)
        effector = [s for s in result.segments if s.name == "effector"][0]
        assert effector.latency_s == 500.0
        assert effector.score == 75.0

    @patch("iamai.repo_reflex._has_unpushed_commits", return_value=False)
    @patch("iamai.repo_reflex._latest_commit_time", return_value=None)
    @patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=None)
    def test_no_commits_no_files(self, mock_mtime, mock_commit, mock_unpushed, tmp_path):
        result = measure_reflex(repo=tmp_path, now=1000.0)
        # All latencies should be 0
        assert all(s.latency_s == 0.0 for s in result.segments)
        assert result.classification == "sharp"

    @patch("iamai.repo_reflex._has_unpushed_commits", return_value=False)
    @patch("iamai.repo_reflex._latest_commit_time", return_value=100.0)
    @patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=50.0)
    def test_stale_files_degrade_sensory(
        self, mock_mtime, mock_commit, mock_unpushed, tmp_path
    ):
        # sensory latency = now - mtime = 1000 - 50 = 950s → score 20
        result = measure_reflex(repo=tmp_path, now=1000.0)
        sensory = [s for s in result.segments if s.name == "sensory"][0]
        assert sensory.latency_s == 950.0
        assert sensory.score == 20.0

    @patch("iamai.repo_reflex._has_unpushed_commits", return_value=False)
    @patch("iamai.repo_reflex._latest_commit_time", return_value=100.0)
    @patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=None)
    def test_composite_weights(self, mock_mtime, mock_commit, mock_unpushed, tmp_path):
        """Verify composite uses correct weights."""
        result = measure_reflex(repo=tmp_path, now=110.0)
        # sensory: 10s → 100, motor: 10s → 100, effector: 0 → 100
        expected = 0.3 * 100 + 0.3 * 100 + 0.4 * 100
        assert abs(result.composite_score - expected) < 0.01


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_negative_latency_clamped(self):
        """Latency should never be negative."""
        # If "now" is before mtime (clock skew), should clamp to 0
        with patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=2000.0):
            with patch("iamai.repo_reflex._latest_commit_time", return_value=2000.0):
                with patch("iamai.repo_reflex._has_unpushed_commits", return_value=False):
                    result = measure_reflex(repo=None, now=1000.0)
                    assert all(s.latency_s >= 0 for s in result.segments)

    def test_all_segment_names_present(self):
        with patch("iamai.repo_reflex._newest_uncommitted_mtime", return_value=None):
            with patch("iamai.repo_reflex._latest_commit_time", return_value=None):
                with patch("iamai.repo_reflex._has_unpushed_commits", return_value=False):
                    result = measure_reflex(repo=None, now=1000.0)
                    names = {s.name for s in result.segments}
                    assert names == {"sensory", "motor", "effector"}
