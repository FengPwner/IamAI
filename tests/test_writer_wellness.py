"""Tests for iamai.writer_wellness."""

import pytest

from iamai.writer_wellness import (
    cadence_signal,
    diversity_signal,
    freshness_signal,
    novelty_signal,
    process_signal,
    trend,
    wellness,
    wellness_summary,
    _clamp,
    _grade,
)


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------

class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_lo(self):
        assert _clamp(-1.0) == 0.0

    def test_above_hi(self):
        assert _clamp(2.0) == 1.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0

    def test_custom_range(self):
        assert _clamp(5, 0, 10) == 5
        assert _clamp(-1, 0, 10) == 0
        assert _clamp(15, 0, 10) == 10


# ---------------------------------------------------------------------------
# freshness_signal
# ---------------------------------------------------------------------------

class TestFreshnessSignal:
    def test_just_wrote(self):
        assert freshness_signal(5.0) == 1.0
        assert freshness_signal(0.0) == 1.0
        assert freshness_signal(30.0) == 1.0

    def test_silent_over_5min(self):
        assert freshness_signal(300.0) == 0.0
        assert freshness_signal(600.0) == 0.0

    def test_midpoint(self):
        # 165s should be roughly 0.5 (midpoint between 30 and 300)
        result = freshness_signal(165.0)
        assert 0.45 <= result <= 0.55

    def test_negative_age_clamped(self):
        assert freshness_signal(-10.0) == 1.0

    def test_linear_interpolation(self):
        # Quarter way: 30 + 0.25 * 270 = 97.5
        result = freshness_signal(97.5)
        assert 0.70 <= result <= 0.80


# ---------------------------------------------------------------------------
# cadence_signal
# ---------------------------------------------------------------------------

class TestCadenceSignal:
    def test_very_steady(self):
        assert cadence_signal(0.05) == 1.0
        assert cadence_signal(0.10) == 1.0

    def test_wildly_irregular(self):
        assert cadence_signal(1.0) == 0.0
        assert cadence_signal(2.0) == 0.0

    def test_midpoint(self):
        # CV 0.55 → midpoint between 0.10 and 1.00
        result = cadence_signal(0.55)
        assert 0.45 <= result <= 0.55

    def test_negative_clamped(self):
        assert cadence_signal(-0.5) == 1.0


# ---------------------------------------------------------------------------
# diversity_signal
# ---------------------------------------------------------------------------

class TestDiversitySignal:
    def test_pass_through(self):
        assert diversity_signal(0.92) == 0.92

    def test_clamped_above(self):
        assert diversity_signal(1.5) == 1.0

    def test_clamped_below(self):
        assert diversity_signal(-0.1) == 0.0

    def test_zero(self):
        assert diversity_signal(0.0) == 0.0

    def test_one(self):
        assert diversity_signal(1.0) == 1.0


# ---------------------------------------------------------------------------
# novelty_signal
# ---------------------------------------------------------------------------

class TestNoveltySignal:
    def test_pass_through(self):
        assert novelty_signal(0.62) == 0.62

    def test_clamped_above(self):
        assert novelty_signal(1.1) == 1.0

    def test_clamped_below(self):
        assert novelty_signal(-0.5) == 0.0


# ---------------------------------------------------------------------------
# process_signal
# ---------------------------------------------------------------------------

class TestProcessSignal:
    def test_all_alive(self):
        assert process_signal(2, 2) == 1.0

    def test_half_alive(self):
        assert process_signal(1, 2) == 0.5

    def test_none_alive(self):
        assert process_signal(0, 2) == 0.0

    def test_zero_expected(self):
        # Nothing expected → nothing broken
        assert process_signal(0, 0) == 1.0

    def test_negative_expected(self):
        assert process_signal(0, -1) == 1.0

    def test_single_process(self):
        assert process_signal(1, 1) == 1.0
        assert process_signal(0, 1) == 0.0


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade:
    def test_thriving(self):
        assert _grade(100) == "thriving"
        assert _grade(80) == "thriving"

    def test_fit(self):
        assert _grade(79) == "fit"
        assert _grade(60) == "fit"

    def test_weary(self):
        assert _grade(59) == "weary"
        assert _grade(40) == "weary"

    def test_strained(self):
        assert _grade(39) == "strained"
        assert _grade(20) == "strained"

    def test_critical(self):
        assert _grade(19) == "critical"
        assert _grade(0) == "critical"


# ---------------------------------------------------------------------------
# wellness (composite)
# ---------------------------------------------------------------------------

