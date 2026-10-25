#!/usr/bin/env python3
"""Tests for repo_pulse.py — repository health pulse indicator."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import repo_pulse as rp


# ---------------------------------------------------------------------------
# score_freshness
# ---------------------------------------------------------------------------

class TestScoreFreshness:
    def test_none_returns_zero(self):
        assert rp.score_freshness(None) == 0.0

    def test_zero_age_returns_max(self):
        assert rp.score_freshness(0.0) == 100.0

    def test_fresh_commit(self):
        """120s old with 600s target → high score."""
        score = rp.score_freshness(120.0, target_s=600.0)
        assert score > 80

    def test_stale_commit(self):
        """3600s old with 600s target → zero (past ceiling)."""
        score = rp.score_freshness(3600.0, target_s=600.0)
        assert score == 0.0

    def test_midpoint(self):
        """900s old with target 600, ceiling 1800 → 50."""
        score = rp.score_freshness(900.0, target_s=600.0)
        assert 45 < score < 55

    def test_exactly_at_ceiling(self):
        """1800s with target 600 → 0."""
        score = rp.score_freshness(1800.0, target_s=600.0)
        assert score == 0.0

    def test_negative_age(self):
        """Negative age (clock skew) treated as fresh."""
        assert rp.score_freshness(-10.0) == 100.0

    def test_custom_target(self):
        score = rp.score_freshness(100.0, target_s=200.0)
        # 100 / (200*3) = 100/600 ≈ 0.167 → ~83.3
        assert 80 < score < 90


# ---------------------------------------------------------------------------
# score_backlog
# ---------------------------------------------------------------------------

class TestScoreBacklog:
    def test_zero_uncommitted(self):
        assert rp.score_backlog(0) == 100.0

    def test_at_threshold(self):
        assert rp.score_backlog(10, threshold=10) == 0.0

    def test_above_threshold(self):
        assert rp.score_backlog(15, threshold=10) == 0.0

    def test_half_threshold(self):
        score = rp.score_backlog(5, threshold=10)
        assert score == 50.0

    def test_negative_count(self):
        """Negative means detection failed → 0."""
        assert rp.score_backlog(-1) == 0.0

    def test_one_file(self):
        score = rp.score_backlog(1, threshold=10)
        assert score == 90.0

    def test_custom_threshold(self):
        score = rp.score_backlog(3, threshold=5)
        # 1 - 3/5 = 0.4 → 40
        assert score == 40.0


# ---------------------------------------------------------------------------
# score_liveness
# ---------------------------------------------------------------------------

class TestScoreLiveness:
    def test_both_alive(self):
        assert rp.score_liveness({"writer": True, "batch": True}) == 100.0

    def test_writer_only(self):
        assert rp.score_liveness({"writer": True, "batch": False}) == 50.0

    def test_batch_only(self):
        assert rp.score_liveness({"writer": False, "batch": True}) == 50.0

    def test_both_dead(self):
        assert rp.score_liveness({"writer": False, "batch": False}) == 0.0

    def test_empty_dict(self):
        assert rp.score_liveness({}) == 0.0


# ---------------------------------------------------------------------------
# score_rhythm
# ---------------------------------------------------------------------------

class TestScoreRhythm:
    def test_empty_gaps(self):
        """No data → midpoint."""
        assert rp.score_rhythm([]) == 50.0

    def test_single_gap(self):
        """Only one data point → midpoint."""
        assert rp.score_rhythm([600.0]) == 50.0

    def test_perfectly_regular(self):
        """Identical intervals → CV=0 → 100."""
        gaps = [600.0] * 10
        assert rp.score_rhythm(gaps) == 100.0

    def test_moderate_variance(self):
        """Some variance but not terrible."""
        gaps = [500, 550, 600, 650, 700, 580, 620, 590, 610, 600]
        score = rp.score_rhythm(gaps)
        assert 70 < score < 100

    def test_high_variance(self):
        """Very erratic intervals → low score."""
        gaps = [10, 1800, 30, 900, 5, 2400, 60, 1200]
        score = rp.score_rhythm(gaps)
        assert score < 40

    def test_all_zero_gaps(self):
        """All zero intervals → avg=0 → 0."""
        assert rp.score_rhythm([0.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# compute_pulse
# ---------------------------------------------------------------------------

class TestComputePulse:
    def test_all_perfect(self):
        result = rp.compute_pulse(100.0, 100.0, 100.0, 100.0)
        assert result["pulse"] == 100.0
        assert result["label"] == "healthy"

    def test_all_zero(self):
        result = rp.compute_pulse(0.0, 0.0, 0.0, 0.0)
        assert result["pulse"] == 0.0
        assert result["label"] == "critical"

    def test_degraded(self):
        result = rp.compute_pulse(50.0, 50.0, 50.0, 50.0)
        assert result["label"] == "degraded"
        assert 40 <= result["pulse"] < 70

    def test_weights_sum_to_one(self):
        """Verify weights are properly normalized."""
        total = sum(rp.WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_score_breakdown_present(self):
        result = rp.compute_pulse(80, 60, 100, 70)
        assert "scores" in result
        assert set(result["scores"].keys()) == {"freshness", "backlog", "liveness", "rhythm"}

    def test_clamped_above(self):
        """Scores over 100 shouldn't produce pulse > 100."""
        result = rp.compute_pulse(200.0, 200.0, 200.0, 200.0)
        assert result["pulse"] == 100.0

    def test_clamped_below(self):
        """Negative scores shouldn't produce pulse < 0."""
        result = rp.compute_pulse(-50.0, -50.0, -50.0, -50.0)
        assert result["pulse"] == 0.0

    def test_label_boundaries(self):
        """Test exact boundary values."""
        r70 = rp.compute_pulse(100, 100, 100, 100)
        # Manually compute: all 100 → pulse=100 → healthy
        assert r70["label"] == "healthy"

        # Construct a case for exactly ~70
        # 0.30*f + 0.25*b + 0.25*l + 0.20*r = 70
        r_edge = rp.compute_pulse(70, 70, 70, 70)
        assert r_edge["pulse"] == 70.0
        assert r_edge["label"] == "healthy"

        r40 = rp.compute_pulse(40, 40, 40, 40)
        assert r40["pulse"] == 40.0
        assert r40["label"] == "degraded"

    def test_just_below_healthy(self):
        result = rp.compute_pulse(69, 69, 69, 69)
        assert result["pulse"] == 69.0
        assert result["label"] == "degraded"

    def test_just_below_degraded(self):
        result = rp.compute_pulse(39, 39, 39, 39)
        assert result["pulse"] == 39.0
        assert result["label"] == "critical"


