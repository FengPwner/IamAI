"""Tests for iamai.repo_maturity_index — repo maturity stage classifier."""

from __future__ import annotations

import pytest

from iamai.repo_maturity_index import (
    MaturityReport,
    _care_ratio,
    _content_ratio,
    _diagnose,
    _log_norm,
    _strokes_per_commit,
    assess_maturity,
    classify_stage,
    maturity_summary,
)


# ---------------------------------------------------------------------------
# _log_norm
# ---------------------------------------------------------------------------


class TestLogNorm:
    def test_zero_returns_zero(self):
        assert _log_norm(0, 2000) == 0.0

    def test_one_returns_zero(self):
        assert _log_norm(1, 2000) == 0.0

    def test_ceiling_returns_one(self):
        assert _log_norm(2000, 2000) == 1.0

    def test_above_ceiling_caps_at_one(self):
        assert _log_norm(5000, 2000) == 1.0

    def test_midpoint_is_fractional(self):
        val = _log_norm(100, 2000)
        assert 0.0 < val < 1.0

    def test_log_curve_concave(self):
        """Log scale has diminishing returns: higher values add less."""
        low = _log_norm(100, 2000)
        high = _log_norm(1000, 2000)
        ceiling = _log_norm(2000, 2000)
        # Gain from 100→1000 should exceed gain from 1000→2000
        assert (high - low) > (ceiling - high)


# ---------------------------------------------------------------------------
# _content_ratio
# ---------------------------------------------------------------------------


class TestContentRatio:
    def test_zero_files(self):
        assert _content_ratio(0, 0) == 0.0

    def test_all_code(self):
        assert _content_ratio(100, 100) == 1.0

    def test_half_code(self):
        assert _content_ratio(50, 100) == 0.5

    def test_caps_at_one(self):
        # code_files > total shouldn't happen, but guard anyway
        assert _content_ratio(200, 100) == 1.0


# ---------------------------------------------------------------------------
# _care_ratio
# ---------------------------------------------------------------------------


class TestCareRatio:
    def test_zero_commits(self):
        assert _care_ratio(10, 0) == 0.0

    def test_no_visits(self):
        assert _care_ratio(0, 1000) == 0.0

    def test_fifty_visits_per_hundred_commits_is_one(self):
        # 50 visits / 100 commits * 100 = 50 → normalised to 1.0
        assert _care_ratio(500, 1000) == 1.0

    def test_low_care_ratio(self):
        val = _care_ratio(10, 1000)
        assert 0.0 < val < 0.1

    def test_high_care_ratio(self):
        # 779 visits / 1100 commits → 70.8 visits/100 → capped at 1.0
        assert _care_ratio(779, 1100) == 1.0


# ---------------------------------------------------------------------------
# _strokes_per_commit
# ---------------------------------------------------------------------------


class TestStrokesPerCommit:
    def test_zero_commits(self):
        assert _strokes_per_commit(100, 0) == 0.0

    def test_normal(self):
        assert _strokes_per_commit(6920, 1100) == pytest.approx(6.29, rel=0.01)

    def test_one_commit(self):
        assert _strokes_per_commit(5, 1) == 5.0


# ---------------------------------------------------------------------------
# classify_stage
# ---------------------------------------------------------------------------


class TestClassifyStage:
    def test_seedling(self):
        assert classify_stage(0.05) == "seedling"

    def test_sapling(self):
        assert classify_stage(0.25) == "sapling"

    def test_canopy(self):
        assert classify_stage(0.45) == "canopy"

    def test_old_growth(self):
        assert classify_stage(0.75) == "old_growth"

    def test_petrified(self):
        assert classify_stage(0.90) == "petrified"

    def test_boundary_seedling_sapling(self):
        assert classify_stage(0.15) == "sapling"

    def test_boundary_canopy_old_growth(self):
        assert classify_stage(0.60) == "old_growth"

    def test_above_one_falls_through(self):
        assert classify_stage(1.0) == "petrified"

    def test_exactly_zero(self):
        assert classify_stage(0.0) == "seedling"


