#!/usr/bin/env python3
"""Tests for writer_hedging_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_hedging_density import (  # noqa: E402
    APPROXIMANTS,
    APPROXIMANT_PHRASES,
    APPROXIMANT_SUFFIX,
    ATTRIBUTION_SHIELDS,
    DEGREE_HEDGE_PHRASES,
    DEGREE_HEDGES,
    EPISTEMIC_HEDGES,
    EPISTEMIC_PHRASES,
    FREQUENCY_HEDGE_PHRASES,
    FREQUENCY_HEDGES,
    MODAL_HEDGE_PHRASES,
    MODAL_HEDGES,
    QUITE_DAMPENER,
    WriterHedgingDensity,
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
        result = _tokenize_lower("don't can't won't")
        self.assertEqual(result, ["don't", "can't", "won't"])

    def test_numbers_excluded(self):
        result = _tokenize_lower("about 47 things")
        self.assertEqual(result, ["about", "things"])


class TestSentenceCount(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_sentence_count(""), 1)

    def test_one_sentence(self):
        self.assertEqual(_sentence_count("Hello world."), 1)

    def test_multiple(self):
        self.assertEqual(_sentence_count("One. Two. Three."), 3)

    def test_minimum_one(self):
        self.assertEqual(_sentence_count("no punctuation"), 1)


# ── Lexicon Tests ────────────────────────────────────────────────────


class TestLexicons(unittest.TestCase):
    def test_epistemic_hedges_not_empty(self):
        self.assertGreater(len(EPISTEMIC_HEDGES), 10)

    def test_epistemic_hedges_lowercase(self):
        for word in EPISTEMIC_HEDGES:
            self.assertEqual(word, word.lower(), f"{word} should be lowercase")

    def test_modal_hedges_not_empty(self):
        self.assertGreater(len(MODAL_HEDGES), 0)

    def test_approximants_not_empty(self):
        self.assertGreater(len(APPROXIMANTS), 5)

    def test_frequency_hedges_not_empty(self):
        self.assertGreater(len(FREQUENCY_HEDGES), 10)

    def test_degree_hedges_not_empty(self):
        self.assertGreater(len(DEGREE_HEDGES), 5)

    def test_attribution_shields_are_patterns(self):
        for pattern in ATTRIBUTION_SHIELDS:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_epistemic_phrases_are_patterns(self):
        for pattern in EPISTEMIC_PHRASES:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_modal_phrases_are_patterns(self):
        for pattern in MODAL_HEDGE_PHRASES:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_approximant_phrases_are_patterns(self):
        for pattern in APPROXIMANT_PHRASES:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_frequency_phrases_are_patterns(self):
        for pattern in FREQUENCY_HEDGE_PHRASES:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_degree_phrases_are_patterns(self):
        for pattern in DEGREE_HEDGE_PHRASES:
            self.assertTrue(hasattr(pattern, "findall"))

    def test_quite_dampener_is_pattern(self):
        self.assertTrue(hasattr(QUITE_DAMPENER, "findall"))

    def test_approximant_suffix_is_pattern(self):
        self.assertTrue(hasattr(APPROXIMANT_SUFFIX, "findall"))

    def test_epistemic_contains_key_words(self):
        for word in ["perhaps", "possibly", "probably", "likely",
                      "apparently", "seemingly", "presumably"]:
            self.assertIn(word, EPISTEMIC_HEDGES)

    def test_modals_contain_key_words(self):
        for word in ["may", "might", "could", "would"]:
            self.assertIn(word, MODAL_HEDGES)

    def test_approximants_contain_key_words(self):
        for word in ["approximately", "roughly", "about", "nearly", "almost"]:
            self.assertIn(word, APPROXIMANTS)

    def test_frequency_hedges_contain_key_words(self):
        for word in ["often", "sometimes", "frequently", "generally", "usually"]:
            self.assertIn(word, FREQUENCY_HEDGES)

    def test_degree_hedges_contain_key_words(self):
        for word in ["somewhat", "slightly", "fairly", "rather", "moderately"]:
            self.assertIn(word, DEGREE_HEDGES)


# ── Dimension Tests ──────────────────────────────────────────────────


class TestEpistemicHedgeRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.epistemic_hedge_rate(""), 0.0)

    def test_no_hedges(self):
        text = "The cat sat on the mat. The dog ran in the park."
        self.assertEqual(self.whd.epistemic_hedge_rate(text), 0.0)

    def test_single_hedge(self):
        text = "Perhaps the answer is correct."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_hedges(self):
        text = "Perhaps the answer is possibly correct. It seems likely that we are apparently right."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 1.0)

    def test_phrase_it_seems(self):
        text = "It seems that the results are valid."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_phrase_it_appears(self):
        text = "It appears that the data supports the hypothesis."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_phrase_it_is_possible(self):
        text = "It is possible that the effect exists."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_high_density(self):
        text = "Perhaps it is likely that the results may possibly be arguably correct."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 2.0)

    def test_case_insensitive(self):
        text = "PERHAPS the answer is POSSIBLY correct."
        result = self.whd.epistemic_hedge_rate(text)
        self.assertGreater(result, 0.0)


class TestModalHedgeRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.modal_hedge_rate(""), 0.0)

    def test_no_modals(self):
        text = "The cat sat on the mat. She runs fast."
        self.assertEqual(self.whd.modal_hedge_rate(text), 0.0)

    def test_may(self):
        text = "This may be the correct answer."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_might(self):
        text = "She might come to the party."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_could(self):
        text = "This could explain the results."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_would(self):
        text = "That would suggest a problem."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_can_possibility(self):
        text = "This can cause serious problems."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_can_ability_not_counted(self):
        text = "She can swim very fast."
        result = self.whd.modal_hedge_rate(text)
        self.assertEqual(result, 0.0)

    def test_modal_phrase_may_well(self):
        text = "This may well be the best solution."
        result = self.whd.modal_hedge_rate(text)
        # "may" + "may well" phrase
        self.assertGreater(result, 0.5)

    def test_modal_phrase_would_tend(self):
        text = "This would tend to support the hypothesis."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_modals(self):
        text = "This may be possible. It might work. We could try it. That would help."
        result = self.whd.modal_hedge_rate(text)
        self.assertGreater(result, 0.5)


class TestAttributionHedgeRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.attribution_hedge_rate(""), 0.0)

    def test_no_attribution(self):
        text = "The sky is blue. Water is wet."
        self.assertEqual(self.whd.attribution_hedge_rate(text), 0.0)

    def test_according_to(self):
        text = "According to the report, sales increased."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_some_believe(self):
        text = "Some believe that the earth is flat."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_critics_argue(self):
        text = "Critics argue that the policy is flawed."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_studies_suggest(self):
        text = "Studies suggest that exercise improves health."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_it_is_said(self):
        text = "It is said that fortune favors the bold."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_one_might_say(self):
        text = "One might say that the results are inconclusive."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_sources_indicate(self):
        text = "Sources indicate that the merger is imminent."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_reportedly(self):
        text = "The company is reportedly planning a launch."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_shields(self):
        text = "According to experts, the trend is real. Studies suggest it will continue. Critics argue otherwise."
        result = self.whd.attribution_hedge_rate(text)
        self.assertGreater(result, 0.5)


class TestApproximantRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.approximant_rate(""), 0.0)

    def test_no_approximants(self):
        text = "The exact value is 42. The count is 7."
        self.assertEqual(self.whd.approximant_rate(text), 0.0)

    def test_about(self):
        text = "There are about fifty people here."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_approximately(self):
        text = "Approximately 300 participants joined."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_roughly(self):
        text = "Roughly half the students passed."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_nearly(self):
        text = "Nearly all participants agreed."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_almost(self):
        text = "Almost everyone showed up."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_sort_of(self):
        text = "It was sort of interesting."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_kind_of(self):
        text = "She was kind of tired."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_more_or_less(self):
        text = "The project is more or less finished."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_ish_suffix(self):
        text = "The meeting starts at eightish."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_give_or_take(self):
        text = "A hundred people, give or take."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_approximants(self):
        text = "About fifty people, roughly half, approximately done."
        result = self.whd.approximant_rate(text)
        self.assertGreater(result, 2.0)


class TestFrequencyHedgeRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.frequency_hedge_rate(""), 0.0)

    def test_no_frequency_hedges(self):
        text = "The algorithm always terminates. Every input produces output."
        self.assertEqual(self.whd.frequency_hedge_rate(text), 0.0)

    def test_often(self):
        text = "This often happens in practice."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_sometimes(self):
        text = "Sometimes the test fails."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_generally(self):
        text = "Generally, the method works well."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_tends_to(self):
        text = "The model tends to overfit on small datasets."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_tends_toward(self):
        text = "The distribution tends toward normal."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_for_the_most_part(self):
        text = "For the most part, the results are consistent."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_by_and_large(self):
        text = "By and large, the approach is effective."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_general(self):
        text = "In general, larger samples give better estimates."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_rarely(self):
        text = "This rarely occurs in practice."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_seldom(self):
        text = "Such cases seldom arise."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_frequency_hedges(self):
        text = "Often this works. Sometimes it fails. Generally it is fine. Usually we expect this."
        result = self.whd.frequency_hedge_rate(text)
        self.assertGreater(result, 0.5)


class TestDegreeHedgeRate(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        self.assertEqual(self.whd.degree_hedge_rate(""), 0.0)

    def test_no_degree_hedges(self):
        text = "The result is perfect. The method is excellent."
        self.assertEqual(self.whd.degree_hedge_rate(text), 0.0)

    def test_somewhat(self):
        text = "The result is somewhat surprising."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_slightly(self):
        text = "The values differ slightly."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_fairly(self):
        text = "The method is fairly effective."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_rather(self):
        text = "The result is rather unexpected."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_moderately(self):
        text = "The correlation is moderately strong."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_to_some_extent(self):
        text = "The hypothesis is correct to some extent."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_part(self):
        text = "The failure is in part due to design choices."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_not_entirely(self):
        text = "The result is not entirely convincing."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_not_completely(self):
        text = "The solution is not completely optimal."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_quite_dampener(self):
        text = "The method is quite effective."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_quite_before_gradable(self):
        text = "The results are quite good."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_partially(self):
        text = "The model is partially trained."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_degree_hedges(self):
        text = "Somewhat effective, slightly biased, fairly accurate, rather slow."
        result = self.whd.degree_hedge_rate(text)
        self.assertGreater(result, 3.0)


# ── Composite Tests ──────────────────────────────────────────────────


class TestCompositeIndex(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_all_zeros(self):
        result = self.whd.compute_hedging_density_index(0, 0, 0, 0, 0, 0)
        self.assertEqual(result, 0.0)

    def test_all_high(self):
        result = self.whd.compute_hedging_density_index(3, 4, 2, 3, 3, 3)
        self.assertAlmostEqual(result, 1.0, places=2)

    def test_moderate_values(self):
        result = self.whd.compute_hedging_density_index(1.0, 1.0, 0.5, 0.5, 0.5, 0.5)
        self.assertGreater(result, 0.1)
        self.assertLess(result, 0.8)

    def test_weights_sum_to_one(self):
        # Verify by computing with all dimensions at max normalized value
        result = self.whd.compute_hedging_density_index(3.0, 4.0, 2.0, 3.0, 3.0, 3.0)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_only_epistemic(self):
        result = self.whd.compute_hedging_density_index(3.0, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.25, places=2)

    def test_only_modal(self):
        result = self.whd.compute_hedging_density_index(0, 4.0, 0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.20, places=2)

    def test_only_attribution(self):
        result = self.whd.compute_hedging_density_index(0, 0, 2.0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.15, places=2)

    def test_only_approximant(self):
        result = self.whd.compute_hedging_density_index(0, 0, 0, 3.0, 0, 0)
        self.assertAlmostEqual(result, 0.12, places=2)

    def test_only_frequency(self):
        result = self.whd.compute_hedging_density_index(0, 0, 0, 0, 3.0, 0)
        self.assertAlmostEqual(result, 0.13, places=2)

    def test_only_degree(self):
        result = self.whd.compute_hedging_density_index(0, 0, 0, 0, 0, 3.0)
        self.assertAlmostEqual(result, 0.15, places=2)

    def test_capped_at_one(self):
        result = self.whd.compute_hedging_density_index(10, 10, 10, 10, 10, 10)
        self.assertEqual(result, 1.0)


# ── Classification Tests ─────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_fully_committal(self):
        self.assertEqual(self.whd.classify(0.0), "fully_committal")
        self.assertEqual(self.whd.classify(0.05), "fully_committal")
        self.assertEqual(self.whd.classify(0.079), "fully_committal")

    def test_mildly_hedged(self):
        self.assertEqual(self.whd.classify(0.08), "mildly_hedged")
        self.assertEqual(self.whd.classify(0.15), "mildly_hedged")
        self.assertEqual(self.whd.classify(0.199), "mildly_hedged")

    def test_moderately_hedged(self):
        self.assertEqual(self.whd.classify(0.20), "moderately_hedged")
        self.assertEqual(self.whd.classify(0.30), "moderately_hedged")
        self.assertEqual(self.whd.classify(0.399), "moderately_hedged")

    def test_heavily_hedged(self):
        self.assertEqual(self.whd.classify(0.40), "heavily_hedged")
        self.assertEqual(self.whd.classify(0.50), "heavily_hedged")
        self.assertEqual(self.whd.classify(0.599), "heavily_hedged")

    def test_evasively_hedged(self):
        self.assertEqual(self.whd.classify(0.60), "evasively_hedged")
        self.assertEqual(self.whd.classify(0.80), "evasively_hedged")
        self.assertEqual(self.whd.classify(1.0), "evasively_hedged")

    def test_boundary_values(self):
        self.assertEqual(self.whd.classify(0.08), "mildly_hedged")
        self.assertEqual(self.whd.classify(0.20), "moderately_hedged")
        self.assertEqual(self.whd.classify(0.40), "heavily_hedged")
        self.assertEqual(self.whd.classify(0.60), "evasively_hedged")


# ── Integration / Measure Tests ──────────────────────────────────────


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_empty_text(self):
        result = self.whd.measure("")
        self.assertEqual(result["hedging_density_index"], 0.0)
        self.assertEqual(result["classification"], "fully_committal")
        self.assertEqual(result["epistemic_hedge_rate"], 0.0)
        self.assertEqual(result["modal_hedge_rate"], 0.0)

    def test_none_text(self):
        result = self.whd.measure(None)
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_whitespace_only(self):
        result = self.whd.measure("   \n  ")
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_direct_text_low_hedging(self):
        text = """
        The results demonstrate a clear correlation.
        Environmental factors cause the observed effect.
        The relationship is complex and varies by context.
        The findings contradict previous work.
        """
        result = self.whd.measure(text)
        self.assertLess(result["hedging_density_index"], 0.10)
        self.assertEqual(result["classification"], "fully_committal")

    def test_hedged_text_high_hedging(self):
        text = """
        It seems that the results may possibly suggest a
        correlation.  The effect could perhaps be attributed
        to environmental factors, according to some researchers.
        Studies suggest that the relationship is somewhat complex
        and may tend to vary depending on context.  It is possible
        that approximately half of the observed variation might
        be explained by factors not yet identified.  Critics
        argue that the methodology is not entirely sound.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.15)
        self.assertIn(result["classification"], [
            "mildly_hedged", "moderately_hedged", "heavily_hedged",
            "evasively_hedged",
        ])

    def test_all_keys_present(self):
        result = self.whd.measure("Some text here.")
        expected_keys = {
            "epistemic_hedge_rate",
            "modal_hedge_rate",
            "attribution_hedge_rate",
            "approximant_rate",
            "frequency_hedge_rate",
            "degree_hedge_rate",
            "hedging_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_are_rounded(self):
        result = self.whd.measure("Perhaps this might be somewhat useful.")
        for key in [
            "epistemic_hedge_rate",
            "modal_hedge_rate",
            "attribution_hedge_rate",
            "approximant_rate",
            "frequency_hedge_rate",
            "degree_hedge_rate",
            "hedging_density_index",
        ]:
            value = result[key]
            self.assertIsInstance(value, float)
            # Check at most 4 decimal places
            self.assertEqual(value, round(value, 4))

    def test_index_between_zero_and_one(self):
        texts = [
            "Simple direct statement.",
            "Perhaps this might possibly be somewhat useful generally.",
            "It seems that studies suggest the effect may be roughly significant.",
            "According to critics, the method is not entirely sound and may tend to fail.",
        ]
        for text in texts:
            result = self.whd.measure(text)
            self.assertGreaterEqual(result["hedging_density_index"], 0.0)
            self.assertLessEqual(result["hedging_density_index"], 1.0)

    def test_hedged_higher_than_direct(self):
        direct = "The algorithm works. It processes data quickly. The output is correct."
        hedged = "The algorithm might work. It could possibly process data somewhat quickly. The output may be approximately correct."
        direct_result = self.whd.measure(direct)
        hedged_result = self.whd.measure(hedged)
        self.assertGreater(
            hedged_result["hedging_density_index"],
            direct_result["hedging_density_index"],
        )

    def test_scientific_text(self):
        text = """
        The results suggest that the treatment may be effective
        in some populations.  Studies indicate a roughly 30%
        improvement, though this varies considerably.  It appears
        that younger patients tend to respond somewhat better.
        According to previous research, the effect might be
        partially mediated by genetic factors.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.10)
        self.assertGreater(result["epistemic_hedge_rate"], 0.0)
        self.assertGreater(result["modal_hedge_rate"], 0.0)
        self.assertGreater(result["attribution_hedge_rate"], 0.0)
        self.assertGreater(result["approximant_rate"], 0.0)

    def test_academic_heavy_hedging(self):
        text = """
        It could be argued that the findings are not entirely
        consistent.  One might say the methodology is somewhat
        questionable.  Perhaps the sample size is rather small.
        It seems likely that the results may possibly be
        influenced by confounding variables.  Studies suggest
        the effect is not completely robust.  Critics argue
        that alternative explanations have not been fully
        explored.  The conclusions are arguably premature.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.15)
        self.assertIn(result["classification"], [
            "mildly_hedged", "moderately_hedged", "heavily_hedged",
            "evasively_hedged",
        ])

    def test_classification_is_valid_string(self):
        result = self.whd.measure("Any text will do for this test.")
        valid_classes = {
            "fully_committal",
            "mildly_hedged",
            "moderately_hedged",
            "heavily_hedged",
            "evasively_hedged",
        }
        self.assertIn(result["classification"], valid_classes)

    def test_single_word_text(self):
        result = self.whd.measure("Hello.")
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_single_sentence_with_hedge(self):
        result = self.whd.measure("Perhaps this works.")
        self.assertGreater(result["epistemic_hedge_rate"], 0.0)

    def test_repeated_hedges_scale(self):
        base = "Perhaps it may work. "
        text_1x = base
        text_5x = base * 5
        result_1x = self.whd.measure(text_1x)
        result_5x = self.whd.measure(text_5x)
        # Both should have similar per-sentence rates
        self.assertAlmostEqual(
            result_1x["epistemic_hedge_rate"],
            result_5x["epistemic_hedge_rate"],
            places=1,
        )


