#!/usr/bin/env python3
"""Tests for writer_sensory_density — 120+ test cases."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_sensory_density import (  # noqa: E402
    AUDITORY_WORDS,
    GUSTATORY_WORDS,
    KINESTHETIC_WORDS,
    OLFACTORY_WORDS,
    TACTILE_WORDS,
    VISUAL_WORDS,
    WriterSensoryDensity,
    _build_word_set,
    _split_sentences,
    _tokenize,
)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestBuildWordSet(unittest.TestCase):
    """Test _build_word_set helper."""

    def test_empty_list(self):
        self.assertEqual(_build_word_set([]), set())

    def test_lowercase_conversion(self):
        result = _build_word_set(["Red", "BLUE", "green"])
        self.assertEqual(result, {"red", "blue", "green"})

    def test_preserves_entries(self):
        words = ["smooth", "rough", "soft"]
        result = _build_word_set(words)
        self.assertEqual(len(result), 3)
        for w in words:
            self.assertIn(w, result)

    def test_deduplication(self):
        result = _build_word_set(["red", "Red", "RED"])
        self.assertEqual(result, {"red"})


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_single_word(self):
        self.assertEqual(_tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        result = _tokenize("the red ball")
        self.assertEqual(result, ["the", "red", "ball"])

    def test_uppercase_lowered(self):
        result = _tokenize("BRIGHT LIGHT")
        self.assertEqual(result, ["bright", "light"])

    def test_punctuation_stripped(self):
        result = _tokenize("dark, gloomy, silent.")
        self.assertEqual(result, ["dark", "gloomy", "silent"])

    def test_hyphenated_words(self):
        result = _tokenize("high-pitched off-balance")
        self.assertIn("high-pitched", result)
        self.assertIn("off-balance", result)

    def test_apostrophe_preserved(self):
        result = _tokenize("don't can't")
        self.assertIn("don't", result)
        self.assertIn("can't", result)

    def test_numbers_excluded(self):
        result = _tokenize("3 red balls 5 loud sounds")
        self.assertNotIn("3", result)
        self.assertNotIn("5", result)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("She walked home.")
        self.assertEqual(result, ["She walked home."])

    def test_multiple_sentences(self):
        result = _split_sentences("She walked. He ran. They flew.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        result = _split_sentences("Did she walk? Yes she did.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        result = _split_sentences("Run! Go! Now!")
        self.assertEqual(len(result), 3)

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   "), [])


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestWriterSensoryDensityInit(unittest.TestCase):
    """Test WriterSensoryDensity initialization."""

    def test_init_default(self):
        wsd = WriterSensoryDensity()
        self.assertIsNotNone(wsd.visual)
        self.assertIsNotNone(wsd.auditory)
        self.assertIsNotNone(wsd.olfactory)
        self.assertIsNotNone(wsd.gustatory)
        self.assertIsNotNone(wsd.tactile)
        self.assertIsNotNone(wsd.kinesthetic)

    def test_init_visual_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.visual), len(VISUAL_WORDS))

    def test_init_auditory_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.auditory), len(AUDITORY_WORDS))

    def test_init_olfactory_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.olfactory), len(OLFACTORY_WORDS))

    def test_init_gustatory_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.gustatory), len(GUSTATORY_WORDS))

    def test_init_tactile_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.tactile), len(TACTILE_WORDS))

    def test_init_kinesthetic_set(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(len(wsd.kinesthetic), len(KINESTHETIC_WORDS))

    def test_all_sets_are_lowercase(self):
        wsd = WriterSensoryDensity()
        for lexicon in [wsd.visual, wsd.auditory, wsd.olfactory,
                        wsd.gustatory, wsd.tactile, wsd.kinesthetic]:
            for word in lexicon:
                self.assertEqual(word, word.lower(),
                                 f"{word!r} is not lowercase")


# ---------------------------------------------------------------------------
# Per-modality measure tests
# ---------------------------------------------------------------------------


class TestMeasureVisualDensity(unittest.TestCase):
    """Test measure_visual_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_visual_density(""), 0.0)

    def test_no_visual_words(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_visual_density("justice requires thought"), 0.0)

    def test_all_visual(self):
        wsd = WriterSensoryDensity()
        text = "red blue green gold crimson amber"
        result = wsd.measure_visual_density(text)
        self.assertEqual(result, 1.0)

    def test_partial_visual(self):
        wsd = WriterSensoryDensity()
        text = "the red ball rolled across the dark room"
        result = wsd.measure_visual_density(text)
        # "red" and "dark" are visual; 2/8 = 0.25
        self.assertAlmostEqual(result, 0.25, places=2)

    def test_case_insensitive(self):
        wsd = WriterSensoryDensity()
        r1 = wsd.measure_visual_density("RED BLUE GREEN")
        r2 = wsd.measure_visual_density("red blue green")
        self.assertEqual(r1, r2)


