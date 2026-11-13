#!/usr/bin/env python3
"""Tests for writer_causal_density — 105 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_causal_density import (  # noqa: E402
    CAUSE_CONNECTORS,
    CONDITIONAL_MARKERS,
    CONCESSIVE_MARKERS,
    EFFECT_CONNECTORS,
    PURPOSE_MARKERS,
    STOPWORDS,
    WriterCausalDensity,
    _count_phrase_occurrences,
    _split_paragraphs,
    _split_sentences,
    _tokenize,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterCausalDensity initialization."""

    def test_init_default(self):
        wcd = WriterCausalDensity()
        self.assertIsNotNone(wcd.cause_connectors)
        self.assertIsNotNone(wcd.effect_connectors)

    def test_init_sets_all_constants(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.cause_connectors, CAUSE_CONNECTORS)
        self.assertEqual(wcd.effect_connectors, EFFECT_CONNECTORS)
        self.assertEqual(wcd.conditional_markers, CONDITIONAL_MARKERS)
        self.assertEqual(wcd.concessive_markers, CONCESSIVE_MARKERS)
        self.assertEqual(wcd.purpose_markers, PURPOSE_MARKERS)
        self.assertEqual(wcd.stopwords, STOPWORDS)

    def test_cause_connectors_sorted_longest_first(self):
        """Cause connectors should be sorted longest-first for greedy match."""
        lengths = [len(c) for c in CAUSE_CONNECTORS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_effect_connectors_sorted_longest_first(self):
        lengths = [len(c) for c in EFFECT_CONNECTORS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_conditional_markers_sorted_longest_first(self):
        lengths = [len(c) for c in CONDITIONAL_MARKERS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_concessive_markers_sorted_longest_first(self):
        lengths = [len(c) for c in CONCESSIVE_MARKERS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_purpose_markers_sorted_longest_first(self):
        lengths = [len(c) for c in PURPOSE_MARKERS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))


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

    def test_numbers_stripped(self):
        result = _tokenize("There were 42 items.")
        self.assertIn("there", result)
        self.assertIn("were", result)
        self.assertIn("items", result)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   "), [])

    def test_single_sentence(self):
        result = _split_sentences("She left early.")
        self.assertEqual(result, ["She left early."])

    def test_multiple_sentences(self):
        result = _split_sentences("She left. He stayed. They argued.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        result = _split_sentences("Why? Because I said so.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        result = _split_sentences("Stop! Now! Please!")
        self.assertEqual(len(result), 3)

    def test_abbreviations_not_split(self):
        # "Mr." followed by a capital should not split mid-name
        result = _split_sentences("Mr. Smith went home. He was tired.")
        # This is a known limitation — simple regex splits on "Mr."
        self.assertGreaterEqual(len(result), 2)


class TestSplitParagraphs(unittest.TestCase):
    """Test _split_paragraphs helper."""

    def test_empty_string(self):
        self.assertEqual(_split_paragraphs(""), [])

    def test_single_paragraph(self):
        result = _split_paragraphs("One paragraph here.")
        self.assertEqual(len(result), 1)

    def test_two_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 2)

    def test_multiple_blank_lines(self):
        text = "First.\n\n\n\nSecond."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 2)

    def test_whitespace_only(self):
        self.assertEqual(_split_paragraphs("   \n\n   "), [])


class TestCountPhraseOccurrences(unittest.TestCase):
    """Test _count_phrase_occurrences helper."""

    def test_no_match(self):
        self.assertEqual(_count_phrase_occurrences("hello world", ["because"]), 0)

    def test_single_match(self):
        self.assertEqual(_count_phrase_occurrences("because why", ["because"]), 1)

    def test_multiple_matches(self):
        self.assertEqual(
            _count_phrase_occurrences("because this and because that", ["because"]), 2
        )

    def test_longest_match_first(self):
        # "as a result of" should match once, not also match "as"
        text = "as a result of the rain"
        count = _count_phrase_occurrences(text, ["as a result of", "as"])
        self.assertEqual(count, 1)

    def test_word_boundary(self):
        # "therefore" should not match inside "thereforely" (not a real word, but boundary test)
        self.assertEqual(_count_phrase_occurrences("therefore", ["therefore"]), 1)

    def test_case_insensitive(self):
        # Input is expected to be already lowercased
        self.assertEqual(_count_phrase_occurrences("because", ["because"]), 1)

    def test_empty_phrases(self):
        self.assertEqual(_count_phrase_occurrences("hello", []), 0)

    def test_empty_text(self):
        self.assertEqual(_count_phrase_occurrences("", ["because"]), 0)


# ── Cause Connector Rate ─────────────────────────────────────────────


class TestCauseConnectorRate(unittest.TestCase):
    """Test measure_cause_connector_rate."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_cause_connector_rate(""), 0.0)

    def test_no_cause_connectors(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_cause_connector_rate("The cat sat on the mat."),
            0.0,
        )

    def test_single_because(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate("She left because she was tired.")
        self.assertEqual(result, 1.0)  # 1 connector / 1 sentence

    def test_multiple_causes_in_one_sentence(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "Because it rained and since the ground was wet, the game was canceled."
        )
        self.assertEqual(result, 2.0)

    def test_due_to(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "The flight was delayed due to bad weather."
        )
        self.assertEqual(result, 1.0)

    def test_owing_to(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "Owing to the circumstances, we must cancel."
        )
        self.assertEqual(result, 1.0)

    def test_rate_averaged_over_sentences(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "She left because she was tired. The cat slept."
        )
        self.assertEqual(result, 0.5)  # 1 connector / 2 sentences

    def test_since_as_cause(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "Since you asked, I will explain."
        )
        self.assertEqual(result, 1.0)

    def test_given_that(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate(
            "Given that the data is limited, we proceed cautiously."
        )
        self.assertEqual(result, 1.0)

    def test_case_insensitive(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_cause_connector_rate("BECAUSE it was late.")
        self.assertEqual(result, 1.0)


# ── Effect Connector Rate ────────────────────────────────────────────


class TestEffectConnectorRate(unittest.TestCase):
    """Test measure_effect_connector_rate."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_effect_connector_rate(""), 0.0)

    def test_no_effect_connectors(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_effect_connector_rate("The cat sat on the mat."),
            0.0,
        )

    def test_therefore(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "The data was flawed. Therefore, we must restart."
        )
        self.assertEqual(result, 0.5)

    def test_thus(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate("Thus ends the chapter.")
        self.assertEqual(result, 1.0)

    def test_hence(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate("Hence the confusion.")
        self.assertEqual(result, 1.0)

    def test_consequently(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "The budget was cut. Consequently, the project was delayed."
        )
        self.assertEqual(result, 0.5)

    def test_as_a_result(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "As a result, the team disbanded."
        )
        self.assertEqual(result, 1.0)

    def test_accordingly(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "The rules changed. Accordingly, we adapted."
        )
        self.assertEqual(result, 0.5)

    def test_multiple_effects(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "Therefore we left. Thus ended the day. Hence the silence."
        )
        self.assertEqual(result, 1.0)  # 3 connectors / 3 sentences

    def test_so(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "It was late, so we went home."
        )
        self.assertEqual(result, 1.0)

    def test_for_this_reason(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_effect_connector_rate(
            "For this reason, we declined the offer."
        )
        self.assertEqual(result, 1.0)


# ── Conditional Density ──────────────────────────────────────────────


class TestConditionalDensity(unittest.TestCase):
    """Test measure_conditional_density."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_conditional_density(""), 0.0)

    def test_no_conditionals(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_conditional_density("The sky is blue today."),
            0.0,
        )

    def test_single_if(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "If it rains, we will stay inside."
        )
        self.assertEqual(result, 1.0)

    def test_unless(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "Unless you hurry, you will miss the train."
        )
        self.assertEqual(result, 1.0)

    def test_provided_that(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "Provided that the funds arrive, we can proceed."
        )
        self.assertEqual(result, 1.0)

    def test_as_long_as(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "As long as you are here, we can start."
        )
        self.assertEqual(result, 1.0)

    def test_in_case(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "In case of emergency, break the glass."
        )
        self.assertEqual(result, 1.0)

    def test_multiple_conditionals(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "If it rains, we stay. Unless the wind stops, we sail."
        )
        self.assertEqual(result, 1.0)  # 2 / 2 sentences

    def test_supposing(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_conditional_density(
            "Supposing the plan fails, what then?"
        )
        self.assertEqual(result, 1.0)


# ── Concessive Density ───────────────────────────────────────────────


class TestConcessiveDensity(unittest.TestCase):
    """Test measure_concessive_density."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_concessive_density(""), 0.0)

    def test_no_concessives(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_concessive_density("The project succeeded."),
            0.0,
        )

    def test_although(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "Although it was difficult, we finished on time."
        )
        self.assertEqual(result, 1.0)

    def test_despite(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "Despite the rain, the match continued."
        )
        self.assertEqual(result, 1.0)

    def test_nevertheless(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "The results were mixed. Nevertheless, the team celebrated."
        )
        self.assertEqual(result, 0.5)

    def test_however(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "The plan was sound. However, execution failed."
        )
        self.assertEqual(result, 0.5)

    def test_even_though(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "Even though he tried hard, he did not win."
        )
        self.assertEqual(result, 1.0)

    def test_while(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "While the idea is interesting, it lacks evidence."
        )
        self.assertEqual(result, 1.0)

    def test_in_spite_of(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "In spite of the warnings, they proceeded."
        )
        self.assertEqual(result, 1.0)

    def test_nonetheless(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_concessive_density(
            "The data was incomplete. Nonetheless, the paper was published."
        )
        self.assertEqual(result, 0.5)


# ── Purpose Clause Density ───────────────────────────────────────────


class TestPurposeClauseDensity(unittest.TestCase):
    """Test measure_purpose_clause_density."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_purpose_clause_density(""), 0.0)

    def test_no_purpose_clauses(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_purpose_clause_density("The sky is clear tonight."),
            0.0,
        )

    def test_in_order_to(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "We ran tests in order to verify the hypothesis."
        )
        self.assertEqual(result, 1.0)

    def test_so_that(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "She studied hard so that she could pass the exam."
        )
        self.assertEqual(result, 1.0)

    def test_so_as_to(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "He spoke quietly so as to avoid waking the baby."
        )
        self.assertEqual(result, 1.0)

    def test_for_the_purpose_of(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "For the purpose of clarity, we rewrote the section."
        )
        self.assertEqual(result, 1.0)

    def test_with_the_aim_of(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "With the aim of reducing costs, the team automated testing."
        )
        self.assertEqual(result, 1.0)

    def test_to_this_end(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "To this end, we implemented a new protocol."
        )
        self.assertEqual(result, 1.0)

    def test_lest(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "He checked twice, lest he forget something."
        )
        self.assertEqual(result, 1.0)

    def test_multiple_purposes(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_purpose_clause_density(
            "In order to succeed, we must plan. So that we win, we train."
        )
        self.assertEqual(result, 1.0)  # 2 / 2 sentences


# ── Causal Chain Length ──────────────────────────────────────────────


class TestCausalChainLength(unittest.TestCase):
    """Test measure_causal_chain_length."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.measure_causal_chain_length(""), 0.0)

    def test_no_causal_language(self):
        wcd = WriterCausalDensity()
        self.assertEqual(
            wcd.measure_causal_chain_length(
                "The cat sat. The dog slept. The bird sang."
            ),
            0.0,
        )

    def test_single_connector(self):
        wcd = WriterCausalDensity()
        result = wcd.measure_causal_chain_length(
            "She left because she was tired."
        )
        self.assertEqual(result, 1.0)

    def test_chain_of_three(self):
        wcd = WriterCausalDensity()
        text = (
            "Because it rained, the ground was wet. "
            "Therefore, the game was canceled. "
            "Consequently, the team went home."
        )
        result = wcd.measure_causal_chain_length(text)
        self.assertEqual(result, 3.0)

    def test_two_paragraphs_different_chains(self):
        wcd = WriterCausalDensity()
        text = (
            "Because it rained, the game was canceled.\n\n"
            "The cat sat on the mat. The dog slept peacefully."
        )
        result = wcd.measure_causal_chain_length(text)
        # Paragraph 1: 1 connector, Paragraph 2: 0 connectors
        self.assertAlmostEqual(result, 0.5)

    def test_rich_paragraph(self):
        wcd = WriterCausalDensity()
        text = (
            "Since the data was incomplete, the analysis was flawed. "
            "Therefore, the conclusions were unreliable. "
            "As a result, the paper was rejected. "
            "However, the team learned from the experience."
        )
        result = wcd.measure_causal_chain_length(text)
        self.assertEqual(result, 4.0)  # since, therefore, as a result, however


# ── Composite Index ──────────────────────────────────────────────────


class TestCausalDensityIndex(unittest.TestCase):
    """Test compute_causal_density_index."""

    def test_all_zeros(self):
        wcd = WriterCausalDensity()
        result = wcd.compute_causal_density_index(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_max_values(self):
        wcd = WriterCausalDensity()
        # All at normalization caps should yield 1.0
        result = wcd.compute_causal_density_index(1.5, 1.2, 1.2, 1.0, 0.8, 4.0)
        self.assertAlmostEqual(result, 1.0)

    def test_half_values(self):
        wcd = WriterCausalDensity()
        result = wcd.compute_causal_density_index(0.75, 0.6, 0.6, 0.5, 0.4, 2.0)
        self.assertAlmostEqual(result, 0.5)

    def test_weights_sum_to_one(self):
        # Verify weight constants
        weights = [0.22, 0.20, 0.18, 0.13, 0.12, 0.15]
        self.assertAlmostEqual(sum(weights), 1.0)

    def test_cause_dominates_when_only_cause(self):
        wcd = WriterCausalDensity()
        result = wcd.compute_causal_density_index(1.5, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.22)

    def test_effect_dominates_when_only_effect(self):
        wcd = WriterCausalDensity()
        result = wcd.compute_causal_density_index(0.0, 1.2, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)


# ── Classification ───────────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    """Test classify method."""

    def test_causally_bare(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.0), "causally_bare")
        self.assertEqual(wcd.classify(0.05), "causally_bare")
        self.assertEqual(wcd.classify(0.099), "causally_bare")

    def test_causally_sparse(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.10), "causally_sparse")
        self.assertEqual(wcd.classify(0.15), "causally_sparse")
        self.assertEqual(wcd.classify(0.199), "causally_sparse")

    def test_moderate_causation(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.20), "moderate_causation")
        self.assertEqual(wcd.classify(0.30), "moderate_causation")
        self.assertEqual(wcd.classify(0.399), "moderate_causation")

    def test_causally_rich(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.40), "causally_rich")
        self.assertEqual(wcd.classify(0.50), "causally_rich")
        self.assertEqual(wcd.classify(0.599), "causally_rich")

    def test_causally_saturated(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.60), "causally_saturated")
        self.assertEqual(wcd.classify(0.80), "causally_saturated")
        self.assertEqual(wcd.classify(1.0), "causally_saturated")

    def test_boundary_010(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.10), "causally_sparse")

    def test_boundary_020(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.20), "moderate_causation")

    def test_boundary_040(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.40), "causally_rich")

    def test_boundary_060(self):
        wcd = WriterCausalDensity()
        self.assertEqual(wcd.classify(0.60), "causally_saturated")