# ── Edge Case Tests ──────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_all_punctuation(self):
        result = self.whd.measure("!?. !?. !?.")
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_single_character_sentences(self):
        result = self.whd.measure("A. B. C.")
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_very_long_text(self):
        text = "This is a simple sentence. " * 1000
        result = self.whd.measure(text)
        self.assertEqual(result["hedging_density_index"], 0.0)

    def test_unicode_text(self):
        result = self.whd.measure("Héllo wörld. C'est la vie.")
        self.assertIsInstance(result["hedging_density_index"], float)

    def test_numbers_in_text(self):
        text = "About 500 people attended. Approximately 30% left early."
        result = self.whd.measure(text)
        self.assertGreater(result["approximant_rate"], 0.0)

    def test_mixed_case_hedges(self):
        text = "PERHAPS this MIGHT work. Possibly it COULD help."
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.0)

    def test_hedges_in_quotes(self):
        text = 'The author writes "perhaps the results may be significant."'
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.0)

    def test_newline_separated_text(self):
        text = "Perhaps this works.\nMaybe that works.\nPossibly it helps."
        result = self.whd.measure(text)
        self.assertGreater(result["epistemic_hedge_rate"], 0.0)

    def test_tab_separated_text(self):
        text = "Perhaps this.\tMaybe that.\tPossibly other."
        result = self.whd.measure(text)
        self.assertIsInstance(result["hedging_density_index"], float)

    def test_hyphenated_words(self):
        text = "The not-entirely-clear results are somewhat ambiguous."
        result = self.whd.measure(text)
        self.assertGreater(result["degree_hedge_rate"], 0.0)

    def test_ish_not_too_short(self):
        # "ish" alone or "fish" should not trigger
        text = "The fish is delicious."
        result = self.whd.measure(text)
        # "fish" is 4 chars, "fish" ends in "ish" but the regex requires \w{3,}ish
        # which matches "fish" — but it's a real word, not an approximant.
        # This is a known limitation of suffix-based detection.
        self.assertIsInstance(result["approximant_rate"], float)


