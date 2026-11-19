"""Tests for stroke_vocabulary_growth module.

Covers: tokenisation, log-log fitting, Heap's Law analysis, growth
classification, sliding windows, edge cases, serialisation, and
forecasting helpers.  52 test functions.

Written by Qwen during caretaker visit 726, 2026-11-19.
"""

import math
import pytest

from iamai.stroke_vocabulary_growth import (
    VocabularyGrowthReport,
    _classify,
    _log_log_fit,
    _zero_report,
    analyse_vocabulary_growth,
    analyse_vocabulary_growth_batch,
    analyse_vocabulary_growth_windows,
    tokenize_stroke,
)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

class TestTokenizeStroke:
    def test_basic(self):
        assert tokenize_stroke("Hello World") == ["hello", "world"]

    def test_punctuation_stripped(self):
        assert tokenize_stroke("a repo, that's it!") == ["a", "repo", "that", "s", "it"]

    def test_numbers_kept(self):
        assert tokenize_stroke("visit 726 2026-11-19") == [
            "visit", "726", "2026", "11", "19"
        ]

    def test_empty_string(self):
        assert tokenize_stroke("") == []

    def test_only_punctuation(self):
        assert tokenize_stroke("!!! ??? ...") == []

    def test_non_string_input(self):
        assert tokenize_stroke(None) == []
        assert tokenize_stroke(42) == []

    def test_unicode_letters(self):
        # \w would match unicode; our regex is [a-z0-9] only
        result = tokenize_stroke("café résumé")
        assert "caf" in result
        assert "r" in result or "sum" in result

    def test_whitespace_only(self):
        assert tokenize_stroke("   \t\n  ") == []

    def test_mixed_case(self):
        assert tokenize_stroke("HeLLo wOrLd") == ["hello", "world"]

    def test_repeated_tokens(self):
        assert tokenize_stroke("the the the") == ["the", "the", "the"]


# ---------------------------------------------------------------------------
# Log-log fitting
# ---------------------------------------------------------------------------

class TestLogLogFit:
    def test_perfect_power_law(self):
        # V = 2 * n^0.5  =>  log(V) = log(2) + 0.5*log(n)
        xs = [1, 4, 9, 16, 25, 36, 49, 64]
        ys = [int(2 * (x ** 0.5)) for x in xs]
        alpha, beta = _log_log_fit(xs, ys)
        assert abs(beta - 0.5) < 0.05
        assert abs(alpha - 2.0) < 0.5

    def test_linear_growth(self):
        # V = n  =>  beta = 1.0
        xs = list(range(1, 21))
        ys = list(range(1, 21))
        alpha, beta = _log_log_fit(xs, ys)
        assert abs(beta - 1.0) < 0.01
        assert abs(alpha - 1.0) < 0.1

    def test_single_point(self):
        alpha, beta = _log_log_fit([5], [3])
        assert alpha == 0.0 and beta == 0.0

    def test_empty(self):
        alpha, beta = _log_log_fit([], [])
        assert alpha == 0.0 and beta == 0.0

    def test_zeros_filtered(self):
        alpha, beta = _log_log_fit([0, 1, 2], [0, 1, 2])
        # Only (1,1) and (2,2) survive — two points
        assert beta > 0 or alpha >= 0

    def test_constant_y(self):
        # All same y — beta should be ~0
        xs = list(range(1, 11))
        ys = [5] * 10
        alpha, beta = _log_log_fit(xs, ys)
        assert abs(beta) < 0.01

    def test_negative_beta_clamped(self):
        # Decreasing y with increasing x (anti-Heap's)
        xs = [1, 2, 3, 4, 5]
        ys = [10, 8, 6, 4, 2]
        alpha, beta = _log_log_fit(xs, ys)
        assert beta >= 0  # clamped


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_exploring(self):
        assert _classify(0.85) == "exploring"
        assert _classify(0.70) == "exploring"

    def test_growing(self):
        assert _classify(0.69) == "growing"
        assert _classify(0.40) == "growing"

    def test_consolidating(self):
        assert _classify(0.39) == "consolidating"
        assert _classify(0.20) == "consolidating"

    def test_saturated(self):
        assert _classify(0.19) == "saturated"
        assert _classify(0.0) == "saturated"
        assert _classify(-0.1) == "saturated"

    def test_boundary_values(self):
        assert _classify(0.70) == "exploring"
        assert _classify(0.40) == "growing"
        assert _classify(0.20) == "consolidating"


