#!/usr/bin/env python3
"""Tests for tools/repo_graft.py — multi-writer graft health scoring."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from repo_graft import (
    GraftMetric,
    GraftReport,
    gini_coefficient,
    score_balance,
    score_interleaving,
    score_coverage,
    score_conflict_rate,
    grade,
    exit_code_for_grade,
    as_text,
)


# ── gini_coefficient ──────────────────────────────────────────────────


class TestGiniCoefficient:
    def test_single_value(self):
        assert gini_coefficient([100.0]) == 0.0

    def test_empty(self):
        assert gini_coefficient([]) == 0.0

    def test_perfect_equality(self):
        g = gini_coefficient([50.0, 50.0])
        assert g == pytest.approx(0.0, abs=0.01)

    def test_perfect_equality_four(self):
        g = gini_coefficient([25.0, 25.0, 25.0, 25.0])
        assert g == pytest.approx(0.0, abs=0.01)

    def test_high_inequality(self):
        # Normalised: [99,1] → gini ≈ 0.98
        g = gini_coefficient([99.0, 1.0])
        assert g > 0.9

    def test_max_inequality_two(self):
        # Perfect concentration: [100, 0] → normalised gini = 1.0
        g = gini_coefficient([100.0, 0.0])
        assert g == pytest.approx(1.0)

    def test_moderate_inequality(self):
        g = gini_coefficient([70.0, 20.0, 10.0])
        assert 0.3 < g < 0.65

    def test_all_zeros(self):
        assert gini_coefficient([0.0, 0.0, 0.0]) == 0.0

    def test_one_nonzero_rest_zero(self):
        g = gini_coefficient([100.0, 0.0, 0.0, 0.0])
        assert g > 0.7


# ── score_balance ─────────────────────────────────────────────────────


class TestScoreBalance:
    def test_single_writer(self):
        m = score_balance({"qwen": 100})
        assert m.value == 25.0
        assert "single writer" in m.detail

    def test_equal_two_writers(self):
        m = score_balance({"qwen": 50, "kimi": 50})
        assert m.value == pytest.approx(25.0, abs=1.0)

    def test_unequal_two_writers(self):
        m = score_balance({"qwen": 99, "kimi": 1})
        assert m.value < 5.0

    def test_empty(self):
        m = score_balance({})
        assert m.value == 0.0
        assert "no writer data" in m.detail

    def test_three_equal(self):
        m = score_balance({"qwen": 33, "kimi": 33, "doubao": 34})
        assert m.value > 20.0

    def test_dominant_writer(self):
        m = score_balance({"qwen": 95, "kimi": 3, "doubao": 2})
        assert m.value < 10.0

    def test_name_attribute(self):
        m = score_balance({"qwen": 10})
        assert m.name == "balance"


# ── score_interleaving ────────────────────────────────────────────────


class TestScoreInterleaving:
    def test_perfect_alternation(self):
        authors = ["a@x.com", "b@x.com", "a@x.com", "b@x.com"]
        m = score_interleaving(authors)
        assert m.value == 25.0

    def test_single_author(self):
        authors = ["a@x.com", "a@x.com", "a@x.com"]
        m = score_interleaving(authors)
        assert m.value == 0.0
        assert "single author" in m.detail

    def test_empty(self):
        m = score_interleaving([])
        assert m.value == 0.0

    def test_one_commit(self):
        m = score_interleaving(["a@x.com"])
        assert m.value == 0.0

    def test_two_authors_clumped(self):
        # aaaaa bbbbb — only 1 transition in 9 possible
        authors = ["a@x.com"] * 5 + ["b@x.com"] * 5
        m = score_interleaving(authors)
        assert m.value < 5.0

    def test_three_authors_alternating(self):
        authors = ["a@x.com", "b@x.com", "c@x.com"] * 10
        m = score_interleaving(authors)
        assert m.value == 25.0

    def test_mostly_one_with_intrusion(self):
        authors = ["a@x.com"] * 20 + ["b@x.com"] + ["a@x.com"] * 20
        m = score_interleaving(authors)
        # 2 transitions out of 40 = 5%
        assert 0 < m.value < 5.0


# ── score_coverage ────────────────────────────────────────────────────


class TestScoreCoverage:
    def test_all_categories_multi_writer(self):
        cats = [
            ("a@x.com", "thought"), ("b@x.com", "thought"),
            ("a@x.com", "garden"), ("b@x.com", "garden"),
            ("a@x.com", "note"), ("b@x.com", "note"),
        ]
        m = score_coverage(cats)
        assert m.value == 25.0

    def test_all_categories_single_writer(self):
        cats = [
            ("a@x.com", "thought"),
            ("a@x.com", "garden"),
            ("a@x.com", "note"),
        ]
        m = score_coverage(cats)
        assert m.value == 0.0

    def test_empty(self):
        m = score_coverage([])
        assert m.value == 0.0

    def test_half_multi_writer(self):
        cats = [
            ("a@x.com", "thought"), ("b@x.com", "thought"),
            ("a@x.com", "garden"),  # only one writer
        ]
        m = score_coverage(cats)
        assert m.value == pytest.approx(12.5, abs=1.0)

    def test_name_attribute(self):
        m = score_coverage([])
        assert m.name == "coverage"


# ── score_conflict_rate ───────────────────────────────────────────────


class TestScoreConflictRate:
    def test_no_conflicts(self):
        m = score_conflict_rate(0, 100)
        assert m.value == 25.0

    def test_one_percent(self):
        m = score_conflict_rate(1, 100)
        assert m.value == 20.0

    def test_five_percent(self):
        m = score_conflict_rate(5, 100)
        assert m.value == 0.0

    def test_over_five_percent(self):
        m = score_conflict_rate(10, 100)
        assert m.value == 0.0

    def test_zero_commits(self):
        m = score_conflict_rate(0, 0)
        assert m.value == 25.0
        assert "no commits" in m.detail

    def test_two_percent(self):
        m = score_conflict_rate(2, 100)
        assert m.value == 15.0

    def test_name_attribute(self):
        m = score_conflict_rate(0, 10)
        assert m.name == "conflict_rate"


# ── grade ─────────────────────────────────────────────────────────────


class TestGrade:
    def test_fused(self):
        assert grade(100) == "fused"
        assert grade(80) == "fused"

    def test_healing(self):
        assert grade(79.9) == "healing"
        assert grade(50) == "healing"

    def test_scarred(self):
        assert grade(49.9) == "scarred"
        assert grade(20) == "scarred"

    def test_rejected(self):
        assert grade(19.9) == "rejected"
        assert grade(0) == "rejected"


# ── exit_code_for_grade ──────────────────────────────────────────────


class TestExitCodeForGrade:
    def test_fused(self):
        assert exit_code_for_grade("fused") == 0

    def test_healing(self):
        assert exit_code_for_grade("healing") == 0

    def test_scarred(self):
        assert exit_code_for_grade("scarred") == 1

    def test_rejected(self):
        assert exit_code_for_grade("rejected") == 2

    def test_unknown(self):
        assert exit_code_for_grade("unknown") == 3


# ── as_text ───────────────────────────────────────────────────────────


class TestAsText:
    def _make_report(self, score=50.0, g="healing"):
        return GraftReport(
            score=score,
            grade=g,
            metrics=[
                GraftMetric("balance", 12.5, detail="test"),
                GraftMetric("interleaving", 12.5, detail="test"),
                GraftMetric("coverage", 12.5, detail="test"),
                GraftMetric("conflict_rate", 12.5, detail="test"),
            ],
            writers=["qwen", "kimi"],
            writer_strokes={"qwen": 50, "kimi": 50},
            total_commits_scanned=100,
            interleaving_ratio=0.5,
            multi_writer_categories=3,
            total_categories=5,
            conflict_count=0,
            timestamp="2026-10-24T01:00:00+00:00",
        )

    def test_contains_score(self):
        r = self._make_report()
        text = as_text(r)
        assert "50.0/100" in text

    def test_contains_grade(self):
        r = self._make_report()
        text = as_text(r)
        assert "HEALING" in text

    def test_contains_writers(self):
        r = self._make_report()
        text = as_text(r)
        assert "qwen" in text
        assert "kimi" in text

    def test_fused_message(self):
        r = self._make_report(score=90, g="fused")
        text = as_text(r)
        assert "fused" in text.lower()

    def test_rejected_message(self):
        r = self._make_report(score=10, g="rejected")
        text = as_text(r)
        assert "rejected" in text.lower()

    def test_scarred_message(self):
        r = self._make_report(score=30, g="scarred")
        text = as_text(r)
        assert "scarred" in text.lower()

    def test_contains_metric_names(self):
        r = self._make_report()
        text = as_text(r)
        assert "balance" in text
        assert "interleaving" in text
        assert "coverage" in text
        assert "conflict_rate" in text


# ── GraftReport.to_dict ──────────────────────────────────────────────


class TestGraftReportToDict:
    def test_round_trip(self):
        r = GraftReport(
            score=75.0,
            grade="healing",
            metrics=[GraftMetric("balance", 20.0, detail="ok")],
            writers=["qwen"],
            writer_strokes={"qwen": 100},
            total_commits_scanned=50,
            interleaving_ratio=0.8,
            multi_writer_categories=2,
            total_categories=4,
            conflict_count=1,
            timestamp="2026-10-24T00:00:00Z",
        )
        d = r.to_dict()
        assert d["score"] == 75.0
        assert d["grade"] == "healing"
        assert len(d["metrics"]) == 1
        assert d["metrics"][0]["name"] == "balance"
        assert d["writers"] == ["qwen"]
        assert d["conflict_count"] == 1


# ── Integration: boundary grading ────────────────────────────────────


class TestGradingBoundaries:
    """Ensure grading transitions happen at exactly the right thresholds."""

    def test_just_below_fused(self):
        assert grade(79.9) == "healing"

    def test_exactly_fused(self):
        assert grade(80.0) == "fused"

    def test_just_below_healing(self):
        assert grade(49.9) == "scarred"

    def test_exactly_healing(self):
        assert grade(50.0) == "healing"

    def test_just_below_scarred(self):
        assert grade(19.9) == "rejected"

    def test_exactly_scarred(self):
        assert grade(20.0) == "scarred"