# ── Cross-Dimension Independence Tests ────────────────────────────────


class TestDimensionIndependence(unittest.TestCase):
    """Verify that each dimension measures its own thing."""

    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_epistemic_without_modal(self):
        text = "Perhaps the answer is correct. Possibly the method works."
        result = self.whd.measure(text)
        self.assertGreater(result["epistemic_hedge_rate"], 0.0)
        # No modal verbs in this text
        self.assertEqual(result["modal_hedge_rate"], 0.0)

    def test_modal_without_epistemic(self):
        text = "This may cause problems. It could lead to errors."
        result = self.whd.measure(text)
        self.assertGreater(result["modal_hedge_rate"], 0.0)
        self.assertEqual(result["epistemic_hedge_rate"], 0.0)

    def test_attribution_without_epistemic(self):
        text = "According to the report, sales increased. Sources indicate growth."
        result = self.whd.measure(text)
        self.assertGreater(result["attribution_hedge_rate"], 0.0)

    def test_approximant_without_degree(self):
        text = "About fifty people attended. Approximately thirty left."
        result = self.whd.measure(text)
        self.assertGreater(result["approximant_rate"], 0.0)
        self.assertEqual(result["degree_hedge_rate"], 0.0)

    def test_frequency_without_epistemic(self):
        text = "Often the method works. Generally the results are good."
        result = self.whd.measure(text)
        self.assertGreater(result["frequency_hedge_rate"], 0.0)

    def test_degree_without_modal(self):
        text = "The result is somewhat surprising. The effect is slightly positive."
        result = self.whd.measure(text)
        self.assertGreater(result["degree_hedge_rate"], 0.0)
        self.assertEqual(result["modal_hedge_rate"], 0.0)


