#!/usr/bin/env python3
"""Tests for writer_concreteness — 105 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_concreteness import (  # noqa: E402
    ABSTRACT_NOUNS,
    ACTION_VERBS,
    BODY_PARTS,
    CONCRETE_NOUNS,
    EMBODIED_VERBS,
    SENSORY_WORDS,
    SPATIAL_MARKERS,
    STATIVE_VERBS,
    WriterConcreteness,
)


class TestWriterConcretenessInit(unittest.TestCase):
    """Test WriterConcreteness initialization."""

    def test_init_default(self):
        wc = WriterConcreteness()
        self.assertIsNotNone(wc.sensory_words)
        self.assertIsNotNone(wc.concrete_nouns)

    def test_init_sets_all_attributes(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.sensory_words, SENSORY_WORDS)
        self.assertEqual(wc.concrete_nouns, CONCRETE_NOUNS)
        self.assertEqual(wc.abstract_nouns, ABSTRACT_NOUNS)
        self.assertEqual(wc.action_verbs, ACTION_VERBS)
        self.assertEqual(wc.stative_verbs, STATIVE_VERBS)
        self.assertEqual(wc.spatial_markers, SPATIAL_MARKERS)
        self.assertEqual(wc.body_parts, BODY_PARTS)
        self.assertEqual(wc.embodied_verbs, EMBODIED_VERBS)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._tokenize(""), [])

    def test_single_word(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        wc = WriterConcreteness()
        tokens = wc._tokenize("The quick brown fox")
        self.assertEqual(tokens, ["the", "quick", "brown", "fox"])

    def test_punctuation_removed(self):
        wc = WriterConcreteness()
        tokens = wc._tokenize("Hello, world!")
        self.assertEqual(tokens, ["hello", "world"])

    def test_case_insensitive(self):
        wc = WriterConcreteness()
        tokens = wc._tokenize("HELLO World")
        self.assertEqual(tokens, ["hello", "world"])

    def test_numbers_excluded(self):
        wc = WriterConcreteness()
        tokens = wc._tokenize("I have 5 cats")
        self.assertIn("have", tokens)
        self.assertNotIn("5", tokens)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._split_sentences(""), [])

    def test_single_sentence(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("The cat sat.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("The cat sat. The dog ran.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("Stop! Help!")
        self.assertEqual(len(result), 2)

    def test_question_marks(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("Why? How?")
        self.assertEqual(len(result), 2)

    def test_mixed_punctuation(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("Hello. Why? Stop!")
        self.assertEqual(len(result), 3)

    def test_whitespace_stripped(self):
        wc = WriterConcreteness()
        result = wc._split_sentences("  Hello.   World.  ")
        self.assertTrue(all(s == s.strip() for s in result))


class TestGetPosSimple(unittest.TestCase):
    """Test _get_pos_simple heuristic."""

    def test_ing_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("running"), "VERB")

    def test_ed_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("walked"), "VERB")

    def test_ly_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("quickly"), "ADV")

    def test_tion_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("action"), "NOUN")

    def test_ment_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("movement"), "NOUN")

    def test_ful_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("beautiful"), "ADJ")

    def test_less_ending(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("careless"), "ADJ")

    def test_other(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._get_pos_simple("cat"), "OTHER")


class TestCountContentWords(unittest.TestCase):
    """Test _count_content_words."""

    def test_empty_list(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._count_content_words([]), 1)

    def test_function_words_only(self):
        wc = WriterConcreteness()
        tokens = ["the", "a", "is", "and"]
        result = wc._count_content_words(tokens)
        self.assertGreaterEqual(result, 1)

    def test_content_words_detected(self):
        wc = WriterConcreteness()
        tokens = ["running", "quickly", "beautiful", "cat"]
        result = wc._count_content_words(tokens)
        self.assertGreaterEqual(result, 1)


class TestCountNouns(unittest.TestCase):
    """Test _count_nouns."""

    def test_empty_list(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._count_nouns([]), 1)

    def test_concrete_noun_detected(self):
        wc = WriterConcreteness()
        tokens = ["table", "chair", "run"]
        result = wc._count_nouns(tokens)
        self.assertGreaterEqual(result, 2)

    def test_abstract_noun_detected(self):
        wc = WriterConcreteness()
        tokens = ["freedom", "justice", "run"]
        result = wc._count_nouns(tokens)
        self.assertGreaterEqual(result, 2)


class TestCountVerbs(unittest.TestCase):
    """Test _count_verbs."""

    def test_empty_list(self):
        wc = WriterConcreteness()
        self.assertEqual(wc._count_verbs([]), 1)

    def test_action_verb_detected(self):
        wc = WriterConcreteness()
        tokens = ["run", "jump", "table"]
        result = wc._count_verbs(tokens)
        self.assertGreaterEqual(result, 2)

    def test_stative_verb_detected(self):
        wc = WriterConcreteness()
        tokens = ["is", "seem", "table"]
        result = wc._count_verbs(tokens)
        self.assertGreaterEqual(result, 2)


class TestSensoryWordRatio(unittest.TestCase):
    """Test measure_sensory_word_ratio."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("")
        self.assertEqual(result, 0.0)

    def test_no_sensory_words(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("The idea of freedom")
        self.assertLess(result, 0.1)

    def test_all_sensory_words(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("red blue green bright dark")
        self.assertGreater(result, 0.5)

    def test_mixed_content(self):
        wc = WriterConcreteness()
        text = "The bright red car drove quickly down the street"
        result = wc.measure_sensory_word_ratio(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_visual_words(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("bright dark shadow light")
        self.assertGreater(result, 0.3)

    def test_auditory_words(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("loud quiet whisper crash")
        self.assertGreater(result, 0.3)

    def test_tactile_words(self):
        wc = WriterConcreteness()
        result = wc.measure_sensory_word_ratio("rough smooth hot cold")
        self.assertGreater(result, 0.3)


class TestConcreteNounRatio(unittest.TestCase):
    """Test measure_concrete_noun_ratio."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure_concrete_noun_ratio("")
        self.assertEqual(result, 0.0)

    def test_no_nouns(self):
        wc = WriterConcreteness()
        result = wc.measure_concrete_noun_ratio("run quickly now")
        self.assertEqual(result, 0.0)

    def test_all_concrete_nouns(self):
        wc = WriterConcreteness()
        result = wc.measure_concrete_noun_ratio("table chair desk bed")
        self.assertGreater(result, 0.8)

    def test_all_abstract_nouns(self):
        wc = WriterConcreteness()
        result = wc.measure_concrete_noun_ratio("freedom justice equality rights")
        self.assertLess(result, 0.3)

    def test_mixed_nouns(self):
        wc = WriterConcreteness()
        text = "The table represents freedom and justice"
        result = wc.measure_concrete_noun_ratio(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_body_parts_concrete(self):
        wc = WriterConcreteness()
        result = wc.measure_concrete_noun_ratio("hand foot arm leg")
        self.assertGreater(result, 0.8)


class TestActionVerbRatio(unittest.TestCase):
    """Test measure_action_verb_ratio."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure_action_verb_ratio("")
        self.assertEqual(result, 0.0)

    def test_no_verbs(self):
        wc = WriterConcreteness()
        result = wc.measure_action_verb_ratio("table chair desk")
        self.assertEqual(result, 0.0)

    def test_all_action_verbs(self):
        wc = WriterConcreteness()
        result = wc.measure_action_verb_ratio("run jump climb fall")
        self.assertGreater(result, 0.8)

    def test_all_stative_verbs(self):
        wc = WriterConcreteness()
        result = wc.measure_action_verb_ratio("is seem become have")
        self.assertLess(result, 0.3)

    def test_mixed_verbs(self):
        wc = WriterConcreteness()
        text = "She runs and thinks and jumps and believes"
        result = wc.measure_action_verb_ratio(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_physical_actions(self):
        wc = WriterConcreteness()
        result = wc.measure_action_verb_ratio("push pull throw catch")
        self.assertGreater(result, 0.8)


class TestSpatialMarkerDensity(unittest.TestCase):
    """Test measure_spatial_marker_density."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure_spatial_marker_density("")
        self.assertEqual(result, 0.0)

    def test_no_spatial_markers(self):
        wc = WriterConcreteness()
        result = wc.measure_spatial_marker_density("The idea is important.")
        self.assertEqual(result, 0.0)

    def test_all_spatial_markers(self):
        wc = WriterConcreteness()
        text = "Above the clouds. Below the surface. Between the trees."
        result = wc.measure_spatial_marker_density(text)
        self.assertGreater(result, 0.8)

    def test_mixed_content(self):
        wc = WriterConcreteness()
        text = "The cat sat. Above the dog. The bird flew. Below the tree."
        result = wc.measure_spatial_marker_density(text)
        self.assertGreater(result, 0.3)
        self.assertLess(result, 1.0)

    def test_directional_markers(self):
        wc = WriterConcreteness()
        result = wc.measure_spatial_marker_density("Look up. Look down. Look around.")
        self.assertGreater(result, 0.5)


class TestEmbodiedLanguageRate(unittest.TestCase):
    """Test measure_embodied_language_rate."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure_embodied_language_rate("")
        self.assertEqual(result, 0.0)

    def test_no_embodied_language(self):
        wc = WriterConcreteness()
        result = wc.measure_embodied_language_rate("The idea is important.")
        self.assertEqual(result, 0.0)

    def test_body_parts(self):
        wc = WriterConcreteness()
        text = "Her hand trembled. His heart raced. Their eyes met."
        result = wc.measure_embodied_language_rate(text)
        self.assertGreater(result, 0.8)

    def test_embodied_verbs(self):
        wc = WriterConcreteness()
        text = "She shivered. He ached. They trembled."
        result = wc.measure_embodied_language_rate(text)
        self.assertGreater(result, 0.2)  # At least one sentence has embodied verbs

    def test_mixed_content(self):
        wc = WriterConcreteness()
        text = "The cat sat. Her hand trembled. The bird flew."
        result = wc.measure_embodied_language_rate(text)
        self.assertGreater(result, 0.2)
        self.assertLess(result, 1.0)


class TestConcretenessIndex(unittest.TestCase):
    """Test compute_concreteness_index."""

    def test_all_zeros(self):
        wc = WriterConcreteness()
        result = wc.compute_concreteness_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        wc = WriterConcreteness()
        result = wc.compute_concreteness_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(result, 1.0)

    def test_weighted_average(self):
        wc = WriterConcreteness()
        result = wc.compute_concreteness_index(0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertEqual(result, 0.5)

    def test_sensory_weight(self):
        wc = WriterConcreteness()
        result1 = wc.compute_concreteness_index(1.0, 0.0, 0.0, 0.0, 0.0)
        result2 = wc.compute_concreteness_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertGreater(result1, result2)

    def test_formula_correctness(self):
        wc = WriterConcreteness()
        result = wc.compute_concreteness_index(0.8, 0.6, 0.7, 0.5, 0.4)
        expected = 0.8 * 0.30 + 0.6 * 0.25 + 0.7 * 0.20 + 0.5 * 0.15 + 0.4 * 0.10
        self.assertAlmostEqual(result, expected, places=4)


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_vivid(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.70), "vivid")
        self.assertEqual(wc.classify(0.60), "vivid")

    def test_concrete(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.55), "concrete")
        self.assertEqual(wc.classify(0.45), "concrete")

    def test_balanced(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.40), "balanced")
        self.assertEqual(wc.classify(0.35), "balanced")

    def test_abstract(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.30), "abstract")
        self.assertEqual(wc.classify(0.20), "abstract")

    def test_ethereal(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.15), "ethereal")
        self.assertEqual(wc.classify(0.0), "ethereal")

    def test_boundary_values(self):
        wc = WriterConcreteness()
        self.assertEqual(wc.classify(0.599), "concrete")
        self.assertEqual(wc.classify(0.449), "balanced")
        self.assertEqual(wc.classify(0.349), "abstract")
        self.assertEqual(wc.classify(0.199), "ethereal")


class TestMeasure(unittest.TestCase):
    """Test measure method with full integration."""

    def test_empty_text(self):
        wc = WriterConcreteness()
        result = wc.measure("")
        self.assertEqual(result["concreteness_index"], 0.0)
        self.assertEqual(result["classification"], "ethereal")

    def test_vivid_text(self):
        wc = WriterConcreteness()
        text = """The rough bark scraped her palm as she climbed.
        Below, the river rushed over smooth stones, cold and clear.
        She could smell the pine needles, sharp and fragrant in the
        morning air. Her muscles ached, but the view from the ridge
        made her heart beat faster."""
        result = wc.measure(text)
        self.assertGreater(result["concreteness_index"], 0.2)
        self.assertIn(result["classification"], ["vivid", "concrete", "balanced", "abstract"])

    def test_abstract_text(self):
        wc = WriterConcreteness()
        text = """The concept of freedom requires understanding
        of individual rights and social responsibility. Democracy
        depends on knowledge and participation. Justice must balance
        equality with liberty. Truth emerges through reason and
        evidence."""
        result = wc.measure(text)
        self.assertLess(result["concreteness_index"], 0.4)
        self.assertIn(result["classification"], ["abstract", "ethereal", "balanced"])

    def test_result_structure(self):
        wc = WriterConcreteness()
        result = wc.measure("The cat sat on the mat.")
        self.assertIn("sensory_word_ratio", result)
        self.assertIn("concrete_noun_ratio", result)
        self.assertIn("action_verb_ratio", result)
        self.assertIn("spatial_marker_density", result)
        self.assertIn("embodied_language_rate", result)
        self.assertIn("concreteness_index", result)
        self.assertIn("classification", result)

    def test_result_types(self):
        wc = WriterConcreteness()
        result = wc.measure("The cat sat on the mat.")
        self.assertIsInstance(result["sensory_word_ratio"], float)
        self.assertIsInstance(result["concrete_noun_ratio"], float)
        self.assertIsInstance(result["action_verb_ratio"], float)
        self.assertIsInstance(result["spatial_marker_density"], float)
        self.assertIsInstance(result["embodied_language_rate"], float)
        self.assertIsInstance(result["concreteness_index"], float)
        self.assertIsInstance(result["classification"], str)

    def test_result_ranges(self):
        wc = WriterConcreteness()
        result = wc.measure("The cat sat on the mat.")
        self.assertGreaterEqual(result["sensory_word_ratio"], 0.0)
        self.assertLessEqual(result["sensory_word_ratio"], 1.0)
        self.assertGreaterEqual(result["concrete_noun_ratio"], 0.0)
        self.assertLessEqual(result["concrete_noun_ratio"], 1.0)
        self.assertGreaterEqual(result["action_verb_ratio"], 0.0)
        self.assertLessEqual(result["action_verb_ratio"], 1.0)
        self.assertGreaterEqual(result["spatial_marker_density"], 0.0)
        self.assertLessEqual(result["spatial_marker_density"], 1.0)
        self.assertGreaterEqual(result["embodied_language_rate"], 0.0)
        self.assertLessEqual(result["embodied_language_rate"], 1.0)
        self.assertGreaterEqual(result["concreteness_index"], 0.0)
        self.assertLessEqual(result["concreteness_index"], 1.0)

    def test_rounding(self):
        wc = WriterConcreteness()
        result = wc.measure("The cat sat on the mat.")
        # Check that values are rounded to 4 decimal places
        for key in ["sensory_word_ratio", "concrete_noun_ratio",
                    "action_verb_ratio", "spatial_marker_density",
                    "embodied_language_rate", "concreteness_index"]:
            value_str = str(result[key])
            if '.' in value_str:
                decimals = len(value_str.split('.')[1])
                self.assertLessEqual(decimals, 4)


class TestWordLists(unittest.TestCase):
    """Test that word lists are properly defined."""

    def test_sensory_words_not_empty(self):
        self.assertGreater(len(SENSORY_WORDS), 50)

    def test_concrete_nouns_not_empty(self):
        self.assertGreater(len(CONCRETE_NOUNS), 50)

    def test_abstract_nouns_not_empty(self):
        self.assertGreater(len(ABSTRACT_NOUNS), 30)

    def test_action_verbs_not_empty(self):
        self.assertGreater(len(ACTION_VERBS), 50)

    def test_stative_verbs_not_empty(self):
        self.assertGreater(len(STATIVE_VERBS), 20)

    def test_spatial_markers_not_empty(self):
        self.assertGreater(len(SPATIAL_MARKERS), 30)

    def test_body_parts_not_empty(self):
        self.assertGreater(len(BODY_PARTS), 30)

    def test_embodied_verbs_not_empty(self):
        self.assertGreater(len(EMBODIED_VERBS), 20)

    def test_sensory_words_lowercase(self):
        for word in SENSORY_WORDS:
            self.assertEqual(word, word.lower())

    def test_concrete_nouns_lowercase(self):
        for word in CONCRETE_NOUNS:
            self.assertEqual(word, word.lower())


if __name__ == "__main__":
    unittest.main()
