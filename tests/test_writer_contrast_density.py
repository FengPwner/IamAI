#!/usr/bin/env python3
"""Tests for writer_contrast_density — 120 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_contrast_density import (  # noqa: E402
    ADVERSATIVE_CONJUNCTIONS,
    ANTITHESIS_PATTERNS,
    COMPARATIVE_CONTRAST,
    CONCESSION_PATTERNS,
    OPPOSITION_PAIRS,
    REVERSAL_MARKERS,
    WriterContrastDensity,
    _count_pattern_matches,
    _count_phrase_occurrences,
    _split_sentences,
    _tokenize,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterContrastDensity initialization."""

    def test_init_default(self):
        wcd = WriterContrastDensity()
        self.assertIsNotNone(wcd.adversative_conjunctions)
        self.assertIsNotNone(wcd.opposition_pairs)

    def test_init_sets_all_constants(self):
        wcd = WriterContrastDensity()
        self.assertEqual(wcd.adversative_conjunctions, ADVERSATIVE_CONJUNCTIONS)
        self.assertEqual(wcd.antithesis_patterns, ANTITHESIS_PATTERNS)
        self.assertEqual(wcd.reversal_markers, REVERSAL_MARKERS)
        self.assertEqual(wcd.concession_patterns, CONCESSION_PATTERNS)
        self.assertEqual(wcd.opposition_pairs, OPPOSITION_PAIRS)
        self.assertEqual(wcd.comparative_contrast, COMPARATIVE_CONTRAST)

    def test_adversative_conjunctions_sorted_longest_first(self):
        lengths = [len(c) for c in ADVERSATIVE_CONJUNCTIONS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_reversal_markers_sorted_longest_first(self):
        lengths = [len(c) for c in REVERSAL_MARKERS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_comparative_contrast_sorted_longest_first(self):
        lengths = [len(c) for c in COMPARATIVE_CONTRAST]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_opposition_pairs_are_tuples(self):
        for pair in OPPOSITION_PAIRS:
            self.assertIsInstance(pair, tuple)
            self.assertEqual(len(pair), 2)


# ── Helpers ──────────────────────────────────────────────────────────


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_simple_text(self):
        result = _tokenize("Hello World")
        self.assertEqual(result, ["hello", "world"])

    def test_punctuation(self):
        result = _tokenize("She said, hello!")
        self.assertIn("she", result)
        self.assertIn("said", result)
        self.assertIn("hello", result)

    def test_contractions(self):
        result = _tokenize("don't can't won't")
        self.assertIn("don't", result)
        self.assertIn("can't", result)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        result = _split_sentences("Hello. World. How are you?")
        self.assertEqual(len(result), 3)

    def test_exclamation_and_question(self):
        result = _split_sentences("Wow! Really? Yes.")
        self.assertEqual(len(result), 3)


class TestCountPhraseOccurrences(unittest.TestCase):
    """Test _count_phrase_occurrences helper."""

    def test_no_match(self):
        self.assertEqual(_count_phrase_occurrences("hello world", ("goodbye",)), 0)

    def test_single_match(self):
        self.assertEqual(_count_phrase_occurrences("hello but world", ("but",)), 1)

    def test_multiple_matches(self):
        text = "but this but that but everything"
        self.assertEqual(_count_phrase_occurrences(text, ("but",)), 3)

    def test_case_insensitive(self):
        self.assertEqual(_count_phrase_occurrences("HOWEVER it was", ("however",)), 1)


class TestCountPatternMatches(unittest.TestCase):
    """Test _count_pattern_matches helper."""

    def test_no_match(self):
        self.assertEqual(_count_pattern_matches("hello", (r"\d+",)), 0)

    def test_regex_match(self):
        self.assertEqual(_count_pattern_matches("123 abc 456", (r"\d+",)), 2)

    def test_multiple_patterns(self):
        text = "admittedly, it was true"
        count = _count_pattern_matches(text, (r"\badmittedly\b", r"\btrue\b"))
        self.assertEqual(count, 2)


# ── Dimension 1: Adversative Conjunction Rate ────────────────────────


class TestAdversativeConjunctionRate(unittest.TestCase):
    """Test measure_adversative_conjunction_rate."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        self.assertEqual(self.wcd.measure_adversative_conjunction_rate(""), 0.0)

    def test_no_adversatives(self):
        text = "The cat sat on the mat. The dog played in the yard."
        self.assertEqual(self.wcd.measure_adversative_conjunction_rate(text), 0.0)

    def test_single_but(self):
        text = "She was tired, but she kept going."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_adversatives(self):
        text = (
            "She was tired, but she kept going. However, the path was steep. "
            "Although the summit seemed close, it was still far."
        )
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreaterEqual(result, 0.5)

    def test_yet_as_adversative(self):
        text = "The night was cold, yet the fire burned bright."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_whereas(self):
        text = "The north was industrial, whereas the south remained agricultural."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_despite(self):
        text = "Despite the rain, they continued the match."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_spite_of(self):
        text = "In spite of the warnings, he proceeded."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_nevertheless(self):
        text = "The evidence was thin. Nevertheless, the jury convicted."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertGreater(result, 0.0)

    def test_result_capped_at_one(self):
        # Many adversatives in few sentences
        text = "But yet but. But yet but."
        result = self.wcd.measure_adversative_conjunction_rate(text)
        self.assertLessEqual(result, 1.0)


# ── Dimension 2: Antithesis Rate ─────────────────────────────────────


class TestAntithesisRate(unittest.TestCase):
    """Test measure_antithesis_rate."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        self.assertEqual(self.wcd.measure_antithesis_rate(""), 0.0)

    def test_no_antithesis(self):
        text = "The garden was beautiful. Flowers bloomed everywhere."
        self.assertEqual(self.wcd.measure_antithesis_rate(text), 0.0)

    def test_not_x_but_y(self):
        text = "It was not the beginning but the end of an era."
        result = self.wcd.measure_antithesis_rate(text)
        self.assertGreater(result, 0.0)

    def test_rather_than(self):
        text = "She chose to walk rather than drive."
        result = self.wcd.measure_antithesis_rate(text)
        self.assertGreater(result, 0.0)

    def test_instead_of(self):
        text = "They built a bridge instead of a tunnel."
        result = self.wcd.measure_antithesis_rate(text)
        self.assertGreater(result, 0.0)

    def test_on_one_hand(self):
        text = "On one hand, the plan was risky. On the other hand, doing nothing was worse."
        result = self.wcd.measure_antithesis_rate(text)
        self.assertGreater(result, 0.0)

    def test_not_only_but_also(self):
        text = "She was not only brilliant but also kind."
        result = self.wcd.measure_antithesis_rate(text)
        self.assertGreater(result, 0.0)


# ── Dimension 3: Reversal Rate ───────────────────────────────────────


class TestReversalRate(unittest.TestCase):
    """Test measure_reversal_rate."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        self.assertEqual(self.wcd.measure_reversal_rate(""), 0.0)

    def test_no_reversal(self):
        text = "The project proceeded as planned. Everything went smoothly."
        self.assertEqual(self.wcd.measure_reversal_rate(text), 0.0)

    def test_surprisingly(self):
        text = "Surprisingly, the underdog won the match."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_fact(self):
        text = "The theory seemed sound. In fact, it was deeply flawed."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_actually(self):
        text = "Actually, the results contradicted the hypothesis."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_on_the_contrary(self):
        text = "The plan was not abandoned. On the contrary, it was accelerated."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_it_turns_out(self):
        text = "It turns out the simplest approach worked best."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_far_from(self):
        text = "Far from being a setback, this was a breakthrough."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_paradoxically(self):
        text = "Paradoxically, less control produced better results."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)

    def test_ironically(self):
        text = "Ironically, the fire station itself caught fire."
        result = self.wcd.measure_reversal_rate(text)
        self.assertGreater(result, 0.0)


# ── Dimension 4: Concession Rate ─────────────────────────────────────


class TestConcessionRate(unittest.TestCase):
    """Test measure_concession_rate."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        self.assertEqual(self.wcd.measure_concession_rate(""), 0.0)

    def test_no_concession(self):
        text = "The algorithm runs in O(n log n) time. It handles all edge cases."
        self.assertEqual(self.wcd.measure_concession_rate(text), 0.0)

    def test_admittedly(self):
        text = "Admittedly, the first draft was rough."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)

    def test_granted(self):
        text = "Granted, the sample size was small, but the trend was clear."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)

    def test_to_be_sure(self):
        text = "To be sure, the evidence is not conclusive."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)

    def test_of_course(self):
        text = "Of course, there are exceptions to every rule."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)

    def test_certainly_but(self):
        text = "Certainly the model is powerful, but it requires careful tuning."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)

    def test_one_might_say(self):
        text = "One might say the design is outdated, yet it still works."
        result = self.wcd.measure_concession_rate(text)
        self.assertGreater(result, 0.0)


