#!/usr/bin/env python3
"""Tests for tools/repo_metabolism.py — repo metabolism scoring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from repo_metabolism import (
    MetabolicMetric,
    MetabolismReport,
    grade,
    exit_code_for_grade,
    score_conversion_rate,
    score_throughput,
    score_waste_ratio,
    score_rhythm_stability,
    as_text,
)


# ── score_conversion_rate ─────────────────────────────────────────────


class TestScoreConversionRate:
    def test_perfect_conversion(self):
        s = score_conversion_rate(100, 100)
        assert s.value == 25.0
        assert "100%" in s.detail

    def test_ninety_percent(self):
        s = score_conversion_rate(90, 100)
        assert s.value == 25.0

    def test_seventy_percent(self):
        s = score_conversion_rate(70, 100)
        # (0.7 - 0.5) / 0.4 = 0.5 → 12.5
        assert s.value == 12.5

    def test_fifty_percent(self):
        s = score_conversion_rate(50, 100)
        assert s.value == 0.0

    def test_below_fifty_percent(self):
        s = score_conversion_rate(30, 100)
        assert s.value == 0.0

    def test_zero_total(self):
        s = score_conversion_rate(0, 0)
        assert s.value == 0.0

    def test_zero_committed_nonzero_total(self):
        s = score_conversion_rate(0, 50)
        assert s.value == 0.0

    def test_all_committed_small_batch(self):
        s = score_conversion_rate(5, 5)
        assert s.value == 25.0


# ── score_throughput ──────────────────────────────────────────────────


class TestScoreThroughput:
    def test_high_throughput(self):
        # 60 strokes/hour = full score
        s = score_throughput(1440, 24.0)
        assert s.value == 25.0

    def test_zero_throughput(self):
        s = score_throughput(0, 24.0)
        assert s.value == 0.0

    def test_half_throughput(self):
        # 30 strokes/hour
        s = score_throughput(720, 24.0)
        assert s.value == 12.5

    def test_above_cap(self):
        # 120 strokes/hour → capped at 25
        s = score_throughput(2880, 24.0)
        assert s.value == 25.0

    def test_zero_window(self):
        s = score_throughput(100, 0)
        assert s.value == 0.0

    def test_short_window_high_rate(self):
        # 60 strokes in 1 hour = 60/hr
        s = score_throughput(60, 1.0)
        assert s.value == 25.0


# ── score_waste_ratio ─────────────────────────────────────────────────


class TestScoreWasteRatio:
    def test_no_waste(self):
        s = score_waste_ratio(0, 100)
        assert s.value == 25.0

    def test_thirty_percent_waste(self):
        s = score_waste_ratio(30, 100)
        assert s.value == 0.0

    def test_ten_percent_waste(self):
        # waste=0.1 → 1 - 0.1/0.3 = 0.667 → 16.67
        s = score_waste_ratio(10, 100)
        assert abs(s.value - 16.67) < 0.1

    def test_fifteen_percent_waste(self):
        # waste=0.15 → 1 - 0.15/0.3 = 0.5 → 12.5
        s = score_waste_ratio(15, 100)
        assert s.value == 12.5

    def test_zero_total(self):
        s = score_waste_ratio(0, 0)
        assert s.value == 25.0  # no waste if nothing exists

    def test_all_waste(self):
        s = score_waste_ratio(100, 100)
        assert s.value == 0.0


# ── score_rhythm_stability ────────────────────────────────────────────


class TestScoreRhythmStability:
    def test_perfectly_stable(self):
        # all same size → CV = 0
        s = score_rhythm_stability([5, 5, 5, 5, 5])
        assert s.value == 25.0

    def test_no_commits(self):
        s = score_rhythm_stability([])
        assert s.value == 0.0

    def test_single_commit(self):
        s = score_rhythm_stability([7])
        assert s.value == 25.0  # benefit of the doubt

    def test_highly_variable(self):
        # CV should be large
        s = score_rhythm_stability([1, 1, 1, 1, 100])
        assert s.value < 10.0

    def test_moderate_variation(self):
        s = score_rhythm_stability([4, 5, 6, 5, 4])
        assert 15.0 < s.value < 25.0

    def test_cv_of_two(self):
        # CV = 2.0 → score = 0
        # values with CV≈2: e.g. [1, 5] → mean=3, std=2, CV=0.67
        # need CV=2: [1, 1, 1, 1, 11] → mean=3, var=16, std=4, CV=1.33
        # just test that very high CV gives low score
        s = score_rhythm_stability([1, 1, 1, 1, 50])
        assert s.value < 5.0


# ── grade ─────────────────────────────────────────────────────────────


class TestGrade:
    def test_anabolic(self):
        assert grade(80) == "anabolic"
        assert grade(100) == "anabolic"

    def test_healthy(self):
        assert grade(50) == "healthy"
        assert grade(79) == "healthy"

    def test_sluggish(self):
        assert grade(20) == "sluggish"
        assert grade(49) == "sluggish"

    def test_dormant(self):
        assert grade(0) == "dormant"
        assert grade(19) == "dormant"

    def test_boundary_values(self):
        assert grade(80.0) == "anabolic"
        assert grade(79.99) == "healthy"
        assert grade(50.0) == "healthy"
        assert grade(49.99) == "sluggish"
        assert grade(20.0) == "sluggish"
        assert grade(19.99) == "dormant"


# ── exit_code_for_grade ───────────────────────────────────────────────


class TestExitCode:
    def test_anabolic(self):
        assert exit_code_for_grade("anabolic") == 0

    def test_healthy(self):
        assert exit_code_for_grade("healthy") == 0

    def test_sluggish(self):
        assert exit_code_for_grade("sluggish") == 1

    def test_dormant(self):
        assert exit_code_for_grade("dormant") == 2

    def test_unknown(self):
        assert exit_code_for_grade("unknown") == 3


# ── as_text ───────────────────────────────────────────────────────────


class TestAsText:
    def test_contains_grade(self):
        report = MetabolismReport(
            score=85.0,
            grade="anabolic",
            metrics=[
                MetabolicMetric("conversion_rate", 25.0, detail="100/100 (100%)"),
                MetabolicMetric("throughput", 25.0, detail="60.0 strokes/hr"),
                MetabolicMetric("waste_ratio", 25.0, detail="0/100 (0% waste)"),
                MetabolicMetric("rhythm_stability", 10.0, detail="CV=1.20"),
            ],
            total_strokes=100,
            committed_strokes=100,
            uncommitted_strokes=0,
            commits_in_window=50,
            window_hours=24.0,
            conversion_pct=100.0,
            throughput_per_hour=60.0,
            timestamp="2026-10-24T00:00:00+00:00",
        )
        text = as_text(report)
        assert "anabolic" in text
        assert "85.0" in text
        assert "conversion_rate" in text
        assert "throughput" in text
        assert "waste_ratio" in text
        assert "rhythm_stability" in text

    def test_dormant_report(self):
        report = MetabolismReport(
            score=5.0,
            grade="dormant",
            metrics=[
                MetabolicMetric("conversion_rate", 0.0, detail="0/0 (0%)"),
                MetabolicMetric("throughput", 0.0, detail="0.0 strokes/hr"),
                MetabolicMetric("waste_ratio", 5.0, detail="some detail"),
                MetabolicMetric("rhythm_stability", 0.0, detail="0 commits"),
            ],
            total_strokes=0,
            committed_strokes=0,
            uncommitted_strokes=0,
            commits_in_window=0,
            window_hours=24.0,
            conversion_pct=0.0,
            throughput_per_hour=0.0,
            timestamp="2026-10-24T00:00:00+00:00",
        )
        text = as_text(report)
        assert "dormant" in text
        assert "5.0" in text


# ── Integration: to_dict ──────────────────────────────────────────────


class TestToDict:
    def test_report_to_dict(self):
        report = MetabolismReport(
            score=50.0,
            grade="healthy",
            metrics=[
                MetabolicMetric("conversion_rate", 12.5),
                MetabolicMetric("throughput", 12.5),
                MetabolicMetric("waste_ratio", 12.5),
                MetabolicMetric("rhythm_stability", 12.5),
            ],
            total_strokes=100,
            committed_strokes=70,
            uncommitted_strokes=10,
            commits_in_window=30,
            window_hours=24.0,
            conversion_pct=63.6,
            throughput_per_hour=2.9,
            timestamp="2026-10-24T00:00:00+00:00",
        )
        d = report.to_dict()
        assert d["score"] == 50.0
        assert d["grade"] == "healthy"
        assert len(d["metrics"]) == 4
        assert d["metrics"][0]["name"] == "conversion_rate"
        assert d["total_strokes"] == 100
