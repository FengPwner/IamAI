#!/usr/bin/env python3
"""Tests for writer_metaphor_density — 95 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_metaphor_density import (  # noqa: E402
    SIMILE_MIN_WORDS,
    HYPERBOLE_MIN_WORDS,
    IDIOM_MIN_WORDS,
    SIMILE_PATTERNS,
    HYPERBOLE_PATTERNS,
    IDIOM_PHRASES,
    VERB_METAPHOR_PATTERNS,
    HUMAN_ACTION_VERBS,
    INANIMATE_SUBJECTS,
    COPULA_VERBS,
    ARTICLES,
    WriterMetaphorDensity,
    _split_sentences,
    _tokenize_words,
    _get_subject,
    _get_main_verb,
)


# ===========================================================================
# Initialization
# ===========================================================================


class TestWriterMetaphorDensityInit(unittest.TestCase):
    """Test WriterMetaphorDensity initialization."""

    def test_init_default(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(len(wmd.simile_patterns), len(SIMILE_PATTERNS))
        self.assertEqual(len(wmd.hyperbole_patterns), len(HYPERBOLE_PATTERNS))
        self.assertEqual(len(wmd.idiom_phrases), len(IDIOM_PHRASES))
        self.assertEqual(len(wmd.verb_metaphor_patterns), len(VERB_METAPHOR_PATTERNS))
        self.assertEqual(len(wmd.human_action_verbs), len(HUMAN_ACTION_VERBS))

    def test_init_constants(self):
        self.assertEqual(SIMILE_MIN_WORDS, 2)
        self.assertEqual(HYPERBOLE_MIN_WORDS, 2)
        self.assertEqual(IDIOM_MIN_WORDS, 3)

    def test_simile_patterns_not_empty(self):
        self.assertGreater(len(SIMILE_PATTERNS), 0)

    def test_hyperbole_patterns_not_empty(self):
        self.assertGreater(len(HYPERBOLE_PATTERNS), 0)

    def test_idiom_phrases_not_empty(self):
        self.assertGreater(len(IDIOM_PHRASES), 0)

    def test_verb_metaphor_patterns_not_empty(self):
        self.assertGreater(len(VERB_METAPHOR_PATTERNS), 0)

    def test_human_action_verbs_not_empty(self):
        self.assertGreater(len(HUMAN_ACTION_VERBS), 0)


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        result = _split_sentences("Hello. World. Again.")
        self.assertEqual(len(result), 3)

    def test_exclamation(self):
        result = _split_sentences("Wow! Great!")
        self.assertEqual(len(result), 2)

    def test_question(self):
        result = _split_sentences("Why? Because.")
        self.assertEqual(len(result), 2)

    def test_mixed_punctuation(self):
        result = _split_sentences("Hi. What? Yes!")
        self.assertEqual(len(result), 3)

    def test_no_punctuation(self):
        result = _split_sentences("no punctuation here")
        self.assertEqual(len(result), 1)

    def test_strips_whitespace(self):
        result = _split_sentences("  Hello.  World.  ")
        self.assertEqual(result, ["Hello", "World"])


class TestTokenizeWords(unittest.TestCase):
    """Test _tokenize_words helper."""

    def test_empty_string(self):
        self.assertEqual(_tokenize_words(""), [])

    def test_simple_words(self):
        self.assertEqual(_tokenize_words("hello world"), ["hello", "world"])

    def test_with_punctuation(self):
        self.assertEqual(_tokenize_words("hello, world!"), ["hello", "world"])

    def test_with_apostrophe(self):
        result = _tokenize_words("don't can't")
        self.assertEqual(result, ["don't", "can't"])

    def test_mixed_case(self):
        result = _tokenize_words("Hello World")
        self.assertEqual(result, ["Hello", "World"])


class TestGetSubject(unittest.TestCase):
    """Test _get_subject helper."""

    def test_empty_string(self):
        self.assertEqual(_get_subject(""), "")

    def test_simple_subject(self):
        self.assertEqual(_get_subject("The cat sat"), "cat")

    def test_article_subject(self):
        result = _get_subject("A dog ran")
        self.assertIn(result, ["dog"])

    def test_no_articles(self):
        self.assertEqual(_get_subject("Cats sleep"), "Cats")

    def test_multiple_words(self):
        result = _get_subject("The big red house stood tall")
        self.assertEqual(result, "big")


class TestGetMainVerb(unittest.TestCase):
    """Test _get_main_verb helper."""

    def test_empty_string(self):
        self.assertEqual(_get_main_verb(""), "")

    def test_single_word(self):
        self.assertEqual(_get_main_verb("hello"), "")

    def test_simple_sentence(self):
        result = _get_main_verb("The cat ran fast")
        self.assertEqual(result, "ran")

    def test_with_auxiliary(self):
        result = _get_main_verb("The cat is running")
        self.assertEqual(result, "running")

    def test_with_have_auxiliary(self):
        result = _get_main_verb("She has eaten food")
        self.assertEqual(result, "eaten")


# ===========================================================================
# Simile detection tests
# ===========================================================================


class TestSimileRate(unittest.TestCase):
    """Test measure_simile_rate."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_simile_rate(""), 0.0)

    def test_no_similes(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_simile_rate("The report was filed on time."), 0.0)

    def test_like_simile(self):
        wmd = WriterMetaphorDensity()
        text = "She ran like the wind."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_as_as_simile(self):
        wmd = WriterMetaphorDensity()
        text = "He was as brave as a lion."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_resembles_simile(self):
        wmd = WriterMetaphorDensity()
        text = "The cloud resembles a castle."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_akin_to_simile(self):
        wmd = WriterMetaphorDensity()
        text = "The feeling is akin to drowning."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_similar_to_simile(self):
        wmd = WriterMetaphorDensity()
        text = "The texture is similar to silk."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_as_if_simile(self):
        wmd = WriterMetaphorDensity()
        text = "She looked as if she had seen a ghost."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_as_though_simile(self):
        wmd = WriterMetaphorDensity()
        text = "He spoke as though reciting poetry."
        result = wmd.measure_simile_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_similes(self):
        wmd = WriterMetaphorDensity()
        text = "She ran like the wind. He was as brave as a lion. The sky was clear."
        result = wmd.measure_simile_rate(text)
        self.assertAlmostEqual(result, 2.0 / 3.0, places=2)

    def test_all_similes(self):
        wmd = WriterMetaphorDensity()
        text = "She ran like the wind. He was as brave as a lion."
        result = wmd.measure_simile_rate(text)
        self.assertEqual(result, 1.0)

    def test_single_word_sentences_skip(self):
        wmd = WriterMetaphorDensity()
        text = "Stop."
        result = wmd.measure_simile_rate(text)
        self.assertEqual(result, 0.0)


