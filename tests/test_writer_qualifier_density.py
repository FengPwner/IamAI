#!/usr/bin/env python3
"""Tests for writer_qualifier_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_qualifier_density import (  # noqa: E402
    COMPARATIVE_QUALIFIER_PHRASES,
    DEGREE_PHRASES,
    DOWNTONERS,
    DOWNTONER_PHRASES,
    INTENSIFIERS,
    SUPERLATIVE_AMPLIFIER_PHRASES,
    WriterQualifierDensity,
    _sentence_count,
    _split_sentences,
    _tokenize_lower,
)


# ── Helpers ──────────────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   \n  "), [])

    def test_single_sentence(self):
        self.assertEqual(_split_sentences("She walked home."), ["She walked home."])

    def test_multiple_sentences(self):
        result = _split_sentences("He ran. She walked. They stayed.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        result = _split_sentences("Why? How? Where?")
        self.assertEqual(len(result), 3)

    def test_exclamation_marks(self):
        result = _split_sentences("Stop! Wait! Go!")
        self.assertEqual(len(result), 3)

    def test_mixed_punctuation(self):
        result = _split_sentences("Hello. What? Yes! No.")
        self.assertEqual(len(result), 4)

    def test_newlines(self):
        result = _split_sentences("First sentence.\nSecond sentence.")
        self.assertEqual(len(result), 2)

    def test_strips_whitespace(self):
        result = _split_sentences("  Hello world.  ")
        self.assertEqual(result, ["Hello world."])


class TestTokenizeLower(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_tokenize_lower(""), [])

    def test_simple(self):
        self.assertEqual(_tokenize_lower("Hello World"), ["hello", "world"])

    def test_mixed_case(self):
        self.assertEqual(_tokenize_lower("HeLLo WoRLd"), ["hello", "world"])

    def test_punctuation(self):
        result = _tokenize_lower("Hello, world! How are you?")
        self.assertEqual(result, ["hello", "world", "how", "are", "you"])

    def test_apostrophes(self):
        result = _tokenize_lower("don't won't can't")
        self.assertEqual(result, ["don't", "won't", "can't"])


class TestSentenceCount(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_sentence_count(""), 1)

    def test_one(self):
        self.assertEqual(_sentence_count("Hello world."), 1)

    def test_multiple(self):
        self.assertEqual(_sentence_count("A. B. C."), 3)

    def test_minimum_one(self):
        self.assertEqual(_sentence_count("no period here"), 1)


# ── Lexicon Membership ──────────────────────────────────────────────


class TestIntensifiers(unittest.TestCase):
    def test_very(self):
        self.assertIn("very", INTENSIFIERS)

    def test_extremely(self):
        self.assertIn("extremely", INTENSIFIERS)

    def test_absolutely(self):
        self.assertIn("absolutely", INTENSIFIERS)

    def test_utterly(self):
        self.assertIn("utterly", INTENSIFIERS)

    def test_remarkably(self):
        self.assertIn("remarkably", INTENSIFIERS)

    def test_not_downtoners(self):
        self.assertNotIn("slightly", INTENSIFIERS)
        self.assertNotIn("somewhat", INTENSIFIERS)


class TestDowntoners(unittest.TestCase):
    def test_slightly(self):
        self.assertIn("slightly", DOWNTONERS)

    def test_somewhat(self):
        self.assertIn("somewhat", DOWNTONERS)

    def test_barely(self):
        self.assertIn("barely", DOWNTONERS)

    def test_not_intensifiers(self):
        self.assertNotIn("very", DOWNTONERS)
        self.assertNotIn("extremely", DOWNTONERS)


# ── Intensifier Rate ─────────────────────────────────────────────────


class TestIntensifierRate(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_no_intensifiers(self):
        text = "The cat sat on the mat. The dog ran in the park."
        self.assertEqual(self.wqd.intensifier_rate(text), 0.0)

    def test_one_intensifier(self):
        text = "The cat was very happy. The dog was sad."
        self.assertAlmostEqual(self.wqd.intensifier_rate(text), 0.5)

    def test_multiple_intensifiers(self):
        text = "She was extremely happy and remarkably calm."
        self.assertAlmostEqual(self.wqd.intensifier_rate(text), 2.0)

    def test_case_insensitive(self):
        text = "VERY good. EXTREMELY fast. Absolutely perfect."
        rate = self.wqd.intensifier_rate(text)
        self.assertGreater(rate, 0)

    def test_empty_text(self):
        self.assertEqual(self.wqd.intensifier_rate(""), 0.0)

    def test_single_sentence_many_intensifiers(self):
        text = "She was very extremely remarkably utterly happy."
        rate = self.wqd.intensifier_rate(text)
        self.assertAlmostEqual(rate, 4.0)

    def test_intensifier_in_repeated_words(self):
        text = "Very very very good."
        rate = self.wqd.intensifier_rate(text)
        self.assertAlmostEqual(rate, 3.0)


# ── Downtoner Rate ───────────────────────────────────────────────────


class TestDowntonerRate(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_no_downtoners(self):
        text = "The cat sat on the mat. The dog ran in the park."
        self.assertEqual(self.wqd.downtoner_rate(text), 0.0)

    def test_single_downtoner(self):
        text = "She was slightly tired. He was energetic."
        self.assertAlmostEqual(self.wqd.downtoner_rate(text), 0.5)

    def test_downtoner_phrase(self):
        text = "It was a bit cold. The weather was fine."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_sort_of(self):
        text = "It was sort of interesting. The book was good."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_kind_of(self):
        text = "She felt kind of tired. He felt great."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_barely_and_hardly(self):
        text = "She barely passed. He hardly tried."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 1.0)

    def test_not_quite(self):
        text = "It was not quite finished. The rest was done."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_not_exactly(self):
        text = "It was not exactly right. The answer was close."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_not_really(self):
        text = "She was not really interested. He was engaged."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_a_smidgen(self):
        text = "Add a smidgen of salt. The dish was perfect."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_ever_so_slightly(self):
        # "slightly" matches DOWNTONERS word + "ever so slightly" matches phrase = 2 hits
        text = "The door was ever so slightly open. Nobody noticed."
        rate = self.wqd.downtoner_rate(text)
        self.assertAlmostEqual(rate, 1.0)

    def test_empty_text(self):
        self.assertEqual(self.wqd.downtoner_rate(""), 0.0)


# ── Degree Phrase Rate ───────────────────────────────────────────────


class TestDegreePhraseRate(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_no_degree_phrases(self):
        text = "The cat sat on the mat. The dog ran."
        self.assertEqual(self.wqd.degree_phrase_rate(text), 0.0)

    def test_to_some_extent(self):
        text = "To some extent, the theory holds. It works."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_by_and_large(self):
        text = "By and large, the plan succeeded. Details varied."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_more_or_less(self):
        text = "The results were more or less expected. Nothing surprised."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_to_a_great_extent(self):
        text = "To a great extent, the model explains the data. Gaps remain."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_at_the_very_least(self):
        text = "At the very least, we learned something. The rest is bonus."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_for_the_most_part(self):
        text = "For the most part, the experiment worked. One trial failed."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_not_in_the_least(self):
        text = "She was not in the least surprised. Everyone else was."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_at_most(self):
        text = "It would take at most three hours. The drive was short."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_at_best(self):
        text = "The outcome was at best uncertain. The team worried."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_at_worst(self):
        text = "At worst, we lose a day. The schedule has slack."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_multiple_degree_phrases(self):
        text = "To some extent, by and large, more or less, the theory works."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 3.0)

    def test_to_a_certain_extent(self):
        text = "To a certain extent, the model is valid. Limitations exist."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_to_a_certain_degree(self):
        text = "To a certain degree, the answer is yes. Nuance matters."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_in_large_measure(self):
        text = "In large measure, the project succeeded. Some goals slipped."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_to_varying_degrees(self):
        text = "The students responded to varying degrees. Some were enthusiastic."
        rate = self.wqd.degree_phrase_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_empty_text(self):
        self.assertEqual(self.wqd.degree_phrase_rate(""), 0.0)


# ── Comparative Qualifier Rate ───────────────────────────────────────


class TestComparativeQualifierRate(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_no_comparatives(self):
        text = "The cat sat on the mat. The dog ran."
        self.assertEqual(self.wqd.comparative_qualifier_rate(text), 0.0)

    def test_more_than(self):
        text = "She earned more than expected. The bonus was small."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_less_than(self):
        text = "The cost was less than budgeted. Savings accumulated."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_rather_than(self):
        text = "She walked rather than drove. The distance was short."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_far_from(self):
        text = "The result was far from perfect. It was acceptable."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_anything_but(self):
        text = "The task was anything but simple. It required expertise."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_everything_but(self):
        text = "The kitchen had everything but a microwave. The rest was complete."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_all_but(self):
        text = "The project was all but finished. One task remained."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_next_to(self):
        text = "Next to nothing remained. The work was done."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_second_only_to(self):
        text = "The team was second only to the champions. They were proud."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_compared_to(self):
        text = "Compared to last year, the results improved. Morale rose."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_relative_to(self):
        text = "Relative to the baseline, the model performed well. Accuracy rose."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_in_comparison_with(self):
        text = "In comparison with the old system, the new one excels. Users prefer it."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_by_comparison(self):
        text = "By comparison, the second trial was shorter. The first dragged."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_as_adjective_as(self):
        text = "She was as fast as lightning. The race was over."
        rate = self.wqd.comparative_qualifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_empty_text(self):
        self.assertEqual(self.wqd.comparative_qualifier_rate(""), 0.0)


# ── Superlative Amplifier Rate ───────────────────────────────────────


class TestSuperlativeAmplifierRate(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_no_superlatives(self):
        text = "The cat sat on the mat. The dog ran."
        self.assertEqual(self.wqd.superlative_amplifier_rate(text), 0.0)

    def test_the_most(self):
        text = "The most important factor was timing. Everything else followed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_the_least(self):
        text = "The least expected outcome occurred. Everyone was surprised."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_the_best(self):
        text = "The best result came from the simplest approach. Complexity failed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_the_worst(self):
        text = "The worst case scenario unfolded. Plans changed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_above_all(self):
        text = "Above all, the team valued honesty. Trust followed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_most_importantly(self):
        text = "Most importantly, the data was clean. Analysis proceeded."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_most_significantly(self):
        text = "Most significantly, the error rate dropped. Users noticed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_first_and_foremost(self):
        text = "First and foremost, we need funding. Everything depends on it."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_beyond_measure(self):
        text = "Her contribution was beyond measure. The team owed her everything."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_without_equal(self):
        text = "The performance was without equal. Critics agreed unanimously."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_unparalleled(self):
        text = "The achievement was unparalleled. No precedent existed."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_unmatched(self):
        text = "Her dedication was unmatched. Nobody else came close."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_unrivaled(self):
        text = "The product quality was unrivaled. Competitors struggled."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_unsurpassed(self):
        text = "The craftsmanship was unsurpassed. Every detail was perfect."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_peerless(self):
        text = "The musician was peerless. Audiences wept."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_incomparable(self):
        text = "The view was incomparable. Nothing else came close."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_more_than_anything(self):
        text = "More than anything, she wanted to help. The mission was clear."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 0.5)

    def test_multiple_superlatives(self):
        text = "Above all, the most important thing was the best result."
        rate = self.wqd.superlative_amplifier_rate(text)
        self.assertAlmostEqual(rate, 3.0)

    def test_empty_text(self):
        self.assertEqual(self.wqd.superlative_amplifier_rate(""), 0.0)


# ── Composite Index ──────────────────────────────────────────────────


class TestComputeQualifierDensityIndex(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_all_zeros(self):
        index = self.wqd.compute_qualifier_density_index(0, 0, 0, 0, 0)
        self.assertAlmostEqual(index, 0.0)

    def test_max_intensifier(self):
        index = self.wqd.compute_qualifier_density_index(3.0, 0, 0, 0, 0)
        self.assertAlmostEqual(index, 0.30)

    def test_max_all(self):
        index = self.wqd.compute_qualifier_density_index(3.0, 3.0, 2.0, 2.0, 1.5)
        self.assertAlmostEqual(index, 1.0)

    def test_partial_values(self):
        index = self.wqd.compute_qualifier_density_index(1.5, 1.5, 1.0, 1.0, 0.75)
        self.assertAlmostEqual(index, 0.5)

    def test_capping(self):
        """Values above cap should still normalize to 1.0."""
        index = self.wqd.compute_qualifier_density_index(10.0, 10.0, 10.0, 10.0, 10.0)
        self.assertAlmostEqual(index, 1.0)

    def test_weights_sum_to_one(self):
        """When all dimensions are at max normalization, index is 1.0."""
        index = self.wqd.compute_qualifier_density_index(3.0, 3.0, 2.0, 2.0, 1.5)
        self.assertAlmostEqual(index, 1.0)


# ── Classification ───────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_unadorned(self):
        self.assertEqual(self.wqd.classify(0.0), "unadorned")
        self.assertEqual(self.wqd.classify(0.03), "unadorned")
        self.assertEqual(self.wqd.classify(0.059), "unadorned")

    def test_minimally_qualified(self):
        self.assertEqual(self.wqd.classify(0.06), "minimally_qualified")
        self.assertEqual(self.wqd.classify(0.10), "minimally_qualified")
        self.assertEqual(self.wqd.classify(0.149), "minimally_qualified")

    def test_moderately_qualified(self):
        self.assertEqual(self.wqd.classify(0.15), "moderately_qualified")
        self.assertEqual(self.wqd.classify(0.25), "moderately_qualified")
        self.assertEqual(self.wqd.classify(0.299), "moderately_qualified")

    def test_richly_qualified(self):
        self.assertEqual(self.wqd.classify(0.30), "richly_qualified")
        self.assertEqual(self.wqd.classify(0.40), "richly_qualified")
        self.assertEqual(self.wqd.classify(0.499), "richly_qualified")

    def test_lavishly_qualified(self):
        self.assertEqual(self.wqd.classify(0.50), "lavishly_qualified")
        self.assertEqual(self.wqd.classify(0.75), "lavishly_qualified")
        self.assertEqual(self.wqd.classify(1.0), "lavishly_qualified")


# ── Measure Integration ──────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_empty_text(self):
        result = self.wqd.measure("")
        self.assertEqual(result["intensifier_rate"], 0.0)
        self.assertEqual(result["downtoner_rate"], 0.0)
        self.assertEqual(result["degree_phrase_rate"], 0.0)
        self.assertEqual(result["comparative_qualifier_rate"], 0.0)
        self.assertEqual(result["superlative_amplifier_rate"], 0.0)
        self.assertEqual(result["qualifier_density_index"], 0.0)
        self.assertEqual(result["classification"], "unadorned")

    def test_none_text(self):
        result = self.wqd.measure(None)
        self.assertEqual(result["classification"], "unadorned")

    def test_whitespace_text(self):
        result = self.wqd.measure("   \n  ")
        self.assertEqual(result["classification"], "unadorned")

    def test_plain_text(self):
        text = "The cat sat on the mat. The dog ran in the park. Birds flew overhead."
        result = self.wqd.measure(text)
        self.assertEqual(result["classification"], "unadorned")
        self.assertEqual(result["intensifier_rate"], 0.0)

    def test_heavily_qualified_text(self):
        text = (
            "The extremely important and remarkably significant "
            "findings were absolutely crucial.  To a great extent, "
            "the most important result was the best outcome.  "
            "Above all, the profoundly moving data surpassed all "
            "expectations by a wide margin."
        )
        result = self.wqd.measure(text)
        self.assertGreater(result["qualifier_density_index"], 0.0)
        self.assertGreater(result["intensifier_rate"], 0.0)

    def test_result_keys(self):
        result = self.wqd.measure("Some text here.")
        expected_keys = {
            "intensifier_rate",
            "downtoner_rate",
            "degree_phrase_rate",
            "comparative_qualifier_rate",
            "superlative_amplifier_rate",
            "qualifier_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_dimensions_present(self):
        text = (
            "She was very happy.  It was sort of cold outside.  "
            "To some extent, the plan worked.  More than anything, "
            "she wanted to succeed.  The best part was the ending."
        )
        result = self.wqd.measure(text)
        self.assertGreater(result["intensifier_rate"], 0.0)
        self.assertGreater(result["downtoner_rate"], 0.0)
        self.assertGreater(result["degree_phrase_rate"], 0.0)
        self.assertGreater(result["comparative_qualifier_rate"], 0.0)
        self.assertGreater(result["superlative_amplifier_rate"], 0.0)

    def test_downtoner_heavy_text(self):
        text = (
            "It was slightly warm.  The soup was somewhat salty.  "
            "She was fairly tired.  The music was rather loud.  "
            "The room was mildly stuffy."
        )
        result = self.wqd.measure(text)
        self.assertGreater(result["downtoner_rate"], 0.0)

    def test_comparative_heavy_text(self):
        text = (
            "More than expected, the results surprised everyone.  "
            "Rather than accept defeat, the team pushed forward.  "
            "Compared to the baseline, the new model excelled."
        )
        result = self.wqd.measure(text)
        self.assertGreater(result["comparative_qualifier_rate"], 0.0)

    def test_values_are_rounded(self):
        text = "The very important result was remarkably clear."
        result = self.wqd.measure(text)
        for key, value in result.items():
            if key != "classification":
                # Check it's a float with at most 4 decimal places
                self.assertEqual(value, round(value, 4))

    def test_classification_is_string(self):
        result = self.wqd.measure("Some text.")
        self.assertIsInstance(result["classification"], str)

    def test_index_between_zero_and_one(self):
        texts = [
            "Plain text with no qualifiers at all.",
            "The very extremely remarkably incredibly qualified text.",
            "A bit of this and somewhat of that, sort of.",
            "To some extent, by and large, more or less, at best.",
            "Above all, the most important thing was the best result.",
        ]
        for text in texts:
            result = self.wqd.measure(text)
            self.assertGreaterEqual(result["qualifier_density_index"], 0.0)
            self.assertLessEqual(result["qualifier_density_index"], 1.0)


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_single_word(self):
        result = self.wqd.measure("Very.")
        self.assertIn("classification", result)

    def test_single_sentence(self):
        result = self.wqd.measure("The very quick brown fox jumped extremely high.")
        self.assertGreater(result["intensifier_rate"], 0.0)

    def test_repeated_qualifiers(self):
        text = "Very very very very important."
        result = self.wqd.measure(text)
        self.assertAlmostEqual(result["intensifier_rate"], 4.0)

    def test_mixed_languages(self):
        """Non-English text should not crash."""
        result = self.wqd.measure("这是中文文本。没有任何英文限定词。")
        self.assertIn("classification", result)

    def test_numbers_only(self):
        result = self.wqd.measure("123 456 789.")
        self.assertEqual(result["intensifier_rate"], 0.0)

    def test_special_characters(self):
        result = self.wqd.measure("!@#$%^&*(). Another sentence here.")
        self.assertIn("classification", result)

    def test_very_long_text(self):
        sentence = "The very important and extremely significant result was remarkably clear. "
        text = sentence * 50
        result = self.wqd.measure(text)
        self.assertGreater(result["intensifier_rate"], 0.0)
        self.assertLessEqual(result["qualifier_density_index"], 1.0)


# ── Orthogonality Smoke Tests ────────────────────────────────────────


class TestOrthogonality(unittest.TestCase):
    """Verify qualifier density is independent of other metrics."""

    def setUp(self):
        self.wqd = WriterQualifierDensity()

    def test_hedging_without_qualifiers(self):
        """Hedged text should not necessarily have high qualifier density."""
        text = "Perhaps the results may suggest a possible correlation."
        result = self.wqd.measure(text)
        # Hedging language (perhaps, may, possible) is not qualifier language
        self.assertEqual(result["intensifier_rate"], 0.0)

    def test_qualifiers_without_hedging(self):
        """Qualified text can be very direct (no hedging)."""
        text = "The absolutely critical and extremely important finding is undeniable."
        result = self.wqd.measure(text)
        self.assertGreater(result["intensifier_rate"], 0.0)

    def test_formal_without_qualifiers(self):
        """Formal text can have low qualifier density."""
        text = "The defendant shall appear before the court on the designated date."
        result = self.wqd.measure(text)
        self.assertEqual(result["intensifier_rate"], 0.0)

    def test_informal_with_qualifiers(self):
        """Informal text can have high qualifier density."""
        text = "That was super incredibly amazingly awesome!"
        result = self.wqd.measure(text)
        # "incredibly" and "amazingly" are intensifiers
        self.assertGreater(result["intensifier_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
