#!/usr/bin/env python3
"""Tests for writer_fragment_density — 110 test cases."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_fragment_density import (  # noqa: E402
    VERBLESS_FRAGMENT_PATTERNS,
    SUBJECTLESS_FRAGMENT_PATTERNS,
    SINGLE_WORD_SENTENCE_PATTERNS,
    CONVERSATIONAL_FRAGMENT_PATTERNS,
    TRAILING_FRAGMENT_PATTERNS,
    WriterFragmentDensity,
    _split_sentences,
    _count_matching,
    _count_tokens,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterFragmentDensity initialization."""

    def test_init_default(self):
        wfd = WriterFragmentDensity()
        self.assertIsNotNone(wfd.verbless_fragment)
        self.assertIsNotNone(wfd.subjectless_fragment)
        self.assertIsNotNone(wfd.single_word_sentence)
        self.assertIsNotNone(wfd.conversational_fragment)
        self.assertIsNotNone(wfd.trailing_fragment)

    def test_init_sets_all_constants(self):
        wfd = WriterFragmentDensity()
        self.assertEqual(wfd.verbless_fragment, VERBLESS_FRAGMENT_PATTERNS)
        self.assertEqual(wfd.subjectless_fragment, SUBJECTLESS_FRAGMENT_PATTERNS)
        self.assertEqual(wfd.single_word_sentence, SINGLE_WORD_SENTENCE_PATTERNS)
        self.assertEqual(wfd.conversational_fragment, CONVERSATIONAL_FRAGMENT_PATTERNS)
        self.assertEqual(wfd.trailing_fragment, TRAILING_FRAGMENT_PATTERNS)

    def test_verbless_patterns_are_compiled(self):
        for p in VERBLESS_FRAGMENT_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_subjectless_patterns_are_compiled(self):
        for p in SUBJECTLESS_FRAGMENT_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_single_word_patterns_are_compiled(self):
        for p in SINGLE_WORD_SENTENCE_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_conversational_patterns_are_compiled(self):
        for p in CONVERSATIONAL_FRAGMENT_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_trailing_patterns_are_compiled(self):
        for p in TRAILING_FRAGMENT_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_pattern_counts(self):
        wfd = WriterFragmentDensity()
        self.assertGreaterEqual(len(wfd.verbless_fragment), 8)
        self.assertGreaterEqual(len(wfd.subjectless_fragment), 5)
        self.assertGreaterEqual(len(wfd.single_word_sentence), 4)
        self.assertGreaterEqual(len(wfd.conversational_fragment), 3)
        self.assertGreaterEqual(len(wfd.trailing_fragment), 6)


# ── Helper functions ─────────────────────────────────────────────────


class TestHelpers(unittest.TestCase):
    """Test module-level helper functions."""

    def test_split_sentences_basic(self):
        text = "Hello world. How are you? Fine."
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_split_sentences_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_split_sentences_single(self):
        result = _split_sentences("Just one sentence.")
        self.assertEqual(len(result), 1)

    def test_split_sentences_exclamation(self):
        text = "Wow! Really! Yes!"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_split_sentences_question(self):
        text = "Who knows? What now? Why bother?"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_split_sentences_preserves_punctuation(self):
        text = "Stop. Wait. Listen."
        result = _split_sentences(text)
        self.assertTrue(result[0].endswith("."))
        self.assertTrue(result[1].endswith("."))

    def test_split_sentences_ellipsis(self):
        text = "Well... Maybe... If only..."
        result = _split_sentences(text)
        self.assertGreaterEqual(len(result), 1)

    def test_split_sentences_em_dash(self):
        text = "And then— She was about to—"
        result = _split_sentences(text)
        self.assertGreaterEqual(len(result), 1)

    def test_count_matching_basic(self):
        sentences = ["The usual.", "A cold morning.", "The committee met."]
        count = _count_matching(sentences, VERBLESS_FRAGMENT_PATTERNS)
        self.assertGreaterEqual(count, 1)

    def test_count_matching_none(self):
        sentences = ["The committee reviewed the quarterly statements."]
        count = _count_matching(sentences, VERBLESS_FRAGMENT_PATTERNS)
        self.assertEqual(count, 0)

    def test_count_matching_all(self):
        sentences = ["Never.", "Impossible.", "Stop."]
        count = _count_matching(sentences, SINGLE_WORD_SENTENCE_PATTERNS)
        self.assertEqual(count, 3)

    def test_count_matching_empty(self):
        count = _count_matching([], VERBLESS_FRAGMENT_PATTERNS)
        self.assertEqual(count, 0)

    def test_count_tokens_basic(self):
        self.assertEqual(_count_tokens("hello world"), 2)

    def test_count_tokens_single(self):
        self.assertEqual(_count_tokens("hello"), 1)

    def test_count_tokens_empty(self):
        self.assertEqual(_count_tokens(""), 0)

    def test_count_tokens_whitespace(self):
        self.assertEqual(_count_tokens("  hello   world  "), 2)