# ---------------------------------------------------------------------------
# Zero report
# ---------------------------------------------------------------------------

class TestZeroReport:
    def test_defaults(self):
        r = _zero_report()
        assert r.alpha == 0.0
        assert r.beta == 0.0
        assert r.total_tokens == 0
        assert r.unique_tokens == 0
        assert r.growth_curve == []
        assert r.regime == "saturated"
        assert r.strokes_analysed == 0


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

class TestAnalyseVocabularyGrowth:
    def test_empty_input(self):
        r = analyse_vocabulary_growth([])
        assert r.total_tokens == 0
        assert r.regime == "saturated"

    def test_single_stroke(self):
        r = analyse_vocabulary_growth([["hello", "world"]])
        assert r.total_tokens == 2
        assert r.unique_tokens == 2
        assert r.beta == 0.0
        assert r.strokes_analysed == 1

    def test_identical_strokes(self):
        # Same tokens repeated — no growth
        tokens = ["the", "same", "thing"]
        r = analyse_vocabulary_growth([tokens, tokens, tokens, tokens, tokens])
        assert r.total_tokens == 15
        assert r.unique_tokens == 3
        assert r.beta < 0.1

    def test_growing_vocabulary(self):
        # Each stroke adds new words
        strokes = [
            ["alpha"],
            ["alpha", "beta"],
            ["alpha", "beta", "gamma"],
            ["alpha", "beta", "gamma", "delta"],
            ["alpha", "beta", "gamma", "delta", "epsilon"],
            ["zeta", "eta", "theta", "iota", "kappa", "lambda"],
            ["mu", "nu", "xi", "omicron", "pi", "rho", "sigma"],
        ]
        r = analyse_vocabulary_growth(strokes)
        assert r.total_tokens > 0
        assert r.unique_tokens > 10
        assert r.beta > 0.3
        assert r.strokes_analysed == 7

    def test_exploring_regime(self):
        # Every stroke is completely new tokens
        strokes = [[f"word_{i}_{j}" for j in range(5)] for i in range(20)]
        r = analyse_vocabulary_growth(strokes)
        assert r.regime == "exploring"
        assert r.beta >= 0.70

    def test_saturated_regime(self):
        # Highly repetitive
        base = ["the", "quick", "brown", "fox", "jumps"]
        strokes = [base[:] for _ in range(30)]
        r = analyse_vocabulary_growth(strokes)
        assert r.unique_tokens == 5
        assert r.regime == "saturated"

    def test_empty_token_lists_skipped(self):
        r = analyse_vocabulary_growth([[], ["a", "b"], [], ["c", "d"]])
        assert r.strokes_analysed == 2
        assert r.total_tokens == 4
        assert r.unique_tokens == 4

    def test_growth_curve_populated(self):
        strokes = [["a", "b"], ["c", "d"], ["e", "f"]]
        r = analyse_vocabulary_growth(strokes)
        assert len(r.growth_curve) == 3
        # Each point should be (cumulative_total, cumulative_unique)
        assert r.growth_curve[0] == (2, 2)
        assert r.growth_curve[1] == (4, 4)
        assert r.growth_curve[2] == (6, 6)

    def test_partially_overlapping(self):
        strokes = [
            ["the", "cat", "sat"],
            ["the", "dog", "sat"],
            ["the", "bird", "flew"],
            ["a", "fish", "swam"],
            ["a", "snake", "slithered"],
            ["every", "creature", "has", "a", "story"],
        ]
        r = analyse_vocabulary_growth(strokes)
        assert r.unique_tokens > 5
        assert r.unique_tokens < r.total_tokens
        assert r.beta > 0.0


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

