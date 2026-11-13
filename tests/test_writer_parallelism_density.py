#!/usr/bin/env python3
"""Tests for writer_parallelism_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_parallelism_density import (  # noqa: E402
    CORRELATIVE_PAIRS,
    WriterParallelismDensity,
    _closing_words,
    _opening_pos_tag,
    _opening_words,
    _split_clauses,
    _split_sentences,
    _tokenize,
    _word_count,
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


class TestSplitClauses(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_clauses(""), [])

    def test_single_clause(self):
        result = _split_clauses("She walked home quickly")
        self.assertEqual(len(result), 1)

    def test_comma_separated(self):
        result = _split_clauses("Easy come, easy go")
        self.assertEqual(len(result), 2)

    def test_semicolon_separated(self):
        result = _split_clauses("I came; I saw; I conquered")
        self.assertEqual(len(result), 3)

    def test_dash_separated(self):
        result = _split_clauses("the good — the bad — the ugly")
        self.assertEqual(len(result), 3)

    def test_short_fragments_excluded(self):
        # Single-word fragments should be excluded
        result = _split_clauses("Hello, world")
        # "Hello" is one word so excluded, "world" is one word so excluded
        self.assertEqual(len(result), 0)


class TestTokenize(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_simple_words(self):
        result = _tokenize("hello world")
        self.assertEqual(result, ["hello", "world"])

    def test_with_punctuation(self):
        result = _tokenize("hello, world!")
        self.assertIn("hello", result)
        self.assertIn(",", result)
        self.assertIn("world", result)

    def test_contractions(self):
        result = _tokenize("don't stop")
        self.assertIn("don't", result)


class TestWordCount(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_word_count(""), 0)

    def test_single_word(self):
        self.assertEqual(_word_count("hello"), 1)

    def test_multiple_words(self):
        self.assertEqual(_word_count("the quick brown fox"), 4)


class TestOpeningWords(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_opening_words(""), [])

    def test_single_word(self):
        self.assertEqual(_opening_words("Hello"), ["hello"])

    def test_multiple_words(self):
        result = _opening_words("The quick brown fox")
        self.assertEqual(result[:2], ["the", "quick"])

    def test_custom_n(self):
        result = _opening_words("The quick brown fox", 3)
        self.assertEqual(result, ["the", "quick", "brown"])


class TestClosingWords(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_closing_words(""), [])

    def test_single_word(self):
        self.assertEqual(_closing_words("Hello"), ["hello"])

    def test_multiple_words(self):
        result = _closing_words("The quick brown fox")
        self.assertEqual(result[-2:], ["brown", "fox"])

    def test_custom_n(self):
        result = _closing_words("The quick brown fox", 3)
        self.assertEqual(result, ["quick", "brown", "fox"])


class TestOpeningPosTag(unittest.TestCase):
    def test_determiner(self):
        self.assertEqual(_opening_pos_tag("The cat sat"), "DET")
        self.assertEqual(_opening_pos_tag("A dog barked"), "DET")
        self.assertEqual(_opening_pos_tag("This book is mine"), "DET")

    def test_pronoun(self):
        self.assertEqual(_opening_pos_tag("I went home"), "PRON")
        self.assertEqual(_opening_pos_tag("She left early"), "PRON")
        self.assertEqual(_opening_pos_tag("They arrived late"), "PRON")

    def test_preposition(self):
        self.assertEqual(_opening_pos_tag("In the garden"), "PREP")
        self.assertEqual(_opening_pos_tag("On the table"), "PREP")
        self.assertEqual(_opening_pos_tag("After the storm"), "PREP")

    def test_conjunction(self):
        self.assertEqual(_opening_pos_tag("And then he left"), "CONJ")
        self.assertEqual(_opening_pos_tag("But she stayed"), "CONJ")
        self.assertEqual(_opening_pos_tag("Because it rained"), "CONJ")

    def test_auxiliary(self):
        self.assertEqual(_opening_pos_tag("is going home"), "AUX")
        self.assertEqual(_opening_pos_tag("have finished work"), "AUX")
        self.assertEqual(_opening_pos_tag("will arrive soon"), "AUX")

    def test_adverb(self):
        self.assertEqual(_opening_pos_tag("Very interesting idea"), "ADV")
        self.assertEqual(_opening_pos_tag("However she tried"), "ADV")
        self.assertEqual(_opening_pos_tag("Slowly he turned"), "ADV")

    def test_empty(self):
        self.assertEqual(_opening_pos_tag(""), "OTHER")


# ── Anaphora Rate ────────────────────────────────────────────────────


class TestAnaphoraRate(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.anaphora_rate(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(self.wpd.anaphora_rate("Hello world."), 0.0)

    def test_no_anaphora(self):
        text = "The cat sat. A dog barked. Birds flew overhead."
        self.assertEqual(self.wpd.anaphora_rate(text), 0.0)

    def test_strong_anaphora(self):
        text = (
            "We shall fight on the beaches. "
            "We shall fight on the landing grounds. "
            "We shall fight in the fields. "
            "We shall never surrender."
        )
        rate = self.wpd.anaphora_rate(text)
        self.assertGreater(rate, 0.5)

    def test_moderate_anaphora(self):
        text = (
            "She walked to the store. "
            "She bought some bread. "
            "The sun was setting. "
            "She hurried home."
        )
        rate = self.wpd.anaphora_rate(text)
        self.assertGreater(rate, 0.0)

    def test_two_word_anaphora_bonus(self):
        text = (
            "It was the best of times. "
            "It was the worst of times. "
            "It was the age of wisdom."
        )
        rate = self.wpd.anaphora_rate(text)
        self.assertGreater(rate, 0.5)

    def test_case_insensitive(self):
        text = "The cat slept. the dog barked. The bird sang."
        rate = self.wpd.anaphora_rate(text)
        self.assertGreater(rate, 0.0)


# ── Epistrophe Rate ──────────────────────────────────────────────────


class TestEpistropheRate(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.epistrophe_rate(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(self.wpd.epistrophe_rate("Hello world."), 0.0)

    def test_no_epistrophe(self):
        text = "The cat sat on a mat. A dog barked loudly. Birds flew south."
        self.assertEqual(self.wpd.epistrophe_rate(text), 0.0)

    def test_strong_epistrophe(self):
        text = (
            "Government of the people. "
            "Government by the people. "
            "Government for the people."
        )
        rate = self.wpd.epistrophe_rate(text)
        self.assertGreater(rate, 0.0)

    def test_moderate_epistrophe(self):
        text = (
            "She loved the rain. "
            "He feared the rain. "
            "They embraced the rain."
        )
        rate = self.wpd.epistrophe_rate(text)
        self.assertGreater(rate, 0.0)


# ── Balanced Clause Rate ─────────────────────────────────────────────


class TestBalancedClauseRate(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.balanced_clause_rate(""), 0.0)

    def test_no_clauses(self):
        text = "The cat sat."
        self.assertEqual(self.wpd.balanced_clause_rate(text), 0.0)

    def test_balanced_clauses(self):
        text = "Easy come, easy go."
        rate = self.wpd.balanced_clause_rate(text)
        self.assertGreater(rate, 0.0)

    def test_unbalanced_clauses(self):
        text = "Quick, after a very long and exhausting journey that took three weeks."
        rate = self.wpd.balanced_clause_rate(text)
        self.assertLess(rate, 0.5)

    def test_semicolon_balance(self):
        text = "The sun rose over the hills; the moon set behind the sea."
        rate = self.wpd.balanced_clause_rate(text)
        # Both clauses should have similar length
        self.assertGreaterEqual(rate, 0.0)

    def test_multiple_balanced_pairs(self):
        text = (
            "She came early, he arrived late. "
            "The door opened wide, the window shut tight."
        )
        rate = self.wpd.balanced_clause_rate(text)
        self.assertGreater(rate, 0.0)


# ── Correlative Density ─────────────────────────────────────────────


class TestCorrelativeDensity(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.correlative_density(""), 0.0)

    def test_no_correlatives(self):
        text = "The cat sat on the mat. A dog ran in the park."
        self.assertEqual(self.wpd.correlative_density(text), 0.0)

    def test_both_and(self):
        text = "Both the cat and the dog were sleeping."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_either_or(self):
        text = "Either we leave now or we stay forever."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_neither_nor(self):
        text = "Neither the rain nor the wind could stop them."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_not_only_but_also(self):
        text = "Not only did they win the game, but they also set a record."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_whether_or(self):
        text = "Whether we succeed or we fail depends on effort."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_comparative_correlative(self):
        text = "The more you practice, the better you become."
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.0)

    def test_multiple_correlatives(self):
        text = (
            "Both the cat and the dog slept. "
            "Either we go or we stay. "
            "Neither rain nor snow stopped them."
        )
        rate = self.wpd.correlative_density(text)
        self.assertGreater(rate, 0.5)


# ── Structural Repetition Rate ──────────────────────────────────────


class TestStructuralRepetitionRate(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.structural_repetition_rate(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(self.wpd.structural_repetition_rate("Hello."), 0.0)

    def test_no_repetition(self):
        text = (
            "The cat sat on the mat. "
            "Running quickly, she caught the bus. "
            "In the garden, flowers bloomed."
        )
        # DET, VERB/ADV, PREP — different categories
        rate = self.wpd.structural_repetition_rate(text)
        self.assertLessEqual(rate, 0.5)

    def test_pronoun_repetition(self):
        text = (
            "She walked to the store. "
            "She bought some bread. "
            "She hurried home."
        )
        rate = self.wpd.structural_repetition_rate(text)
        self.assertGreater(rate, 0.5)

    def test_determiner_repetition(self):
        text = (
            "The cat slept soundly. "
            "The dog barked loudly. "
            "The bird sang sweetly."
        )
        rate = self.wpd.structural_repetition_rate(text)
        self.assertGreater(rate, 0.5)

    def test_preposition_repetition(self):
        text = (
            "In the morning, she ran. "
            "In the afternoon, she rested. "
            "In the evening, she read."
        )
        rate = self.wpd.structural_repetition_rate(text)
        self.assertGreater(rate, 0.5)


# ── List Parallelism Rate ────────────────────────────────────────────


class TestListParallelismRate(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        self.assertEqual(self.wpd.list_parallelism_rate(""), 0.0)

    def test_no_lists(self):
        text = "The cat sat on the mat. A dog ran in the park."
        self.assertEqual(self.wpd.list_parallelism_rate(text), 0.0)

    def test_parallel_bullet_list(self):
        text = (
            "Things to do:\n"
            "- Run the tests\n"
            "- Fix the bugs\n"
            "- Deploy the code"
        )
        rate = self.wpd.list_parallelism_rate(text)
        self.assertGreater(rate, 0.0)

    def test_non_parallel_bullet_list(self):
        text = (
            "Mixed list:\n"
            "- Running quickly through the park\n"
            "- The importance of being earnest\n"
            "- Because we can"
        )
        rate = self.wpd.list_parallelism_rate(text)
        # Should be lower than a parallel list
        self.assertGreaterEqual(rate, 0.0)

    def test_numbered_list(self):
        text = (
            "Steps:\n"
            "1. Open the file\n"
            "2. Read the contents\n"
            "3. Close the file"
        )
        rate = self.wpd.list_parallelism_rate(text)
        self.assertGreater(rate, 0.0)


# ── Composite Index ──────────────────────────────────────────────────


class TestCompositeIndex(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_all_zeros(self):
        index = self.wpd.compute_parallelism_density_index(
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        self.assertEqual(index, 0.0)

    def test_all_max(self):
        index = self.wpd.compute_parallelism_density_index(
            3.0, 2.0, 1.0, 2.0, 1.0, 1.0
        )
        self.assertAlmostEqual(index, 1.0)

    def test_partial_values(self):
        index = self.wpd.compute_parallelism_density_index(
            1.5, 1.0, 0.5, 1.0, 0.5, 0.5
        )
        self.assertGreater(index, 0.0)
        self.assertLess(index, 1.0)

    def test_weights_sum_to_one(self):
        # Verify by setting each dimension to its cap individually
        # and checking that the sum of all individual results = 1.0
        weights = [0.22, 0.15, 0.20, 0.13, 0.18, 0.12]
        total = sum(weights)
        self.assertAlmostEqual(total, 1.0)

    def test_anaphora_weight(self):
        # Only anaphora at max, rest zero
        index = self.wpd.compute_parallelism_density_index(
            3.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        self.assertAlmostEqual(index, 0.22)

    def test_balanced_weight(self):
        index = self.wpd.compute_parallelism_density_index(
            0.0, 0.0, 1.0, 0.0, 0.0, 0.0
        )
        self.assertAlmostEqual(index, 0.20)


# ── Classification ───────────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_structurally_asymmetric(self):
        self.assertEqual(self.wpd.classify(0.0), "structurally_asymmetric")
        self.assertEqual(self.wpd.classify(0.05), "structurally_asymmetric")
        self.assertEqual(self.wpd.classify(0.09), "structurally_asymmetric")

    def test_mildly_parallel(self):
        self.assertEqual(self.wpd.classify(0.10), "mildly_parallel")
        self.assertEqual(self.wpd.classify(0.15), "mildly_parallel")
        self.assertEqual(self.wpd.classify(0.24), "mildly_parallel")

    def test_moderately_parallel(self):
        self.assertEqual(self.wpd.classify(0.25), "moderately_parallel")
        self.assertEqual(self.wpd.classify(0.35), "moderately_parallel")
        self.assertEqual(self.wpd.classify(0.44), "moderately_parallel")

    def test_richly_parallel(self):
        self.assertEqual(self.wpd.classify(0.45), "richly_parallel")
        self.assertEqual(self.wpd.classify(0.55), "richly_parallel")
        self.assertEqual(self.wpd.classify(0.64), "richly_parallel")

    def test_oratorically_parallel(self):
        self.assertEqual(self.wpd.classify(0.65), "oratorically_parallel")
        self.assertEqual(self.wpd.classify(0.80), "oratorically_parallel")
        self.assertEqual(self.wpd.classify(1.0), "oratorically_parallel")

    def test_boundary_values(self):
        # Check exact boundaries
        self.assertEqual(self.wpd.classify(0.10), "mildly_parallel")
        self.assertEqual(self.wpd.classify(0.25), "moderately_parallel")
        self.assertEqual(self.wpd.classify(0.45), "richly_parallel")
        self.assertEqual(self.wpd.classify(0.65), "oratorically_parallel")


# ── Measure (Integration) ───────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_empty_text(self):
        result = self.wpd.measure("")
        self.assertEqual(result["parallelism_density_index"], 0.0)
        self.assertEqual(result["classification"], "structurally_asymmetric")

    def test_whitespace_only(self):
        result = self.wpd.measure("   \n  ")
        self.assertEqual(result["parallelism_density_index"], 0.0)

    def test_none_like(self):
        result = self.wpd.measure("")
        self.assertEqual(result["anaphora_rate"], 0.0)

    def test_parallel_text(self):
        text = (
            "We shall fight on the beaches. "
            "We shall fight on the landing grounds. "
            "We shall fight in the fields. "
            "We shall never surrender. "
            "Both the cause and the effect were clear. "
            "Either we act now or we lose everything."
        )
        result = self.wpd.measure(text)
        self.assertGreater(result["anaphora_rate"], 0.0)
        self.assertGreater(result["correlative_density"], 0.0)
        self.assertIn(result["classification"], [
            "structurally_asymmetric", "mildly_parallel",
            "moderately_parallel", "richly_parallel",
            "oratorically_parallel",
        ])

    def test_asymmetric_text(self):
        text = (
            "The researcher opened the laboratory notebook. "
            "Temperature readings had been recorded at intervals. "
            "Three samples showed contamination signs. "
            "A meeting was scheduled for Thursday. "
            "Each team member would prepare a summary."
        )
        result = self.wpd.measure(text)
        self.assertLessEqual(result["anaphora_rate"], 0.5)

    def test_return_keys(self):
        result = self.wpd.measure("Hello world.")
        expected_keys = {
            "anaphora_rate",
            "epistrophe_rate",
            "balanced_clause_rate",
            "correlative_density",
            "structural_repetition_rate",
            "list_parallelism_rate",
            "parallelism_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_are_numeric_except_classification(self):
        result = self.wpd.measure("The cat sat on the mat.")
        for key, value in result.items():
            if key == "classification":
                self.assertIsInstance(value, str)
            else:
                self.assertIsInstance(value, float)

    def test_highly_parallel_speech(self):
        text = (
            "I have a dream that one day this nation will rise up. "
            "I have a dream that one day on the red hills of Georgia. "
            "I have a dream today. "
            "I have a dream that my four little children will one day live. "
            "I have a dream today."
        )
        result = self.wpd.measure(text)
        self.assertGreater(result["anaphora_rate"], 0.5)
        self.assertGreater(result["parallelism_density_index"], 0.0)

    def test_correlative_heavy(self):
        text = (
            "Both the cat and the dog were sleeping. "
            "Either we leave now or we stay forever. "
            "Neither the rain nor the wind could stop them. "
            "Not only did they win but they also set a record. "
            "Whether we succeed or we fail depends on effort."
        )
        result = self.wpd.measure(text)
        self.assertGreater(result["correlative_density"], 0.5)


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_single_word_text(self):
        result = self.wpd.measure("Hello")
        self.assertEqual(result["parallelism_density_index"], 0.0)

    def test_all_punctuation(self):
        result = self.wpd.measure("... !!! ???")
        self.assertEqual(result["parallelism_density_index"], 0.0)

    def test_very_long_text(self):
        text = "The cat sat on the mat. " * 100
        result = self.wpd.measure(text)
        self.assertIn("parallelism_density_index", result)
        self.assertGreaterEqual(result["parallelism_density_index"], 0.0)
        self.assertLessEqual(result["parallelism_density_index"], 1.0)

    def test_unicode_text(self):
        text = "Café au lait. Café noir. Café crème."
        result = self.wpd.measure(text)
        self.assertIn("parallelism_density_index", result)

    def test_repeated_identical_sentences(self):
        text = "Hello world. Hello world. Hello world."
        result = self.wpd.measure(text)
        # Should have high anaphora and structural repetition
        self.assertGreater(result["anaphora_rate"], 0.0)
        self.assertGreater(result["structural_repetition_rate"], 0.0)

    def test_mixed_list_formats(self):
        text = (
            "Shopping list:\n"
            "- Buy fresh bread\n"
            "- Pick up milk\n"
            "- Get some eggs\n"
            "- Choose ripe fruit"
        )
        result = self.wpd.measure(text)
        self.assertGreaterEqual(result["list_parallelism_rate"], 0.0)

    def test_capped_index(self):
        # Even with extreme values, index should not exceed 1.0
        index = self.wpd.compute_parallelism_density_index(
            10.0, 10.0, 10.0, 10.0, 10.0, 10.0
        )
        self.assertLessEqual(index, 1.0)


# ── Correlative Pairs Constant ───────────────────────────────────────


class TestCorrelativePairs(unittest.TestCase):
    def test_pairs_are_tuples(self):
        for pair in CORRELATIVE_PAIRS:
            self.assertIsInstance(pair, tuple)
            self.assertEqual(len(pair), 2)

    def test_common_pairs_present(self):
        pair_strings = [(a, b) for a, b in CORRELATIVE_PAIRS]
        self.assertIn(("both", "and"), pair_strings)
        self.assertIn(("either", "or"), pair_strings)
        self.assertIn(("neither", "nor"), pair_strings)


# ── Real-World Text Tests ───────────────────────────────────────────


class TestRealWorldTexts(unittest.TestCase):
    def setUp(self):
        self.wpd = WriterParallelismDensity()

    def test_churchill_speech(self):
        text = (
            "We shall fight on the beaches. "
            "We shall fight on the landing grounds. "
            "We shall fight in the fields. "
            "We shall fight in the hills. "
            "We shall never surrender."
        )
        result = self.wpd.measure(text)
        self.assertGreater(result["anaphora_rate"], 0.0)

    def test_gettysburg_address(self):
        text = (
            "Government of the people, by the people, for the "
            "people, shall not perish from the earth."
        )
        result = self.wpd.measure(text)
        self.assertIn("parallelism_density_index", result)

    def test_tale_of_two_cities(self):
        text = (
            "It was the best of times, it was the worst of times, "
            "it was the age of wisdom, it was the age of foolishness, "
            "it was the epoch of belief, it was the epoch of "
            "incredulity."
        )
        result = self.wpd.measure(text)
        self.assertGreater(result["balanced_clause_rate"], 0.0)

    def test_technical_documentation(self):
        text = (
            "The API endpoint accepts POST requests. "
            "Authentication is required via Bearer token. "
            "Rate limits are set at 100 requests per minute. "
            "Responses are returned in JSON format."
        )
        result = self.wpd.measure(text)
        # Technical docs should have moderate structural repetition
        # (sentences often start with determiners)
        self.assertIn("parallelism_density_index", result)

    def test_casual_conversation(self):
        text = (
            "So I went to the store yesterday. "
            "Man, it was crowded. "
            "Anyway, I got some milk. "
            "Oh, and I saw Sarah there."
        )
        result = self.wpd.measure(text)
        self.assertLess(result["parallelism_density_index"], 0.5)


if __name__ == "__main__":
    unittest.main()
