#!/usr/bin/env python3
"""Tests for writer_transitions — 102 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_transitions import (  # noqa: E402
    FUNCTION_WORDS,
    LOGICAL_CONNECTORS,
    TEMPORAL_MARKERS,
    TRANSITIONAL_WORDS,
    _content_words,
    _multiword_match,
    _singleword_match,
    _split_paragraphs,
    _split_sentences,
    _words,
    analyze_transitions,
    classify_transitions,
    compute_logical_connector_density,
    compute_paragraph_transition_density,
    compute_semantic_bridge_ratio,
    compute_temporal_sequence_rate,
    compute_transition_index,
    compute_transition_metrics,
    compute_transitional_word_rate,
    format_transition_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_none_input(self):
        self.assertEqual(_split_sentences(None), [])

    def test_non_string_input(self):
        self.assertEqual(_split_sentences(42), [])

    def test_single_sentence(self):
        result = _split_sentences("The cat sat on the mat.")
        self.assertEqual(len(result), 1)
        self.assertIn("cat", result[0])

    def test_multiple_sentences(self):
        text = "The cat sat. The dog ran. The bird flew."
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_exclamation_marks(self):
        text = "Stop! Wait! Help!"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        text = "Why? How? When?"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   \n\t  "), [])

    def test_no_terminal_punctuation(self):
        result = _split_sentences("one sentence no period")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Helper: _split_paragraphs
# ---------------------------------------------------------------------------

class TestSplitParagraphs(unittest.TestCase):
    """Test _split_paragraphs helper."""

    def test_empty(self):
        self.assertEqual(_split_paragraphs(""), [])

    def test_none(self):
        self.assertEqual(_split_paragraphs(None), [])

    def test_single_paragraph(self):
        result = _split_paragraphs("Just one paragraph here.")
        self.assertEqual(len(result), 1)

    def test_two_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 2)

    def test_multiple_paragraphs(self):
        text = "A.\n\nB.\n\nC."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 3)

    def test_extra_whitespace_between_paragraphs(self):
        text = "A.\n\n   \n\nB."
        result = _split_paragraphs(text)
        # Should collapse to 2 non-empty paragraphs
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# Helper: _words and _content_words
# ---------------------------------------------------------------------------

class TestWords(unittest.TestCase):
    """Test _words helper."""

    def test_basic(self):
        result = _words("Hello World")
        self.assertEqual(result, ["hello", "world"])

    def test_with_punctuation(self):
        result = _words("It's a test, really.")
        self.assertIn("it's", result)
        self.assertIn("test", result)

    def test_empty(self):
        self.assertEqual(_words(""), [])


class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_excludes_function_words(self):
        result = _content_words("the cat is on the mat")
        self.assertNotIn("the", result)
        self.assertNotIn("is", result)
        self.assertNotIn("on", result)
        self.assertIn("cat", result)
        self.assertIn("mat", result)

    def test_excludes_single_char(self):
        result = _content_words("I a cat")
        self.assertNotIn("i", result)
        self.assertNotIn("a", result)
        self.assertIn("cat", result)

    def test_empty(self):
        self.assertEqual(_content_words(""), set())


# ---------------------------------------------------------------------------
# Helper: _multiword_match and _singleword_match
# ---------------------------------------------------------------------------

class TestMultiwordMatch(unittest.TestCase):
    """Test _multiword_match helper."""

    def test_finds_phrase(self):
        count = _multiword_match("for example this is good", TRANSITIONAL_WORDS)
        self.assertGreater(count, 0)

    def test_no_match(self):
        count = _multiword_match("just some random text", TRANSITIONAL_WORDS)
        self.assertEqual(count, 0)

    def test_single_words_ignored(self):
        count = _multiword_match("however this works", frozenset({"in addition"}))
        self.assertEqual(count, 0)


class TestSinglewordMatch(unittest.TestCase):
    """Test _singleword_match helper."""

    def test_finds_word_in_window(self):
        words = ["however", "the", "cat", "sat"]
        count = _singleword_match(words, frozenset({"however"}))
        self.assertEqual(count, 1)

    def test_ignores_multiword_phrases(self):
        words = ["for", "example", "the"]
        count = _singleword_match(words, frozenset({"for example"}))
        self.assertEqual(count, 0)

    def test_word_outside_window(self):
        words = ["a"] * 10 + ["however"]
        count = _singleword_match(words, frozenset({"however"}))
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# Metric: transitional_word_rate
# ---------------------------------------------------------------------------

class TestTransitionalWordRate(unittest.TestCase):
    """Test compute_transitional_word_rate."""

    def test_empty(self):
        self.assertEqual(compute_transitional_word_rate(""), 0.0)

    def test_none(self):
        self.assertEqual(compute_transitional_word_rate(None), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_transitional_word_rate("One sentence only."), 0.0)

    def test_all_transitioned(self):
        text = "First idea. However, the second idea. Moreover, the third idea. Therefore, the conclusion."
        rate = compute_transitional_word_rate(text)
        self.assertGreater(rate, 0.5)

    def test_no_transitions(self):
        text = "The cat sat. The dog ran. The bird flew. The fish swam."
        rate = compute_transitional_word_rate(text)
        self.assertEqual(rate, 0.0)

    def test_some_transitions(self):
        text = "The cat sat. However, the dog ran. The bird flew. Therefore, the fish swam."
        rate = compute_transitional_word_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_multiword_transition(self):
        text = "The experiment failed. As a result, we redesigned the protocol."
        rate = compute_transitional_word_rate(text)
        self.assertGreater(rate, 0.0)

    def test_adversative_transition(self):
        text = "We expected success. Nevertheless, the results were disappointing."
        rate = compute_transitional_word_rate(text)
        self.assertGreater(rate, 0.0)


# ---------------------------------------------------------------------------
# Metric: logical_connector_density
# ---------------------------------------------------------------------------

class TestLogicalConnectorDensity(unittest.TestCase):
    """Test compute_logical_connector_density."""

    def test_empty(self):
        self.assertEqual(compute_logical_connector_density(""), 0.0)

    def test_none(self):
        self.assertEqual(compute_logical_connector_density(None), 0.0)

    def test_all_connected(self):
        text = "Because it rained, we stayed home. Although tired, she continued. Since the data was clear, we published."
        density = compute_logical_connector_density(text)
        self.assertEqual(density, 1.0)

    def test_no_connectors(self):
        text = "The sun set. Stars appeared. The moon rose."
        density = compute_logical_connector_density(text)
        self.assertEqual(density, 0.0)

    def test_causal(self):
        text = "We cancelled the picnic because it rained."
        density = compute_logical_connector_density(text)
        self.assertGreater(density, 0.0)

    def test_concessive(self):
        text = "Although the sample was small, the results were significant."
        density = compute_logical_connector_density(text)
        self.assertGreater(density, 0.0)

    def test_conditional(self):
        text = "If the temperature drops, the reaction will slow."
        density = compute_logical_connector_density(text)
        self.assertGreater(density, 0.0)

    def test_multiword_connector(self):
        text = "We proceeded in order to complete the experiment on time."
        density = compute_logical_connector_density(text)
        self.assertGreater(density, 0.0)

    def test_mixed(self):
        text = "Because it rained, we stayed inside. The sun came out. Although tired, she ran."
        density = compute_logical_connector_density(text)
        self.assertGreater(density, 0.0)
        self.assertLess(density, 1.0)


# ---------------------------------------------------------------------------
# Metric: semantic_bridge_ratio
# ---------------------------------------------------------------------------

class TestSemanticBridgeRatio(unittest.TestCase):
    """Test compute_semantic_bridge_ratio."""

    def test_empty(self):
        self.assertEqual(compute_semantic_bridge_ratio(""), 0.0)

    def test_none(self):
        self.assertEqual(compute_semantic_bridge_ratio(None), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_semantic_bridge_ratio("One sentence."), 0.0)

    def test_all_bridged(self):
        text = "The algorithm processes data efficiently. This data structure optimizes the algorithm further. The optimized algorithm runs faster."
        ratio = compute_semantic_bridge_ratio(text)
        self.assertEqual(ratio, 1.0)

    def test_no_bridges(self):
        text = "The cat sat on the mat. Quantum physics explains subatomic behavior. Bananas grow in tropical climates."
        ratio = compute_semantic_bridge_ratio(text)
        self.assertEqual(ratio, 0.0)

    def test_partial_bridges(self):
        text = "The algorithm processes data efficiently. The algorithm was then optimized. Bananas grow in tropical climates."
        ratio = compute_semantic_bridge_ratio(text)
        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 1.0)

    def test_function_words_excluded(self):
        text = "The cat is happy. The dog is hungry."
        ratio = compute_semantic_bridge_ratio(text)
        # "cat" and "dog" are different content words; "the/is" are function words
        self.assertEqual(ratio, 0.0)

    def test_shared_content_word(self):
        text = "The research team published findings. The findings surprised everyone."
        ratio = compute_semantic_bridge_ratio(text)
        self.assertGreater(ratio, 0.0)


# ---------------------------------------------------------------------------
# Metric: temporal_sequence_rate
# ---------------------------------------------------------------------------

class TestTemporalSequenceRate(unittest.TestCase):
    """Test compute_temporal_sequence_rate."""

    def test_empty(self):
        self.assertEqual(compute_temporal_sequence_rate(""), 0.0)

    def test_none(self):
        self.assertEqual(compute_temporal_sequence_rate(None), 0.0)

    def test_all_temporal(self):
        text = "First we gathered data. Then we analyzed results. After that, we wrote the report. Meanwhile, the team reviewed."
        rate = compute_temporal_sequence_rate(text)
        self.assertGreater(rate, 0.5)

    def test_no_temporal(self):
        text = "The sky is blue. Grass is green. Water is wet."
        rate = compute_temporal_sequence_rate(text)
        self.assertEqual(rate, 0.0)

    def test_some_temporal(self):
        text = "The experiment began. Then the temperature rose. The data was collected. Afterward, we analyzed."
        rate = compute_temporal_sequence_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_multiword_temporal(self):
        text = "The meeting started. In the meantime, the team prepared."
        rate = compute_temporal_sequence_rate(text)
        self.assertGreater(rate, 0.0)

    def test_single_temporal_word(self):
        text = "Previously, this was not possible. Now it works."
        rate = compute_temporal_sequence_rate(text)
        self.assertGreater(rate, 0.0)


# ---------------------------------------------------------------------------
# Metric: paragraph_transition_density
# ---------------------------------------------------------------------------

class TestParagraphTransitionDensity(unittest.TestCase):
    """Test compute_paragraph_transition_density."""

    def test_empty(self):
        self.assertEqual(compute_paragraph_transition_density(""), 0.0)

    def test_none(self):
        self.assertEqual(compute_paragraph_transition_density(None), 0.0)

    def test_single_paragraph(self):
        self.assertEqual(compute_paragraph_transition_density("Just one paragraph."), 0.0)

    def test_transitioned_break(self):
        text = "The experiment showed promising results.\n\nHowever, further testing is needed before deployment."
        density = compute_paragraph_transition_density(text)
        self.assertGreater(density, 0.0)

    def test_shared_content_word_transition(self):
        text = "The algorithm processes data in linear time.\n\nThe algorithm was tested on large datasets."
        density = compute_paragraph_transition_density(text)
        self.assertGreater(density, 0.0)

    def test_demonstrative_transition(self):
        text = "The team discovered a new approach to optimization.\n\nThis approach reduced processing time significantly."
        density = compute_paragraph_transition_density(text)
        self.assertGreater(density, 0.0)

    def test_no_transition(self):
        text = "Cats are independent animals.\n\nQuantum physics describes subatomic behavior."
        density = compute_paragraph_transition_density(text)
        self.assertEqual(density, 0.0)

    def test_logical_connector_transition(self):
        text = "The results were inconclusive.\n\nBecause the sample was too small, we need more data."
        density = compute_paragraph_transition_density(text)
        self.assertGreater(density, 0.0)

    def test_multiple_paragraphs_mixed(self):
        text = "The initial study examined algorithms.\n\nHowever, the findings required further validation.\n\nCats sleep eighteen hours daily."
        density = compute_paragraph_transition_density(text)
        self.assertGreater(density, 0.0)
        self.assertLess(density, 1.0)


# ---------------------------------------------------------------------------
# Composite: transition_index
# ---------------------------------------------------------------------------

class TestTransitionIndex(unittest.TestCase):
    """Test compute_transition_index."""

    def test_all_zeros(self):
        metrics = {
            "transitional_word_rate": 0.0,
            "logical_connector_density": 0.0,
            "semantic_bridge_ratio": 0.0,
            "temporal_sequence_rate": 0.0,
            "paragraph_transition_density": 0.0,
        }
        self.assertEqual(compute_transition_index(metrics), 0.0)

    def test_all_ones(self):
        metrics = {
            "transitional_word_rate": 1.0,
            "logical_connector_density": 1.0,
            "semantic_bridge_ratio": 1.0,
            "temporal_sequence_rate": 1.0,
            "paragraph_transition_density": 1.0,
        }
        self.assertEqual(compute_transition_index(metrics), 1.0)

    def test_partial(self):
        metrics = {
            "transitional_word_rate": 0.5,
            "logical_connector_density": 0.5,
            "semantic_bridge_ratio": 0.5,
            "temporal_sequence_rate": 0.5,
            "paragraph_transition_density": 0.5,
        }
        index = compute_transition_index(metrics)
        self.assertAlmostEqual(index, 0.5, places=2)

    def test_weights_applied(self):
        # Only paragraph_transition_density = 1.0 (weight 0.30)
        metrics = {
            "transitional_word_rate": 0.0,
            "logical_connector_density": 0.0,
            "semantic_bridge_ratio": 0.0,
            "temporal_sequence_rate": 0.0,
            "paragraph_transition_density": 1.0,
        }
        index = compute_transition_index(metrics)
        self.assertAlmostEqual(index, 0.30, places=2)

    def test_missing_key_defaults_zero(self):
        metrics = {"transitional_word_rate": 1.0}
        index = compute_transition_index(metrics)
        self.assertAlmostEqual(index, 0.20, places=2)

    def test_returns_rounded(self):
        metrics = {
            "transitional_word_rate": 0.333333,
            "logical_connector_density": 0.333333,
            "semantic_bridge_ratio": 0.333333,
            "temporal_sequence_rate": 0.333333,
            "paragraph_transition_density": 0.333333,
        }
        index = compute_transition_index(metrics)
        # Should be rounded to 4 decimal places
        self.assertEqual(str(index), str(round(index, 4)))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassifyTransitions(unittest.TestCase):
    """Test classify_transitions."""

    def test_seamless(self):
        self.assertEqual(classify_transitions(0.75), "seamless")
        self.assertEqual(classify_transitions(0.90), "seamless")
        self.assertEqual(classify_transitions(1.00), "seamless")

    def test_smooth(self):
        self.assertEqual(classify_transitions(0.55), "smooth")
        self.assertEqual(classify_transitions(0.70), "smooth")
        self.assertEqual(classify_transitions(0.74), "smooth")

    def test_adequate(self):
        self.assertEqual(classify_transitions(0.35), "adequate")
        self.assertEqual(classify_transitions(0.50), "adequate")
        self.assertEqual(classify_transitions(0.54), "adequate")

    def test_choppy(self):
        self.assertEqual(classify_transitions(0.20), "choppy")
        self.assertEqual(classify_transitions(0.30), "choppy")
        self.assertEqual(classify_transitions(0.34), "choppy")

    def test_disjointed(self):
        self.assertEqual(classify_transitions(0.00), "disjointed")
        self.assertEqual(classify_transitions(0.10), "disjointed")
        self.assertEqual(classify_transitions(0.19), "disjointed")

    def test_boundary_values(self):
        # Exact boundary values
        self.assertEqual(classify_transitions(0.75), "seamless")
        self.assertEqual(classify_transitions(0.55), "smooth")
        self.assertEqual(classify_transitions(0.35), "adequate")
        self.assertEqual(classify_transitions(0.20), "choppy")
        self.assertEqual(classify_transitions(0.199999), "disjointed")


# ---------------------------------------------------------------------------
# Pipeline: analyze_transitions
# ---------------------------------------------------------------------------

class TestAnalyzeTransitions(unittest.TestCase):
    """Test analyze_transitions pipeline."""

    def test_empty(self):
        result = analyze_transitions("")
        self.assertEqual(result["transition_index"], 0.0)
        self.assertEqual(result["transition_class"], "disjointed")
        self.assertEqual(result["sentence_count"], 0)
        self.assertEqual(result["paragraph_count"], 0)

    def test_well_transitioned_text(self):
        text = (
            "The research team began their investigation.\n\n"
            "However, the initial results were inconclusive. "
            "Because the sample size was small, the team decided to "
            "expand the study. Therefore, they recruited additional "
            "participants.\n\n"
            "As a result, the expanded study produced clearer findings. "
            "The findings suggested a strong correlation."
        )
        result = analyze_transitions(text)
        self.assertIn("metrics", result)
        self.assertIn("transition_index", result)
        self.assertIn("transition_class", result)
        self.assertGreater(result["transition_index"], 0.0)
        self.assertEqual(result["paragraph_count"], 3)

    def test_poorly_transitioned_text(self):
        text = "Cats sleep. Quantum physics. Bananas grow."
        result = analyze_transitions(text)
        self.assertEqual(result["transition_class"], "disjointed")

    def test_returns_all_keys(self):
        result = analyze_transitions("A simple sentence.")
        expected_keys = {"metrics", "transition_index", "transition_class",
                         "sentence_count", "paragraph_count"}
        self.assertEqual(set(result.keys()), expected_keys)

    def test_metrics_keys(self):
        result = analyze_transitions("A simple sentence.")
        expected_metric_keys = {
            "transitional_word_rate",
            "logical_connector_density",
            "semantic_bridge_ratio",
            "temporal_sequence_rate",
            "paragraph_transition_density",
        }
        self.assertEqual(set(result["metrics"].keys()), expected_metric_keys)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormatTransitionReport(unittest.TestCase):
    """Test format_transition_report."""

    def test_empty_analysis(self):
        analysis = analyze_transitions("")
        report = format_transition_report(analysis)
        self.assertIn("disjointed", report)
        self.assertIn("0 sentences", report)

    def test_report_contains_all_metrics(self):
        text = "First sentence. However, the second sentence. Therefore, the third."
        analysis = analyze_transitions(text)
        report = format_transition_report(analysis)
        self.assertIn("Transitional word rate", report)
        self.assertIn("Logical connector density", report)
        self.assertIn("Semantic bridge ratio", report)
        self.assertIn("Temporal sequence rate", report)
        self.assertIn("Paragraph transition density", report)

    def test_report_contains_class(self):
        text = "First sentence. However, the second sentence."
        analysis = analyze_transitions(text)
        report = format_transition_report(analysis)
        self.assertIn(analysis["transition_class"], report)

    def test_report_contains_counts(self):
        text = "First.\n\nSecond. Third."
        analysis = analyze_transitions(text)
        report = format_transition_report(analysis)
        self.assertIn("sentences", report)
        self.assertIn("paragraphs", report)


# ---------------------------------------------------------------------------
# Constants validation
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """Validate constant sets."""

    def test_transitional_words_not_empty(self):
        self.assertGreater(len(TRANSITIONAL_WORDS), 0)

    def test_logical_connectors_not_empty(self):
        self.assertGreater(len(LOGICAL_CONNECTORS), 0)

    def test_temporal_markers_not_empty(self):
        self.assertGreater(len(TEMPORAL_MARKERS), 0)

    def test_function_words_not_empty(self):
        self.assertGreater(len(FUNCTION_WORDS), 0)

    def test_transitional_words_lowercase(self):
        for word in TRANSITIONAL_WORDS:
            self.assertEqual(word, word.lower(), f"{word} not lowercase")

    def test_logical_connectors_lowercase(self):
        for word in LOGICAL_CONNECTORS:
            self.assertEqual(word, word.lower(), f"{word} not lowercase")

    def test_temporal_markers_lowercase(self):
        for word in TEMPORAL_MARKERS:
            self.assertEqual(word, word.lower(), f"{word} not lowercase")

    def test_common_transitions_present(self):
        for w in ["however", "therefore", "moreover", "furthermore"]:
            self.assertIn(w, TRANSITIONAL_WORDS)

    def test_common_connectors_present(self):
        for w in ["because", "although", "since", "unless"]:
            self.assertIn(w, LOGICAL_CONNECTORS)

    def test_common_temporal_present(self):
        for w in ["before", "after", "then", "meanwhile"]:
            self.assertIn(w, TEMPORAL_MARKERS)


# ---------------------------------------------------------------------------
# Integration / end-to-end
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end integration tests."""

    def test_narrative_prose(self):
        text = (
            "The team arrived at the laboratory early. First, they "
            "calibrated the instruments. Then they ran the initial "
            "tests. However, the results were unexpected.\n\n"
            "Because the data showed anomalous patterns, the team "
            "decided to investigate further. The investigation revealed "
            "a systematic error. Therefore, they recalibrated and "
            "repeated the experiment.\n\n"
            "Subsequently, the corrected results confirmed the original "
            "hypothesis. The hypothesis, which had seemed doubtful, "
            "was now validated."
        )
        result = analyze_transitions(text)
        self.assertGreater(result["transition_index"], 0.20)
        self.assertIn(result["transition_class"],
                       {"seamless", "smooth", "adequate"})

    def test_choppy_prose(self):
        text = "Dogs bark. Trees grow. Fish swim. Clouds form. Rain falls."
        result = analyze_transitions(text)
        self.assertLessEqual(result["transition_index"], 0.25)
        self.assertIn(result["transition_class"], {"disjointed", "choppy"})

    def test_scientific_prose(self):
        text = (
            "The experiment tested the effect of temperature on reaction rate. "
            "Because higher temperatures increase molecular collisions, the "
            "expected outcome was faster reactions. However, the results "
            "showed a plateau above 80 degrees.\n\n"
            "This plateau suggested enzyme denaturation. Although the "
            "substrate concentration remained constant, the enzyme lost "
            "its catalytic activity. Therefore, the optimal temperature "
            "was identified as 75 degrees."
        )
        result = analyze_transitions(text)
        self.assertGreater(result["transition_index"], 0.30)

    def test_single_long_paragraph(self):
        text = (
            "The project began in January. First, the team outlined requirements. "
            "Then they designed the architecture. After that, implementation "
            "started. However, midway through development, the client changed "
            "the specifications. Consequently, the team had to refactor "
            "significant portions. Despite the setback, the project shipped "
            "on time."
        )
        result = analyze_transitions(text)
        self.assertGreater(result["metrics"]["transitional_word_rate"], 0.0)
        self.assertGreater(result["metrics"]["temporal_sequence_rate"], 0.0)

    def test_repeated_content_creates_bridges(self):
        text = (
            "The compiler optimizes loops. The optimizer uses SSA form. "
            "SSA form enables constant propagation. Constant propagation "
            "reduces redundant computations."
        )
        result = analyze_transitions(text)
        self.assertGreater(result["metrics"]["semantic_bridge_ratio"], 0.5)

    def test_report_format_stability(self):
        """Ensure report has predictable number of lines."""
        text = "A sentence. However, another sentence."
        analysis = analyze_transitions(text)
        report = format_transition_report(analysis)
        lines = report.strip().split("\n")
        self.assertEqual(len(lines), 7)  # header + 5 metrics + counts


if __name__ == "__main__":
    unittest.main()
