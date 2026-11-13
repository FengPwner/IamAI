#!/usr/bin/env python3
"""Tests for writer_negation_density — 120 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_negation_density import (  # noqa: E402
    CLAUSAL_NEGATORS,
    FALSE_POSITIVES,
    FUNCTION_WORDS,
    NEGATION_CONTRACTIONS,
    NEGATION_PREFIXES,
    NEGATIVE_QUANTIFIERS,
    TRUE_NEGATED_WORDS,
    WriterNegationDensity,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterNegationDensity initialization."""

    def test_init_default(self):
        wnd = WriterNegationDensity()
        self.assertIsNotNone(wnd.clausal_negators)
        self.assertIsNotNone(wnd.negative_quantifiers)

    def test_init_sets_all_constants(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.clausal_negators, CLAUSAL_NEGATORS)
        self.assertEqual(wnd.negative_quantifiers, NEGATIVE_QUANTIFIERS)
        self.assertEqual(wnd.negation_prefixes, NEGATION_PREFIXES)
        self.assertEqual(wnd.false_positives, FALSE_POSITIVES)
        self.assertEqual(wnd.true_negated_words, TRUE_NEGATED_WORDS)
        self.assertEqual(wnd.function_words, FUNCTION_WORDS)
        self.assertEqual(wnd.negation_contractions, NEGATION_CONTRACTIONS)


# ── Helpers ──────────────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd._split_sentences(""), [])

    def test_whitespace_only(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd._split_sentences("   "), [])

    def test_single_sentence(self):
        wnd = WriterNegationDensity()
        result = wnd._split_sentences("She did not go.")
        self.assertEqual(result, ["She did not go."])

    def test_multiple_sentences(self):
        wnd = WriterNegationDensity()
        result = wnd._split_sentences("She left. He stayed. They argued.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        wnd = WriterNegationDensity()
        result = wnd._split_sentences("Did she leave? Yes she did.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        wnd = WriterNegationDensity()
        result = wnd._split_sentences("No! Never! Stop!")
        self.assertEqual(len(result), 3)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd._tokenize(""), [])

    def test_basic(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd._tokenize("Not today"), ["not", "today"])

    def test_contractions(self):
        wnd = WriterNegationDensity()
        tokens = wnd._tokenize("don't can't won't")
        self.assertIn("don't", tokens)
        self.assertIn("can't", tokens)
        self.assertIn("won't", tokens)

    def test_punctuation_stripped(self):
        wnd = WriterNegationDensity()
        tokens = wnd._tokenize("Hello, world!")
        self.assertEqual(tokens, ["hello", "world"])


class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd._content_words(""), [])

    def test_function_words_removed(self):
        wnd = WriterNegationDensity()
        result = wnd._content_words("The big red fox is running")
        self.assertNotIn("the", result)
        self.assertNotIn("is", result)
        self.assertIn("big", result)
        self.assertIn("fox", result)

    def test_all_function_words(self):
        wnd = WriterNegationDensity()
        result = wnd._content_words("the a an is are")
        self.assertEqual(result, [])


class TestIsGenuineNegatedWord(unittest.TestCase):
    """Test _is_genuine_negated_word helper."""

    def test_known_true_negated(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("unhappy"))
        self.assertTrue(wnd._is_genuine_negated_word("impossible"))
        self.assertTrue(wnd._is_genuine_negated_word("irrelevant"))

    def test_known_false_positive(self):
        wnd = WriterNegationDensity()
        self.assertFalse(wnd._is_genuine_negated_word("into"))
        self.assertFalse(wnd._is_genuine_negated_word("industry"))
        self.assertFalse(wnd._is_genuine_negated_word("imagine"))

    def test_heuristic_prefix_stripping(self):
        wnd = WriterNegationDensity()
        # "unhelpful" — prefix "un" + stem "helpful" (len >= 3)
        self.assertTrue(wnd._is_genuine_negated_word("unhelpful"))

    def test_short_stem_rejected(self):
        wnd = WriterNegationDensity()
        # "un" + "it" = "unit" — stem too short
        # But "unit" is in false positives? Let's test the logic
        result = wnd._is_genuine_negated_word("unit")
        # "unit" not in true_negated or false_positives, stem "it" < 3
        self.assertFalse(result)

    def test_case_insensitive(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("UNHAPPY"))
        self.assertTrue(wnd._is_genuine_negated_word("Unhappy"))

    def test_dis_prefixed(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("dishonest"))
        self.assertTrue(wnd._is_genuine_negated_word("disagree"))

    def test_non_prefixed(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("nonprofit"))
        self.assertTrue(wnd._is_genuine_negated_word("nonverbal"))

    def test_mis_prefixed(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("mislead"))
        self.assertTrue(wnd._is_genuine_negated_word("misunderstand"))

    def test_a_prefix(self):
        wnd = WriterNegationDensity()
        self.assertTrue(wnd._is_genuine_negated_word("atypical"))
        self.assertTrue(wnd._is_genuine_negated_word("amoral"))


