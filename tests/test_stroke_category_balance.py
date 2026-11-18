"""Tests for iamai.stroke_category_balance — category distribution analysis."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from iamai.stroke_category_balance import BalanceReport, StrokeCategoryBalance


# ── helpers ────────────────────────────────────────────────────────────

def _write_jsonl(lines, path):
    with open(path, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")


def _make_strokes(spec):
    """spec: list of (kind, seq) tuples."""
    return [{"seq": s, "at": "2026-01-01T00:00:00+00:00", "kind": k,
             "text": "stub"} for s, k in spec]


# ── BalanceReport ─────────────────────────────────────────────────────

class TestBalanceReport:

    def test_suggest_returns_none_when_no_starved(self):
        r = BalanceReport(
            total_strokes=100, category_counts={"a": 50, "b": 50},
            category_fractions={"a": 0.5, "b": 0.5},
            richness=2, shannon_entropy=1.0, max_entropy=1.0,
            entropy_ratio=1.0, gini_coefficient=0.0,
            herfindahl_index=0.5, dominant_category="a",
            dominant_fraction=0.5, starved_categories=[])
        assert r.suggest_next_category() is None

    def test_suggest_returns_lowest_starved(self):
        r = BalanceReport(
            total_strokes=100,
            category_counts={"a": 80, "b": 15, "c": 5},
            category_fractions={"a": 0.80, "b": 0.15, "c": 0.05},
            richness=3, shannon_entropy=0.9, max_entropy=1.585,
            entropy_ratio=0.57, gini_coefficient=0.5,
            herfindahl_index=0.665, dominant_category="a",
            dominant_fraction=0.80, starved_categories=["b", "c"])
        assert r.suggest_next_category() == "c"

    def test_to_dict_rounds(self):
        r = BalanceReport(
            total_strokes=10, category_counts={"x": 10},
            category_fractions={"x": 1.0},
            richness=1, shannon_entropy=0.0, max_entropy=0.0,
            entropy_ratio=0.0, gini_coefficient=0.0,
            herfindahl_index=1.0, dominant_category="x",
            dominant_fraction=1.0)
        d = r.to_dict()
        assert d["total_strokes"] == 10
        assert d["entropy_ratio"] == 0.0
        assert d["suggestion"] is None


# ── StrokeCategoryBalance.from_counts ─────────────────────────────────

class TestFromCounts:

    def test_empty(self):
        bal = StrokeCategoryBalance.from_counts({})
        r = bal.report()
        assert r.total_strokes == 0
        assert r.richness == 0
        assert r.entropy_ratio == 0.0
        assert r.dominant_category == ""

    def test_single_category(self):
        bal = StrokeCategoryBalance.from_counts({"thought": 100})
        r = bal.report()
        assert r.total_strokes == 100
        assert r.richness == 1
        assert r.shannon_entropy == 0.0
        assert r.max_entropy == 0.0
        assert r.entropy_ratio == 0.0
        assert r.gini_coefficient == 0.0
        assert r.herfindahl_index == 1.0
        assert r.dominant_category == "thought"
        assert r.dominant_fraction == 1.0

    def test_uniform_two_categories(self):
        bal = StrokeCategoryBalance.from_counts({"a": 50, "b": 50})
        r = bal.report()
        assert r.total_strokes == 100
        assert r.richness == 2
        assert abs(r.shannon_entropy - 1.0) < 1e-9
        assert abs(r.entropy_ratio - 1.0) < 1e-9
        assert abs(r.gini_coefficient - 0.0) < 1e-9
        assert abs(r.herfindahl_index - 0.5) < 1e-9
        assert len(r.starved_categories) == 0

    def test_uniform_three_categories(self):
        bal = StrokeCategoryBalance.from_counts({"a": 33, "b": 33, "c": 34})
        r = bal.report()
        assert r.richness == 3
        assert r.entropy_ratio > 0.99
        assert r.gini_coefficient < 0.01
        assert len(r.starved_categories) == 0

    def test_skewed_distribution(self):
        bal = StrokeCategoryBalance.from_counts(
            {"thought": 900, "note": 50, "devlog": 30, "garden": 10,
             "metrics": 5, "snippet": 5})
        r = bal.report()
        assert r.dominant_category == "thought"
        assert r.dominant_fraction == 0.9
        assert r.entropy_ratio < 0.5
        assert r.gini_coefficient > 0.5
        # snippet and metrics should be starved
        assert "snippet" in r.starved_categories or "metrics" in r.starved_categories

    def test_negative_counts_clamped(self):
        bal = StrokeCategoryBalance.from_counts({"a": -5, "b": 10})
        r = bal.report()
        assert r.total_strokes == 10
        assert "a" not in r.category_counts or r.category_counts["a"] == 0

    def test_zero_counts_mixed(self):
        bal = StrokeCategoryBalance.from_counts({"a": 0, "b": 10})
        r = bal.report()
        assert r.total_strokes == 10
        assert r.richness == 1  # only "b" has strokes


# ── StrokeCategoryBalance.from_jsonl ──────────────────────────────────

class TestFromJsonl:

    def test_missing_file(self, tmp_path):
        bal = StrokeCategoryBalance.from_jsonl(tmp_path / "nope.jsonl")
        r = bal.report()
        assert r.total_strokes == 0

    def test_valid_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        strokes = _make_strokes([(1, "thought"), (2, "thought"),
                                  (3, "note"), (4, "devlog")])
        _write_jsonl(strokes, p)
        bal = StrokeCategoryBalance.from_jsonl(p)
        r = bal.report()
        assert r.total_strokes == 4
        assert r.category_counts["thought"] == 2
        assert r.category_counts["note"] == 1
        assert r.category_counts["devlog"] == 1

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with open(p, "w") as fh:
            fh.write('{"seq":1,"kind":"thought","text":"ok","at":"x"}\n')
            fh.write("NOT JSON\n")
            fh.write('{"seq":2,"kind":"note","text":"ok","at":"x"}\n')
            fh.write('{"seq":3,"text":"missing kind"}\n')
        bal = StrokeCategoryBalance.from_jsonl(p)
        r = bal.report()
        assert r.total_strokes == 2
        assert r.richness == 2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        bal = StrokeCategoryBalance.from_jsonl(p)
        r = bal.report()
        assert r.total_strokes == 0


# ── entropy calculations ──────────────────────────────────────────────

class TestEntropy:

    def test_entropy_two_equal(self):
        bal = StrokeCategoryBalance.from_counts({"a": 50, "b": 50})
        r = bal.report()
        assert abs(r.shannon_entropy - 1.0) < 1e-9

    def test_entropy_four_equal(self):
        bal = StrokeCategoryBalance.from_counts(
            {"a": 25, "b": 25, "c": 25, "d": 25})
        r = bal.report()
        assert abs(r.shannon_entropy - 2.0) < 1e-9
        assert abs(r.max_entropy - 2.0) < 1e-9

    def test_entropy_ratio_always_leq_one(self):
        for spec in [{"a": 100},
                     {"a": 99, "b": 1},
                     {"a": 25, "b": 25, "c": 25, "d": 25},
                     {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}]:
            bal = StrokeCategoryBalance.from_counts(spec)
            r = bal.report()
            assert 0.0 <= r.entropy_ratio <= 1.0

    def test_max_entropy_zero_for_single_category(self):
        bal = StrokeCategoryBalance.from_counts({"x": 42})
        r = bal.report()
        assert r.max_entropy == 0.0


# ── Gini coefficient ──────────────────────────────────────────────────

class TestGini:

    def test_gini_uniform(self):
        bal = StrokeCategoryBalance.from_counts(
            {"a": 20, "b": 20, "c": 20, "d": 20, "e": 20})
        r = bal.report()
        assert abs(r.gini_coefficient) < 1e-9

    def test_gini_maximum_skew(self):
        bal = StrokeCategoryBalance.from_counts({"a": 100, "b": 0})
        r = bal.report()
        # only "a" has strokes → richness=1, gini=0 for single element
        assert r.gini_coefficient == 0.0

    def test_gini_two_unequal(self):
        bal = StrokeCategoryBalance.from_counts({"a": 90, "b": 10})
        r = bal.report()
        assert 0.0 < r.gini_coefficient < 1.0


# ── Herfindahl index ──────────────────────────────────────────────────

class TestHerfindahl:

    def test_hhi_monopoly(self):
        bal = StrokeCategoryBalance.from_counts({"a": 100})
        r = bal.report()
        assert r.herfindahl_index == 1.0

    def test_hhi_duopoly_equal(self):
        bal = StrokeCategoryBalance.from_counts({"a": 50, "b": 50})
        r = bal.report()
        assert abs(r.herfindahl_index - 0.5) < 1e-9

    def test_hhi_range(self):
        bal = StrokeCategoryBalance.from_counts(
            {"a": 60, "b": 25, "c": 15})
        r = bal.report()
        assert 1 / 3 <= r.herfindahl_index <= 1.0


# ── starvation detection ──────────────────────────────────────────────

class TestStarvation:

    def test_no_starvation_when_uniform(self):
        bal = StrokeCategoryBalance.from_counts(
            {"a": 33, "b": 34, "c": 33})
        r = bal.report()
        assert r.starved_categories == []

    def test_starvation_detected(self):
        bal = StrokeCategoryBalance.from_counts(
            {"thought": 950, "note": 20, "devlog": 10,
             "garden": 10, "metrics": 5, "snippet": 5})
        r = bal.report()
        assert len(r.starved_categories) > 0
        # all starved categories should have fraction < threshold
        threshold = 1.0 / (2 * r.richness)
        for c in r.starved_categories:
            assert r.category_fractions[c] < threshold

    def test_starvation_suggests_lowest(self):
        bal = StrokeCategoryBalance.from_counts(
            {"thought": 900, "note": 50, "devlog": 30,
             "garden": 10, "metrics": 5, "snippet": 5})
        r = bal.report()
        suggestion = r.suggest_next_category()
        assert suggestion is not None
        assert suggestion in r.starved_categories


# ── corpus integration ────────────────────────────────────────────────

class TestCorpusIntegration:

    def test_real_corpus_balance(self):
        """Smoke test against the actual strokes.jsonl if it exists."""
        path = Path("data/strokes.jsonl")
        if not path.exists():
            pytest.skip("data/strokes.jsonl not available")
        bal = StrokeCategoryBalance.from_jsonl(path)
        r = bal.report()
        assert r.total_strokes > 100
        assert r.richness >= 2
        assert 0.0 <= r.entropy_ratio <= 1.0
        assert r.dominant_fraction > 0.5  # thought dominates
        # to_dict should serialise cleanly
        d = r.to_dict()
        assert "suggestion" in d