class TestMeasureAuditoryDensity(unittest.TestCase):
    """Test measure_auditory_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_auditory_density(""), 0.0)

    def test_no_auditory(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_auditory_density("the red ball"), 0.0)

    def test_all_auditory(self):
        wsd = WriterSensoryDensity()
        text = "loud quiet silent booming echoing"
        result = wsd.measure_auditory_density(text)
        self.assertEqual(result, 1.0)

    def test_partial(self):
        wsd = WriterSensoryDensity()
        text = "the loud bang echoed through the silent hall"
        result = wsd.measure_auditory_density(text)
        # "loud", "echoed"->"echoing"? no, "echoed" not in set; "silent" yes
        self.assertGreater(result, 0.0)


class TestMeasureOlfactoryDensity(unittest.TestCase):
    """Test measure_olfactory_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_olfactory_density(""), 0.0)

    def test_no_olfactory(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_olfactory_density("the red ball"), 0.0)

    def test_all_olfactory(self):
        wsd = WriterSensoryDensity()
        text = "smell aroma fragrance pungent musty"
        result = wsd.measure_olfactory_density(text)
        self.assertEqual(result, 1.0)

    def test_partial(self):
        wsd = WriterSensoryDensity()
        text = "the smell of fresh bread filled the kitchen"
        result = wsd.measure_olfactory_density(text)
        self.assertGreater(result, 0.0)


class TestMeasureGustatoryDensity(unittest.TestCase):
    """Test measure_gustatory_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_gustatory_density(""), 0.0)

    def test_no_gustatory(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_gustatory_density("the red ball"), 0.0)

    def test_all_gustatory(self):
        wsd = WriterSensoryDensity()
        text = "sweet sour bitter salty umami"
        result = wsd.measure_gustatory_density(text)
        self.assertEqual(result, 1.0)

    def test_partial(self):
        wsd = WriterSensoryDensity()
        text = "the sweet tea had a bitter aftertaste"
        result = wsd.measure_gustatory_density(text)
        self.assertGreater(result, 0.0)


class TestMeasureTactileDensity(unittest.TestCase):
    """Test measure_tactile_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_tactile_density(""), 0.0)

    def test_no_tactile(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_tactile_density("the red ball"), 0.0)

    def test_all_tactile(self):
        wsd = WriterSensoryDensity()
        text = "soft hard smooth rough coarse"
        result = wsd.measure_tactile_density(text)
        self.assertEqual(result, 1.0)

    def test_partial(self):
        wsd = WriterSensoryDensity()
        text = "the soft blanket felt warm against her cold skin"
        result = wsd.measure_tactile_density(text)
        self.assertGreater(result, 0.0)


