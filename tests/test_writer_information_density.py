#!/usr/bin/env python3
"""Tests for writer_information_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_information_density import (
    InformationDensityResult,
    measure_information_density,
    _tokenize,
    _split_sentences,
    _content_words,
    _bigrams,
    _count_filler_phrases,
    _compute_sentence_density,
    _compute_redundancy,
    _score,
    _classify,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_information_density("")
        assert r.total_words == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_information_density("   \n\n   ")
        assert r.classification == "unknown"

    def test_single_word(self):
        r = measure_information_density("Hello.")
        assert r.total_words == 1
        assert r.total_sentences == 1

    def test_none_like(self):
        r = measure_information_density("")
        assert r.density_score == 0.0

    def test_numbers_only(self):
        r = measure_information_density("123 456 789.")
        assert r.total_words == 3
        assert r.total_content_words >= 0


# ── tokenization ────────────────────────────────────────────────


class TestTokenization:
    def test_simple_words(self):
        tokens = _tokenize("The cat sat on the mat")
        assert "the" in tokens
        assert "cat" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! How are you?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "," not in tokens

    def test_lowercase(self):
        tokens = _tokenize("UPPERCASE MiXeD")
        assert "uppercase" in tokens
        assert "mixed" in tokens


# ── sentence splitting ─────────────────────────────────────────


class TestSentenceSplitting:
    def test_simple_split(self):
        sents = _split_sentences("First sentence. Second sentence.")
        assert len(sents) == 2

    def test_question_marks(self):
        sents = _split_sentences("What is this? Why does it matter?")
        assert len(sents) == 2

    def test_exclamation(self):
        sents = _split_sentences("Stop! Now!")
        assert len(sents) == 2

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        assert len(sents) == 1

    def test_empty_input(self):
        sents = _split_sentences("")
        assert len(sents) == 0


# ── content words ───────────────────────────────────────────────


class TestContentWords:
    def test_filters_stop_words(self):
        tokens = ["the", "cat", "sat", "on", "the", "mat"]
        content = _content_words(tokens)
        assert "cat" in content
        assert "mat" in content
        assert "the" not in content
        assert "on" not in content

    def test_filters_short_tokens(self):
        tokens = ["a", "is", "cat", "run"]
        content = _content_words(tokens)
        assert "cat" in content
        assert "run" in content

    def test_all_stop_words(self):
        tokens = ["the", "is", "and", "or"]
        content = _content_words(tokens)
        assert len(content) == 0


# ── bigrams ─────────────────────────────────────────────────────


class TestBigrams:
    def test_simple_bigrams(self):
        bgs = _bigrams(["a", "b", "c"])
        assert ("a", "b") in bgs
        assert ("b", "c") in bgs
        assert len(bgs) == 2

    def test_single_word(self):
        bgs = _bigrams(["alone"])
        assert len(bgs) == 0

    def test_empty(self):
        bgs = _bigrams([])
        assert len(bgs) == 0


# ── filler phrases ──────────────────────────────────────────────


class TestFillerPhrases:
    def test_detects_filler(self):
        text = "In terms of performance, at the end of the day it works."
        count = _count_filler_phrases(text)
        assert count == 2

    def test_no_filler(self):
        text = "The algorithm sorts the array in linear time."
        count = _count_filler_phrases(text)
        assert count == 0

    def test_case_insensitive(self):
        text = "IN TERMS OF speed, In Order To achieve results."
        count = _count_filler_phrases(text)
        assert count == 2


# ── redundancy ──────────────────────────────────────────────────


class TestRedundancy:
    def test_no_redundancy(self):
        tokens = ["a", "b", "c", "d"]
        redundant, total = _compute_redundancy(tokens)
        assert redundant == 0
        assert total == 3

    def test_full_redundancy(self):
        tokens = ["a", "b", "a", "b", "a", "b"]
        redundant, total = _compute_redundancy(tokens)
        assert redundant > 0

    def test_empty(self):
        redundant, total = _compute_redundancy([])
        assert redundant == 0
        assert total == 0


# ── sentence density computation ───────────────────────────────


class TestSentenceDensity:
    def test_all_content_words(self):
        tokens = ["algorithm", "sorts", "array", "linear", "time"]
        ratio, novelty, seen = _compute_sentence_density(tokens, set())
        assert ratio == 1.0
        assert novelty == 1.0
        assert len(seen) == 5

    def test_all_stop_words(self):
        tokens = ["the", "is", "and", "or"]
        ratio, novelty, seen = _compute_sentence_density(tokens, set())
        assert ratio == 0.0
        assert novelty == 0.0

    def test_novelty_decreases_with_repetition(self):
        tokens1 = ["algorithm", "sorts", "array"]
        _, _, seen = _compute_sentence_density(tokens1, set())

        tokens2 = ["algorithm", "processes", "data"]
        _, novelty2, _ = _compute_sentence_density(tokens2, seen)
        assert novelty2 < 1.0  # "algorithm" is no longer novel

    def test_empty_tokens(self):
        ratio, novelty, seen = _compute_sentence_density([], set())
        assert ratio == 0.0
        assert novelty == 0.0


# ── scoring ─────────────────────────────────────────────────────


class TestScoring:
    def test_high_density_input(self):
        score = _score(
            content_word_ratio=0.60,
            unique_content_ratio=0.75,
            novel_sentence_ratio=0.65,
            redundancy_rate=0.02,
            filler_phrase_rate=0.0,
        )
        assert score >= 70

    def test_low_density_input(self):
        score = _score(
            content_word_ratio=0.20,
            unique_content_ratio=0.30,
            novel_sentence_ratio=0.20,
            redundancy_rate=0.15,
            filler_phrase_rate=2.0,
        )
        assert score <= 30

    def test_score_bounded(self):
        score = _score(1.0, 1.0, 1.0, 0.0, 0.0)
        assert 0 <= score <= 100

    def test_score_zero_inputs(self):
        score = _score(0.0, 0.0, 0.0, 1.0, 10.0)
        assert score >= 0


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_unknown(self):
        assert _classify(0) == "unknown"

    def test_thin(self):
        assert _classify(10) == "thin"

    def test_light(self):
        assert _classify(30) == "light"

    def test_balanced(self):
        assert _classify(50) == "balanced"

    def test_dense(self):
        assert _classify(70) == "dense"

    def test_compressed(self):
        assert _classify(90) == "compressed"

    def test_boundary_20(self):
        assert _classify(20) == "thin"

    def test_boundary_21(self):
        assert _classify(21) == "light"


# ── integration: dense text ────────────────────────────────────


class TestDenseText:
    def test_technical_prose(self):
        text = (
            "Quicksort partitions the array around a pivot element. "
            "Elements smaller than the pivot move left; larger elements "
            "move right. The partition step runs in linear time. "
            "Recursive calls handle each subarray independently. "
            "Average case complexity is O(n log n)."
        )
        r = measure_information_density(text)
        assert r.total_sentences == 5
        assert r.content_word_ratio > 0.35
        assert r.density_score > 40
        assert r.classification in ("balanced", "dense", "compressed")

    def test_filler_heavy_text(self):
        text = (
            "In terms of the situation, at the end of the day, "
            "it is important to note that things are basically "
            "what they are. In other words, for all intents and "
            "purposes, the fact of the matter is that at this "
            "point in time, we are where we are."
        )
        r = measure_information_density(text)
        assert r.filler_count >= 4
        assert r.filler_phrase_rate > 5.0
        # filler-heavy text still scores below dense threshold
        assert r.density_score < 75
        assert r.classification != "compressed"


# ── integration: mixed text ────────────────────────────────────


class TestMixedText:
    def test_conversational_prose(self):
        text = (
            "The river runs through the valley. "
            "It has been doing so for thousands of years. "
            "The water carries sediment downstream. "
            "Farmers depend on the annual flooding. "
            "Without it, the soil would be too dry for crops."
        )
        r = measure_information_density(text)
        assert r.total_sentences == 5
        assert r.total_words > 20
        assert r.content_word_ratio > 0.25
        assert r.classification != "unknown"

    def test_repetitive_text(self):
        text = (
            "The cat sat on the mat. "
            "The cat was sitting on the mat. "
            "On the mat sat the cat. "
            "The mat had a cat sitting on it. "
            "A cat was on a mat."
        )
        r = measure_information_density(text)
        assert r.redundancy_rate > 0.05
        assert r.unique_content_ratio < 0.6


# ── integration: short text ────────────────────────────────────


class TestShortText:
    def test_single_sentence(self):
        text = "Entropy increases in closed systems."
        r = measure_information_density(text)
        assert r.total_sentences == 1
        assert r.density_score > 0
        assert r.classification != "unknown"

    def test_two_sentences(self):
        text = "Compilers translate source code. Machine code executes on hardware."
        r = measure_information_density(text)
        assert r.total_sentences == 2
        assert r.novel_sentence_ratio > 0


# ── result dataclass ────────────────────────────────────────────


class TestResultDataclass:
    def test_default_values(self):
        r = InformationDensityResult()
        assert r.total_sentences == 0
        assert r.density_score == 0.0
        assert r.classification == "unknown"
        assert r.sentence_densities == []

    def test_fields_populated(self):
        r = measure_information_density(
            "Graph theory studies vertices and edges. "
            "Trees are connected acyclic graphs. "
            "Spanning trees cover all vertices."
        )
        assert r.total_sentences == 3
        assert len(r.sentence_densities) == 3
        assert r.mean_info_per_sentence > 0
        assert r.total_bigram_count > 0


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_punctuation(self):
        r = measure_information_density("... !!! ???")
        assert r.total_sentences >= 0

    def test_very_long_single_sentence(self):
        text = "The " + "very " * 50 + "long sentence ends here."
        r = measure_information_density(text)
        assert r.total_sentences == 1
        assert r.redundancy_rate > 0.1

    def test_unicode_text(self):
        text = "Café résumé naïve façade."
        r = measure_information_density(text)
        assert r.total_words > 0

    def test_repeated_words(self):
        text = "very very very very very important point."
        r = measure_information_density(text)
        assert r.redundancy_rate > 0.3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