# ---------------------------------------------------------------------------
# format_pulse
# ---------------------------------------------------------------------------

class TestFormatPulse:
    def test_healthy_format(self):
        result = {"pulse": 85.0, "label": "healthy",
                  "scores": {"freshness": 90, "backlog": 80, "liveness": 100, "rhythm": 70}}
        output = rp.format_pulse(result)
        assert "●" in output
        assert "85.0/100" in output
        assert "healthy" in output

    def test_degraded_format(self):
        result = {"pulse": 55.0, "label": "degraded",
                  "scores": {"freshness": 50, "backlog": 60, "liveness": 50, "rhythm": 60}}
        output = rp.format_pulse(result)
        assert "◐" in output
        assert "degraded" in output

    def test_critical_format(self):
        result = {"pulse": 20.0, "label": "critical",
                  "scores": {"freshness": 10, "backlog": 20, "liveness": 0, "rhythm": 50}}
        output = rp.format_pulse(result)
        assert "○" in output
        assert "critical" in output


# ---------------------------------------------------------------------------
# integration: check_processes
# ---------------------------------------------------------------------------

class TestCheckProcesses:
    def test_returns_dict_keys(self):
        """Should always return writer and batch keys."""
        result = rp.check_processes("nonexistent_writer_xyz")
        assert "writer" in result
        assert "batch" in result
        assert result["writer"] is False
        assert result["batch"] is False


# ---------------------------------------------------------------------------
# integration: count_uncommitted
# ---------------------------------------------------------------------------

class TestCountUncommitted:
    def test_invalid_repo(self, tmp_path):
        """Non-repo path should return -1."""
        result = rp.count_uncommitted(str(tmp_path))
        assert result == -1

    def test_valid_repo(self):
        """Real repo should return >= 0."""
        result = rp.count_uncommitted(str(REPO))
        assert result >= 0


# ---------------------------------------------------------------------------
# integration: get_last_commit_age
# ---------------------------------------------------------------------------

class TestGetLastCommitAge:
    def test_invalid_repo(self, tmp_path):
        assert rp.get_last_commit_age(str(tmp_path)) is None

    def test_valid_repo(self):
        age = rp.get_last_commit_age(str(REPO))
        assert age is not None
        assert age >= 0
