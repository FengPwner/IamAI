#!/usr/bin/env python3
"""Tests for writer_musicality — 88 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_musicality import (  # noqa: E402
    ALLITERATION_THRESHOLD,
    ASSONANCE_THRESHOLD,
    CONSONANCE_THRESHOLD,
    SIBILANCE_THRESHOLD,
    EUPHONY_LIQUID_WEIGHT,
    EUPHONY_PLOSIVE_WEIGHT,
    WriterMusicality,
    _get_initial_sound,
    _is_vowel_sound,
    _get_stressed_vowel,
    _get_final_consonants,
    _count_sibilants,
    _count_liquid_nasal,
    _count_plosive_fricative,
    _tokenize_words,
    _split_sentences,
)


# ===========================================================================
# Initialization
# ===========================================================================


class TestWriterMusicalityInit(unittest.TestCase):
    """Test WriterMusicality initialization."""

    def test_init_default(self):
        wm = WriterMusicality()
        self.assertEqual(wm.alliteration_min_len, ALLITERATION_THRESHOLD)
        self.assertEqual(wm.assonance_min_len, ASSONANCE_THRESHOLD)
        self.assertEqual(wm.consonance_min_len, CONSONANCE_THRESHOLD)
        self.assertEqual(wm.sibilance_threshold, SIBILANCE_THRESHOLD)

    def test_init_constants(self):
        self.assertEqual(ALLITERATION_THRESHOLD, 2)
        self.assertEqual(ASSONANCE_THRESHOLD, 2)
        self.assertEqual(CONSONANCE_THRESHOLD, 2)
        self.assertEqual(SIBILANCE_THRESHOLD, 3)
        self.assertEqual(EUPHONY_LIQUID_WEIGHT, 1.0)
        self.assertEqual(EUPHONY_PLOSIVE_WEIGHT, 1.0)


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestGetInitialSound(unittest.TestCase):
    """Test _get_initial_sound helper."""

    def test_empty_string(self):
        self.assertEqual(_get_initial_sound(""), "")

    def test_single_letter(self):
        self.assertEqual(_get_initial_sound("a"), "a")

    def test_consonant_start(self):
        self.assertEqual(_get_initial_sound("cat"), "c")

    def test_th_digraph(self):
        self.assertEqual(_get_initial_sound("the"), "th")

    def test_sh_digraph(self):
        self.assertEqual(_get_initial_sound("ship"), "sh")

    def test_ch_digraph(self):
        self.assertEqual(_get_initial_sound("church"), "ch")

    def test_ph_digraph(self):
        self.assertEqual(_get_initial_sound("phone"), "ph")

    def test_silent_kn(self):
        self.assertEqual(_get_initial_sound("knight"), "n")

    def test_silent_wr(self):
        self.assertEqual(_get_initial_sound("write"), "r")

    def test_silent_gn(self):
        self.assertEqual(_get_initial_sound("gnome"), "n")

    def test_silent_ps(self):
        self.assertEqual(_get_initial_sound("psychology"), "s")

    def test_silent_wh(self):
        self.assertEqual(_get_initial_sound("whale"), "w")

    def test_quoted_word(self):
        self.assertEqual(_get_initial_sound("'hello'"), "h")


class TestIsVowelSound(unittest.TestCase):
    """Test _is_vowel_sound helper."""

    def test_empty_string(self):
        self.assertFalse(_is_vowel_sound(""))

    def test_vowel_start(self):
        self.assertTrue(_is_vowel_sound("apple"))

    def test_consonant_start(self):
        self.assertFalse(_is_vowel_sound("banana"))

    def test_y_start_is_consonant(self):
        self.assertFalse(_is_vowel_sound("yellow"))

    def test_silent_kn(self):
        self.assertFalse(_is_vowel_sound("knee"))

    def test_uni_prefix(self):
        self.assertFalse(_is_vowel_sound("university"))


class TestGetStressedVowel(unittest.TestCase):
    """Test _get_stressed_vowel helper."""

    def test_empty_string(self):
        self.assertEqual(_get_stressed_vowel(""), "")

    def test_simple_word(self):
        result = _get_stressed_vowel("cat")
        self.assertEqual(result, "a")

    def test_multiple_vowels(self):
        result = _get_stressed_vowel("beautiful")
        self.assertEqual(result, "eau")

    def test_no_vowels(self):
        result = _get_stressed_vowel("rhythm")
        self.assertEqual(result, "")


class TestGetFinalConsonants(unittest.TestCase):
    """Test _get_final_consonants helper."""

    def test_empty_string(self):
        self.assertEqual(_get_final_consonants(""), "")

    def test_consonant_ending(self):
        result = _get_final_consonants("hand")
        self.assertIn("nd", result)

    def test_silent_e(self):
        result = _get_final_consonants("make")
        self.assertIn("k", result)

    def test_vowel_ending(self):
        result = _get_final_consonants("area")
        self.assertEqual(result, "")


class TestCountSibilants(unittest.TestCase):
    """Test _count_sibilants helper."""

    def test_no_sibilants(self):
        self.assertEqual(_count_sibilants("lamp"), 0)

    def test_single_s(self):
        self.assertEqual(_count_sibilants("sun"), 1)

    def test_sh_digraph(self):
        self.assertEqual(_count_sibilants("ship"), 1)

    def test_multiple_sibilants(self):
        self.assertEqual(_count_sibilants("sizzle"), 3)

    def test_ch_digraph(self):
        self.assertEqual(_count_sibilants("church"), 2)

    def test_j_sibilant(self):
        self.assertEqual(_count_sibilants("judge"), 1)


class TestCountLiquidNasal(unittest.TestCase):
    """Test _count_liquid_nasal helper."""

    def test_no_liquid_nasal(self):
        self.assertEqual(_count_liquid_nasal("beep"), 0)

    def test_l_count(self):
        self.assertEqual(_count_liquid_nasal("lull"), 3)

    def test_m_n_count(self):
        self.assertEqual(_count_liquid_nasal("morning"), 4)

    def test_r_w_y_count(self):
        self.assertEqual(_count_liquid_nasal("wormy"), 4)


class TestCountPlosiveFricative(unittest.TestCase):
    """Test _count_plosive_fricative helper."""

    def test_no_plosive_fricative(self):
        self.assertEqual(_count_plosive_fricative("moon"), 0)

    def test_plosives(self):
        result = _count_plosive_fricative("pat")
        self.assertGreaterEqual(result, 2)

    def test_th_digraph(self):
        result = _count_plosive_fricative("the")
        self.assertGreaterEqual(result, 1)

    def test_sh_digraph(self):
        result = _count_plosive_fricative("ship")
        self.assertGreaterEqual(result, 1)


class TestTokenizeWords(unittest.TestCase):
    """Test _tokenize_words helper."""

    def test_empty_string(self):
        self.assertEqual(_tokenize_words(""), [])

    def test_simple_sentence(self):
        result = _tokenize_words("Hello world")
        self.assertEqual(result, ["Hello", "world"])

    def test_with_punctuation(self):
        result = _tokenize_words("Hello, world! How are you?")
        self.assertEqual(len(result), 5)

    def test_apostrophes(self):
        result = _tokenize_words("it's a test")
        self.assertIn("it's", result)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        result = _split_sentences("Hello. World. Test.")
        self.assertEqual(len(result), 3)

    def test_exclamation_question(self):
        result = _split_sentences("Really! Are you sure? Yes.")
        self.assertEqual(len(result), 3)


# ===========================================================================
# Metric tests
# ===========================================================================


class TestAlliterationRate(unittest.TestCase):
    """Test measure_alliteration_rate."""

    def test_empty_text(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_alliteration_rate(""), 0.0)

    def test_single_word(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_alliteration_rate("hello"), 0.0)

    def test_alliterative_text(self):
        wm = WriterMusicality()
        text = "Peter Piper picked a peck of pickled peppers."
        rate = wm.measure_alliteration_rate(text)
        self.assertGreater(rate, 0.0)

    def test_no_alliteration(self):
        wm = WriterMusicality()
        text = "The dog ran across the field quickly."
        rate = wm.measure_alliteration_rate(text)
        self.assertLess(rate, 0.3)

    def test_consonant_clusters(self):
        wm = WriterMusicality()
        text = "She sells seashells by the seashore."
        rate = wm.measure_alliteration_rate(text)
        self.assertGreater(rate, 0.0)


class TestAssonanceDensity(unittest.TestCase):
    """Test measure_assonance_density."""

    def test_empty_text(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_assonance_density(""), 0.0)

    def test_assonant_text(self):
        wm = WriterMusicality()
        text = "Meet the fleet, sweet and deep, see the free sheep."
        density = wm.measure_assonance_density(text)
        self.assertGreater(density, 0.0)

    def test_no_assonance(self):
        wm = WriterMusicality()
        text = "Big red trucks drove past the old brick school."
        density = wm.measure_assonance_density(text)
        self.assertIsInstance(density, float)


class TestConsonanceRate(unittest.TestCase):
    """Test measure_consonance_rate."""

    def test_empty_text(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_consonance_rate(""), 0.0)

    def test_consonant_text(self):
        wm = WriterMusicality()
        text = "Blank and think, drink and shrink, sink and wink."
        rate = wm.measure_consonance_rate(text)
        self.assertGreater(rate, 0.0)

    def test_varied_endings(self):
        wm = WriterMusicality()
        text = "The cat sat on the mat with a hat."
        rate = wm.measure_consonance_rate(text)
        self.assertGreater(rate, 0.0)


class TestSibilanceDensity(unittest.TestCase):
    """Test measure_sibilance_density."""

    def test_empty_text(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_sibilance_density(""), 0.0)

    def test_sibilant_text(self):
        wm = WriterMusicality()
        text = "She sells seashells. Six sleek swans swam silently."
        density = wm.measure_sibilance_density(text)
        self.assertGreater(density, 0.0)

    def test_no_sibilants(self):
        wm = WriterMusicality()
        text = "The lamp lit the room warmly."
        density = wm.measure_sibilance_density(text)
        self.assertEqual(density, 0.0)

    def test_short_words_excluded(self):
        wm = WriterMusicality()
        text = "I am so up on it."
        density = wm.measure_sibilance_density(text)
        self.assertEqual(density, 0.0)


class TestEuphonyRatio(unittest.TestCase):
    """Test measure_euphony_ratio."""

    def test_empty_text(self):
        wm = WriterMusicality()
        self.assertEqual(wm.measure_euphony_ratio(""), 0.0)

    def test_euphonious_text(self):
        wm = WriterMusicality()
        text = "The mellow moonlight rolled along the warm river."
        ratio = wm.measure_euphony_ratio(text)
        self.assertGreater(ratio, 0.0)

    def test_cacophonous_text(self):
        wm = WriterMusicality()
        text = "The thick black brick cracked. The gate banged shut."
        ratio = wm.measure_euphony_ratio(text)
        self.assertIsInstance(ratio, float)

    def test_mixed_sentences(self):
        wm = WriterMusicality()
        text = "The wind blew softly. The truck hit the curb hard."
        ratio = wm.measure_euphony_ratio(text)
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)


# ===========================================================================
# Composite and classification tests
# ===========================================================================


class TestCompositeAndClassification(unittest.TestCase):
    """Test compute_musicality_index and classify."""

    def test_zero_scores(self):
        wm = WriterMusicality()
        index = wm.compute_musicality_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(index, 0.0)
        self.assertEqual(wm.classify(index), "flat")

    def test_max_scores(self):
        wm = WriterMusicality()
        index = wm.compute_musicality_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(index, 1.0)
        self.assertEqual(wm.classify(index), "lyrical")

    def test_classify_flat(self):
        wm = WriterMusicality()
        self.assertEqual(wm.classify(0.0), "flat")
        self.assertEqual(wm.classify(0.04), "flat")

    def test_classify_spoken(self):
        wm = WriterMusicality()
        self.assertEqual(wm.classify(0.05), "spoken")
        self.assertEqual(wm.classify(0.14), "spoken")

    def test_classify_rhythmic(self):
        wm = WriterMusicality()
        self.assertEqual(wm.classify(0.15), "rhythmic")
        self.assertEqual(wm.classify(0.29), "rhythmic")

    def test_classify_melodic(self):
        wm = WriterMusicality()
        self.assertEqual(wm.classify(0.30), "melodic")
        self.assertEqual(wm.classify(0.44), "melodic")

    def test_classify_lyrical(self):
        wm = WriterMusicality()
        self.assertEqual(wm.classify(0.45), "lyrical")
        self.assertEqual(wm.classify(1.0), "lyrical")

    def test_weighted_computation(self):
        wm = WriterMusicality()
        index = wm.compute_musicality_index(0.5, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(index, 0.125)


# ===========================================================================
# Integration tests — full measure()
# ===========================================================================


class TestMeasure(unittest.TestCase):
    """Test the full measure() pipeline."""

    def test_empty_text(self):
        wm = WriterMusicality()
        result = wm.measure("")
        self.assertEqual(result["musicality_index"], 0.0)
        self.assertEqual(result["classification"], "flat")

    def test_lyrical_text(self):
        wm = WriterMusicality()
        text = """The silken sad uncertain rustling of each purple curtain
        thrilled me, filled me with fantastic terrors never felt before."""
        result = wm.measure(text)
        self.assertGreater(result["musicality_index"], 0.0)
        self.assertIn(result["classification"], ["lyrical", "melodic", "rhythmic", "spoken"])

    def test_flat_text(self):
        wm = WriterMusicality()
        text = """The quarterly report was submitted on time. Revenue
        increased by eight percent. The team completed all tasks."""
        result = wm.measure(text)
        self.assertLess(result["musicality_index"], 0.30)

    def test_result_keys(self):
        wm = WriterMusicality()
        result = wm.measure("Hello world. How are you.")
        expected_keys = {
            "alliteration_rate",
            "assonance_density",
            "consonance_rate",
            "sibilance_density",
            "euphony_ratio",
            "musicality_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_are_rounded(self):
        wm = WriterMusicality()
        result = wm.measure("Peter Piper picked a peck of pickled peppers.")
        for key in result:
            if key != "classification":
                val = result[key]
                self.assertEqual(val, round(val, 4))


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word(self):
        wm = WriterMusicality()
        result = wm.measure("Hello")
        self.assertLessEqual(result["musicality_index"], 0.25)

    def test_only_punctuation(self):
        wm = WriterMusicality()
        result = wm.measure("...!!! ???...")
        self.assertEqual(result["musicality_index"], 0.0)

    def test_repeated_alliterative(self):
        wm = WriterMusicality()
        text = "Big brown bears. " * 20
        result = wm.measure(text)
        self.assertGreater(result["alliteration_rate"], 0.0)

    def test_very_long_text(self):
        wm = WriterMusicality()
        text = "The server processed the request normally. " * 500
        result = wm.measure(text)
        self.assertIsInstance(result["musicality_index"], float)

    def test_unicode_text(self):
        wm = WriterMusicality()
        text = "The café served excellent coffee. Lovely morning."
        result = wm.measure(text)
        self.assertIsInstance(result["musicality_index"], float)

    def test_numbers_and_symbols(self):
        wm = WriterMusicality()
        text = "There are 42 items and $100 in the box."
        result = wm.measure(text)
        self.assertIsInstance(result["musicality_index"], float)

    def test_mixed_content(self):
        wm = WriterMusicality()
        text = """The wind whispered through the willows. The server
        responded with a 200 status code. Moonlight melted across the
        meadow. The deployment succeeded at 14:00 UTC."""
        result = wm.measure(text)
        self.assertGreater(result["musicality_index"], 0.0)
        self.assertIn(result["classification"], ["lyrical", "melodic", "rhythmic", "spoken"])


if __name__ == "__main__":
    unittest.main()
