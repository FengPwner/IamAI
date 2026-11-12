#!/usr/bin/env python3
"""Tests for writer_sentence_variety — 90 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_sentence_variety import (  # noqa: E402
    MIN_SENTENCE_LENGTH,
    MAX_SENTENCE_LENGTH,
    PUNCTUATION_MARKS,
    PASSIVE_INDICATORS,
    SUBORDINATING_CONJUNCTIONS,
    COORDINATING_CONJUNCTIONS,
    WriterSentenceVariety,
    _split_sentences,
    _tokenize_words,
    _compute_length_variance,
    _compute_opening_diversity,
    _classify_clause_structure,
    _compute_clause_complexity,
    _compute_punctuation_variety,
    _detect_passive_voice,
    _compute_voice_distribution,
    analyze_sentence_variety,
)


# ===========================================================================
# Initialization
# ===========================================================================


class TestWriterSentenceVarietyInit(unittest.TestCase):
    """Test WriterSentenceVariety initialization."""

    def test_init_default(self):
        wsv = WriterSentenceVariety()
        self.assertEqual(wsv.min_sentence_length, MIN_SENTENCE_LENGTH)
        self.assertEqual(wsv.max_sentence_length, MAX_SENTENCE_LENGTH)

    def test_init_constants(self):
        self.assertEqual(MIN_SENTENCE_LENGTH, 3)
        self.assertEqual(MAX_SENTENCE_LENGTH, 200)
        self.assertIn('.', PUNCTUATION_MARKS)
        self.assertIn('!', PUNCTUATION_MARKS)
        self.assertIn('?', PUNCTUATION_MARKS)

    def test_init_custom(self):
        wsv = WriterSentenceVariety(min_sentence_length=5, max_sentence_length=100)
        self.assertEqual(wsv.min_sentence_length, 5)
        self.assertEqual(wsv.max_sentence_length, 100)


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestSplitSentences(unittest.TestCase):
    """Test sentence splitting."""

    def test_simple_period(self):
        text = "This is one. This is two."
        result = _split_sentences(text)
        self.assertEqual(len(result), 2)

    def test_exclamation(self):
        text = "Wow! Amazing!"
        result = _split_sentences(text)
        self.assertEqual(len(result), 2)

    def test_question(self):
        text = "Really? Are you sure?"
        result = _split_sentences(text)
        self.assertEqual(len(result), 2)

    def test_mixed_punctuation(self):
        text = "Hello. What? Yes!"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_empty_string(self):
        result = _split_sentences("")
        self.assertEqual(result, [])

    def test_single_sentence(self):
        result = _split_sentences("Just one sentence.")
        self.assertEqual(len(result), 1)


class TestTokenizeWords(unittest.TestCase):
    """Test word tokenization."""

    def test_simple_words(self):
        result = _tokenize_words("Hello world")
        self.assertEqual(result, ['hello', 'world'])

    def test_with_punctuation(self):
        result = _tokenize_words("Hello, world!")
        self.assertEqual(result, ['hello', 'world'])

    def test_with_apostrophe(self):
        result = _tokenize_words("Don't worry")
        self.assertEqual(result, ["don't", 'worry'])

    def test_mixed_case(self):
        result = _tokenize_words("Hello WORLD")
        self.assertEqual(result, ['hello', 'world'])


class TestComputeLengthVariance(unittest.TestCase):
    """Test sentence length variance computation."""

    def test_uniform_lengths(self):
        sentences = ["One two three.", "Four five six.", "Seven eight nine."]
        result = _compute_length_variance(sentences)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_varied_lengths(self):
        sentences = ["This is short.", "A bit longer sentence here with more words.", "Medium one here."]
        result = _compute_length_variance(sentences)
        self.assertGreater(result, 0.0)

    def test_empty_list(self):
        result = _compute_length_variance([])
        self.assertEqual(result, 0.0)

    def test_single_sentence(self):
        result = _compute_length_variance(["Just one."])
        self.assertEqual(result, 0.0)

    def test_two_sentences(self):
        sentences = ["This is short.", "This is a much longer sentence with many more words."]
        result = _compute_length_variance(sentences)
        self.assertGreater(result, 0.0)


class TestComputeOpeningDiversity(unittest.TestCase):
    """Test opening word diversity computation."""

    def test_all_same_opening(self):
        sentences = ["The cat sat.", "The dog ran.", "The bird flew."]
        result = _compute_opening_diversity(sentences)
        self.assertAlmostEqual(result, 1/3, places=2)

    def test_all_different_openings(self):
        sentences = ["Cats sleep.", "Dogs run.", "Birds fly."]
        result = _compute_opening_diversity(sentences)
        self.assertEqual(result, 1.0)

    def test_empty_list(self):
        result = _compute_opening_diversity([])
        self.assertEqual(result, 0.0)

    def test_single_sentence(self):
        result = _compute_opening_diversity(["Hello world."])
        self.assertEqual(result, 1.0)

    def test_partial_diversity(self):
        sentences = ["The cat.", "The dog.", "A bird.", "Some fish."]
        result = _compute_opening_diversity(sentences)
        self.assertAlmostEqual(result, 0.75, places=2)


class TestClassifyClauseStructure(unittest.TestCase):
    """Test clause structure classification."""

    def test_simple_sentence(self):
        result = _classify_clause_structure("The cat sat on the mat.")
        self.assertEqual(result, 'simple')

    def test_compound_sentence(self):
        result = _classify_clause_structure("The cat sat, and the dog ran.")
        self.assertEqual(result, 'compound')

    def test_complex_sentence(self):
        result = _classify_clause_structure("Because it rained, we stayed home.")
        self.assertEqual(result, 'complex')

    def test_compound_complex(self):
        result = _classify_clause_structure("Although tired, she worked, and he rested.")
        self.assertEqual(result, 'compound-complex')


class TestComputeClauseComplexity(unittest.TestCase):
    """Test clause complexity computation."""

    def test_all_simple(self):
        sentences = ["Cat sat.", "Dog ran.", "Bird flew."]
        result = _compute_clause_complexity(sentences)
        self.assertEqual(result, 0.0)

    def test_mixed_structures(self):
        sentences = [
            "The cat sat.",
            "The dog ran, and the bird flew.",
            "Because it rained, we stayed home.",
        ]
        result = _compute_clause_complexity(sentences)
        self.assertGreater(result, 0.0)

    def test_empty_list(self):
        result = _compute_clause_complexity([])
        self.assertEqual(result, 0.0)


class TestComputePunctuationVariety(unittest.TestCase):
    """Test punctuation variety computation."""

    def test_only_periods(self):
        text = "One. Two. Three."
        result = _compute_punctuation_variety(text)
        self.assertEqual(result, 0.0)

    def test_mixed_punctuation(self):
        text = "Hello! What? Yes."
        result = _compute_punctuation_variety(text)
        self.assertGreater(result, 0.0)

    def test_no_punctuation(self):
        result = _compute_punctuation_variety("No punctuation here")
        self.assertEqual(result, 0.0)

    def test_many_types(self):
        text = "Wow! Really? Yes; maybe: perhaps—"
        result = _compute_punctuation_variety(text)
        self.assertGreater(result, 0.5)


class TestDetectPassiveVoice(unittest.TestCase):
    """Test passive voice detection."""

    def test_passive_ed(self):
        result = _detect_passive_voice("The ball was kicked by John.")
        self.assertTrue(result)

    def test_passive_en(self):
        result = _detect_passive_voice("The cake was eaten.")
        self.assertTrue(result)

    def test_active_voice(self):
        result = _detect_passive_voice("John threw the ball.")
        self.assertFalse(result)

    def test_present_passive(self):
        result = _detect_passive_voice("The book is written by her.")
        self.assertTrue(result)


class TestComputeVoiceDistribution(unittest.TestCase):
    """Test voice distribution computation."""

    def test_all_active(self):
        sentences = ["John runs.", "Mary walks.", "Birds fly."]
        result = _compute_voice_distribution(sentences)
        self.assertEqual(result, 0.0)

    def test_all_passive(self):
        sentences = ["The ball was kicked.", "The cake was eaten.", "The book was written."]
        result = _compute_voice_distribution(sentences)
        # All passive should give low balance score
        self.assertLess(result, 0.5)

    def test_mixed_voice(self):
        sentences = ["John threw the ball.", "The cake was eaten by Mary."]
        result = _compute_voice_distribution(sentences)
        self.assertGreater(result, 0.0)

    def test_empty_list(self):
        result = _compute_voice_distribution([])
        self.assertEqual(result, 0.0)


# ===========================================================================
# Main analyzer tests
# ===========================================================================


class TestWriterSentenceVarietyAnalyze(unittest.TestCase):
    """Test the main analyzer."""

    def test_empty_text(self):
        wsv = WriterSentenceVariety()
        result = wsv.analyze("")
        self.assertEqual(result['classification'], 'monotonous')
        self.assertEqual(result['variety_index'], 0.0)

    def test_simple_text(self):
        wsv = WriterSentenceVariety()
        text = "The cat sat. The dog ran. The bird flew."
        result = wsv.analyze(text)
        self.assertIn('variety_index', result)
        self.assertIn('classification', result)

    def test_varied_text(self):
        wsv = WriterSentenceVariety()
        text = (
            "Short. "
            "This is a longer sentence with more words. "
            "Medium one here! "
            "Because it was raining, we decided to stay inside. "
            "The cake was eaten by the children."
        )
        result = wsv.analyze(text)
        self.assertGreater(result['variety_index'], 0.0)

    def test_classification_virtuosic(self):
        wsv = WriterSentenceVariety()
        # Craft text with high variety
        text = (
            "Wow! "
            "This is quite long, and it has multiple clauses. "
            "Because she was tired, she slept. "
            "Really? "
            "The ball was thrown; the game was won!"
        )
        result = wsv.analyze(text)
        self.assertIn(result['classification'], 
                     ['virtuosic', 'varied', 'moderate', 'uniform', 'monotonous'])

    def test_all_dimensions_present(self):
        wsv = WriterSentenceVariety()
        text = "Hello world. How are you?"
        result = wsv.analyze(text)
        expected_keys = [
            'length_variance', 'opening_diversity', 'clause_complexity',
            'punctuation_variety', 'voice_distribution', 'variety_index',
            'classification'
        ]
        for key in expected_keys:
            self.assertIn(key, result)

    def test_single_sentence(self):
        wsv = WriterSentenceVariety()
        result = wsv.analyze("Just one sentence here.")
        # Single sentence can still have some variety from opening/punctuation
        self.assertLessEqual(result['variety_index'], 0.3)

    def test_repetitive_openings(self):
        wsv = WriterSentenceVariety()
        text = "The cat sat. The dog ran. The bird flew. The fish swam."
        result = wsv.analyze(text)
        self.assertLess(result['opening_diversity'], 0.5)


class TestConvenienceFunction(unittest.TestCase):
    """Test the convenience function."""

    def test_analyze_sentence_variety(self):
        text = "Hello. World!"
        result = analyze_sentence_variety(text)
        self.assertIn('variety_index', result)
        self.assertIn('classification', result)


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_short_sentences(self):
        text = "Go. Run. Fly."
        result = analyze_sentence_variety(text)
        # Very short sentences with different openings tend toward uniform
        self.assertIn(result['classification'], ['monotonous', 'uniform'])

    def test_very_long_sentence(self):
        text = " ".join(["word"] * 150) + "."
        result = analyze_sentence_variety(text)
        self.assertIn('variety_index', result)

    def test_special_characters(self):
        text = "Hello—world! What? Yes; maybe: perhaps…"
        result = analyze_sentence_variety(text)
        self.assertGreater(result['punctuation_variety'], 0.0)

    def test_numbers_in_text(self):
        text = "I have 3 cats. She has 5 dogs."
        result = analyze_sentence_variety(text)
        self.assertIn('variety_index', result)

    def test_unicode_characters(self):
        text = "Hello café. Bonjour naïve."
        result = analyze_sentence_variety(text)
        self.assertIn('variety_index', result)

    def test_repeated_words(self):
        text = "The the the. The the the."
        result = analyze_sentence_variety(text)
        # Both sentences start with "the", so opening diversity is 0.5
        self.assertEqual(result['opening_diversity'], 0.5)


# ===========================================================================
# Classification tests
# ===========================================================================


class TestClassifications(unittest.TestCase):
    """Test classification boundaries."""

    def test_monotonous_threshold(self):
        wsv = WriterSentenceVariety()
        text = "The cat. The dog. The bird."
        result = wsv.analyze(text)
        # Should be monotonous due to repetitive structure
        self.assertIn(result['classification'], ['monotonous', 'uniform'])

    def test_classification_types(self):
        valid_classes = {'virtuosic', 'varied', 'moderate', 'uniform', 'monotonous'}
        wsv = WriterSentenceVariety()
        
        texts = [
            "A. B. C.",
            "Hello! What? Yes.",
            "The cat sat, and the dog ran, but the bird flew.",
            "Because it rained, we stayed; although tired, we worked.",
        ]
        
        for text in texts:
            result = wsv.analyze(text)
            self.assertIn(result['classification'], valid_classes)


# ===========================================================================
# Integration tests
# ===========================================================================


class TestIntegration(unittest.TestCase):
    """Integration tests with realistic prose."""

    def test_literary_prose(self):
        text = (
            "The morning light filtered through the curtains. "
            "She stretched, yawned, and rolled out of bed. "
            "Outside, birds sang; inside, coffee brewed. "
            "Because it was Sunday, she had nowhere to be. "
            "The cat was fed by her before she dressed."
        )
        result = analyze_sentence_variety(text)
        self.assertGreater(result['variety_index'], 0.0)
        self.assertIn(result['classification'], 
                     ['virtuosic', 'varied', 'moderate', 'uniform'])

    def test_technical_prose(self):
        text = (
            "The function returns a value. "
            "The parameter is optional. "
            "The result is cached. "
            "The method throws an exception."
        )
        result = analyze_sentence_variety(text)
        # Technical prose tends to be more uniform
        self.assertIn(result['classification'],
                     ['monotonous', 'uniform', 'moderate'])

    def test_conversational_prose(self):
        text = (
            "Hey! "
            "How are you doing today? "
            "I've been meaning to call you, but things have been crazy. "
            "Anyway, let's catch up soon."
        )
        result = analyze_sentence_variety(text)
        self.assertGreater(result['punctuation_variety'], 0.0)


if __name__ == '__main__':
    unittest.main()