# ---------------------------------------------------------------------------
# assess_maturity
# ---------------------------------------------------------------------------


class TestAssessMaturity:
    def test_returns_report(self):
        r = assess_maturity(
            commits=100, files=200, code_files=80,
            caretaker_visits=50, stroke_count=500,
        )
        assert isinstance(r, MaturityReport)

    def test_young_repo_is_not_petrified(self):
        """A 20-commit repo with healthy metrics is mature but not petrified."""
        r = assess_maturity(
            commits=20, files=30, code_files=15,
            caretaker_visits=2, stroke_count=40,
        )
        assert r.stage != "petrified"
        assert r.score < 0.85

    def test_current_iamai_state(self):
        """The actual IamAI repo at visit 779."""
        r = assess_maturity(
            commits=1100, files=2591, code_files=1770,
            caretaker_visits=779, stroke_count=6920,
        )
        assert r.stage in ("canopy", "old_growth", "petrified")
        assert r.care_ratio == 1.0  # 779/1100 = 70.8 visits/100 → capped
        assert r.strokes_per_commit == pytest.approx(6.29, rel=0.01)

    def test_healthy_mature_repo(self):
        """A large repo with low caretaker need."""
        r = assess_maturity(
            commits=1500, files=3000, code_files=2000,
            caretaker_visits=50, stroke_count=15000,
        )
        assert r.score > 0.6
        assert r.care_ratio < 0.1

    def test_zero_everything(self):
        r = assess_maturity(
            commits=0, files=0, code_files=0,
            caretaker_visits=0, stroke_count=0,
        )
        assert r.stage == "seedling"
        assert r.score == 0.0

    def test_score_bounded(self):
        r = assess_maturity(
            commits=99999, files=99999, code_files=99999,
            caretaker_visits=0, stroke_count=999999,
        )
        assert 0.0 <= r.score <= 1.0


# ---------------------------------------------------------------------------
# maturity_summary
# ---------------------------------------------------------------------------


class TestMaturitySummary:
    def test_contains_stage(self):
        r = assess_maturity(
            commits=500, files=1000, code_files=500,
            caretaker_visits=100, stroke_count=3000,
        )
        text = maturity_summary(r)
        assert r.stage in text

    def test_contains_score(self):
        r = assess_maturity(
            commits=500, files=1000, code_files=500,
            caretaker_visits=100, stroke_count=3000,
        )
        text = maturity_summary(r)
        assert f"{r.score:.2f}" in text

    def test_ends_with_period(self):
        r = assess_maturity(
            commits=10, files=20, code_files=10,
            caretaker_visits=1, stroke_count=10,
        )
        text = maturity_summary(r)
        assert text.endswith(".")


# ---------------------------------------------------------------------------
# _diagnose
# ---------------------------------------------------------------------------


class TestDiagnose:
    def test_seedling_message(self):
        d = _diagnose(0.1, 0.1, 5.0, "seedling")
        assert "young" in d.lower() or "finding" in d.lower()

    def test_petrified_message(self):
        d = _diagnose(0.95, 0.8, 6.0, "petrified")
        assert "plateau" in d.lower() or "museum" in d.lower()

    def test_high_care_warning(self):
        d = _diagnose(0.7, 0.8, 6.0, "old_growth")
        assert "cannot sustain" in d.lower()

    def test_many_strokes_warning(self):
        d = _diagnose(0.5, 0.1, 15.0, "canopy")
        assert "batching" in d.lower() or "coarse" in d.lower()

    def test_few_strokes_warning(self):
        d = _diagnose(0.5, 0.1, 0.5, "canopy")
        assert "idle" in d.lower()

    def test_ends_with_period(self):
        d = _diagnose(0.5, 0.3, 5.0, "canopy")
        assert d.endswith(".")