class TestWellness:
    def test_perfect_wellness(self):
        w = wellness(
            freshness_age=10.0,
            cadence_cv=0.05,
            type_evenness=0.95,
            novelty_mean=0.80,
            processes_alive=2,
            processes_expected=2,
        )
        assert w["score"] >= 95.0
        assert w["grade"] == "thriving"

    def test_critical_wellness(self):
        w = wellness(
            freshness_age=600.0,
            cadence_cv=2.0,
            type_evenness=0.0,
            novelty_mean=0.0,
            processes_alive=0,
            processes_expected=2,
        )
        assert w["score"] == 0.0
        assert w["grade"] == "critical"

    def test_weakest_signal_detected(self):
        w = wellness(
            freshness_age=10.0,
            cadence_cv=0.05,
            type_evenness=0.95,
            novelty_mean=0.10,  # lowest signal
            processes_alive=2,
            processes_expected=2,
        )
        assert w["weakest"] == "novelty"

    def test_weakest_tie_breaking(self):
        # All signals equal → priority order picks process first
        w = wellness(
            freshness_age=97.5,   # ~0.75
            cadence_cv=0.325,     # ~0.75
            type_evenness=0.75,
            novelty_mean=0.75,
            processes_alive=0,    # 0.0 — actually weakest
            processes_expected=2,
        )
        # process = 0.0, others ≈ 0.75 → process is weakest
        assert w["weakest"] == "process"

    def test_signals_present(self):
        w = wellness(
            freshness_age=30.0,
            cadence_cv=0.12,
            type_evenness=0.85,
            novelty_mean=0.62,
            processes_alive=2,
            processes_expected=2,
        )
        assert set(w["signals"].keys()) == {
            "freshness", "cadence", "diversity", "novelty", "process"
        }
        for v in w["signals"].values():
            assert 0.0 <= v <= 1.0

    def test_mixed_health(self):
        # Good process & freshness, bad novelty & cadence
        w = wellness(
            freshness_age=15.0,
            cadence_cv=0.80,
            type_evenness=0.70,
            novelty_mean=0.15,
            processes_alive=2,
            processes_expected=2,
        )
        assert 30 <= w["score"] <= 70
        assert w["grade"] in ("fit", "weary", "strained")

    def test_score_is_rounded(self):
        w = wellness(
            freshness_age=30.0,
            cadence_cv=0.12,
            type_evenness=0.85,
            novelty_mean=0.62,
            processes_alive=2,
            processes_expected=2,
        )
        # Score should have at most 1 decimal
        assert w["score"] == round(w["score"], 1)


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------

class TestTrend:
    def test_improving(self):
        assert trend({"score": 70.0}, {"score": 80.0}) == "improving"
        assert trend({"score": 70.0}, {"score": 75.0}) == "improving"

    def test_stable(self):
        assert trend({"score": 70.0}, {"score": 72.0}) == "stable"
        assert trend({"score": 70.0}, {"score": 70.0}) == "stable"
        assert trend({"score": 70.0}, {"score": 74.9}) == "stable"

    def test_declining(self):
        assert trend({"score": 70.0}, {"score": 60.0}) == "declining"
        assert trend({"score": 70.0}, {"score": 65.0}) == "declining"

    def test_exact_boundary_improving(self):
        assert trend({"score": 70.0}, {"score": 75.0}) == "improving"

    def test_exact_boundary_declining(self):
        assert trend({"score": 70.0}, {"score": 65.0}) == "declining"


# ---------------------------------------------------------------------------
# wellness_summary
# ---------------------------------------------------------------------------

class TestWellnessSummary:
    def test_contains_grade_and_score(self):
        w = wellness(
            freshness_age=30.0,
            cadence_cv=0.12,
            type_evenness=0.85,
            novelty_mean=0.62,
            processes_alive=2,
            processes_expected=2,
        )
        s = wellness_summary(w)
        assert "wellness" in s
        assert str(int(w["score"])) in s
        assert w["grade"] in s
        assert w["weakest"] in s

    def test_all_signals_listed(self):
        w = wellness(
            freshness_age=30.0,
            cadence_cv=0.12,
            type_evenness=0.85,
            novelty_mean=0.62,
            processes_alive=2,
            processes_expected=2,
        )
        s = wellness_summary(w)
        for name in ("freshness", "cadence", "diversity", "novelty", "process"):
            assert name in s

    def test_format_consistency(self):
        w = wellness(
            freshness_age=100.0,
            cadence_cv=0.5,
            type_evenness=0.5,
            novelty_mean=0.5,
            processes_alive=1,
            processes_expected=2,
        )
        s = wellness_summary(w)
        assert s.startswith("wellness ")
        assert "/100" in s
        assert "[weakest:" in s