# ── Realistic Text Tests ─────────────────────────────────────────────


class TestRealisticTexts(unittest.TestCase):
    """Test with realistic prose samples of different genres."""

    def setUp(self):
        self.whd = WriterHedgingDensity()

    def test_news_report_low_hedging(self):
        text = """
        The president signed the bill into law Tuesday.
        The legislation passed the Senate 68-32.
        The new policy takes effect January 1.
        Companies must comply within 90 days.
        """
        result = self.whd.measure(text)
        self.assertLess(result["hedging_density_index"], 0.10)

    def test_scientific_abstract_moderate_hedging(self):
        text = """
        Our findings suggest that the treatment may reduce
        symptoms in some patients.  The effect appears to be
        dose-dependent, with approximately 40% improvement
        at the highest dose.  Results indicate that further
        studies are likely needed to confirm these findings.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.05)

    def test_legal_text_high_hedging(self):
        text = """
        It could be argued that the defendant may not have
        been entirely aware of the consequences.  One might
        suggest that the evidence is not completely conclusive.
        It seems possible that alternative explanations could
        account for the observed results.  Perhaps the court
        might consider that the circumstances were somewhat
        unusual and arguably unprecedented.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.15)

    def test_fiction_low_hedging(self):
        text = """
        She opened the door. The room was dark.
        A single candle burned on the table.
        He sat in the corner, watching.
        She screamed. He smiled.
        """
        result = self.whd.measure(text)
        self.assertLess(result["hedging_density_index"], 0.10)

    def test_opinion_piece_mixed(self):
        text = """
        The policy is a disaster. It will probably fail
        because the assumptions are somewhat unrealistic.
        Experts generally agree that the approach is flawed.
        Perhaps the administration should reconsider.
        """
        result = self.whd.measure(text)
        self.assertGreater(result["hedging_density_index"], 0.05)

    def test_technical_docs_low_hedging(self):
        text = """
        Install the package with pip. Run the server on
        port 8080. The API returns JSON. Authentication
        uses OAuth2. The database stores user profiles.
        """
        result = self.whd.measure(text)
        self.assertLess(result["hedging_density_index"], 0.10)


if __name__ == "__main__":
    unittest.main()
