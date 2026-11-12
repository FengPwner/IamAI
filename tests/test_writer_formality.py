#!/usr/bin/env python3
"""Tests for writer_formality — 112 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_formality import (  # noqa: E402
    COLLOQUIAL_EXPRESSIONS,
    CONTRACTIONS,
    FORMAL_HEDGES,
    FORMAL_HEDGE_PHRASES,
    FUNCTION_WORDS,
    INFORMAL_PRONOUNS,
    LATINATE_PREFIXES,
    LATINATE_SUFFIXES,
    WriterFormality,
)


class TestWriterFormalityInit(unittest.TestCase):
    """Test WriterFormality initialization."""

    def test_init_default(self):
        wf = WriterFormality()
        self.assertIsNotNone(wf.contractions)
        self.assertIsNotNone(wf.informal_pronouns)

    def test_init_sets_all_attributes(self):
        wf = WriterFormality()
        self.assertEqual(wf.contractions, CONTRACTIONS)
        self.assertEqual(wf.informal_pronouns, INFORMAL_PRONOUNS)
        self.assertEqual(wf.colloquial_expressions, COLLOQUIAL_EXPRESSIONS)
        self.assertEqual(wf.latinate_suffixes, LATINATE_SUFFIXES)
        self.assertEqual(wf.latinate_prefixes, LATINATE_PREFIXES)
        self.assertEqual(wf.formal_hedges, FORMAL_HEDGES)
        self.assertEqual(wf.formal_hedge_phrases, FORMAL_HEDGE_PHRASES)
        self.assertEqual(wf.function_words, FUNCTION_WORDS)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        wf = WriterFormality()
        self.assertEqual(wf._tokenize(""), [])

    def test_single_word(self):
        wf = WriterFormality()
        self.assertEqual(wf._tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        wf = WriterFormality()
        tokens = wf._tokenize("The quick brown fox")
        self.assertEqual(tokens, ["the", "quick", "brown", "fox"])

    def test_punctuation_removed(self):
        wf = WriterFormality()
        tokens = wf._tokenize("Hello, world!")
        self.assertEqual(tokens, ["hello", "world"])

    def test_case_insensitive(self):
        wf = WriterFormality()
        tokens = wf._tokenize("HELLO World")
        self.assertEqual(tokens, ["hello", "world"])

    def test_numbers_excluded(self):
        wf = WriterFormality()
        tokens = wf._tokenize("I have 5 cats")
        self.assertIn("have", tokens)
        self.assertNotIn("5", tokens)


class TestTokenizeWithContractions(unittest.TestCase):
    """Test _tokenize_with_contractions helper."""

    def test_empty_string(self):
        wf = WriterFormality()
        self.assertEqual(wf._tokenize_with_contractions(""), [])

    def test_preserves_contractions(self):
        wf = WriterFormality()
        tokens = wf._tokenize_with_contractions("don't won't can't")
        self.assertIn("don't", tokens)
        self.assertIn("won't", tokens)
        self.assertIn("can't", tokens)

    def test_mixed_tokens(self):
        wf = WriterFormality()
        tokens = wf._tokenize_with_contractions("I don't like it")
        self.assertIn("don't", tokens)
        self.assertIn("like", tokens)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wf = WriterFormality()
        self.assertEqual(wf._split_sentences(""), [])

    def test_single_sentence(self):
        wf = WriterFormality()
        result = wf._split_sentences("The cat sat.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        wf = WriterFormality()
        result = wf._split_sentences("The cat sat. The dog ran.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        wf = WriterFormality()
        result = wf._split_sentences("Stop! Help!")
        self.assertEqual(len(result), 2)

    def test_question_marks(self):
        wf = WriterFormality()
        result = wf._split_sentences("Why? How?")
        self.assertEqual(len(result), 2)

    def test_whitespace_stripped(self):
        wf = WriterFormality()
        result = wf._split_sentences("  Hello.   World.  ")
        self.assertTrue(all(s == s.strip() for s in result))


class TestHasLatinateMorphology(unittest.TestCase):
    """Test _has_latinate_morphology helper."""

    def test_function_word_excluded(self):
        wf = WriterFormality()
        self.assertFalse(wf._has_latinate_morphology("the"))
        self.assertFalse(wf._has_latinate_morphology("and"))

    def test_short_word_excluded(self):
        wf = WriterFormality()
        self.assertFalse(wf._has_latinate_morphology("cat"))
        self.assertFalse(wf._has_latinate_morphology("run"))

    def test_tion_suffix(self):
        wf = WriterFormality()
        self.assertTrue(wf._has_latinate_morphology("implementation"))
        self.assertTrue(wf._has_latinate_morphology("classification"))

    def test_ment_suffix(self):
        wf = WriterFormality()
        self.assertTrue(wf._has_latinate_morphology("implementation"))
        self.assertTrue(wf._has_latinate_morphology("establishment"))

    def test_ity_suffix(self):
        wf = WriterFormality()
        self.assertTrue(wf._has_latinate_morphology("complexity"))
        self.assertTrue(wf._has_latinate_morphology("specificity"))

    def test_non_latinate_word(self):
        wf = WriterFormality()
        self.assertFalse(wf._has_latinate_morphology("table"))
        self.assertFalse(wf._has_latinate_morphology("happy"))


class TestCountPassiveConstructions(unittest.TestCase):
    """Test _count_passive_constructions helper."""

    def test_empty_text(self):
        wf = WriterFormality()
        self.assertEqual(wf._count_passive_constructions(""), 0)

    def test_no_passive(self):
        wf = WriterFormality()
        text = "The cat chased the mouse. The dog ran fast."
        self.assertEqual(wf._count_passive_constructions(text), 0)

    def test_simple_passive(self):
        wf = WriterFormality()
        text = "The mouse was chased by the cat."
        self.assertGreater(wf._count_passive_constructions(text), 0)

    def test_perfect_passive(self):
        wf = WriterFormality()
        text = "The data has been collected by the researchers."
        self.assertGreater(wf._count_passive_constructions(text), 0)

    def test_future_passive(self):
        wf = WriterFormality()
        text = "The report will be completed tomorrow."
        self.assertGreater(wf._count_passive_constructions(text), 0)

    def test_multiple_passives(self):
        wf = WriterFormality()
        text = "The data was collected. The results were analyzed."
        self.assertGreaterEqual(wf._count_passive_constructions(text), 2)


class TestContractionRate(unittest.TestCase):
    """Test measure_contraction_rate."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_contraction_rate("")
        self.assertEqual(result, 0.0)

    def test_no_contractions(self):
        wf = WriterFormality()
        text = "I do not believe we are going to the store."
        result = wf.measure_contraction_rate(text)
        self.assertEqual(result, 0.0)

    def test_all_contractions(self):
        wf = WriterFormality()
        text = "don't won't can't shouldn't wouldn't"
        result = wf.measure_contraction_rate(text)
        self.assertGreater(result, 0.8)

    def test_mixed_contractions(self):
        wf = WriterFormality()
        text = "I don't think we'll make it, but we should try."
        result = wf.measure_contraction_rate(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_pronoun_contractions(self):
        wf = WriterFormality()
        text = "I'm sure they're coming. He's already here."
        result = wf.measure_contraction_rate(text)
        self.assertGreater(result, 0.5)

    def test_no_verbs(self):
        wf = WriterFormality()
        text = "beautiful wonderful amazing"
        result = wf.measure_contraction_rate(text)
        self.assertEqual(result, 0.0)


class TestInformalPronounRate(unittest.TestCase):
    """Test measure_informal_pronoun_rate."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_informal_pronoun_rate("")
        self.assertEqual(result, 0.0)

    def test_no_personal_pronouns(self):
        wf = WriterFormality()
        text = "The data suggests a correlation between variables."
        result = wf.measure_informal_pronoun_rate(text)
        self.assertEqual(result, 0.0)

    def test_first_person_heavy(self):
        wf = WriterFormality()
        text = "I think I should go. I need my book."
        result = wf.measure_informal_pronoun_rate(text)
        self.assertGreater(result, 0.3)

    def test_second_person(self):
        wf = WriterFormality()
        text = "You should try this. Your results will improve."
        result = wf.measure_informal_pronoun_rate(text)
        self.assertGreater(result, 0.2)

    def test_capped_at_one(self):
        wf = WriterFormality()
        text = "I me my mine myself we us our ours"
        result = wf.measure_informal_pronoun_rate(text)
        self.assertLessEqual(result, 1.0)


class TestColloquialDensity(unittest.TestCase):
    """Test measure_colloquial_density."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_colloquial_density("")
        self.assertEqual(result, 0.0)

    def test_no_colloquialisms(self):
        wf = WriterFormality()
        text = "The implementation of the methodology was thorough."
        result = wf.measure_colloquial_density(text)
        self.assertEqual(result, 0.0)

    def test_heavy_slang(self):
        wf = WriterFormality()
        text = "gonna wanna kinda sorta prolly legit sus"
        result = wf.measure_colloquial_density(text)
        self.assertGreater(result, 0.8)

    def test_mixed_register(self):
        wf = WriterFormality()
        text = "The implementation was basically done already kinda."
        result = wf.measure_colloquial_density(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 0.5)

    def test_discourse_markers(self):
        wf = WriterFormality()
        text = "like literally honestly basically seriously"
        result = wf.measure_colloquial_density(text)
        self.assertGreater(result, 0.8)

    def test_fillers(self):
        wf = WriterFormality()
        text = "um uh well okay yeah nope meh"
        result = wf.measure_colloquial_density(text)
        self.assertGreater(result, 0.8)


class TestPassiveVoiceRatio(unittest.TestCase):
    """Test measure_passive_voice_ratio."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_passive_voice_ratio("")
        self.assertEqual(result, 0.0)

    def test_no_passive(self):
        wf = WriterFormality()
        text = "The cat chased the mouse. The dog ran fast."
        result = wf.measure_passive_voice_ratio(text)
        self.assertEqual(result, 0.0)

    def test_all_passive(self):
        wf = WriterFormality()
        text = "The data was collected. The results were analyzed."
        result = wf.measure_passive_voice_ratio(text)
        self.assertGreater(result, 0.5)

    def test_mixed_voice(self):
        wf = WriterFormality()
        text = "The researcher collected the data. The results were analyzed."
        result = wf.measure_passive_voice_ratio(text)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_capped_at_one(self):
        wf = WriterFormality()
        text = "was chased was caught was eaten was broken"
        result = wf.measure_passive_voice_ratio(text)
        self.assertLessEqual(result, 1.0)


class TestLatinateVocabularyRatio(unittest.TestCase):
    """Test measure_latinate_vocabulary_ratio."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_latinate_vocabulary_ratio("")
        self.assertEqual(result, 0.0)

    def test_no_latinate_words(self):
        wf = WriterFormality()
        text = "The cat sat on the mat and ate a big fish."
        result = wf.measure_latinate_vocabulary_ratio(text)
        self.assertEqual(result, 0.0)

    def test_all_latinate(self):
        wf = WriterFormality()
        text = "implementation classification determination specification"
        result = wf.measure_latinate_vocabulary_ratio(text)
        self.assertGreater(result, 0.5)

    def test_academic_text(self):
        wf = WriterFormality()
        text = "The investigation of computational methodologies requires careful consideration."
        result = wf.measure_latinate_vocabulary_ratio(text)
        self.assertGreater(result, 0.2)

    def test_function_words_excluded(self):
        wf = WriterFormality()
        text = "the and or but in on at to"
        result = wf.measure_latinate_vocabulary_ratio(text)
        self.assertEqual(result, 0.0)


class TestFormalityHedgeRate(unittest.TestCase):
    """Test measure_formality_hedge_rate."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure_formality_hedge_rate("")
        self.assertEqual(result, 0.0)

    def test_no_hedging(self):
        wf = WriterFormality()
        text = "The cat sat on the mat. The dog ran fast."
        result = wf.measure_formality_hedge_rate(text)
        self.assertEqual(result, 0.0)

    def test_single_word_hedges(self):
        wf = WriterFormality()
        text = "Arguably, this is correct. Presumably, it works."
        result = wf.measure_formality_hedge_rate(text)
        self.assertGreater(result, 0.5)

    def test_phrase_hedges(self):
        wf = WriterFormality()
        text = "It should be noted that this approach has limitations."
        result = wf.measure_formality_hedge_rate(text)
        self.assertGreater(result, 0.5)

    def test_mixed_hedging(self):
        wf = WriterFormality()
        text = "The cat sat. It appears that the dog ran. The bird flew."
        result = wf.measure_formality_hedge_rate(text)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_tentative_language(self):
        wf = WriterFormality()
        text = "It is possible that the results are significant."
        result = wf.measure_formality_hedge_rate(text)
        self.assertGreater(result, 0.5)


class TestFormalityIndex(unittest.TestCase):
    """Test compute_formality_index."""

    def test_all_zeros(self):
        """All informal signals at max, no formal signals."""
        wf = WriterFormality()
        result = wf.compute_formality_index(1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_all_ones(self):
        """No informal signals, all formal signals at max."""
        wf = WriterFormality()
        result = wf.compute_formality_index(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_mixed_signals(self):
        wf = WriterFormality()
        result = wf.compute_formality_index(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        # (1-0.5)*0.20 + (1-0.5)*0.15 + (1-0.5)*0.20 + 0.5*0.15 + 0.5*0.20 + 0.5*0.10
        expected = 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.20 + 0.5 * 0.10
        self.assertAlmostEqual(result, expected, places=4)

    def test_formula_correctness(self):
        wf = WriterFormality()
        result = wf.compute_formality_index(0.2, 0.3, 0.1, 0.6, 0.7, 0.4)
        expected = (
            (1 - 0.2) * 0.20
            + (1 - 0.3) * 0.15
            + (1 - 0.1) * 0.20
            + 0.6 * 0.15
            + 0.7 * 0.20
            + 0.4 * 0.10
        )
        self.assertAlmostEqual(result, expected, places=4)

    def test_weights_sum_to_one(self):
        """Verify that weights sum to 1.0."""
        weights = [0.20, 0.15, 0.20, 0.15, 0.20, 0.10]
        self.assertAlmostEqual(sum(weights), 1.0)


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_academic(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.80), "academic")
        self.assertEqual(wf.classify(0.75), "academic")

    def test_formal(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.65), "formal")
        self.assertEqual(wf.classify(0.55), "formal")

    def test_conversational(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.45), "conversational")
        self.assertEqual(wf.classify(0.35), "conversational")

    def test_casual(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.30), "casual")
        self.assertEqual(wf.classify(0.20), "casual")

    def test_colloquial(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.15), "colloquial")
        self.assertEqual(wf.classify(0.0), "colloquial")

    def test_boundary_values(self):
        wf = WriterFormality()
        self.assertEqual(wf.classify(0.749), "formal")
        self.assertEqual(wf.classify(0.549), "conversational")
        self.assertEqual(wf.classify(0.349), "casual")
        self.assertEqual(wf.classify(0.199), "colloquial")


class TestMeasure(unittest.TestCase):
    """Test measure method with full integration."""

    def test_empty_text(self):
        wf = WriterFormality()
        result = wf.measure("")
        self.assertEqual(result["formality_index"], 0.0)
        self.assertEqual(result["classification"], "colloquial")

    def test_academic_text(self):
        wf = WriterFormality()
        text = """The utilization of computational methodologies in the
        analysis of linguistic phenomena has been extensively documented
        in contemporary scholarship. It should be noted that the
        implementation of automated text classification systems
        necessitates careful consideration of methodological limitations."""
        result = wf.measure(text)
        self.assertGreater(result["formality_index"], 0.4)
        self.assertIn(result["classification"], ["academic", "formal", "conversational"])

    def test_casual_text(self):
        wf = WriterFormality()
        text = """So I was like, totally gonna go to the store but then
        my friend texted me and we ended up just chilling at home. It
        was super cool though, we watched this really awesome movie and
        stuff. Honestly, it was the best night ever."""
        result = wf.measure(text)
        self.assertLess(result["formality_index"], 0.6)
        self.assertIn(result["classification"], ["casual", "colloquial", "conversational"])

    def test_result_structure(self):
        wf = WriterFormality()
        result = wf.measure("The cat sat on the mat.")
        self.assertIn("contraction_rate", result)
        self.assertIn("informal_pronoun_rate", result)
        self.assertIn("colloquial_density", result)
        self.assertIn("passive_voice_ratio", result)
        self.assertIn("latinate_vocabulary_ratio", result)
        self.assertIn("formality_hedge_rate", result)
        self.assertIn("formality_index", result)
        self.assertIn("classification", result)

    def test_result_types(self):
        wf = WriterFormality()
        result = wf.measure("The cat sat on the mat.")
        self.assertIsInstance(result["contraction_rate"], float)
        self.assertIsInstance(result["informal_pronoun_rate"], float)
        self.assertIsInstance(result["colloquial_density"], float)
        self.assertIsInstance(result["passive_voice_ratio"], float)
        self.assertIsInstance(result["latinate_vocabulary_ratio"], float)
        self.assertIsInstance(result["formality_hedge_rate"], float)
        self.assertIsInstance(result["formality_index"], float)
        self.assertIsInstance(result["classification"], str)

    def test_result_ranges(self):
        wf = WriterFormality()
        result = wf.measure("The cat sat on the mat.")
        for key in ["contraction_rate", "informal_pronoun_rate",
                     "colloquial_density", "passive_voice_ratio",
                     "latinate_vocabulary_ratio", "formality_hedge_rate",
                     "formality_index"]:
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 1.0)

    def test_rounding(self):
        wf = WriterFormality()
        result = wf.measure("The cat sat on the mat.")
        for key in ["contraction_rate", "informal_pronoun_rate",
                     "colloquial_density", "passive_voice_ratio",
                     "latinate_vocabulary_ratio", "formality_hedge_rate",
                     "formality_index"]:
            value_str = str(result[key])
            if '.' in value_str:
                decimals = len(value_str.split('.')[1])
                self.assertLessEqual(decimals, 4)

    def test_contraction_detection_in_measure(self):
        wf = WriterFormality()
        result = wf.measure("I don't think we'll make it, can't you see?")
        self.assertGreater(result["contraction_rate"], 0.3)

    def test_latinate_detection_in_measure(self):
        wf = WriterFormality()
        result = wf.measure("The implementation of the specification requires determination.")
        self.assertGreater(result["latinate_vocabulary_ratio"], 0.2)


class TestWordLists(unittest.TestCase):
    """Test that word lists are properly defined."""

    def test_contractions_not_empty(self):
        self.assertGreater(len(CONTRACTIONS), 30)

    def test_informal_pronouns_not_empty(self):
        self.assertGreater(len(INFORMAL_PRONOUNS), 10)

    def test_colloquial_expressions_not_empty(self):
        self.assertGreater(len(COLLOQUIAL_EXPRESSIONS), 100)

    def test_latinate_suffixes_not_empty(self):
        self.assertGreater(len(LATINATE_SUFFIXES), 10)

    def test_latinate_prefixes_not_empty(self):
        self.assertGreater(len(LATINATE_PREFIXES), 10)

    def test_formal_hedges_not_empty(self):
        self.assertGreater(len(FORMAL_HEDGES), 8)

    def test_formal_hedge_phrases_not_empty(self):
        self.assertGreater(len(FORMAL_HEDGE_PHRASES), 15)

    def test_function_words_not_empty(self):
        self.assertGreater(len(FUNCTION_WORDS), 50)

    def test_contractions_lowercase(self):
        for word in CONTRACTIONS:
            self.assertEqual(word, word.lower())

    def test_informal_pronouns_lowercase(self):
        for word in INFORMAL_PRONOUNS:
            self.assertEqual(word, word.lower())

    def test_colloquial_lowercase(self):
        for word in COLLOQUIAL_EXPRESSIONS:
            self.assertEqual(word, word.lower())

    def test_formal_hedges_lowercase(self):
        for word in FORMAL_HEDGES:
            self.assertEqual(word, word.lower())


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word_text(self):
        wf = WriterFormality()
        result = wf.measure("hello")
        self.assertIsNotNone(result["formality_index"])

    def test_only_punctuation(self):
        wf = WriterFormality()
        result = wf.measure("...!!!???")
        self.assertIsNotNone(result["formality_index"])

    def test_very_long_sentence(self):
        wf = WriterFormality()
        text = "The " + "very " * 100 + "long sentence."
        result = wf.measure(text)
        self.assertIsNotNone(result["formality_index"])

    def test_repeated_words(self):
        wf = WriterFormality()
        text = "gonna gonna gonna gonna gonna"
        result = wf.measure(text)
        self.assertGreater(result["colloquial_density"], 0.5)

    def test_mixed_case_contractions(self):
        wf = WriterFormality()
        result = wf.measure("DON'T WON'T CAN'T")
        self.assertGreater(result["contraction_rate"], 0.5)

    def test_numbers_in_text(self):
        wf = WriterFormality()
        result = wf.measure("There are 5 items in the collection of 100.")
        self.assertIsNotNone(result["formality_index"])

    def test_unicode_text(self):
        wf = WriterFormality()
        result = wf.measure("café résumé naïve")
        self.assertIsNotNone(result["formality_index"])

    def test_single_sentence_no_period(self):
        wf = WriterFormality()
        result = wf.measure("The cat sat on the mat")
        self.assertIsNotNone(result["formality_index"])

    def test_formal_vs_informal_ordering(self):
        """Formal text should score higher than informal text."""
        wf = WriterFormality()
        formal = wf.measure(
            "The implementation of the specification requires careful "
            "consideration of methodological limitations. It should be "
            "noted that the utilization of computational approaches has "
            "been extensively documented."
        )
        informal = wf.measure(
            "I'm gonna go to the store cuz I kinda need stuff. "
            "My friend said it's super cool there and they've got "
            "awesome things. Wanna come?"
        )
        self.assertGreater(formal["formality_index"], informal["formality_index"])


if __name__ == "__main__":
    unittest.main()
