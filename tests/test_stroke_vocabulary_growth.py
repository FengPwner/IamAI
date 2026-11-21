"""Tests for iamai.stroke_vocabulary_growth — vocabulary growth tracking."""

from __future__ import annotations

import pytest

from iamai.stroke_vocabulary_growth import (
    _split_words,
    _tokenise,
    classify_growth,
    compute_ttr,
    growth_summary,
    moving_ttr,
    novel_words,
    vocabulary_growth,
)


# ---------------------------------------------------------------------------
# _tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic_tokenisation(self):
        tokens = _tokenise("Hello World from Python")
        assert "hello" in tokens
        assert "world" in tokens
        assert "python" in tokens

    def test_stop_words_removed(self):
        tokens = _tokenise("the quick brown fox is a very fast animal")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "very" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens

    def test_single_char_removed(self):
        tokens = _tokenise("I am a x y z developer")
        assert "x" not in tokens
        assert "y" not in tokens
        assert "z" not in tokens
        assert "developer" in tokens

    def test_empty_string(self):
        assert _tokenise("") == []

    def test_punctuation_stripped(self):
        tokens = _tokenise("hello, world! testing... done?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens
        assert "done" in tokens

    def test_numbers_kept(self):
        tokens = _tokenise("version 42 release 3")
        assert "42" in tokens
        assert "release" in tokens

    def test_contractions_handled(self):
        tokens = _tokenise("don't won't can't")
        # After stop-word removal, these may or may not remain
        # but they should not crash
        assert isinstance(tokens, list)

    def test_case_insensitive(self):
        tokens = _tokenise("PYTHON Python python")
        # All should become "python"
        assert tokens.count("python") == 3


# ---------------------------------------------------------------------------
# compute_ttr
# ---------------------------------------------------------------------------


class TestComputeTTR:
    def test_all_unique(self):
        assert compute_ttr(["alpha", "beta", "gamma"]) == pytest.approx(1.0)

    def test_all_same(self):
        assert compute_ttr(["alpha"] * 10) == pytest.approx(0.1)

    def test_half_unique(self):
        words = ["alpha", "beta", "alpha", "beta"]
        assert compute_ttr(words) == pytest.approx(0.5)

    def test_empty(self):
        assert compute_ttr([]) == 0.0

    def test_single_word(self):
        assert compute_ttr(["alpha"]) == pytest.approx(1.0)

    def test_two_different(self):
        assert compute_ttr(["alpha", "beta"]) == pytest.approx(1.0)

    def test_known_ratio(self):
        # 3 unique out of 4 = 0.75
        assert compute_ttr(["a1", "a2", "a3", "a1"]) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# moving_ttr
# ---------------------------------------------------------------------------


class TestMovingTTR:
    def test_output_length(self):
        strokes = [{"text": "alpha beta gamma delta"}] * 10
        result = moving_ttr(strokes, window_size=3)
        assert len(result) == 10

    def test_empty_input(self):
        assert moving_ttr([]) == []

    def test_uniform_content(self):
        # Same content everywhere → interior TTR values should be consistent
        strokes = [{"text": "alpha beta gamma"}] * 20
        result = moving_ttr(strokes, window_size=5)
        # Edge values differ due to smaller windows; interior should match
        interior = result[3:-3]  # skip edges
        assert len(interior) > 0
        assert len(set(round(v, 4) for v in interior)) == 1

    def test_diverse_content_higher_ttr(self):
        uniform = [{"text": "alpha alpha alpha"}] * 10
        diverse = [{"text": f"word{i} unique{i} special{i}"} for i in range(10)]
        ttr_uniform = moving_ttr(uniform, window_size=3)
        ttr_diverse = moving_ttr(diverse, window_size=3)
        assert sum(ttr_diverse) / len(ttr_diverse) > sum(ttr_uniform) / len(ttr_uniform)

    def test_single_stroke(self):
        strokes = [{"text": "hello world testing"}]
        result = moving_ttr(strokes, window_size=5)
        assert len(result) == 1
        assert result[0] > 0


# ---------------------------------------------------------------------------
# novel_words
# ---------------------------------------------------------------------------


class TestNovelWords:
    def test_basic_novelty(self):
        result = novel_words(["alpha", "beta", "gamma"], ["alpha", "delta"])
        assert result == {"beta", "gamma"}

    def test_no_novel_words(self):
        result = novel_words(["alpha", "beta"], ["alpha", "beta", "gamma"])
        assert result == set()

    def test_all_novel(self):
        result = novel_words(["x", "y", "z"], ["a", "b", "c"])
        assert result == {"x", "y", "z"}

    def test_empty_recent(self):
        result = novel_words([], ["alpha", "beta"])
        assert result == set()

    def test_empty_baseline(self):
        result = novel_words(["alpha", "beta"], [])
        assert result == {"alpha", "beta"}

    def test_both_empty(self):
        result = novel_words([], [])
        assert result == set()


# ---------------------------------------------------------------------------
# classify_growth
# ---------------------------------------------------------------------------


class TestClassifyGrowth:
    def test_expanding(self):
        assert classify_growth(0.05, 0.2) == "expanding"

    def test_stable(self):
        assert classify_growth(0.01, 0.2) == "stable"

    def test_contracting(self):
        assert classify_growth(-0.04, 0.2) == "contracting"

    def test_depleted(self):
        assert classify_growth(0.01, 0.02) == "depleted"

    def test_depleted_overrides_expanding(self):
        # Even with positive growth, if novel ratio is tiny → depleted
        assert classify_growth(0.05, 0.03) == "depleted"

    def test_boundary_expanding(self):
        assert classify_growth(0.021, 0.1) == "expanding"

    def test_boundary_contracting(self):
        assert classify_growth(-0.021, 0.1) == "contracting"

    def test_boundary_stable(self):
        assert classify_growth(0.02, 0.1) == "stable"

    def test_zero_growth(self):
        assert classify_growth(0.0, 0.1) == "stable"


# ---------------------------------------------------------------------------
# vocabulary_growth
# ---------------------------------------------------------------------------


class TestVocabularyGrowth:
    def _make_strokes(self, texts: list[str]) -> list[dict]:
        return [{"seq": i + 1, "text": t} for i, t in enumerate(texts)]

    def test_expanding_vocabulary(self):
        # First half: repetitive; second half: diverse
        first = ["alpha beta alpha beta"] * 20
        second = [f"novel{i} unique{i} special{i} fresh{i}" for i in range(20)]
        strokes = self._make_strokes(first + second)
        result = vocabulary_growth(strokes, window=40)
        assert result["band"] in ("expanding", "stable")
        assert result["novel_word_count"] > 0
        assert result["stroke_count"] == 40

    def test_contracting_vocabulary(self):
        # First half: diverse; second half: repetitive
        first = [f"word{i} distinct{i} original{i}" for i in range(20)]
        second = ["alpha beta alpha beta"] * 20
        strokes = self._make_strokes(first + second)
        result = vocabulary_growth(strokes, window=40)
        assert result["growth_rate"] < 0

    def test_empty_strokes(self):
        result = vocabulary_growth([], window=100)
        assert result["band"] == "stable"
        assert result["total_words"] == 0

    def test_very_few_words(self):
        strokes = self._make_strokes(["hi", "ok"])
        result = vocabulary_growth(strokes, window=10)
        assert result["band"] == "stable"

    def test_window_truncation(self):
        # 200 strokes but window=50
        strokes = self._make_strokes(
            [f"word{i} test{i} sample{i}" for i in range(200)]
        )
        result = vocabulary_growth(strokes, window=50)
        assert result["stroke_count"] == 50

    def test_all_keys_present(self):
        strokes = self._make_strokes(["hello world test"] * 10)
        result = vocabulary_growth(strokes, window=10)
        expected_keys = {
            "band", "ttr_first_half", "ttr_second_half", "growth_rate",
            "novel_word_count", "novel_word_ratio", "total_words",
            "unique_words", "overall_ttr", "stroke_count",
        }
        assert set(result.keys()) == expected_keys

    def test_custom_text_key(self):
        strokes = [{"content": "alpha beta gamma"}] * 10
        result = vocabulary_growth(strokes, window=10, text_key="content")
        assert result["total_words"] > 0

    def test_depleted_vocabulary(self):
        # Use the same few words everywhere
        strokes = self._make_strokes(["alpha beta"] * 100)
        result = vocabulary_growth(strokes, window=100)
        # With identical halves, growth_rate ≈ 0 and novel_ratio ≈ 0
        assert result["novel_word_ratio"] < 0.05

    def test_novel_word_ratio_range(self):
        strokes = self._make_strokes(
            [f"word{i} data{i}" for i in range(50)]
        )
        result = vocabulary_growth(strokes, window=50)
        assert 0.0 <= result["novel_word_ratio"] <= 1.0

    def test_ttr_values_bounded(self):
        strokes = self._make_strokes(
            [f"alpha beta gamma {i}" for i in range(40)]
        )
        result = vocabulary_growth(strokes, window=40)
        assert 0.0 <= result["ttr_first_half"] <= 1.0
        assert 0.0 <= result["ttr_second_half"] <= 1.0
        assert 0.0 <= result["overall_ttr"] <= 1.0

    def test_growth_rate_matches_difference(self):
        strokes = self._make_strokes(
            [f"word{i} test content" for i in range(30)]
        )
        result = vocabulary_growth(strokes, window=30)
        expected = round(result["ttr_second_half"] - result["ttr_first_half"], 4)
        assert result["growth_rate"] == expected


# ---------------------------------------------------------------------------
# growth_summary
# ---------------------------------------------------------------------------


class TestGrowthSummary:
    def test_returns_string(self):
        strokes = [{"text": f"hello world test{i}"} for i in range(20)]
        text = growth_summary(strokes, window=20)
        assert isinstance(text, str)

    def test_contains_band(self):
        strokes = [{"text": f"hello world test{i}"} for i in range(20)]
        text = growth_summary(strokes, window=20)
        first_word = text.split(" ")[0]
        assert first_word in ("expanding", "stable", "contracting", "depleted")

    def test_contains_ttr_arrow(self):
        strokes = [{"text": f"data sample unique{i}"} for i in range(30)]
        text = growth_summary(strokes, window=30)
        assert "→" in text or "->" in text or "TTR" in text

    def test_contains_novel_count(self):
        strokes = [{"text": f"alpha beta gamma{i}"} for i in range(30)]
        text = growth_summary(strokes, window=30)
        assert "novel words" in text

    def test_empty_input(self):
        text = growth_summary([], window=10)
        assert isinstance(text, str)
        assert "stable" in text


# ---------------------------------------------------------------------------
# _split_words
# ---------------------------------------------------------------------------


class TestSplitWords:
    def test_equal_split(self):
        strokes = [{"text": "alpha beta gamma delta"}]
        baseline, recent = _split_words(strokes)
        # "alpha beta gamma delta" → 4 tokens → split at 2
        assert len(baseline) + len(recent) == 4

    def test_empty(self):
        baseline, recent = _split_words([])
        assert baseline == []
        assert recent == []

    def test_custom_text_key(self):
        strokes = [{"content": "hello world"}]
        baseline, recent = _split_words(strokes, text_key="content")
        assert len(baseline) + len(recent) == 2