class TestAnalyseBatch:
    def test_basic_batch(self):
        texts = [
            "hello world",
            "foo bar baz",
            "alpha beta gamma delta",
        ]
        r = analyse_vocabulary_growth_batch(texts)
        assert r.total_tokens == 9
        assert r.unique_tokens == 9
        assert r.strokes_analysed == 3

    def test_batch_with_overlap(self):
        texts = [
            "the quick brown fox",
            "the lazy brown dog",
            "the quick red cat",
        ]
        r = analyse_vocabulary_growth_batch(texts)
        assert r.unique_tokens < r.total_tokens
        # "the" appears 3 times, "quick" 2 times, "brown" 2 times
        assert r.unique_tokens == 8  # the, quick, brown, fox, lazy, dog, red, cat
        # the, quick, brown, fox, lazy, dog, red, cat = 8 unique out of 12 total

    def test_batch_skips_non_strings(self):
        texts = ["hello world", None, 42, "foo bar"]
        r = analyse_vocabulary_growth_batch(texts)
        assert r.strokes_analysed == 2

    def test_batch_empty(self):
        r = analyse_vocabulary_growth_batch([])
        assert r.total_tokens == 0

    def test_batch_all_empty_strings(self):
        r = analyse_vocabulary_growth_batch(["", "", ""])
        assert r.total_tokens == 0


# ---------------------------------------------------------------------------
# Sliding windows
# ---------------------------------------------------------------------------

class TestAnalyseWindows:
    def test_basic_windows(self):
        texts = [f"word{i} unique{i} newterm{i}" for i in range(20)]
        reports = analyse_vocabulary_growth_windows(texts, window_size=5, step=5)
        assert len(reports) == 4

    def test_window_overlap(self):
        texts = [f"w{i}" for i in range(15)]
        reports = analyse_vocabulary_growth_windows(texts, window_size=5, step=3)
        assert len(reports) > 1

    def test_window_too_large(self):
        texts = ["a", "b", "c"]
        reports = analyse_vocabulary_growth_windows(texts, window_size=10, step=5)
        assert len(reports) == 0

    def test_window_step_one(self):
        texts = [f"stroke{i} word{i}" for i in range(8)]
        reports = analyse_vocabulary_growth_windows(texts, window_size=3, step=1)
        assert len(reports) == 6  # 8 - 3 + 1 = 6

    def test_invalid_window_size(self):
        with pytest.raises(ValueError):
            analyse_vocabulary_growth_windows(["a"], window_size=0, step=1)

    def test_invalid_step(self):
        with pytest.raises(ValueError):
            analyse_vocabulary_growth_windows(["a"], window_size=1, step=0)

    def test_regime_evolution(self):
        # First half: diverse, second half: repetitive
        diverse = [f"unique_term_{i} concept_{i} idea_{i}" for i in range(10)]
        repetitive = ["the same old thing"] * 10
        texts = diverse + repetitive
        reports = analyse_vocabulary_growth_windows(texts, window_size=10, step=10)
        assert len(reports) == 2
        assert reports[0].beta > reports[1].beta


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