# ── Verbless fragment rate ───────────────────────────────────────────


class TestVerblessFragmentRate(unittest.TestCase):
    """Test verbless fragment detection."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        self.assertEqual(self.wfd.measure_verbless_fragment_rate(""), 0.0)

    def test_no_fragments(self):
        text = "The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertEqual(rate, 0.0)

    def test_noun_phrase_fragment(self):
        text = "A cold morning. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_the_usual(self):
        text = "The usual. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_possessive_fragment(self):
        text = "My mistake. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_prepositional_fragment(self):
        text = "In the garden. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_quantifier_fragment(self):
        text = "All of them. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_such_fragment(self):
        text = "Such beauty. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_like_fragment(self):
        text = "Like a dream. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_two_word_nominal(self):
        text = "Big deal. The committee met."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_all_fragments(self):
        text = "The usual. A cold morning. My mistake. In the garden."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreater(rate, 0.5)

    def test_rate_bounded(self):
        text = "The usual. The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_verbless_fragment_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Subjectless fragment rate ────────────────────────────────────────


class TestSubjectlessFragmentRate(unittest.TestCase):
    """Test subjectless fragment detection."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        self.assertEqual(self.wfd.measure_subjectless_fragment_rate(""), 0.0)

    def test_no_fragments(self):
        text = "The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertEqual(rate, 0.0)

    def test_participle_fragment(self):
        text = "Running late. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_past_participle_fragment(self):
        text = "Gone. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_past_tense_fragment(self):
        text = "Went to the store. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_imperative_fragment(self):
        text = "Stop. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_short_verb_only(self):
        text = "Agreed. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_noted_fragment(self):
        text = "Noted. The committee met."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_rate_bounded(self):
        text = "Running late. Gone. The committee reviewed statements."
        rate = self.wfd.measure_subjectless_fragment_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Single word sentence rate ────────────────────────────────────────


class TestSingleWordSentenceRate(unittest.TestCase):
    """Test single-word sentence detection."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        self.assertEqual(self.wfd.measure_single_word_sentence_rate(""), 0.0)

    def test_no_single_words(self):
        text = "The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertEqual(rate, 0.0)

    def test_yes(self):
        text = "Yes. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_never(self):
        text = "Never. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_impossible(self):
        text = "Impossible. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_enough(self):
        text = "Enough. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_interjection(self):
        text = "Wow! The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_temporal(self):
        text = "Now. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_pronoun(self):
        text = "Nobody. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_multiple_single_words(self):
        text = "Yes. Never. Impossible. The committee met."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreater(rate, 0.5)

    def test_rate_bounded(self):
        text = "Yes. The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_single_word_sentence_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Conversational fragment rate ─────────────────────────────────────


class TestConversationalFragmentRate(unittest.TestCase):
    """Test conversational fragment detection."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        self.assertEqual(self.wfd.measure_conversational_fragment_rate(""), 0.0)

    def test_no_conversational(self):
        text = "The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertEqual(rate, 0.0)

    def test_of_course(self):
        text = "Of course. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_no_way(self):
        text = "No way. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_fair_enough(self):
        text = "Fair enough. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_my_bad(self):
        text = "My bad. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_makes_sense(self):
        text = "Makes sense. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_i_guess(self):
        text = "I guess. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_discourse_marker(self):
        text = "Anyway. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_acknowledgment(self):
        text = "Bingo. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_exclamatory(self):
        text = "No kidding. The committee met."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_rate_bounded(self):
        text = "Of course. The committee reviewed the quarterly statements."
        rate = self.wfd.measure_conversational_fragment_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Trailing fragment rate ──────────────────────────────────────────