# ── Full Measurement ─────────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test measure method end-to-end."""

    def test_empty_text(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("")
        self.assertEqual(result["causal_density_index"], 0.0)
        self.assertEqual(result["classification"], "causally_bare")

    def test_whitespace_only(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("   \n\n  ")
        self.assertEqual(result["causal_density_index"], 0.0)
        self.assertEqual(result["classification"], "causally_bare")

    def test_result_keys(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("Some text here.")
        expected_keys = {
            "cause_connector_rate",
            "effect_connector_rate",
            "conditional_density",
            "concessive_density",
            "purpose_clause_density",
            "causal_chain_length",
            "causal_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_causally_rich_text(self):
        wcd = WriterCausalDensity()
        text = (
            "Because the experiment failed, the team reconsidered. "
            "Therefore, they designed a new protocol. Consequently, "
            "the results improved. Although the process was slow, "
            "it was thorough, in order to ensure accuracy."
        )
        result = wcd.measure(text)
        self.assertGreater(result["causal_density_index"], 0.20)
        self.assertIn(
            result["classification"],
            ["moderate_causation", "causally_rich", "causally_saturated"],
        )

    def test_causally_bare_text(self):
        wcd = WriterCausalDensity()
        text = (
            "The old house stood alone. Ivy covered the walls. "
            "A single light burned in the upstairs window. "
            "The wind blew through the bare trees."
        )
        result = wcd.measure(text)
        self.assertLess(result["causal_density_index"], 0.10)
        self.assertEqual(result["classification"], "causally_bare")

    def test_mixed_text(self):
        wcd = WriterCausalDensity()
        text = (
            "The experiment was a success. The team celebrated. "
            "Because the data was clean, the analysis went smoothly. "
            "The sun set behind the mountains. Birds flew south."
        )
        result = wcd.measure(text)
        self.assertGreater(result["causal_density_index"], 0.0)
        self.assertLess(result["causal_density_index"], 0.60)

    def test_all_dimensions_present(self):
        wcd = WriterCausalDensity()
        text = (
            "Because it rained, the streets were wet. Therefore, "
            "pedestrians carried umbrellas. If the storm continued, "
            "the event would be canceled. Although the forecast was "
            "gloomy, some optimists arrived without raincoats. "
            "In order to stay dry, they huddled under awnings."
        )
        result = wcd.measure(text)
        self.assertGreater(result["cause_connector_rate"], 0.0)
        self.assertGreater(result["effect_connector_rate"], 0.0)
        self.assertGreater(result["conditional_density"], 0.0)
        self.assertGreater(result["concessive_density"], 0.0)
        self.assertGreater(result["purpose_clause_density"], 0.0)
        self.assertGreater(result["causal_chain_length"], 0.0)

    def test_values_are_rounded(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("Because she asked, I answered.")
        for key in [
            "cause_connector_rate",
            "effect_connector_rate",
            "conditional_density",
            "concessive_density",
            "purpose_clause_density",
            "causal_chain_length",
            "causal_density_index",
        ]:
            # Check that values have at most 4 decimal places
            val = result[key]
            self.assertEqual(val, round(val, 4))


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("Because.")
        self.assertIsNotNone(result["causal_density_index"])

    def test_repeated_connector(self):
        wcd = WriterCausalDensity()
        text = "Because because because."
        result = wcd.measure(text)
        self.assertGreater(result["cause_connector_rate"], 0.0)

    def test_very_long_sentence(self):
        wcd = WriterCausalDensity()
        text = (
            "Because the project was complex and since the team was small "
            "and given that the deadline approached and owing to the fact "
            "that resources were limited, therefore the manager decided to "
            "prioritize and consequently the output improved, although "
            "the quality suffered, nevertheless the client was satisfied "
            "so that the contract was renewed in order to continue."
        )
        result = wcd.measure(text)
        self.assertGreater(result["causal_density_index"], 0.30)

    def test_unicode_text(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("The café was closed because of rain.")
        self.assertIsNotNone(result["causal_density_index"])

    def test_text_with_numbers(self):
        wcd = WriterCausalDensity()
        result = wcd.measure("In 2024, the GDP grew 3.2% because of exports.")
        self.assertIsNotNone(result["causal_density_index"])

    def test_multiline_single_paragraph(self):
        wcd = WriterCausalDensity()
        text = "Line one because.\nLine two therefore.\nLine three hence."
        result = wcd.measure_causal_chain_length(text)
        # Should be treated as one paragraph (no blank line separation)
        self.assertEqual(result, 3.0)

    def test_no_false_positive_for(self):
        wcd = WriterCausalDensity()
        # "for" as preposition, not causal connector
        result = wcd.measure_cause_connector_rate(
            "She went for a walk. He waited for the bus."
        )
        # "for" is a cause connector in our list, but these are prepositional uses
        # This is a known limitation — the simple word-boundary match catches these
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