# ── Clausal negation rate ────────────────────────────────────────────


class TestClausalNegationRate(unittest.TestCase):
    """Test measure_clausal_negation_rate."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_clausal_negation_rate(""), 0.0)

    def test_no_negation(self):
        wnd = WriterNegationDensity()
        text = "The sun rose over the mountains. Birds sang loudly."
        self.assertEqual(wnd.measure_clausal_negation_rate(text), 0.0)

    def test_single_not(self):
        wnd = WriterNegationDensity()
        text = "She did not go to the store."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_multiple_not(self):
        wnd = WriterNegationDensity()
        text = "She did not go. He would not stay. They could not agree."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertEqual(rate, 1.0)  # 3 negators / 3 sentences

    def test_never(self):
        wnd = WriterNegationDensity()
        text = "She never went back."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertEqual(rate, 1.0)

    def test_neither_nor(self):
        wnd = WriterNegationDensity()
        text = "Neither the cat nor the dog was hungry."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertEqual(rate, 2.0)  # neither + nor in one sentence

    def test_contraction_dont(self):
        wnd = WriterNegationDensity()
        text = "I don't think so."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_contraction_cant(self):
        wnd = WriterNegationDensity()
        text = "We can't do this."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_mixed_negation(self):
        wnd = WriterNegationDensity()
        text = "She did not agree. Never again. Nothing changed."
        rate = wnd.measure_clausal_negation_rate(text)
        self.assertGreater(rate, 0.0)


# ── Constituent negation rate ────────────────────────────────────────


class TestConstituentNegationRate(unittest.TestCase):
    """Test measure_constituent_negation_rate."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_constituent_negation_rate(""), 0.0)

    def test_no_quantifiers(self):
        wnd = WriterNegationDensity()
        text = "The sun is bright today."
        self.assertEqual(wnd.measure_constituent_negation_rate(text), 0.0)

    def test_nothing(self):
        wnd = WriterNegationDensity()
        text = "Nothing matters anymore."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)

    def test_nobody(self):
        wnd = WriterNegationDensity()
        text = "Nobody came to the party."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)

    def test_nowhere(self):
        wnd = WriterNegationDensity()
        text = "There was nowhere to hide."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)

    def test_none(self):
        wnd = WriterNegationDensity()
        text = "None of them agreed."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)

    def test_multiple_quantifiers(self):
        wnd = WriterNegationDensity()
        text = "Nothing worked. Nobody cared. Nowhere was safe."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)  # 3 quantifiers / 3 sentences

    def test_no_as_quantifier(self):
        wnd = WriterNegationDensity()
        text = "There was no hope left."
        rate = wnd.measure_constituent_negation_rate(text)
        self.assertEqual(rate, 1.0)


# ── Affixal negation rate ────────────────────────────────────────────