class TestTrailingFragmentRate(unittest.TestCase):
    """Test trailing fragment detection."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        self.assertEqual(self.wfd.measure_trailing_fragment_rate(""), 0.0)

    def test_no_trailing(self):
        text = "The committee reviewed the quarterly financial statements."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertEqual(rate, 0.0)

    def test_ellipsis_trailing(self):
        text = "If only... The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_em_dash_trailing(self):
        text = "And then— The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_well_maybe(self):
        text = "Well, maybe... The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_but_still(self):
        text = "But still... The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_was_about_to(self):
        text = "She was about to— The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_or_something(self):
        text = "He said or something. The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_you_know(self):
        text = "You know... The committee met."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreater(rate, 0.0)

    def test_rate_bounded(self):
        text = "If only... The committee reviewed the quarterly statements."
        rate = self.wfd.measure_trailing_fragment_rate(text)
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Composite index ─────────────────────────────────────────────────


class TestFragmentDensityIndex(unittest.TestCase):
    """Test composite index computation."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_all_zeros(self):
        index = self.wfd.compute_fragment_density_index(0, 0, 0, 0, 0)
        self.assertEqual(index, 0.0)

    def test_all_ones(self):
        index = self.wfd.compute_fragment_density_index(1, 1, 1, 1, 1)
        self.assertEqual(index, 1.0)

    def test_capped_at_one(self):
        index = self.wfd.compute_fragment_density_index(2, 2, 2, 2, 2)
        self.assertEqual(index, 1.0)

    def test_weighted_average(self):
        index = self.wfd.compute_fragment_density_index(1, 0, 0, 0, 0)
        self.assertAlmostEqual(index, 0.25)

    def test_weights_sum_to_one(self):
        index = self.wfd.compute_fragment_density_index(1, 1, 1, 1, 1)
        self.assertAlmostEqual(index, 1.0)

    def test_trailing_weight(self):
        index = self.wfd.compute_fragment_density_index(0, 0, 0, 0, 1)
        self.assertAlmostEqual(index, 0.15)

    def test_subjectless_weight(self):
        index = self.wfd.compute_fragment_density_index(0, 1, 0, 0, 0)
        self.assertAlmostEqual(index, 0.20)

    def test_single_word_weight(self):
        index = self.wfd.compute_fragment_density_index(0, 0, 1, 0, 0)
        self.assertAlmostEqual(index, 0.20)

    def test_conversational_weight(self):
        index = self.wfd.compute_fragment_density_index(0, 0, 0, 1, 0)
        self.assertAlmostEqual(index, 0.20)

    def test_partial_values(self):
        index = self.wfd.compute_fragment_density_index(0.5, 0.3, 0.2, 0.1, 0.4)
        expected = 0.25 * 0.5 + 0.20 * 0.3 + 0.20 * 0.2 + 0.20 * 0.1 + 0.15 * 0.4
        self.assertAlmostEqual(index, expected)


