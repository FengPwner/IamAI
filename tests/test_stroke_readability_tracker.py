"""Tests for iamai/stroke_readability_tracker.py — readability tracking.

Run:  python3 -m pytest tests/test_stroke_readability_tracker.py -v

Written by Qwen during caretaker visit 731, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_readability_tracker import (  # noqa: E402
    ReadabilityReport,
    StrokeReadability,
    WindowReadability,
    _classify,
    _clamp,
    _FILLERS,
    analyse_readability_windows,
    analyse_stroke,
    analyse_stream,
    compute_readability_score,
    split_sentences,
    tokenise,
)


# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_single_sentence(self):
        result = split_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_multiple_sentences(self):
        result = split_sentences("First sentence. Second sentence. Third.")
        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[1] == "Second sentence."
        assert result[2] == "Third."

    def test_question_marks(self):
        result = split_sentences("What? Really? Yes.")
        assert len(result) == 3

    def test_exclamation_marks(self):
        result = split_sentences("Wow! Amazing! Great.")
        assert len(result) == 3

    def test_empty_string(self):
        assert split_sentences("") == []

    def test_whitespace_only(self):
        assert split_sentences("   ") == []

    def test_no_punctuation(self):
        result = split_sentences("just a fragment without ending")
        assert len(result) == 1

    def test_strips_whitespace(self):
        result = split_sentences("  Hello world.  ")
        assert result == ["Hello world."]


# ---------------------------------------------------------------------------
# tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        tokens = tokenise("Hello World")
        assert tokens == ["hello", "world"]

    def test_filters_punctuation(self):
        tokens = tokenise("Hello, world!")
        assert tokens == ["hello", "world"]

    def test_filters_numbers(self):
        tokens = tokenise("test 123 value")
        assert tokens == ["test", "value"]

    def test_lowercases(self):
        tokens = tokenise("UPPER CASE WORDS")
        assert tokens == ["upper", "case", "words"]

    def test_empty(self):
        assert tokenise("") == []

    def test_single_letter(self):
        tokens = tokenise("a b c")
        assert tokens == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _clamp
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_below_zero(self):
        assert _clamp(-10.0) == 0.0

    def test_above_hundred(self):
        assert _clamp(150.0) == 100.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0

    def test_custom_range(self):
        assert _clamp(-5, lo=0, hi=10) == 0
        assert _clamp(15, lo=0, hi=10) == 10


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_accessible(self):
        assert _classify(70.0) == "accessible"
        assert _classify(100.0) == "accessible"
        assert _classify(75.5) == "accessible"

    def test_balanced(self):
        assert _classify(40.0) == "balanced"
        assert _classify(69.9) == "balanced"
        assert _classify(55.0) == "balanced"

    def test_dense(self):
        assert _classify(20.0) == "dense"
        assert _classify(39.9) == "dense"
        assert _classify(25.0) == "dense"

    def test_impenetrable(self):
        assert _classify(0.0) == "impenetrable"
        assert _classify(19.9) == "impenetrable"
        assert _classify(5.0) == "impenetrable"


# ---------------------------------------------------------------------------
# compute_readability_score
# ---------------------------------------------------------------------------


class TestComputeReadabilityScore:
    def test_perfect_score(self):
        # Short sentences, short words, no long words, no fillers
        score = compute_readability_score(
            mean_sent_len=5.0,
            mean_word_len=3.0,
            long_word_frac=0.0,
            filler_ratio=0.0,
        )
        assert score == 100.0

    def test_long_sentences_penalised(self):
        score_short = compute_readability_score(5.0, 4.0, 0.0, 0.0)
        score_long = compute_readability_score(30.0, 4.0, 0.0, 0.0)
        assert score_short > score_long

    def test_long_words_penalised(self):
        score_short = compute_readability_score(10.0, 3.0, 0.0, 0.0)
        score_long = compute_readability_score(10.0, 8.0, 0.0, 0.0)
        assert score_short > score_long

    def test_long_word_fraction_penalised(self):
        score_low = compute_readability_score(10.0, 5.0, 0.0, 0.0)
        score_high = compute_readability_score(10.0, 5.0, 0.5, 0.0)
        assert score_low > score_high

    def test_filler_penalised(self):
        score_low = compute_readability_score(10.0, 5.0, 0.0, 0.0)
        score_high = compute_readability_score(10.0, 5.0, 0.0, 0.3)
        assert score_low > score_high

    def test_clamped_to_zero(self):
        score = compute_readability_score(100.0, 20.0, 1.0, 1.0)
        assert score >= 0.0

    def test_clamped_to_hundred(self):
        score = compute_readability_score(1.0, 1.0, 0.0, 0.0)
        assert score <= 100.0


# ---------------------------------------------------------------------------
# analyse_stroke
# ---------------------------------------------------------------------------


class TestAnalyseStroke:
    def test_simple_accessible_text(self):
        text = "The cat sat on the mat. It was a good day."
        result = analyse_stroke(text)
        assert isinstance(result, StrokeReadability)
        assert result.sentence_count == 2
        assert result.word_count > 0
        assert result.regime in ("accessible", "balanced", "dense", "impenetrable")
        assert 0 <= result.readability_score <= 100

    def test_empty_text(self):
        result = analyse_stroke("")
        assert result.word_count == 0
        assert result.sentence_count == 0
        assert result.readability_score == 100.0
        assert result.regime == "accessible"

    def test_single_word(self):
        result = analyse_stroke("hello")
        assert result.word_count == 1
        assert result.mean_word_length == 5.0

    def test_long_complex_text(self):
        text = (
            "The extraordinary philosophical ramifications of "
            "epistemological transformation fundamentally "
            "reconceptualised our understanding of phenomenological "
            "interpretation throughout the interdisciplinary framework."
        )
        result = analyse_stroke(text)
        assert result.long_word_fraction > 0.5
        assert result.readability_score < 50

    def test_filler_heavy_text(self):
        text = (
            "Well basically actually just really quite literally "
            "sort of perhaps maybe indeed truly essentially "
            "basically actually just really quite."
        )
        result = analyse_stroke(text)
        assert result.filler_ratio > 0.5

    def test_sentence_count(self):
        text = "One. Two. Three. Four. Five."
        result = analyse_stroke(text)
        assert result.sentence_count == 5

    def test_mean_sentence_length(self):
        text = "One two three. Four five six."
        result = analyse_stroke(text)
        assert result.mean_sentence_length == 3.0

    def test_long_word_fraction_zero(self):
        # All words <= 8 chars
        text = "cat dog fox run sit."
        result = analyse_stroke(text)
        assert result.long_word_fraction == 0.0

    def test_long_word_fraction_mixed(self):
        # "extraordinary" (13 chars) is > 8, "the" and "cat" are not
        text = "the extraordinary cat."
        result = analyse_stroke(text)
        # 1 out of 3 words is long
        assert abs(result.long_word_fraction - 1 / 3) < 0.01


# ---------------------------------------------------------------------------
# analyse_stream
# ---------------------------------------------------------------------------


class TestAnalyseStream:
    def test_empty(self):
        result = analyse_stream([])
        assert isinstance(result, ReadabilityReport)
        assert result.total_strokes == 0
        assert result.trend == "unknown"

    def test_single_stroke(self):
        result = analyse_stream(["Hello world."])
        assert result.total_strokes == 1
        assert result.trend == "stable"  # not enough strokes for trend

    def test_multiple_strokes(self):
        texts = [
            "The cat sat on the mat.",
            "Dogs run in the park.",
            "Birds fly over trees.",
            "Fish swim in rivers.",
        ]
        result = analyse_stream(texts)
        assert result.total_strokes == 4
        assert 0 <= result.mean_score <= 100
        assert result.regime in ("accessible", "balanced", "dense", "impenetrable")

    def test_regime_counts(self):
        texts = [
            "Simple short text here.",
            "Another simple one here.",
            "Yet another simple text.",
        ]
        result = analyse_stream(texts)
        assert sum(result.regime_counts.values()) == 3

    def test_improving_trend(self):
        # Start with complex text, end with simple text
        complex_text = (
            "The extraordinary philosophical ramifications of "
            "epistemological transformation fundamentally "
            "reconceptualised our understanding of phenomenological "
            "interpretation throughout the interdisciplinary framework."
        )
        simple_text = "Cat sat. Dog ran. Fox hid."
        texts = [complex_text] * 4 + [simple_text] * 4
        result = analyse_stream(texts)
        assert result.trend == "improving"

    def test_declining_trend(self):
        complex_text = (
            "The extraordinary philosophical ramifications of "
            "epistemological transformation fundamentally "
            "reconceptualised our understanding of phenomenological "
            "interpretation throughout the interdisciplinary framework."
        )
        simple_text = "Cat sat. Dog ran. Fox hid."
        texts = [simple_text] * 4 + [complex_text] * 4
        result = analyse_stream(texts)
        assert result.trend == "declining"

    def test_stable_trend(self):
        texts = ["The cat sat on the mat."] * 8
        result = analyse_stream(texts)
        assert result.trend == "stable"

    def test_aggregate_metrics(self):
        texts = [
            "Short one.",
            "Short two.",
            "Short three.",
        ]
        result = analyse_stream(texts)
        assert result.mean_sentence_length > 0
        assert result.mean_word_length > 0
        assert result.mean_long_word_fraction >= 0
        assert result.mean_filler_ratio >= 0


# ---------------------------------------------------------------------------
# analyse_readability_windows
# ---------------------------------------------------------------------------


class TestAnalyseReadabilityWindows:
    def test_empty(self):
        result = analyse_readability_windows([])
        assert result == []

    def test_single_window(self):
        texts = ["Hello world."] * 5
        result = analyse_readability_windows(texts, window_size=10, step=5)
        assert len(result) >= 1
        assert isinstance(result[0], WindowReadability)

    def test_window_fields(self):
        texts = ["Hello world."] * 20
        result = analyse_readability_windows(texts, window_size=10, step=5)
        for w in result:
            assert hasattr(w, "start")
            assert hasattr(w, "end")
            assert hasattr(w, "mean_score")
            assert hasattr(w, "regime")
            assert hasattr(w, "mean_sentence_length")
            assert hasattr(w, "filler_ratio")
            assert 0 <= w.mean_score <= 100
            assert w.regime in ("accessible", "balanced", "dense", "impenetrable")

    def test_multiple_windows(self):
        texts = ["Simple text here."] * 30
        result = analyse_readability_windows(texts, window_size=10, step=10)
        assert len(result) == 3

    def test_overlapping_windows(self):
        texts = ["Simple text here."] * 25
        result = analyse_readability_windows(texts, window_size=10, step=5)
        # 0-10, 5-15, 10-20, 15-25, 20-25
        assert len(result) == 5

    def test_window_covers_all_strokes(self):
        texts = [f"Stroke number {i}." for i in range(15)]
        result = analyse_readability_windows(texts, window_size=10, step=5)
        # First window starts at 0
        assert result[0].start == 0
        # Last window ends at or beyond len(texts)
        assert result[-1].end >= len(texts)

    def test_window_size_larger_than_data(self):
        texts = ["Hello."] * 3
        result = analyse_readability_windows(texts, window_size=100, step=1)
        assert len(result) >= 1
        assert result[0].end == 3

    def test_step_one(self):
        texts = ["A."] * 5
        result = analyse_readability_windows(texts, window_size=3, step=1)
        # Windows at 0, 1, 2, 3, 4
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Integration: end-to-end
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_accessible_stream(self):
        texts = [
            "The cat sat on the mat.",
            "A dog ran in the park.",
            "Birds fly over the trees.",
            "Fish swim in the lake.",
            "Kids play in the yard.",
        ]
        report = analyse_stream(texts)
        assert report.regime in ("accessible", "balanced")
        assert report.mean_score > 40

    def test_complex_stream(self):
        complex_text = (
            "The extraordinary philosophical ramifications of "
            "epistemological transformation fundamentally "
            "reconceptualised our understanding of phenomenological "
            "interpretation throughout the interdisciplinary framework."
        )
        texts = [complex_text] * 5
        report = analyse_stream(texts)
        assert report.mean_long_word_fraction > 0.3
        assert report.mean_score < 60

    def test_mixed_stream_windows(self):
        simple = "Cat sat. Dog ran."
        complex_text = (
            "The extraordinary philosophical ramifications of "
            "epistemological transformation fundamentally "
            "reconceptualised our understanding of phenomenological "
            "interpretation throughout the interdisciplinary framework."
        )
        texts = [simple] * 10 + [complex_text] * 10
        windows = analyse_readability_windows(texts, window_size=10, step=5)
        assert len(windows) >= 2
        # Early windows should be more readable than later ones
        assert windows[0].mean_score > windows[-1].mean_score

    def test_filler_detection(self):
        filler_text = (
            "Basically actually just really quite literally "
            "sort of perhaps maybe indeed truly essentially."
        )
        result = analyse_stroke(filler_text)
        # Most words should be fillers
        assert result.filler_ratio > 0.8

    def test_single_long_sentence(self):
        text = (
            "The quick brown fox jumped over the lazy dog and then "
            "it ran across the field and through the forest and over "
            "the hill and down into the valley where it found a stream."
        )
        result = analyse_stroke(text)
        assert result.sentence_count == 1
        assert result.mean_sentence_length > 20
        assert result.readability_score < 80
