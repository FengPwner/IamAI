"""Tests for snippets/stroke_diversity.py — caretaker visit 736.

Covers: shannon_entropy, max_entropy, window_diversity, diversity_stream,
classify_trend, diversity_report, edge cases.

Pure Python, no numpy/scipy.  Written by Qwen, 2026-11-20.
"""

import math
import pytest

from snippets.stroke_diversity import (
    classify_trend,
    diversity_report,
    diversity_stream,
    max_entropy,
    shannon_entropy,
    window_diversity,
)
from collections import Counter


# ── helpers ──────────────────────────────────────────────────────────────

def _strokes(kinds):
    """Build a list of stroke dicts from a list of kind strings."""
    return [{"kind": k, "seq": i} for i, k in enumerate(kinds)]


# ── shannon_entropy ──────────────────────────────────────────────────────

class TestShannonEntropy:
    def test_empty_counter(self):
        assert shannon_entropy(Counter()) == 0.0

    def test_single_category(self):
        assert shannon_entropy(Counter({"a": 10})) == 0.0

    def test_uniform_binary(self):
        # Two equally likely categories → 1 bit
        assert shannon_entropy(Counter({"a": 50, "b": 50})) == pytest.approx(1.0, abs=1e-9)

    def test_uniform_quaternary(self):
        # Four equally likely → 2 bits
        c = Counter({"a": 25, "b": 25, "c": 25, "d": 25})
        assert shannon_entropy(c) == pytest.approx(2.0, abs=1e-9)

    def test_skewed_distribution(self):
        c = Counter({"a": 97, "b": 1, "c": 1, "d": 1})
        ent = shannon_entropy(c)
        assert 0 < ent < 1.0  # far below max of 2 bits

    def test_all_zeros_in_counter(self):
        # Counter with keys but zero values (shouldn't happen in practice, but guard)
        assert shannon_entropy(Counter({"a": 0, "b": 0})) == 0.0


# ── max_entropy ──────────────────────────────────────────────────────────

class TestMaxEntropy:
    def test_zero_categories(self):
        assert max_entropy(0) == 0.0

    def test_one_category(self):
        assert max_entropy(1) == 0.0

    def test_two_categories(self):
        assert max_entropy(2) == pytest.approx(1.0)

    def test_eight_categories(self):
        assert max_entropy(8) == pytest.approx(3.0)


# ── window_diversity ─────────────────────────────────────────────────────

class TestWindowDiversity:
    def test_empty_strokes(self):
        result = window_diversity([])
        assert result["entropy"] == 0.0
        assert result["richness"] == 0
        assert result["normalised"] == 0.0

    def test_single_stroke(self):
        result = window_diversity(_strokes(["devlog"]))
        assert result["entropy"] == 0.0
        assert result["richness"] == 1
        assert result["normalised"] == 0.0

    def test_uniform_six_kinds(self):
        kinds = ["devlog", "garden", "metrics", "note", "snippet", "thought"] * 10
        result = window_diversity(_strokes(kinds))
        assert result["richness"] == 6
        assert result["normalised"] == pytest.approx(1.0, abs=0.01)
        assert result["entropy"] == pytest.approx(math.log2(6), abs=0.01)

    def test_dominance(self):
        kinds = ["devlog"] * 90 + ["garden"] * 10
        result = window_diversity(_strokes(kinds))
        assert result["dominance"]["kind"] == "devlog"
        assert result["dominance"]["share"] == pytest.approx(0.9, abs=0.01)

    def test_custom_kind_field(self):
        strokes = [{"type": "a"}, {"type": "b"}, {"type": "a"}, {"type": "b"}]
        result = window_diversity(strokes, kind_field="type")
        assert result["richness"] == 2
        assert result["normalised"] == pytest.approx(1.0)

    def test_missing_kind_field_defaults_to_unknown(self):
        strokes = [{"seq": 1}, {"seq": 2}]
        result = window_diversity(strokes)
        assert result["richness"] == 1
        assert "unknown" in result["counts"]


# ── diversity_stream ─────────────────────────────────────────────────────

class TestDiversityStream:
    def test_basic_sliding(self):
        kinds = ["devlog", "garden", "metrics", "note", "snippet", "thought"] * 10
        windows = diversity_stream(_strokes(kinds), window_size=12, step=6)
        assert len(windows) > 1
        for w in windows:
            assert "start" in w
            assert "end" in w
            assert "entropy" in w

    def test_window_larger_than_data(self):
        strokes = _strokes(["devlog", "garden"])
        windows = diversity_stream(strokes, window_size=100, step=10)
        assert len(windows) == 1
        assert windows[0]["richness"] == 2

    def test_invalid_window_size(self):
        with pytest.raises(ValueError):
            diversity_stream(_strokes(["a"]), window_size=0)

    def test_invalid_step(self):
        with pytest.raises(ValueError):
            diversity_stream(_strokes(["a"]), step=0)

    def test_expanding_diversity(self):
        """Start with one kind, gradually introduce more."""
        kinds = ["devlog"] * 20
        for i in range(5):
            kinds += ["garden"] * 4
        kinds += ["metrics", "note", "snippet", "thought"] * 5
        windows = diversity_stream(_strokes(kinds), window_size=20, step=10)
        entropies = [w["entropy"] for w in windows]
        assert entropies[-1] > entropies[0]

    def test_narrowing_diversity(self):
        """Start diverse, converge to one kind."""
        kinds = ["devlog", "garden", "metrics", "note", "snippet", "thought"] * 5
        kinds += ["devlog"] * 30
        windows = diversity_stream(_strokes(kinds), window_size=20, step=10)
        entropies = [w["entropy"] for w in windows]
        assert entropies[-1] < entropies[0]


# ── classify_trend ───────────────────────────────────────────────────────

class TestClassifyTrend:
    def test_insufficient_data(self):
        assert classify_trend([{"normalised": 0.5}]) == "insufficient_data"
        assert classify_trend([]) == "insufficient_data"

    def test_expanding(self):
        windows = [{"normalised": 0.2}, {"normalised": 0.5}, {"normalised": 0.9}]
        assert classify_trend(windows) == "expanding"

    def test_narrowing(self):
        windows = [{"normalised": 0.9}, {"normalised": 0.5}, {"normalised": 0.1}]
        assert classify_trend(windows) == "narrowing"

    def test_stable(self):
        windows = [{"normalised": 0.8}, {"normalised": 0.81}, {"normalised": 0.79}]
        assert classify_trend(windows) == "stable"


# ── diversity_report ─────────────────────────────────────────────────────

class TestDiversityReport:
    def test_full_report_structure(self):
        kinds = ["devlog", "garden", "metrics", "note", "snippet", "thought"] * 10
        report = diversity_report(_strokes(kinds), window_size=12, step=6)
        assert "overall" in report
        assert "windows" in report
        assert "trend" in report
        assert "total_strokes" in report
        assert report["total_strokes"] == 60
        assert report["window_size"] == 12
        assert report["step"] == 6

    def test_report_on_uniform_data(self):
        kinds = ["a", "b", "c", "d"] * 25
        report = diversity_report(_strokes(kinds))
        assert report["overall"]["richness"] == 4
        assert report["trend"] == "stable"

    def test_report_on_expanding_data(self):
        kinds = ["a"] * 30 + ["a", "b", "c", "d", "e", "f"] * 10
        report = diversity_report(_strokes(kinds), window_size=20, step=10)
        assert report["trend"] == "expanding"