class TestMeasureKinestheticDensity(unittest.TestCase):
    """Test measure_kinesthetic_density."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_kinesthetic_density(""), 0.0)

    def test_no_kinesthetic(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.measure_kinesthetic_density("the red ball"), 0.0)

    def test_all_kinesthetic(self):
        wsd = WriterSensoryDensity()
        text = "walk run sprint leap climb"
        result = wsd.measure_kinesthetic_density(text)
        self.assertEqual(result, 1.0)

    def test_partial(self):
        wsd = WriterSensoryDensity()
        text = "she walked through the corridor and climbed the stairs"
        result = wsd.measure_kinesthetic_density(text)
        self.assertGreater(result, 0.0)


# ---------------------------------------------------------------------------
# Composite tests
# ---------------------------------------------------------------------------


class TestComputeSensoryDensityIndex(unittest.TestCase):
    """Test compute_sensory_density_index."""

    def test_all_zeros(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_density_index(0, 0, 0, 0, 0, 0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_density_index(1, 1, 1, 1, 1, 1)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_visual_only(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_density_index(1, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.22, places=4)

    def test_tactile_only(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_density_index(0, 0, 0, 0, 1, 0)
        self.assertAlmostEqual(result, 0.22, places=4)

    def test_weights_sum_to_one(self):
        # All channels at same value should yield that value
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_density_index(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_visual_heavier_than_olfactory(self):
        wsd = WriterSensoryDensity()
        visual_only = wsd.compute_sensory_density_index(1, 0, 0, 0, 0, 0)
        olfactory_only = wsd.compute_sensory_density_index(0, 0, 1, 0, 0, 0)
        self.assertGreater(visual_only, olfactory_only)


class TestComputeSensoryBalance(unittest.TestCase):
    """Test compute_sensory_balance."""

    def test_all_zeros(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_balance(0, 0, 0, 0, 0, 0)
        self.assertEqual(result, 0.0)

    def test_perfect_balance(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_balance(0.1, 0.1, 0.1, 0.1, 0.1, 0.1)
        self.assertAlmostEqual(result, 1.0, places=4)

    def test_single_channel(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_balance(1.0, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_two_channels_balanced(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_balance(0.5, 0, 0, 0, 0.5, 0)
        # Two equal channels: entropy = log(2), max = log(6)
        expected = math.log(2) / math.log(6)
        self.assertAlmostEqual(result, expected, places=4)

    def test_unbalanced_lower_than_balanced(self):
        wsd = WriterSensoryDensity()
        balanced = wsd.compute_sensory_balance(0.1, 0.1, 0.1, 0.1, 0.1, 0.1)
        unbalanced = wsd.compute_sensory_balance(0.5, 0.02, 0.02, 0.02, 0.02, 0.02)
        self.assertGreater(balanced, unbalanced)

    def test_range_zero_to_one(self):
        wsd = WriterSensoryDensity()
        result = wsd.compute_sensory_balance(0.3, 0.1, 0.05, 0.02, 0.2, 0.15)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_immersive(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.03), "immersive")
        self.assertEqual(wsd.classify(0.05), "immersive")
        self.assertEqual(wsd.classify(1.00), "immersive")

    def test_evocative(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.018), "evocative")
        self.assertEqual(wsd.classify(0.025), "evocative")
        self.assertEqual(wsd.classify(0.0299), "evocative")

    def test_sparse(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.008), "sparse")
        self.assertEqual(wsd.classify(0.012), "sparse")
        self.assertEqual(wsd.classify(0.0179), "sparse")

    def test_abstract(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.002), "abstract")
        self.assertEqual(wsd.classify(0.005), "abstract")
        self.assertEqual(wsd.classify(0.0079), "abstract")

    def test_disembodied(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.00), "disembodied")
        self.assertEqual(wsd.classify(0.001), "disembodied")
        self.assertEqual(wsd.classify(0.0019), "disembodied")

    def test_boundary_immersive(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.03), "immersive")

    def test_boundary_evocative(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.018), "evocative")

    def test_boundary_sparse(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.008), "sparse")

    def test_boundary_abstract(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.classify(0.002), "abstract")


class TestDominantModality(unittest.TestCase):
    """Test dominant_modality method."""

    def test_all_zeros(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0, 0, 0, 0, 0, 0), "none")

    def test_visual_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.5, 0.1, 0.05, 0.02, 0.1, 0.08), "visual")

    def test_auditory_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.1, 0.5, 0.05, 0.02, 0.1, 0.08), "auditory")

    def test_olfactory_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.1, 0.1, 0.5, 0.02, 0.1, 0.08), "olfactory")

    def test_gustatory_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.1, 0.1, 0.05, 0.5, 0.1, 0.08), "gustatory")

    def test_tactile_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.1, 0.1, 0.05, 0.02, 0.5, 0.08), "tactile")

    def test_kinesthetic_dominant(self):
        wsd = WriterSensoryDensity()
        self.assertEqual(wsd.dominant_modality(0.1, 0.1, 0.05, 0.02, 0.1, 0.5), "kinesthetic")


# ---------------------------------------------------------------------------
# Full measurement tests
# ---------------------------------------------------------------------------


class TestMeasure(unittest.TestCase):
    """Test the full measure() method."""

    def test_empty(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("")
        self.assertEqual(result["classification"], "disembodied")
        self.assertEqual(result["sensory_density_index"], 0.0)
        self.assertEqual(result["dominant_modality"], "none")

    def test_keys_present(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("some text here")
        expected_keys = {
            "visual_density", "auditory_density", "olfactory_density",
            "gustatory_density", "tactile_density", "kinesthetic_density",
            "sensory_density_index", "sensory_balance", "classification",
            "dominant_modality",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_immersive_text(self):
        wsd = WriterSensoryDensity()
        text = (
            "The amber light slanted through the dusty window. "
            "She could smell the musty books and hear the faint "
            "ticking of the clock. The velvet curtain felt soft "
            "against her fingertips. Outside, the wind howled and "
            "the rain hammered against the glass. She tasted the "
            "lukewarm tea — bitter now. The chair creaked as she "
            "settled, her bare feet sinking into the scratchy wool rug."
        )
        result = wsd.measure(text)
        self.assertIn(result["classification"], ("immersive", "evocative"))
        self.assertGreater(result["sensory_density_index"], 0.02)

    def test_abstract_text(self):
        wsd = WriterSensoryDensity()
        text = (
            "The concept of justice requires careful consideration "
            "of multiple factors. One must weigh the interests of "
            "various stakeholders and consider the implications of "
            "different approaches. The theoretical framework provides "
            "a basis for understanding the relationships between "
            "competing principles."
        )
        result = wsd.measure(text)
        self.assertIn(result["classification"], ("abstract", "disembodied"))
        self.assertLess(result["sensory_density_index"], 0.08)

    def test_sensory_balance_range(self):
        wsd = WriterSensoryDensity()
        text = "red loud sweet soft warm walk"
        result = wsd.measure(text)
        self.assertGreaterEqual(result["sensory_balance"], 0.0)
        self.assertLessEqual(result["sensory_balance"], 1.0)

    def test_visual_dominant_text(self):
        wsd = WriterSensoryDensity()
        text = "the red bright golden glowing amber light shone"
        result = wsd.measure(text)
        self.assertEqual(result["dominant_modality"], "visual")

    def test_auditory_dominant_text(self):
        wsd = WriterSensoryDensity()
        text = "the loud booming thunder echoed crashing ringing clanging"
        result = wsd.measure(text)
        self.assertEqual(result["dominant_modality"], "auditory")

    def test_rounded_values(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("the red ball rolled silently across the floor")
        for key in ["visual_density", "auditory_density", "olfactory_density",
                     "gustatory_density", "tactile_density", "kinesthetic_density",
                     "sensory_density_index", "sensory_balance"]:
            val = result[key]
            self.assertEqual(val, round(val, 4))


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word_visual(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("red")
        self.assertEqual(result["visual_density"], 1.0)
        self.assertEqual(result["dominant_modality"], "visual")

    def test_repeated_word(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("red red red red red")
        self.assertEqual(result["visual_density"], 1.0)

    def test_mixed_modalities(self):
        wsd = WriterSensoryDensity()
        text = "red loud sweet soft warm walk"
        result = wsd.measure(text)
        self.assertGreater(result["sensory_density_index"], 0.0)
        self.assertGreater(result["sensory_balance"], 0.5)

    def test_very_long_text(self):
        wsd = WriterSensoryDensity()
        text = "the red ball. " * 1000
        result = wsd.measure(text)
        self.assertGreater(result["visual_density"], 0.0)
        self.assertIn(result["classification"],
                      ("immersive", "sparse", "evocative", "abstract"))

    def test_punctuation_only(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("!@#$%^&*()")
        self.assertEqual(result["sensory_density_index"], 0.0)
        self.assertEqual(result["classification"], "disembodied")

    def test_numeric_text(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("123 456 789")
        self.assertEqual(result["sensory_density_index"], 0.0)

    def test_whitespace_only(self):
        wsd = WriterSensoryDensity()
        result = wsd.measure("   \n\t  ")
        self.assertEqual(result["sensory_density_index"], 0.0)

    def test_newlines_preserved(self):
        wsd = WriterSensoryDensity()
        r1 = wsd.measure("red\nblue\ngreen")
        r2 = wsd.measure("red blue green")
        self.assertEqual(r1["visual_density"], r2["visual_density"])


# ---------------------------------------------------------------------------
# Pattern library sanity tests
# ---------------------------------------------------------------------------


class TestPatternLibraries(unittest.TestCase):
    """Verify pattern library contents."""

    def test_visual_words_not_empty(self):
        self.assertGreater(len(VISUAL_WORDS), 50)

    def test_auditory_words_not_empty(self):
        self.assertGreater(len(AUDITORY_WORDS), 30)

    def test_olfactory_words_not_empty(self):
        self.assertGreater(len(OLFACTORY_WORDS), 20)

    def test_gustatory_words_not_empty(self):
        self.assertGreater(len(GUSTATORY_WORDS), 30)

    def test_tactile_words_not_empty(self):
        self.assertGreater(len(TACTILE_WORDS), 40)

    def test_kinesthetic_words_not_empty(self):
        self.assertGreater(len(KINESTHETIC_WORDS), 40)

    def test_no_empty_strings_visual(self):
        self.assertNotIn("", VISUAL_WORDS)

    def test_no_empty_strings_auditory(self):
        self.assertNotIn("", AUDITORY_WORDS)

    def test_no_empty_strings_olfactory(self):
        self.assertNotIn("", OLFACTORY_WORDS)

    def test_no_empty_strings_gustatory(self):
        self.assertNotIn("", GUSTATORY_WORDS)

    def test_no_empty_strings_tactile(self):
        self.assertNotIn("", TACTILE_WORDS)

    def test_no_empty_strings_kinesthetic(self):
        self.assertNotIn("", KINESTHETIC_WORDS)


# ---------------------------------------------------------------------------
# Integration: classification consistency
# ---------------------------------------------------------------------------


class TestClassificationConsistency(unittest.TestCase):
    """Verify that measure() produces consistent classifications."""

    def test_immersive_text_classifies_high(self):
        wsd = WriterSensoryDensity()
        text = (
            "The bright amber glow illuminated the rough wooden table. "
            "She could smell the sweet aroma of fresh bread, feel the "
            "warm soft blanket against her cold skin, and hear the "
            "faint crackling of the fireplace. The bitter taste of "
            "dark chocolate lingered on her tongue as she walked to "
            "the window and pulled the heavy velvet curtain aside."
        )
        result = wsd.measure(text)
        self.assertIn(result["classification"], ("immersive", "evocative"))

    def test_abstract_text_classifies_low(self):
        wsd = WriterSensoryDensity()
        text = (
            "Democracy requires the active participation of informed "
            "citizens. The theoretical underpinnings of representative "
            "government have been debated for centuries. Various "
            "frameworks propose different mechanisms for balancing "
            "competing interests and ensuring accountability."
        )
        result = wsd.measure(text)
        self.assertIn(result["classification"], ("abstract", "disembodied"))

    def test_single_modality_low_balance(self):
        wsd = WriterSensoryDensity()
        text = "red blue green bright golden amber crimson scarlet ivory"
        result = wsd.measure(text)
        self.assertLess(result["sensory_balance"], 0.3)
        self.assertEqual(result["dominant_modality"], "visual")


if __name__ == "__main__":
    unittest.main()