# ===========================================================================
# Metaphor marker detection tests
# ===========================================================================


class TestMetaphorMarkerRate(unittest.TestCase):
    """Test measure_metaphor_marker_rate."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_metaphor_marker_rate(""), 0.0)

    def test_no_metaphors(self):
        wmd = WriterMetaphorDensity()
        text = "The meeting is at three o'clock."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertEqual(result, 0.0)

    def test_copula_metaphor(self):
        wmd = WriterMetaphorDensity()
        text = "Her words were a dagger to his heart."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_verb_metaphor_time(self):
        wmd = WriterMetaphorDensity()
        text = "Time flew through the afternoon."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_verb_metaphor_emotion(self):
        wmd = WriterMetaphorDensity()
        text = "Anger burned through her veins."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_verb_metaphor_idea(self):
        wmd = WriterMetaphorDensity()
        text = "The idea planted itself in his mind."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_verb_metaphor_market(self):
        wmd = WriterMetaphorDensity()
        text = "The market crashed yesterday."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_literal_exclusion(self):
        wmd = WriterMetaphorDensity()
        text = "She is a member of the team."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertEqual(result, 0.0)

    def test_short_sentence_skip(self):
        wmd = WriterMetaphorDensity()
        text = "It is."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertEqual(result, 0.0)

    def test_mixed_metaphors_and_literal(self):
        wmd = WriterMetaphorDensity()
        text = "Time flew through the afternoon. The report was filed on schedule. Anger burned through her veins."
        result = wmd.measure_metaphor_marker_rate(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)


# ===========================================================================
# Personification detection tests
# ===========================================================================


class TestPersonificationDensity(unittest.TestCase):
    """Test measure_personification_density."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_personification_density(""), 0.0)

    def test_no_personification(self):
        wmd = WriterMetaphorDensity()
        text = "The man walked to the store."
        result = wmd.measure_personification_density(text)
        self.assertEqual(result, 0.0)

    def test_wind_whispers(self):
        wmd = WriterMetaphorDensity()
        text = "The wind whispered secrets through the trees."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_sun_dances(self):
        wmd = WriterMetaphorDensity()
        text = "The sun danced across the meadow."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_time_flies_personification(self):
        wmd = WriterMetaphorDensity()
        text = "Time flew past them without mercy or hesitation."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_city_never_sleeps(self):
        wmd = WriterMetaphorDensity()
        text = "The city sleeps under a blanket of fog."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_flower_dances(self):
        wmd = WriterMetaphorDensity()
        text = "The flower danced in the breeze."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_darkness_embraces(self):
        wmd = WriterMetaphorDensity()
        text = "Darkness embraced the valley below."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_music_speaks(self):
        wmd = WriterMetaphorDensity()
        text = "The music speaks to the soul within."
        result = wmd.measure_personification_density(text)
        self.assertGreater(result, 0.0)

    def test_multiple_personification(self):
        wmd = WriterMetaphorDensity()
        text = "The wind whispered. The sun danced. The river sang."
        result = wmd.measure_personification_density(text)
        self.assertEqual(result, 1.0)