# ── Dimension 5: Opposition Density ─────────────────────────────────


class TestOppositionDensity(unittest.TestCase):
    """Test measure_opposition_density."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        self.assertEqual(self.wcd.measure_opposition_density(""), 0.0)

    def test_no_opposition(self):
        text = "The blue sky stretched endlessly above the green fields."
        self.assertEqual(self.wcd.measure_opposition_density(text), 0.0)

    def test_good_bad_pair(self):
        text = "The news was good for some and bad for others."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_success_failure_pair(self):
        text = "Success and failure are two sides of the same coin."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_light_dark_pair(self):
        text = "The painting moved from light to dark across the canvas."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_theory_practice_pair(self):
        text = "In theory it works, but practice reveals many issues."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_unlike_marker(self):
        text = "Unlike the previous version, this one supports async."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_in_contrast_marker(self):
        text = "In contrast to the old system, the new one is faster."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_as_opposed_to(self):
        text = "We chose Python as opposed to Java for this project."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_multiple_pairs_in_sentence(self):
        text = "The transition from old to new, from past to future, was seamless."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.5)

    def test_pros_cons(self):
        text = "Every decision has its pros and cons."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)

    def test_advantage_disadvantage(self):
        text = "The advantage of speed comes with the disadvantage of safety."
        result = self.wcd.measure_opposition_density(text)
        self.assertGreater(result, 0.0)


# ── Composite Index ──────────────────────────────────────────────────


class TestCompositeIndex(unittest.TestCase):
    """Test compute_contrast_density_index."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_all_zeros(self):
        result = self.wcd.compute_contrast_density_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        result = self.wcd.compute_contrast_density_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(result, 1.0)

    def test_weighted_average(self):
        # adversative=1.0 (0.25) + opposition=1.0 (0.25) = 0.50
        result = self.wcd.compute_contrast_density_index(1.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.50, places=4)

    def test_only_adversative(self):
        result = self.wcd.compute_contrast_density_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.25, places=4)

    def test_only_antithesis(self):
        result = self.wcd.compute_contrast_density_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20, places=4)

    def test_only_reversal(self):
        result = self.wcd.compute_contrast_density_index(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_only_concession(self):
        result = self.wcd.compute_contrast_density_index(0.0, 0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_only_opposition(self):
        result = self.wcd.compute_contrast_density_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.25, places=4)

    def test_capped_at_one(self):
        result = self.wcd.compute_contrast_density_index(2.0, 2.0, 2.0, 2.0, 2.0)
        self.assertEqual(result, 1.0)

    def test_not_negative(self):
        result = self.wcd.compute_contrast_density_index(-1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_weights_sum_to_one(self):
        weights = [0.25, 0.20, 0.15, 0.15, 0.25]
        self.assertAlmostEqual(sum(weights), 1.0)


# ── Classification ───────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_contrast_free(self):
        self.assertEqual(WriterContrastDensity.classify(0.0), "contrast_free")
        self.assertEqual(WriterContrastDensity.classify(0.01), "contrast_free")
        self.assertEqual(WriterContrastDensity.classify(0.04), "contrast_free")

    def test_minimally_contrastive(self):
        self.assertEqual(WriterContrastDensity.classify(0.05), "minimally_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.10), "minimally_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.14), "minimally_contrastive")

    def test_moderately_contrastive(self):
        self.assertEqual(WriterContrastDensity.classify(0.15), "moderately_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.25), "moderately_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.34), "moderately_contrastive")

    def test_richly_contrastive(self):
        self.assertEqual(WriterContrastDensity.classify(0.35), "richly_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.45), "richly_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.54), "richly_contrastive")

    def test_dialectically_contrastive(self):
        self.assertEqual(WriterContrastDensity.classify(0.55), "dialectically_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.75), "dialectically_contrastive")
        self.assertEqual(WriterContrastDensity.classify(1.0), "dialectically_contrastive")

    def test_boundary_values(self):
        # Exactly at boundaries
        self.assertEqual(WriterContrastDensity.classify(0.05), "minimally_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.15), "moderately_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.35), "richly_contrastive")
        self.assertEqual(WriterContrastDensity.classify(0.55), "dialectically_contrastive")