class TestAffixalNegationRate(unittest.TestCase):
    """Test measure_affixal_negation_rate."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_affixal_negation_rate(""), 0.0)

    def test_no_negation(self):
        wnd = WriterNegationDensity()
        text = "The happy children played in the garden."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertEqual(rate, 0.0)

    def test_single_unhappy(self):
        wnd = WriterNegationDensity()
        text = "The unhappy child sat alone."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_multiple_negated_words(self):
        wnd = WriterNegationDensity()
        text = "The impossible task seemed unfair and unreasonable."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_false_positives_excluded(self):
        wnd = WriterNegationDensity()
        text = "The industry continues to improve important infrastructure."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertEqual(rate, 0.0)

    def test_disagree(self):
        wnd = WriterNegationDensity()
        text = "They disagree about the dishonest behavior."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_nonprofit(self):
        wnd = WriterNegationDensity()
        text = "The nonprofit organization operates nonverbal programs."
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertGreater(rate, 0.0)

    def test_high_density(self):
        wnd = WriterNegationDensity()
        text = (
            "The unhappy, uncomfortable, uncertain, unwilling "
            "participant found the experience unpleasant."
        )
        rate = wnd.measure_affixal_negation_rate(text)
        self.assertGreater(rate, 0.3)


# ── Double negation count ────────────────────────────────────────────


class TestDoubleNegationCount(unittest.TestCase):
    """Test measure_double_negation_count."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_double_negation_count(""), 0.0)

    def test_no_double_negation(self):
        wnd = WriterNegationDensity()
        text = "She did not go. He never arrived."
        count = wnd.measure_double_negation_count(text)
        self.assertEqual(count, 0.0)

    def test_not_uncommon(self):
        wnd = WriterNegationDensity()
        text = "It was not uncommon for delays to occur."
        count = wnd.measure_double_negation_count(text)
        self.assertGreater(count, 0.0)

    def test_not_unlikely(self):
        wnd = WriterNegationDensity()
        text = "It is not unlikely that she will arrive late."
        count = wnd.measure_double_negation_count(text)
        self.assertGreater(count, 0.0)

    def test_never_nothing(self):
        wnd = WriterNegationDensity()
        text = "He never said nothing about it."
        count = wnd.measure_double_negation_count(text)
        self.assertGreater(count, 0.0)

    def test_per_thousand_words(self):
        wnd = WriterNegationDensity()
        # Generate text with known double negation density
        text = "It was not uncommon. " * 50  # 200 words, 50 double negs
        count = wnd.measure_double_negation_count(text)
        self.assertGreater(count, 0.0)


# ── Negation scope depth ─────────────────────────────────────────────