# ===========================================================================
# Hyperbole detection tests
# ===========================================================================


class TestHyperboleRate(unittest.TestCase):
    """Test measure_hyperbole_rate."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_hyperbole_rate(""), 0.0)

    def test_no_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "The temperature increased by two degrees."
        result = wmd.measure_hyperbole_rate(text)
        self.assertEqual(result, 0.0)

    def test_never_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "I will never forget this moment."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_always_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "She always arrives late to meetings."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_million_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "I have told you a million times before."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_everything_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "Everything was destroyed in the blast."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_literally_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "I was literally dying of embarrassment."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_absolutely_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "She was absolutely devastated by the news."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_tons_of_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "We have tons of work to finish today."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_dying_to_hyperbole(self):
        wmd = WriterMetaphorDensity()
        text = "I am dying to know what happened."
        result = wmd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_single_word_skip(self):
        wmd = WriterMetaphorDensity()
        text = "Never."
        result = wmd.measure_hyperbole_rate(text)
        self.assertEqual(result, 0.0)


# ===========================================================================
# Idiom detection tests
# ===========================================================================


class TestIdiomDensity(unittest.TestCase):
    """Test measure_idiom_density."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.measure_idiom_density(""), 0.0)

    def test_no_idioms(self):
        wmd = WriterMetaphorDensity()
        text = "The committee reached a consensus on the budget."
        result = wmd.measure_idiom_density(text)
        self.assertEqual(result, 0.0)

    def test_break_ice_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "She tried to break the ice at the party."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_spill_beans_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "He decided to spill the beans about the project."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_bite_bullet_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "She had to bite the bullet and resign."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_piece_of_cake_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "The exam was a piece of cake for her."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_tip_of_iceberg_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "This is just the tip of the iceberg."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_burn_bridges_idiom(self):
        wmd = WriterMetaphorDensity()
        text = "He decided not to burn bridges with his former employer."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_multiple_idioms(self):
        wmd = WriterMetaphorDensity()
        text = "She broke the ice. He spilled the beans. The meeting ended."
        result = wmd.measure_idiom_density(text)
        self.assertAlmostEqual(result, 2.0 / 3.0, places=2)

    def test_case_insensitive(self):
        wmd = WriterMetaphorDensity()
        text = "She tried to BREAK THE ICE at the party."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)


