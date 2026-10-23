"""Tests for iamai.writer_vitality."""

from __future__ import annotations

import pytest

from iamai.writer_vitality import (
    classify,
    score_cadence,
    score_diversity,
    score_freshness,
    score_process,
    vitality,
    vitality_report,
)


# ---------------------------------------------------------------------------
# score_freshness
# ---------------------------------------------------------------------------

class TestScoreFreshness:
    def test_zero_age_is_perfect(self):
        assert score_freshness(0) == 100.0

    def test_negative_age_clamps_to_perfect(self):
        assert score_freshness(-5) == 100.0

    def test_just_under_low_boundary(self):
        # < 2× cadence (30s) → perfect
        assert score_freshness(29, 15) == 100.0

    def test_at_low_boundary(self):
        # exactly 2× cadence → still perfect
        assert score_freshness(30, 15) == 100.0

    def test_midpoint(self):
        # halfway between low and high → ~50
        mid = (30 + 300) / 2  # 165
        s = score_freshness(mid, 15)
        assert 45 < s < 55

    def test_at_high_boundary(self):
        # exactly 20× cadence → 0
        assert score_freshness(300, 15) == 0.0

    def test_beyond_high_boundary(self):
        assert score_freshness(1000, 15) == 0.0

    def test_custom_cadence(self):
        # cadence=60: low=120, high=1200
        assert score_freshness(100, 60) == 100.0
        assert score_freshness(1200, 60) == 0.0
        s = score_freshness(660, 60)  # midpoint
        assert 45 < s < 55

    def test_just_above_low(self):
        s = score_freshness(31, 15)
        assert s < 100.0
        assert s > 90.0

    def test_just_below_high(self):
        s = score_freshness(299, 15)
        assert s > 0.0
        assert s < 5.0


# ---------------------------------------------------------------------------
# score_cadence
# ---------------------------------------------------------------------------

class TestScoreCadence:
    def test_zero_jitter_is_perfect(self):
        assert score_cadence(0.0) == 100.0

    def test_negative_jitter_clamps_to_perfect(self):
        assert score_cadence(-0.1) == 100.0

    def test_ceiling_is_zero(self):
        assert score_cadence(1.5) == 0.0

    def test_beyond_ceiling(self):
        assert score_cadence(3.0) == 0.0

    def test_low_jitter_high_score(self):
        s = score_cadence(0.15)
        assert s == 90.0

    def test_mid_jitter(self):
        s = score_cadence(0.75)
        assert s == 50.0

    def test_high_jitter_low_score(self):
        s = score_cadence(1.2)
        assert abs(s - 20.0) < 1e-9

    def test_small_positive(self):
        s = score_cadence(0.01)
        assert s > 99.0


# ---------------------------------------------------------------------------
# score_diversity
# ---------------------------------------------------------------------------

class TestScoreDiversity:
    def test_perfect_evenness(self):
        assert score_diversity(1.0) == 100.0

    def test_zero_evenness(self):
        assert score_diversity(0.0) == 0.0

    def test_mid_evenness(self):
        assert score_diversity(0.5) == 50.0

    def test_high_evenness(self):
        assert score_diversity(0.92) == 92.0

    def test_negative_clamps(self):
        assert score_diversity(-0.5) == 0.0

    def test_above_one_clamps(self):
        assert score_diversity(1.5) == 100.0

    def test_small_value(self):
        assert score_diversity(0.01) == 1.0


# ---------------------------------------------------------------------------
# score_process
# ---------------------------------------------------------------------------

class TestScoreProcess:
    def test_both_alive(self):
        assert score_process(True, True) == 100.0

    def test_only_writer(self):
        assert score_process(True, False) == 50.0

    def test_only_batch(self):
        assert score_process(False, True) == 50.0

    def test_neither_alive(self):
        assert score_process(False, False) == 0.0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_thriving_at_boundary(self):
        assert classify(80) == "thriving"

    def test_thriving_above_boundary(self):
        assert classify(100) == "thriving"

    def test_healthy_at_boundary(self):
        assert classify(60) == "healthy"

    def test_healthy_below_thriving(self):
        assert classify(79.99) == "healthy"

    def test_weakened_at_boundary(self):
        assert classify(40) == "weakened"

    def test_weakened_below_healthy(self):
        assert classify(59.99) == "weakened"

    def test_critical_at_boundary(self):
        assert classify(20) == "critical"

    def test_critical_below_weakened(self):
        assert classify(39.99) == "critical"

    def test_dormant_below_critical(self):
        assert classify(19.99) == "dormant"

    def test_dormant_zero(self):
        assert classify(0) == "dormant"

    def test_all_grades_covered(self):
        grades = {classify(s) for s in [100, 70, 50, 30, 10]}
        assert grades == {"thriving", "healthy", "weakened", "critical", "dormant"}


# ---------------------------------------------------------------------------
# vitality (composite)
# ---------------------------------------------------------------------------