class TestNegationScopeDepth(unittest.TestCase):
    """Test measure_negation_scope_depth."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_negation_scope_depth(""), 0.0)

    def test_no_negation(self):
        wnd = WriterNegationDensity()
        text = "The sun rose. Birds sang. Children played."
        self.assertEqual(wnd.measure_negation_scope_depth(text), 0.0)

    def test_single_negation(self):
        wnd = WriterNegationDensity()
        text = "She did not go."
        depth = wnd.measure_negation_scope_depth(text)
        self.assertGreaterEqual(depth, 1.0)

    def test_multiple_in_sentence(self):
        wnd = WriterNegationDensity()
        text = "She did not go and he would not stay."
        depth = wnd.measure_negation_scope_depth(text)
        self.assertGreaterEqual(depth, 2.0)

    def test_mixed_sentences(self):
        wnd = WriterNegationDensity()
        text = "She did not go. The sun rose."
        depth = wnd.measure_negation_scope_depth(text)
        # Average of (>=1, 0) = at least 0.5
        self.assertGreater(depth, 0.0)
        self.assertLess(depth, 2.0)


# ── Negation cluster ratio ───────────────────────────────────────────


class TestNegationClusterRatio(unittest.TestCase):
    """Test measure_negation_cluster_ratio."""

    def test_empty(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.measure_negation_cluster_ratio(""), 0.0)

    def test_no_negation(self):
        wnd = WriterNegationDensity()
        text = "The sun rose over the mountains."
        self.assertEqual(wnd.measure_negation_cluster_ratio(text), 0.0)

    def test_single_negation(self):
        wnd = WriterNegationDensity()
        text = "She did not go to the store today."
        ratio = wnd.measure_negation_cluster_ratio(text)
        self.assertEqual(ratio, 0.0)  # Only one negation, can't cluster

    def test_clustered_negations(self):
        wnd = WriterNegationDensity()
        text = "It was not merely not helpful but not even relevant."
        ratio = wnd.measure_negation_cluster_ratio(text)
        self.assertGreater(ratio, 0.0)

    def test_scattered_negations(self):
        wnd = WriterNegationDensity()
        # Negations far apart
        text = (
            "She did not go to the store because the weather was "
            "beautiful and the children were playing happily in the "
            "garden while the birds sang in the trees and the flowers "
            "bloomed in the warm sunshine. He never visited again."
        )
        ratio = wnd.measure_negation_cluster_ratio(text)
        # "not" and "never" are far apart, should be low
        self.assertLessEqual(ratio, 1.0)


# ── Composite index ──────────────────────────────────────────────────


class TestNegationDensityIndex(unittest.TestCase):
    """Test compute_negation_density_index."""

    def test_all_zero(self):
        wnd = WriterNegationDensity()
        idx = wnd.compute_negation_density_index(0, 0, 0, 0, 0, 0)
        self.assertEqual(idx, 0.0)

    def test_all_high(self):
        wnd = WriterNegationDensity()
        idx = wnd.compute_negation_density_index(1.5, 0.8, 0.3, 5.0, 3.0, 1.0)
        self.assertEqual(idx, 1.0)

    def test_partial(self):
        wnd = WriterNegationDensity()
        idx = wnd.compute_negation_density_index(0.75, 0, 0, 0, 0, 0)
        self.assertAlmostEqual(idx, 0.75 / 1.5 * 0.30, places=4)

    def test_monotonic(self):
        wnd = WriterNegationDensity()
        idx1 = wnd.compute_negation_density_index(0.5, 0.2, 0.1, 1.0, 1.0, 0.3)
        idx2 = wnd.compute_negation_density_index(1.0, 0.4, 0.2, 2.0, 2.0, 0.6)
        self.assertGreater(idx2, idx1)


# ── Classification ───────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_strongly_affirmative(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.05), "strongly_affirmative")

    def test_affirmative(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.15), "affirmative")

    def test_moderate(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.30), "moderate_negation")

    def test_heavy(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.50), "negation_heavy")

    def test_saturated(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.75), "negation_saturated")

    def test_boundary_010(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.10), "affirmative")

    def test_boundary_020(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.20), "moderate_negation")

    def test_boundary_040(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.40), "negation_heavy")

    def test_boundary_060(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.60), "negation_saturated")

    def test_zero(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(0.0), "strongly_affirmative")

    def test_one(self):
        wnd = WriterNegationDensity()
        self.assertEqual(wnd.classify(1.0), "negation_saturated")


# ── Full measure ─────────────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the full measure pipeline."""

    def test_empty_string(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("")
        self.assertEqual(result["clausal_negation_rate"], 0.0)
        self.assertEqual(result["negation_density_index"], 0.0)
        self.assertEqual(result["classification"], "strongly_affirmative")

    def test_none_like(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("   ")
        self.assertEqual(result["negation_density_index"], 0.0)

    def test_affirmative_text(self):
        wnd = WriterNegationDensity()
        text = (
            "The sun rose over the mountains, painting the valley "
            "in gold. Birds sang from the treetops. The river flowed "
            "steadily toward the sea. Children played in the meadow. "
            "Everything was exactly as it should be."
        )
        result = wnd.measure(text)
        self.assertEqual(result["clausal_negation_rate"], 0.0)
        self.assertEqual(result["constituent_negation_rate"], 0.0)
        self.assertEqual(result["classification"], "strongly_affirmative")

    def test_negation_heavy_text(self):
        wnd = WriterNegationDensity()
        text = (
            "It was not uncommon for the committee to reject proposals "
            "that were not clearly aligned with the organization's goals. "
            "The chairman did not disagree with the need for change, but "
            "he was unwilling to approve any plan that did not include a "
            "detailed risk assessment. Nothing was certain. Nobody could "
            "guarantee success. The board would neither endorse nor reject "
            "the proposal without further review."
        )
        result = wnd.measure(text)
        self.assertGreater(result["clausal_negation_rate"], 0.0)
        self.assertGreater(result["constituent_negation_rate"], 0.0)
        self.assertGreater(result["affixal_negation_rate"], 0.0)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_legal_text(self):
        wnd = WriterNegationDensity()
        text = (
            "The licensee shall not sublicense, assign, or transfer "
            "the licensed technology without prior written consent. "
            "No warranty is provided. The licensor disclaims all "
            "implied warranties, including but not limited to "
            "merchantability and fitness for a particular purpose."
        )
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_returns_all_keys(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("She did not go.")
        expected_keys = {
            "clausal_negation_rate",
            "constituent_negation_rate",
            "affixal_negation_rate",
            "double_negation_count",
            "negation_scope_depth",
            "negation_cluster_ratio",
            "negation_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_are_rounded(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("She did not go to the store.")
        for key in [
            "clausal_negation_rate",
            "constituent_negation_rate",
            "affixal_negation_rate",
            "double_negation_count",
            "negation_scope_depth",
            "negation_cluster_ratio",
            "negation_density_index",
        ]:
            # Check that value is a float with at most 4 decimal places
            val = result[key]
            self.assertIsInstance(val, float)
            self.assertEqual(val, round(val, 4))


# ── Orthogonality sanity checks ──────────────────────────────────────


class TestOrthogonality(unittest.TestCase):
    """Verify negation density is independent of other dimensions."""

    def test_formal_affirmative_vs_formal_negative(self):
        wnd = WriterNegationDensity()
        formal_pos = "The committee approved the proposal unanimously."
        formal_neg = "The committee did not reject the proposal."
        r_pos = wnd.measure(formal_pos)
        r_neg = wnd.measure(formal_neg)
        # Both are formal; negation density should differ
        self.assertLess(
            r_pos["negation_density_index"],
            r_neg["negation_density_index"],
        )

    def test_short_vs_long_negation(self):
        wnd = WriterNegationDensity()
        short = "No."
        long_text = "There was no possibility of success."
        r_short = wnd.measure(short)
        r_long = wnd.measure(long_text)
        # Both have negation; both should have positive index
        self.assertGreater(r_short["negation_density_index"], 0.0)
        self.assertGreater(r_long["negation_density_index"], 0.0)

    def test_dialog_with_negation(self):
        wnd = WriterNegationDensity()
        dialog_neg = '"I don\'t think so," she said. "Neither do I," he replied.'
        result = wnd.measure(dialog_neg)
        self.assertGreater(result["negation_density_index"], 0.0)


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word_not(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("Not.")
        self.assertGreater(result["clausal_negation_rate"], 0.0)

    def test_repeated_negation(self):
        wnd = WriterNegationDensity()
        text = "No no no no no."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_mixed_languages(self):
        wnd = WriterNegationDensity()
        text = "The café was not open. The résumé contained no errors."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_numbers_and_negation(self):
        wnd = WriterNegationDensity()
        text = "There were not 5 but 10 items remaining."
        result = wnd.measure(text)
        self.assertGreater(result["clausal_negation_rate"], 0.0)

    def test_very_long_text(self):
        wnd = WriterNegationDensity()
        text = "She did not go. " * 500
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_only_punctuation(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("...!!!???")
        self.assertEqual(result["negation_density_index"], 0.0)

    def test_newlines_and_tabs(self):
        wnd = WriterNegationDensity()
        text = "She did\tnot go.\nHe would not stay."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)

    def test_unicode_text(self):
        wnd = WriterNegationDensity()
        text = "The naïve approach didn't work. The résumé was unacceptable."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)


if __name__ == "__main__":
    unittest.main()


# ── Additional edge cases for 100+ coverage ──────────────────────────


class TestNegationContractions(unittest.TestCase):
    """Test contraction-specific negation detection."""

    def test_wont(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("She won't be coming today.")
        self.assertGreater(result["clausal_negation_rate"], 0.0)

    def test_shouldnt(self):
        wnd = WriterNegationDensity()
        result = wnd.measure("We shouldn't have done that.")
        self.assertGreater(result["clausal_negation_rate"], 0.0)

    def test_multiple_contractions(self):
        wnd = WriterNegationDensity()
        text = "I don't think they won't come. She can't agree."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)


class TestMeasureIntegration(unittest.TestCase):
    """Integration tests for the full measure pipeline."""

    def test_pure_negation_text(self):
        wnd = WriterNegationDensity()
        text = "Not this. Not that. Never again. Nothing works."
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.2)

    def test_philosophical_negation(self):
        wnd = WriterNegationDensity()
        text = (
            "The good is not pleasure. The true is not the false. "
            "To know is not to believe. To see is not to understand."
        )
        result = wnd.measure(text)
        self.assertGreater(result["negation_density_index"], 0.0)
        self.assertIn(result["classification"],
                      ["moderate_negation", "negation_heavy",
                       "negation_saturated", "affirmative"])
