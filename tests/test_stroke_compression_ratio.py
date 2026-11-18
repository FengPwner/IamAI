#!/usr/bin/env python3
"""Tests for stroke_compression_ratio.py — information density analysis."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_compression_ratio import (
    CompressionReport,
    StrokeScore,
    _linear_slope,
    _pearson,
    _tokenize,
    analyze_corpus,
    compress_ratio,
    grade_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stroke(text: str, kind: str = "thought", seq: int = 0) -> dict:
    """Build a minimal stroke dict."""
    return {"text": text, "kind": kind, "seq": seq, "at": "2026-11-18T12:00:00+00:00"}


def _corpus(texts: list[str], kind: str = "thought") -> list[dict]:
    """Build a corpus of strokes from a list of texts."""
    return [_stroke(t, kind=kind, seq=i) for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []

    def test_simple(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_case_insensitive(self):
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_strip_punctuation(self):
        assert _tokenize("hello, world! how's it?") == [
            "hello", "world", "how's", "it"
        ]

    def test_numbers(self):
        assert _tokenize("stroke 42 in 2026") == ["stroke", "42", "in", "2026"]

    def test_extra_whitespace(self):
        assert _tokenize("  hello   world  ") == ["hello", "world"]

    def test_apostrophes(self):
        assert _tokenize("don't won't can't") == ["don't", "won't", "can't"]

    def test_unicode_passthrough(self):
        # Non-ASCII letters are not captured by [a-zA-Z]
        result = _tokenize("café world")
        assert "world" in result
        # "café" → "caf" and "é" is stripped (the é is outside [a-zA-Z])
        assert "caf" in result


# ---------------------------------------------------------------------------
# compress_ratio
# ---------------------------------------------------------------------------

class TestCompressRatio:
    def test_empty_text(self):
        assert compress_ratio("") == 1.0

    def test_all_unique(self):
        assert compress_ratio("hello world foo bar") == 1.0

    def test_all_same(self):
        # "go go go go" → 1 unique / 4 total = 0.25
        assert compress_ratio("go go go go") == pytest.approx(0.25)

    def test_partial_repeat(self):
        # "the cat sat on the mat" → 5 unique / 6 total
        assert compress_ratio("the cat sat on the mat") == pytest.approx(5 / 6)

    def test_single_word(self):
        assert compress_ratio("hello") == 1.0

    def test_single_repeated(self):
        assert compress_ratio("a a a") == pytest.approx(1 / 3)

    def test_case_insensitive_repeat(self):
        # "Hello hello HELLO" → 1 unique / 3 total
        assert compress_ratio("Hello hello HELLO") == pytest.approx(1 / 3)

    def test_mixed_punctuation(self):
        # "is it? it is!" → {"is", "it"} → 2/4 = 0.5
        assert compress_ratio("is it? it is!") == pytest.approx(0.5)

    def test_longer_text_reasonable(self):
        text = "the quick brown fox jumps over the lazy dog"
        # tokens: the quick brown fox jumps over the lazy dog → 8 unique / 9 total
        assert compress_ratio(text) == pytest.approx(8 / 9)


# ---------------------------------------------------------------------------
# grade_ratio
# ---------------------------------------------------------------------------

class TestGradeRatio:
    def test_grade_a(self):
        assert grade_ratio(0.95) == "A"
        assert grade_ratio(0.80) == "A"

    def test_grade_b(self):
        assert grade_ratio(0.79) == "B"
        assert grade_ratio(0.60) == "B"

    def test_grade_c(self):
        assert grade_ratio(0.59) == "C"
        assert grade_ratio(0.40) == "C"

    def test_grade_d(self):
        assert grade_ratio(0.39) == "D"
        assert grade_ratio(0.20) == "D"

    def test_grade_f(self):
        assert grade_ratio(0.19) == "F"
        assert grade_ratio(0.0) == "F"

    def test_boundary_values(self):
        assert grade_ratio(1.0) == "A"
        assert grade_ratio(0.0) == "F"


# ---------------------------------------------------------------------------
# StrokeScore
# ---------------------------------------------------------------------------

class TestStrokeScore:
    def test_grade_method(self):
        s = StrokeScore(seq=1, text="hello world", kind="thought",
                        total_tokens=2, unique_tokens=2, ratio=1.0)
        assert s.grade() == "A"

    def test_grade_low(self):
        s = StrokeScore(seq=1, text="go go go", kind="note",
                        total_tokens=3, unique_tokens=1, ratio=0.33)
        assert s.grade() == "D"


# ---------------------------------------------------------------------------
# _pearson
# ---------------------------------------------------------------------------

class TestPearson:
    def test_empty(self):
        assert _pearson([], []) == 0.0

    def test_single_point(self):
        assert _pearson([1.0], [2.0]) == 0.0

    def test_perfect_positive(self):
        xs = [1, 2, 3, 4, 5]
        ys = [2, 4, 6, 8, 10]
        assert _pearson(xs, ys) == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative(self):
        xs = [1, 2, 3, 4, 5]
        ys = [10, 8, 6, 4, 2]
        assert _pearson(xs, ys) == pytest.approx(-1.0, abs=1e-6)

    def test_no_correlation(self):
        xs = [1, 2, 3, 4]
        ys = [1, 1, 1, 1]
        assert _pearson(xs, ys) == 0.0

    def test_realistic(self):
        xs = [10, 20, 30, 40, 50]
        ys = [0.8, 0.7, 0.6, 0.5, 0.4]
        assert _pearson(xs, ys) == pytest.approx(-1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# _linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope:
    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_single(self):
        assert _linear_slope([5.0]) == 0.0

    def test_flat(self):
        assert _linear_slope([3.0, 3.0, 3.0, 3.0]) == 0.0

    def test_positive_slope(self):
        # y = 2x + 1 → slope = 2.0
        ys = [1, 3, 5, 7, 9]
        assert _linear_slope(ys) == pytest.approx(2.0, abs=1e-6)

    def test_negative_slope(self):
        # y = -0.5x + 10
        ys = [10, 9.5, 9, 8.5, 8]
        assert _linear_slope(ys) == pytest.approx(-0.5, abs=1e-6)

    def test_noisy(self):
        ys = [1.0, 2.1, 2.9, 4.2, 4.8]
        assert _linear_slope(ys) > 0.0


# ---------------------------------------------------------------------------
# analyze_corpus — basic
# ---------------------------------------------------------------------------

class TestAnalyzeCorpusBasic:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            analyze_corpus([])

    def test_single_stroke(self):
        strokes = _corpus(["hello world foo bar"])
        report = analyze_corpus(strokes)
        assert isinstance(report, CompressionReport)
        assert report.total_strokes == 1
        assert report.global_ratio == 1.0  # all unique

    def test_all_identical(self):
        strokes = _corpus(["go go go"] * 10)
        report = analyze_corpus(strokes)
        assert report.global_ratio == pytest.approx(1 / 3, abs=0.01)

    def test_global_ratio_calculation(self):
        # 3 strokes: "a b c" (1.0), "a a a" (1/3), "x y" (1.0)
        strokes = _corpus(["a b c", "a a a", "x y"])
        report = analyze_corpus(strokes)
        expected = (1.0 + 1 / 3 + 1.0) / 3
        assert report.global_ratio == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# analyze_corpus — kind_ratios
# ---------------------------------------------------------------------------

class TestKindRatios:
    def test_single_kind(self):
        strokes = _corpus(["hello world", "foo bar baz"], kind="note")
        report = analyze_corpus(strokes)
        assert "note" in report.kind_ratios
        assert report.kind_ratios["note"] == 1.0

    def test_multiple_kinds(self):
        strokes = [
            _stroke("hello world", kind="thought", seq=0),
            _stroke("go go go", kind="note", seq=1),
            _stroke("foo bar baz", kind="thought", seq=2),
        ]
        report = analyze_corpus(strokes)
        assert "thought" in report.kind_ratios
        assert "note" in report.kind_ratios
        assert report.kind_ratios["thought"] == 1.0
        assert report.kind_ratios["note"] == pytest.approx(1 / 3, abs=0.01)

    def test_kind_ordering(self):
        # kinds should be sorted alphabetically
        strokes = [
            _stroke("hello", kind="zeta", seq=0),
            _stroke("world", kind="alpha", seq=1),
        ]
        report = analyze_corpus(strokes)
        keys = list(report.kind_ratios.keys())
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# analyze_corpus — length_correlation
# ---------------------------------------------------------------------------

class TestLengthCorrelation:
    def test_longer_more_padded(self):
        # Short strokes are dense, long strokes repeat words
        strokes = _corpus([
            "hello world",
            "foo bar baz qux",
            "the the the the the the the the the the",
        ])
        report = analyze_corpus(strokes)
        assert report.length_correlation < 0.0  # longer → lower ratio

    def test_uniform(self):
        # All same length, same ratio
        strokes = _corpus(["a b c d"] * 5)
        report = analyze_corpus(strokes)
        # Zero variance in either dimension → 0.0
        assert report.length_correlation == 0.0


# ---------------------------------------------------------------------------
# analyze_corpus — recent_trend
# ---------------------------------------------------------------------------

class TestRecentTrend:
    def test_declining_density(self):
        # Start dense, end padded
        dense = ["hello world foo bar baz"] * 20
        padded = ["the the the the the the"] * 20
        strokes = _corpus(dense + padded)
        report = analyze_corpus(strokes)
        assert report.recent_trend < 0.0

    def test_stable_density(self):
        strokes = _corpus(["hello world foo bar"] * 40)
        report = analyze_corpus(strokes)
        assert report.recent_trend == 0.0

    def test_improving_density(self):
        padded = ["the the the the the the"] * 20
        dense = ["hello world foo bar baz"] * 20
        strokes = _corpus(padded + dense)
        report = analyze_corpus(strokes)
        assert report.recent_trend > 0.0

    def test_window_clamp(self):
        # Fewer strokes than window → use all
        strokes = _corpus(["hello world"] * 5)
        report = analyze_corpus(strokes, recent_window=100)
        assert isinstance(report.recent_trend, float)


# ---------------------------------------------------------------------------
# analyze_corpus — diminishing_returns
# ---------------------------------------------------------------------------

class TestDiminishingReturns:
    def test_all_same(self):
        strokes = _corpus(["hello world foo"] * 10)
        report = analyze_corpus(strokes)
        # All ratios identical → none below median → 0.0
        assert report.diminishing_returns == 0.0

    def test_second_half_worse(self):
        first = ["hello world foo bar baz"] * 5  # ratio = 1.0
        second = ["go go go go go"] * 5          # ratio = 0.2
        strokes = _corpus(first + second)
        report = analyze_corpus(strokes)
        # first-half median = 1.0, all second-half (0.2) < 1.0 → 1.0
        assert report.diminishing_returns == 1.0

    def test_second_half_better(self):
        first = ["go go go go go"] * 5          # ratio = 0.2
        second = ["hello world foo bar baz"] * 5  # ratio = 1.0
        strokes = _corpus(first + second)
        report = analyze_corpus(strokes)
        # first-half median = 0.2, second-half all 1.0 > 0.2 → 0.0
        assert report.diminishing_returns == 0.0

    def test_single_stroke(self):
        strokes = _corpus(["hello world"])
        report = analyze_corpus(strokes)
        # mid = 0 → returns 0.0
        assert report.diminishing_returns == 0.0


# ---------------------------------------------------------------------------
# analyze_corpus — worst_strokes
# ---------------------------------------------------------------------------

class TestWorstStrokes:
    def test_returns_worst(self):
        strokes = _corpus([
            "hello world foo bar baz",    # 1.0
            "go go go go go",              # 0.2
            "the the the",                 # 0.333
        ])
        report = analyze_corpus(strokes, worst_count=2)
        assert len(report.worst_strokes) == 2
        # Worst first
        assert report.worst_strokes[0][2] < report.worst_strokes[1][2]

    def test_text_truncation(self):
        long_text = "word " * 100
        strokes = _corpus([long_text])
        report = analyze_corpus(strokes)
        # Text should be truncated to 80 chars
        assert len(report.worst_strokes[0][1]) <= 80

    def test_worst_count_larger_than_corpus(self):
        strokes = _corpus(["hello world"])
        report = analyze_corpus(strokes, worst_count=10)
        assert len(report.worst_strokes) == 1


# ---------------------------------------------------------------------------
# analyze_corpus — mean_length
# ---------------------------------------------------------------------------

class TestMeanLength:
    def test_uniform(self):
        strokes = _corpus(["hello world"] * 5)
        report = analyze_corpus(strokes)
        assert report.mean_length == 2.0  # 2 tokens each

    def test_mixed(self):
        strokes = _corpus(["a", "b c d"])  # 1 and 3 tokens
        report = analyze_corpus(strokes)
        assert report.mean_length == 2.0  # (1+3)/2


# ---------------------------------------------------------------------------
# analyze_corpus — scores field
# ---------------------------------------------------------------------------

class TestScores:
    def test_scores_populated(self):
        strokes = _corpus(["hello world", "foo bar"])
        report = analyze_corpus(strokes)
        assert len(report.scores) == 2
        assert all(isinstance(s, StrokeScore) for s in report.scores)

    def test_scores_match_strokes(self):
        strokes = _corpus(["hello world foo"])
        report = analyze_corpus(strokes)
        s = report.scores[0]
        assert s.total_tokens == 3
        assert s.unique_tokens == 3
        assert s.ratio == 1.0


# ---------------------------------------------------------------------------
# Integration-style: realistic corpus
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_mixed_corpus(self):
        strokes = [
            _stroke("a repo that only accumulates is a landfill with a README",
                     kind="thought", seq=1),
            _stroke("round 40370  bloom 100.0%  plants  146/384",
                     kind="metrics", seq=2),
            _stroke("commit history is the only honest documentation",
                     kind="note", seq=3),
            _stroke("go go go go go go go go",
                     kind="snippet", seq=4),
            _stroke("naming is hard because a bad name is cheap to type",
                     kind="thought", seq=5),
            _stroke("the the the the the",
                     kind="devlog", seq=6),
        ]
        report = analyze_corpus(strokes)

        assert report.total_strokes == 6
        assert 0.0 < report.global_ratio <= 1.0
        assert "thought" in report.kind_ratios
        assert "metrics" in report.kind_ratios
        assert isinstance(report.worst_strokes, list)
        assert len(report.worst_strokes) <= 5

        # "go go go go go go go go" should be worst
        worst_seq = report.worst_strokes[0][0]
        assert worst_seq == 4

    def test_grade_consistency(self):
        """Report grade matches individual score grades."""
        strokes = _corpus(["hello world foo bar baz qux"])
        report = analyze_corpus(strokes)
        for s in report.scores:
            assert s.grade() == grade_ratio(s.ratio)