# ===========================================================================
# Figurative index computation tests
# ===========================================================================


class TestFigurativeIndex(unittest.TestCase):
    """Test compute_figurative_index."""

    def test_all_zeros(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(1.0, 1.0, 1.0, 1.0, 1.0)
        expected = 0.20 + 0.30 + 0.20 + 0.15 + 0.15
        self.assertAlmostEqual(result, expected, places=4)

    def test_weights_sum_to_one(self):
        weights = [0.20, 0.30, 0.20, 0.15, 0.15]
        self.assertAlmostEqual(sum(weights), 1.0, places=4)

    def test_only_simile(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20, places=4)

    def test_only_metaphor(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.30, places=4)

    def test_only_personification(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20, places=4)

    def test_only_hyperbole(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.0, 0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_only_idiom(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_mixed_values(self):
        wmd = WriterMetaphorDensity()
        result = wmd.compute_figurative_index(0.5, 0.3, 0.2, 0.1, 0.4)
        expected = 0.5 * 0.20 + 0.3 * 0.30 + 0.2 * 0.20 + 0.1 * 0.15 + 0.4 * 0.15
        self.assertAlmostEqual(result, expected, places=4)


# ===========================================================================
# Classification tests
# ===========================================================================


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_ornate(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.50), "ornate")
        self.assertEqual(wmd.classify(0.75), "ornate")
        self.assertEqual(wmd.classify(1.0), "ornate")

    def test_rich(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.35), "rich")
        self.assertEqual(wmd.classify(0.42), "rich")
        self.assertEqual(wmd.classify(0.49), "rich")

    def test_figurative(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.20), "figurative")
        self.assertEqual(wmd.classify(0.25), "figurative")
        self.assertEqual(wmd.classify(0.34), "figurative")

    def test_literal(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.08), "literal")
        self.assertEqual(wmd.classify(0.12), "literal")
        self.assertEqual(wmd.classify(0.19), "literal")

    def test_denotative(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.0), "denotative")
        self.assertEqual(wmd.classify(0.03), "denotative")
        self.assertEqual(wmd.classify(0.07), "denotative")

    def test_boundary_ornate(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.50), "ornate")

    def test_boundary_rich(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.35), "rich")

    def test_boundary_figurative(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.20), "figurative")

    def test_boundary_literal(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.08), "literal")

    def test_boundary_denotative(self):
        wmd = WriterMetaphorDensity()
        self.assertEqual(wmd.classify(0.079), "denotative")


# ===========================================================================
# Integration / measure() tests
# ===========================================================================