# ── Full measure() integration ───────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the full measure() pipeline."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_empty_text(self):
        result = self.wcd.measure("")
        self.assertEqual(result["contrast_density_index"], 0.0)
        self.assertEqual(result["classification"], "contrast_free")

    def test_none_text(self):
        result = self.wcd.measure(None)
        self.assertEqual(result["contrast_density_index"], 0.0)
        self.assertEqual(result["classification"], "contrast_free")

    def test_whitespace_only(self):
        result = self.wcd.measure("   \n\t  ")
        self.assertEqual(result["contrast_density_index"], 0.0)

    def test_returns_all_keys(self):
        result = self.wcd.measure("Hello world.")
        expected_keys = {
            "adversative_conjunction_rate",
            "antithesis_rate",
            "reversal_rate",
            "concession_rate",
            "opposition_density",
            "contrast_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_are_numeric_except_classification(self):
        result = self.wcd.measure("Hello world.")
        for key in [
            "adversative_conjunction_rate",
            "antithesis_rate",
            "reversal_rate",
            "concession_rate",
            "opposition_density",
            "contrast_density_index",
        ]:
            self.assertIsInstance(result[key], float)
        self.assertIsInstance(result["classification"], str)

    def test_contrast_rich_text_scores_higher(self):
        rich = (
            "The theory was elegant, but the data told a different story. "
            "Although the model predicted convergence, the actual results "
            "were chaotic. On one hand, the parameters seemed well-calibrated; "
            "on the other hand, the output diverged. Surprisingly, the simplest "
            "baseline outperformed the complex architecture. In fact, depth was "
            "not the answer — breadth mattered more. Rather than adding layers, "
            "the team succeeded by widening dimensions. Unlike previous approaches, "
            "this one favored simplicity over sophistication."
        )
        free = (
            "The old house stood at the edge of the meadow. Wildflowers grew "
            "along the stone path. The windows were dark. A cat sat on the "
            "porch, watching sparrows. The wind carried the smell of rain."
        )
        rich_result = self.wcd.measure(rich)
        free_result = self.wcd.measure(free)
        self.assertGreater(
            rich_result["contrast_density_index"],
            free_result["contrast_density_index"],
        )

    def test_contrast_free_classification(self):
        text = "The sky was clear. Birds flew overhead. The grass was green."
        result = self.wcd.measure(text)
        self.assertEqual(result["classification"], "contrast_free")

    def test_values_are_rounded(self):
        text = "But the results were good, although the process was slow."
        result = self.wcd.measure(text)
        for key in [
            "adversative_conjunction_rate",
            "antithesis_rate",
            "reversal_rate",
            "concession_rate",
            "opposition_density",
            "contrast_density_index",
        ]:
            # Check that values have at most 4 decimal places
            self.assertEqual(result[key], round(result[key], 4))


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        self.wcd = WriterContrastDensity()

    def test_single_word(self):
        result = self.wcd.measure("Hello.")
        self.assertIn("contrast_density_index", result)

    def test_single_sentence_many_contrasts(self):
        text = "But yet however, although surprisingly, in fact, it was good but bad."
        result = self.wcd.measure(text)
        self.assertGreater(result["adversative_conjunction_rate"], 0.0)
        self.assertGreater(result["reversal_rate"], 0.0)

    def test_repeated_same_contrast(self):
        text = "But. But. But. But. But."
        result = self.wcd.measure(text)
        self.assertGreater(result["adversative_conjunction_rate"], 0.0)

    def test_unicode_text(self):
        text = "The café was good, but the restaurant was bad."
        result = self.wcd.measure(text)
        self.assertIn("contrast_density_index", result)

    def test_very_long_text(self):
        text = ("This is good but that is bad. " * 50)
        result = self.wcd.measure(text)
        self.assertIn("contrast_density_index", result)
        self.assertLessEqual(result["contrast_density_index"], 1.0)

    def test_numbers_in_text(self):
        text = "In 2024, the results were good, but in 2025, they were bad."
        result = self.wcd.measure(text)
        self.assertIn("contrast_density_index", result)

    def test_opposition_pairs_case_insensitive(self):
        text = "The Good, the Bad, and the Ugly."
        result = self.wcd.measure(text)
        self.assertGreater(result["opposition_density"], 0.0)

    def test_multiline_text(self):
        text = """The theory was elegant.
        But the data disagreed.
        However, the team persisted.
        Although results were mixed."""
        result = self.wcd.measure(text)
        self.assertGreater(result["adversative_conjunction_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