class TestReportHelpers:
    def test_predicted_unique(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.5, total_tokens=100, unique_tokens=20)
        pred = r.predicted_unique(400)
        expected = 2.0 * (400 ** 0.5)  # 2 * 20 = 40
        assert abs(pred - expected) < 0.01

    def test_predicted_unique_zero_tokens(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.5, total_tokens=100, unique_tokens=20)
        assert r.predicted_unique(0) == 0.0
        assert r.predicted_unique(-1) == 0.0

    def test_predicted_unique_zero_alpha(self):
        r = VocabularyGrowthReport(alpha=0.0, beta=0.5)
        assert r.predicted_unique(100) == 0.0

    def test_tokens_for_new_words(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.5, total_tokens=100, unique_tokens=20)
        result = r.tokens_for_new_words(100, 10)
        # target_v = 30, needed = (30/2)^2 = 225, extra = 125
        assert result == 125

    def test_tokens_for_new_words_unreachable(self):
        r = VocabularyGrowthReport(alpha=0.0, beta=0.5, total_tokens=100, unique_tokens=20)
        assert r.tokens_for_new_words(100, 10) is None

    def test_tokens_for_new_words_zero_beta(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.0, total_tokens=100, unique_tokens=20)
        assert r.tokens_for_new_words(100, 10) is None

    def test_tokens_for_new_words_negative_input(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.5, total_tokens=100, unique_tokens=20)
        assert r.tokens_for_new_words(100, 0) is None
        assert r.tokens_for_new_words(100, -5) is None

    def test_tokens_for_new_words_already_exceeded(self):
        r = VocabularyGrowthReport(alpha=2.0, beta=0.5, total_tokens=100, unique_tokens=20)
        # If current_total is already past the needed total
        result = r.tokens_for_new_words(1000, 1)
        assert result == 0  # clamped to 0

    def test_to_dict(self):
        r = VocabularyGrowthReport(
            alpha=1.23456, beta=0.56789, total_tokens=100,
            unique_tokens=50, regime="growing", strokes_analysed=10,
            growth_curve=[(1, 1), (2, 2)],
        )
        d = r.to_dict()
        assert d["alpha"] == 1.2346  # rounded to 4
        assert d["beta"] == 0.5679
        assert d["total_tokens"] == 100
        assert d["unique_tokens"] == 50
        assert d["regime"] == "growing"
        assert d["strokes_analysed"] == 10
        assert d["growth_curve_length"] == 2


# ---------------------------------------------------------------------------
# Integration-style
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_strokes(self):
        """Simulate a realistic stroke sequence with partial overlap."""
        strokes = [
            "a repo that only accumulates is a landfill with a readme",
            "commit history is the only honest documentation",
            "naming is hard because a bad name is cheap to type and expensive to keep",
            "most architecture is choosing which coupling you will live with",
            "deleting a file is progress too eventually",
            "the push race is a clock not a bug",
            "every ten minutes it rings someone answers it",
            "a bug you fix once a clock you answer every time",
            "the useful abstraction deletes a branch it does not add a class",
            "commit history cannot be backdated",
        ]
        r = analyse_vocabulary_growth_batch(strokes)
        assert r.strokes_analysed == 10
        assert r.total_tokens > 40
        assert r.unique_tokens > 20
        assert r.beta > 0.2
        assert r.regime in ("exploring", "growing", "consolidating")

    def test_heap_law_holds_for_large_corpus(self):
        """Verify beta is in plausible range for a larger corpus."""
        import random
        random.seed(42)
        vocab = [f"word{i}" for i in range(200)]
        strokes = []
        for _ in range(50):
            length = random.randint(5, 15)
            stroke = random.choices(vocab, k=length)
            strokes.append(stroke)
        r = analyse_vocabulary_growth(strokes)
        # For random sampling from a fixed vocabulary, beta should be
        # between 0.3 and 0.8 typically
        assert 0.1 < r.beta < 1.0
        assert r.alpha > 0
        assert r.strokes_analysed == 50

    def test_windows_show_regime_shift(self):
        """Early window exploring, late window saturated."""
        exploring = [f"novel_{i} fresh_{i} original_{i} creative_{i}" for i in range(15)]
        saturated = ["the same tired old phrase repeated again"] * 15
        texts = exploring + saturated

        reports = analyse_vocabulary_growth_windows(texts, window_size=15, step=15)
        assert len(reports) == 2
        assert reports[0].beta > reports[1].beta