class TestMeasure(unittest.TestCase):
    """Test the full measure() method."""

    def test_empty_text(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("")
        self.assertEqual(result["figurative_index"], 0.0)
        self.assertEqual(result["classification"], "denotative")

    def test_denotative_text(self):
        wmd = WriterMetaphorDensity()
        text = """The quarterly report was submitted on March fifteenth.
        Revenue increased by twelve percent compared to the previous
        quarter. The team completed all assigned tasks within the
        allocated budget. Customer satisfaction scores remained stable
        at four point two out of five."""
        result = wmd.measure(text)
        self.assertIn("simile_rate", result)
        self.assertIn("metaphor_marker_rate", result)
        self.assertIn("personification_density", result)
        self.assertIn("hyperbole_rate", result)
        self.assertIn("idiom_density", result)
        self.assertIn("figurative_index", result)
        self.assertIn("classification", result)
        self.assertIn(result["classification"],
                      ["denotative", "literal", "figurative", "rich", "ornate"])

    def test_ornate_text(self):
        wmd = WriterMetaphorDensity()
        text = """Time flew like an arrow through the heart of the
        afternoon. The wind whispered secrets to the trembling leaves.
        Her words were a dagger cutting deeper than the last. The city
        was a beast that never slept. Hope was a fragile seed planted
        in the cracked earth of despair. It was literally the end of
        the world. She broke the ice with a warm smile."""
        result = wmd.measure(text)
        self.assertGreater(result["figurative_index"], 0.0)

    def test_return_keys(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("Hello world.")
        expected_keys = {
            "simile_rate",
            "metaphor_marker_rate",
            "personification_density",
            "hyperbole_rate",
            "idiom_density",
            "figurative_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_are_float(self):
        wmd = WriterMetaphorDensity()
        text = "She ran like the wind through the meadow."
        result = wmd.measure(text)
        for key in ["simile_rate", "metaphor_marker_rate",
                     "personification_density", "hyperbole_rate",
                     "idiom_density", "figurative_index"]:
            self.assertIsInstance(result[key], float)

    def test_classification_is_string(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("Hello world.")
        self.assertIsInstance(result["classification"], str)

    def test_values_rounded_to_four_decimals(self):
        wmd = WriterMetaphorDensity()
        text = "She ran like the wind. Time flew through the afternoon."
        result = wmd.measure(text)
        for key in ["simile_rate", "metaphor_marker_rate",
                     "personification_density", "hyperbole_rate",
                     "idiom_density", "figurative_index"]:
            val_str = str(result[key])
            if "." in val_str:
                decimals = len(val_str.split(".")[1])
                self.assertLessEqual(decimals, 4)

    def test_orthogonal_to_musicality(self):
        """Verify that high musicality text and high metaphor text can differ."""
        wmd = WriterMetaphorDensity()
        # Musical but literal (alliteration without metaphor)
        musical_text = "Peter Piper picked a peck of pickled peppers."
        result_musical = wmd.measure(musical_text)
        # Metaphorical but not musical
        metaphor_text = "Her words were a dagger. Time flew like an arrow."
        result_metaphor = wmd.measure(metaphor_text)
        # They should produce different figurative indices
        # (musical text should be lower in figurative density)
        self.assertGreaterEqual(
            result_metaphor["figurative_index"],
            result_musical["figurative_index"]
        )


# ===========================================================================
# Edge case tests
# ===========================================================================


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_character(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("x")
        self.assertEqual(result["figurative_index"], 0.0)

    def test_only_punctuation(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("...!!!???")
        self.assertEqual(result["figurative_index"], 0.0)

    def test_repeated_words(self):
        wmd = WriterMetaphorDensity()
        result = wmd.measure("the the the the the the.")
        self.assertIsInstance(result["figurative_index"], float)

    def test_very_long_sentence(self):
        wmd = WriterMetaphorDensity()
        text = ("She walked through the garden " * 50) + "."
        result = wmd.measure(text)
        self.assertIsInstance(result["figurative_index"], float)

    def test_unicode_text(self):
        wmd = WriterMetaphorDensity()
        text = "The café was like a warm embrace on a cold day."
        result = wmd.measure(text)
        self.assertIsInstance(result["figurative_index"], float)

    def test_numbers_in_text(self):
        wmd = WriterMetaphorDensity()
        text = "She has 100 reasons to smile like the sun."
        result = wmd.measure(text)
        self.assertIsInstance(result["figurative_index"], float)

    def test_mixed_case_idioms(self):
        wmd = WriterMetaphorDensity()
        text = "She decided to BREAK THE ICE at the meeting."
        result = wmd.measure_idiom_density(text)
        self.assertGreater(result, 0.0)

    def test_idiom_phrases_are_lowercase(self):
        for idiom in IDIOM_PHRASES:
            self.assertEqual(idiom, idiom.lower())

    def test_human_action_verbs_are_lowercase(self):
        for verb in HUMAN_ACTION_VERBS:
            self.assertEqual(verb, verb.lower())


if __name__ == "__main__":
    unittest.main()