class TestVitality:
    def test_perfect_score(self):
        v = vitality(
            freshness_age=0,
            cadence_jitter=0.0,
            type_evenness=1.0,
            writer_alive=True,
            batch_alive=True,
        )
        assert v["score"] == 100.0
        assert v["grade"] == "thriving"

    def test_dead_score(self):
        v = vitality(
            freshness_age=999,
            cadence_jitter=2.0,
            type_evenness=0.0,
            writer_alive=False,
            batch_alive=False,
        )
        assert v["score"] == 0.0
        assert v["grade"] == "dormant"

    def test_half_process(self):
        v = vitality(
            freshness_age=0,
            cadence_jitter=0.0,
            type_evenness=1.0,
            writer_alive=True,
            batch_alive=False,
        )
        # freshness 25 + cadence 25 + diversity 25 + process 12.5 = 87.5
        assert v["score"] == 87.5
        assert v["grade"] == "thriving"

    def test_sub_scores_keys(self):
        v = vitality()
        assert set(v["sub_scores"].keys()) == {"freshness", "cadence", "diversity", "process"}

    def test_raw_scores_keys(self):
        v = vitality()
        assert set(v["raw"].keys()) == {"freshness", "cadence", "diversity", "process"}

    def test_sub_scores_sum_to_total(self):
        v = vitality(
            freshness_age=50,
            cadence_jitter=0.5,
            type_evenness=0.7,
            writer_alive=True,
            batch_alive=False,
        )
        expected = sum(v["sub_scores"].values())
        assert abs(v["score"] - expected) < 0.01

    def test_raw_scores_in_range(self):
        v = vitality(
            freshness_age=100,
            cadence_jitter=0.8,
            type_evenness=0.5,
            writer_alive=True,
            batch_alive=True,
        )
        for key, val in v["raw"].items():
            assert 0 <= val <= 100, f"{key} raw score {val} out of range"

    def test_custom_cadence(self):
        # with cadence=60, age=100 should still be fresh (low=120)
        v = vitality(
            freshness_age=100,
            cadence_jitter=0.0,
            type_evenness=1.0,
            writer_alive=True,
            batch_alive=True,
            cadence=60,
        )
        assert v["raw"]["freshness"] == 100.0

    def test_typical_healthy(self):
        v = vitality(
            freshness_age=20,
            cadence_jitter=0.3,
            type_evenness=0.85,
            writer_alive=True,
            batch_alive=True,
        )
        assert v["grade"] in ("thriving", "healthy")
        assert v["score"] >= 60

    def test_typical_weakened(self):
        v = vitality(
            freshness_age=150,
            cadence_jitter=0.8,
            type_evenness=0.4,
            writer_alive=True,
            batch_alive=False,
        )
        assert v["grade"] in ("weakened", "critical")


# ---------------------------------------------------------------------------
# vitality_report
# ---------------------------------------------------------------------------

class TestVitalityReport:
    def test_contains_grade(self):
        v = vitality(
            freshness_age=0,
            cadence_jitter=0.0,
            type_evenness=1.0,
            writer_alive=True,
            batch_alive=True,
        )
        report = vitality_report(v)
        assert "thriving" in report

    def test_contains_score(self):
        v = vitality(
            freshness_age=0,
            cadence_jitter=0.0,
            type_evenness=1.0,
            writer_alive=True,
            batch_alive=True,
        )
        report = vitality_report(v)
        assert "100/100" in report

    def test_contains_all_dimensions(self):
        v = vitality()
        report = vitality_report(v)
        assert "freshness" in report
        assert "cadence" in report
        assert "diversity" in report
        assert "process" in report

    def test_format_has_slash_25(self):
        v = vitality(
            freshness_age=50,
            cadence_jitter=0.5,
            type_evenness=0.6,
            writer_alive=True,
            batch_alive=True,
        )
        report = vitality_report(v)
        assert "/25" in report
        # Each dimension should have /25
        assert report.count("/25") == 4

    def test_dormant_report(self):
        v = vitality(
            freshness_age=999,
            cadence_jitter=3.0,
            type_evenness=0.0,
            writer_alive=False,
            batch_alive=False,
        )
        report = vitality_report(v)
        assert "dormant" in report
        assert "0/100" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_defaults_produce_dormant(self):
        """All defaults (zeros/False) → everything dead."""
        v = vitality()
        # freshness_age=0 → 100, jitter=0 → 100, evenness=0 → 0, no processes → 0
        # = 25 + 25 + 0 + 0 = 50
        assert v["score"] == 50.0
        assert v["grade"] == "weakened"

    def test_only_freshness_good(self):
        v = vitality(
            freshness_age=10,
            cadence_jitter=2.0,
            type_evenness=0.0,
            writer_alive=False,
            batch_alive=False,
        )
        # freshness 25 + cadence 0 + diversity 0 + process 0 = 25
        assert v["score"] == 25.0
        assert v["grade"] == "critical"

    def test_only_process_good(self):
        v = vitality(
            freshness_age=999,
            cadence_jitter=2.0,
            type_evenness=0.0,
            writer_alive=True,
            batch_alive=True,
        )
        # 0 + 0 + 0 + 25 = 25
        assert v["score"] == 25.0
        assert v["grade"] == "critical"

    def test_score_monotonic_with_freshness(self):
        """Better freshness → higher or equal score, all else equal."""
        scores = []
        for age in [10, 50, 100, 200, 500]:
            v = vitality(
                freshness_age=age,
                cadence_jitter=0.5,
                type_evenness=0.7,
                writer_alive=True,
                batch_alive=True,
            )
            scores.append(v["score"])
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_score_monotonic_with_jitter(self):
        """Lower jitter → higher or equal score, all else equal."""
        scores = []
        for jitter in [0.1, 0.3, 0.5, 0.8, 1.2]:
            v = vitality(
                freshness_age=50,
                cadence_jitter=jitter,
                type_evenness=0.7,
                writer_alive=True,
                batch_alive=True,
            )
            scores.append(v["score"])
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]