# ── Classification ──────────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    """Test fragment density classification."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_syntactically_complete(self):
        self.assertEqual(self.wfd.classify(0.0), "syntactically_complete")
        self.assertEqual(self.wfd.classify(0.01), "syntactically_complete")
        self.assertEqual(self.wfd.classify(0.04), "syntactically_complete")

    def test_minimally_fragmentary(self):
        self.assertEqual(self.wfd.classify(0.05), "minimally_fragmentary")
        self.assertEqual(self.wfd.classify(0.10), "minimally_fragmentary")
        self.assertEqual(self.wfd.classify(0.14), "minimally_fragmentary")

    def test_moderately_fragmentary(self):
        self.assertEqual(self.wfd.classify(0.15), "moderately_fragmentary")
        self.assertEqual(self.wfd.classify(0.20), "moderately_fragmentary")
        self.assertEqual(self.wfd.classify(0.29), "moderately_fragmentary")

    def test_richly_fragmentary(self):
        self.assertEqual(self.wfd.classify(0.30), "richly_fragmentary")
        self.assertEqual(self.wfd.classify(0.40), "richly_fragmentary")
        self.assertEqual(self.wfd.classify(0.49), "richly_fragmentary")

    def test_staccato(self):
        self.assertEqual(self.wfd.classify(0.50), "staccato")
        self.assertEqual(self.wfd.classify(0.75), "staccato")
        self.assertEqual(self.wfd.classify(1.0), "staccato")

    def test_boundary_values(self):
        self.assertEqual(self.wfd.classify(0.05), "minimally_fragmentary")
        self.assertEqual(self.wfd.classify(0.15), "moderately_fragmentary")
        self.assertEqual(self.wfd.classify(0.30), "richly_fragmentary")
        self.assertEqual(self.wfd.classify(0.50), "staccato")


# ── Full measure ────────────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the full measure() method."""

    def setUp(self):
        self.wfd = WriterFragmentDensity()

    def test_empty_text(self):
        result = self.wfd.measure("")
        self.assertEqual(result["fragment_density_index"], 0.0)
        self.assertEqual(result["classification"], "syntactically_complete")

    def test_returns_all_keys(self):
        result = self.wfd.measure("The committee met.")
        expected_keys = {
            "verbless_fragment_rate",
            "subjectless_fragment_rate",
            "single_word_sentence_rate",
            "conversational_fragment_rate",
            "trailing_fragment_rate",
            "fragment_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_are_rounded(self):
        text = "The usual. Never. Of course. If only... The committee met."
        result = self.wfd.measure(text)
        for key in [
            "verbless_fragment_rate",
            "subjectless_fragment_rate",
            "single_word_sentence_rate",
            "conversational_fragment_rate",
            "trailing_fragment_rate",
            "fragment_density_index",
        ]:
            self.assertEqual(result[key], round(result[key], 4))

    def test_fragmentary_text_scores_higher(self):
        fragmentary = "The usual. A cold morning. Running late. Forgot everything. Never. Impossible. Of course. Fair enough. If only... Stop. Listen. Gone."
        formal = "The committee reviewed the quarterly financial statements and approved the proposed budget for the upcoming fiscal period."
        frag_result = self.wfd.measure(fragmentary)
        form_result = self.wfd.measure(formal)
        self.assertGreater(
            frag_result["fragment_density_index"],
            form_result["fragment_density_index"],
        )

    def test_fragmentary_text_classification(self):
        text = "The usual. A cold morning. Never. Impossible. Of course. Fair enough. If only... Stop. Gone. No way. My bad. Sounds good."
        result = self.wfd.measure(text)
        self.assertIn(result["classification"], [
            "minimally_fragmentary",
            "moderately_fragmentary",
            "richly_fragmentary",
            "staccato",
        ])

    def test_formal_text_classification(self):
        text = (
            "The committee reviewed the quarterly financial statements and approved "
            "the proposed budget. Revenue increased by twelve percent compared to the "
            "previous fiscal period. Operating expenses remained within the approved "
            "allocation. The board confirmed the capital expenditure plan for the "
            "upcoming quarter. All members voted in favor of the resolution."
        )
        result = self.wfd.measure(text)
        self.assertIn(result["classification"], [
            "syntactically_complete",
            "minimally_fragmentary",
        ])

    def test_index_bounded(self):
        text = "The usual. Never. Impossible. Of course. If only... The committee reviewed the quarterly financial statements."
        result = self.wfd.measure(text)
        self.assertGreaterEqual(result["fragment_density_index"], 0.0)
        self.assertLessEqual(result["fragment_density_index"], 1.0)

    def test_single_sentence(self):
        result = self.wfd.measure("Hello world.")
        self.assertIn("fragment_density_index", result)

    def test_only_fragments(self):
        text = "The usual. My mistake. In the garden. Running late. Gone. Yes. Never. Of course. Fair enough. If only..."
        result = self.wfd.measure(text)
        self.assertGreater(result["fragment_density_index"], 0.0)


if __name__ == "__main__":
    unittest.main()
