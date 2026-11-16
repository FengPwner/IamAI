#!/usr/bin/env python3
"""Tests for writer_sentiment_polarity module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_sentiment_polarity import (
    SentimentPolarityResult,
    measure_sentiment_polarity,
    _tokenize,
    _split_sentences,
    _is_negated,
    _score_sentence,
    _detect_shift,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_sentiment_polarity("")
        assert r.positive_words == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_sentiment_polarity("   \n\n   ")
        assert r.positive_words == 0
        assert r.classification == "unknown"

    def test_single_word_neutral(self):
        r = measure_sentiment_polarity("Hello.")
        assert r.positive_words == 0
        assert r.negative_words == 0
        assert r.word_count == 1

    def test_no_sentiment_words(self):
        r = measure_sentiment_polarity("The cat sat on the mat.")
        assert r.total_sentiment_words == 0
        assert r.classification == "neutral"

    def test_numbers_only(self):
        r = measure_sentiment_polarity("123 456 789.")
        assert r.word_count == 0 or r.classification in ("neutral", "unknown")


# ── positive text ───────────────────────────────────────────────


class TestPositiveText:
    def test_mildly_positive(self):
        text = "The project made good progress today. The team is happy with the results."
        r = measure_sentiment_polarity(text)
        assert r.positive_words > 0
        assert r.polarity > 0
        assert r.classification in ("mildly_positive", "strongly_positive")

    def test_strongly_positive(self):
        text = "This is an outstanding, magnificent, extraordinary achievement. We are ecstatic and elated."
        r = measure_sentiment_polarity(text)
        assert r.positive_words >= 3
        assert r.polarity > 0.3
        assert r.classification == "strongly_positive"

    def test_positive_ratio(self):
        text = "Great work, happy team, excellent results, wonderful day."
        r = measure_sentiment_polarity(text)
        assert r.positive_ratio > 0.8

    def test_positive_word_count(self):
        text = "She felt joy and delight with love and hope."
        r = measure_sentiment_polarity(text)
        assert r.positive_words >= 3  # joy, delight, love, hope


# ── negative text ───────────────────────────────────────────────


class TestNegativeText:
    def test_mildly_negative(self):
        text = "The code has some errors and the build is slow. A few issues remain."
        r = measure_sentiment_polarity(text)
        assert r.negative_words > 0
        assert r.polarity < 0
        assert r.classification in ("mildly_negative", "strongly_negative")

    def test_strongly_negative(self):
        text = "This is a devastating, horrific, catastrophic disaster. The situation is unbearable."
        r = measure_sentiment_polarity(text)
        assert r.negative_words >= 3
        assert r.polarity < -0.3
        assert r.classification == "strongly_negative"

    def test_negative_ratio(self):
        text = "Terrible mistake, awful result, horrible failure, dreadful outcome."
        r = measure_sentiment_polarity(text)
        assert r.positive_ratio < 0.2

    def test_negative_word_count(self):
        text = "He felt angry and sad about the damage and harm."
        r = measure_sentiment_polarity(text)
        assert r.negative_words >= 2  # angry, sad, damage, harm


# ── negation handling ───────────────────────────────────────────


class TestNegation:
    def test_not_good(self):
        r = measure_sentiment_polarity("This is not good.")
        # "not good" should invert the positive polarity of "good"
        assert r.negative_words >= 1 or r.polarity <= 0

    def test_not_bad(self):
        r = measure_sentiment_polarity("The result is not bad.")
        # "not bad" should invert the negative polarity of "bad"
        assert r.positive_words >= 1 or r.polarity >= 0

    def test_never_excellent(self):
        r = measure_sentiment_polarity("The service was never excellent.")
        assert r.negative_words >= 1 or r.polarity <= 0

    def test_no_hope(self):
        r = measure_sentiment_polarity("There is no hope left.")
        # "no hope" should invert the positive polarity of "hope"
        assert r.negative_words >= 1 or r.polarity <= 0

    def test_is_negated_helper(self):
        tokens = ["this", "is", "not", "good"]
        assert _is_negated(tokens, 3) is True

    def test_not_negated_far_away(self):
        tokens = ["not", "the", "cat", "but", "the", "dog", "is", "good"]
        # "good" at index 7, "not" at index 0, window=2 → not negated
        assert _is_negated(tokens, 7, window=2) is False


# ── mixed sentiment ─────────────────────────────────────────────


class TestMixedSentiment:
    def test_balanced_text(self):
        text = "The team made good progress but found some error and doubt. They feel happy but also fear."
        r = measure_sentiment_polarity(text)
        assert r.positive_words > 0
        assert r.negative_words > 0
        assert r.total_sentiment_words >= 3

    def test_mostly_positive_with_caveat(self):
        text = "Excellent work overall, great improvements, though a few issues remain."
        r = measure_sentiment_polarity(text)
        assert r.positive_words > r.negative_words

    def test_mostly_negative_with_silver_lining(self):
        text = "Terrible quarter, awful losses, catastrophic failures, but some hope remains."
        r = measure_sentiment_polarity(text)
        assert r.negative_words > r.positive_words


# ── intensity weighting ─────────────────────────────────────────


class TestIntensity:
    def test_mild_vs_strong_positive(self):
        mild = measure_sentiment_polarity("The food was nice and okay.")
        strong = measure_sentiment_polarity("The food was magnificent and extraordinary.")
        assert strong.polarity > mild.polarity

    def test_mild_vs_strong_negative(self):
        mild = measure_sentiment_polarity("The code is bad and slow.")
        strong = measure_sentiment_polarity("The code is abysmal and devastating.")
        assert strong.polarity < mild.polarity


# ── sentiment shift detection ───────────────────────────────────


class TestSentimentShift:
    def test_rising_sentiment(self):
        text = (
            "The project started with problems and errors. "
            "Things were difficult and frustrating. "
            "Then progress came, good results appeared. "
            "Finally the team achieved excellent, wonderful success."
        )
        r = measure_sentiment_polarity(text)
        assert r.sentiment_shift in ("rising", "stable")

    def test_falling_sentiment(self):
        text = (
            "We began with great optimism and wonderful plans. "
            "The early results were excellent and promising. "
            "Then problems emerged and errors multiplied. "
            "Eventually everything collapsed into a terrible disaster."
        )
        r = measure_sentiment_polarity(text)
        assert r.sentiment_shift in ("falling", "stable")

    def test_stable_sentiment(self):
        text = (
            "The system is stable and reliable. "
            "Performance is good and consistent. "
            "The team is happy and productive."
        )
        r = measure_sentiment_polarity(text)
        assert r.sentiment_shift == "stable"

    def test_detect_shift_helper_stable(self):
        polarities = [0.1, 0.1, 0.0, 0.1, 0.1]
        assert _detect_shift(polarities) == "stable"

    def test_detect_shift_rising(self):
        polarities = [-0.5, -0.3, 0.0, 0.3, 0.5]
        assert _detect_shift(polarities) == "rising"

    def test_detect_shift_falling(self):
        polarities = [0.5, 0.3, 0.0, -0.3, -0.5]
        assert _detect_shift(polarities) == "falling"

    def test_detect_shift_oscillating(self):
        polarities = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5]
        assert _detect_shift(polarities) == "oscillating"


# ── sentence-level analysis ─────────────────────────────────────


class TestSentenceLevel:
    def test_sentence_polarities_populated(self):
        text = "Great day. Bad news. Good work."
        r = measure_sentiment_polarity(text)
        assert len(r.sentence_polarities) == 3

    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third sentence."
        r = measure_sentiment_polarity(text)
        assert r.sentence_count == 3


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_word_count(self):
        text = "One two three four five."
        r = measure_sentiment_polarity(text)
        assert r.word_count == 5

    def test_sentiment_density(self):
        text = "Good bad happy sad cat dog."
        r = measure_sentiment_polarity(text)
        # 4 sentiment words out of 6 total = 66.67 per 100
        assert r.sentiment_density > 50

    def test_top_positive_populated(self):
        text = "Great excellent wonderful great excellent."
        r = measure_sentiment_polarity(text)
        assert len(r.top_positive) > 0

    def test_top_negative_populated(self):
        text = "Terrible awful horrible terrible awful."
        r = measure_sentiment_polarity(text)
        assert len(r.top_negative) > 0


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_sentiment_word(self):
        text = "Good good good good good."
        r = measure_sentiment_polarity(text)
        assert r.positive_words == 5

    def test_case_insensitive(self):
        lower = measure_sentiment_polarity("this is great.")
        upper = measure_sentiment_polarity("THIS IS GREAT.")
        assert lower.polarity == upper.polarity

    def test_punctuation_handling(self):
        text = "Great! Wonderful! Excellent!"
        r = measure_sentiment_polarity(text)
        assert r.positive_words >= 3

    def test_long_text(self):
        text = "The system is good. " * 50
        r = measure_sentiment_polarity(text)
        assert r.classification in ("mildly_positive", "strongly_positive")
        assert r.word_count == 200

    def test_polarity_bounded(self):
        text = "Excellent outstanding magnificent extraordinary phenomenal spectacular."
        r = measure_sentiment_polarity(text)
        assert -1.0 <= r.polarity <= 1.0

    def test_neutral_text(self):
        text = "The meeting was on Tuesday. The report has five sections. The server runs Linux."
        r = measure_sentiment_polarity(text)
        assert r.classification == "neutral"


# ── score_sentence helper ───────────────────────────────────────


class TestScoreSentence:
    def test_positive_sentence(self):
        tokens = ["this", "is", "great", "and", "wonderful"]
        net, pos, neg, pos_c, neg_c = _score_sentence(tokens)
        assert net > 0
        assert pos >= 2
        assert neg == 0

    def test_negative_sentence(self):
        tokens = ["this", "is", "terrible", "and", "awful"]
        net, pos, neg, pos_c, neg_c = _score_sentence(tokens)
        assert net < 0
        assert neg >= 2
        assert pos == 0

    def test_mixed_sentence(self):
        tokens = ["good", "and", "bad"]
        net, pos, neg, pos_c, neg_c = _score_sentence(tokens)
        assert pos == 1
        assert neg == 1


# ── classification boundaries ───────────────────────────────────


class TestClassification:
    def test_strongly_positive_boundary(self):
        r = measure_sentiment_polarity("Excellent outstanding magnificent extraordinary.")
        assert r.classification == "strongly_positive"

    def test_strongly_negative_boundary(self):
        r = measure_sentiment_polarity("Devastating horrific catastrophic abysmal.")
        assert r.classification == "strongly_negative"

    def test_neutral_boundary(self):
        r = measure_sentiment_polarity("The table has four legs.")
        assert r.classification == "neutral"
