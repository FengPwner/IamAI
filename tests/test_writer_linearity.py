#!/usr/bin/env python3
"""Tests for writer_linearity — 88 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_linearity import (  # noqa: E402
    BACK_REFERENCE_PATTERNS,
    CAUSAL_CONNECTIVES,
    FUNCTION_WORDS,
    TEMPORAL_CONNECTIVES,
    _content_words,
    _split_paragraphs,
    _split_sentences,
    _word_overlap,
    analyze_linearity,
    classify_linearity,
    compute_back_reference_density,
    compute_forward_build_ratio,
    compute_idea_recursion_rate,
    compute_linearity_index,
    compute_linearity_metrics,
    compute_paragraph_drift_rate,
    compute_rephrasing_loop_rate,
    format_linearity_report,
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

    def test_exclamation_and_question(self):
        text = "What happened? The dog ran! It was amazing."
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_abbreviation_handling(self):
        text = "Dr. Smith arrived. He was early."
        result = _split_sentences(text)
        self.assertEqual(len(result), 2)

    def test_short_fragments_excluded(self):
        text = "This is a long sentence that should be included. Hi."
        result = _split_sentences(text)
        # "Hi." is too short (≤5 chars), should be excluded
        self.assertEqual(len(result), 1)

    def test_strip_whitespace(self):
        text = "  First sentence here.   Second sentence here.  "
        result = _split_sentences(text)
        for s in result:
            self.assertFalse(s.startswith(" "))
            self.assertFalse(s.endswith(" "))


# ---------------------------------------------------------------------------
# Helper: _split_paragraphs
# ---------------------------------------------------------------------------

class TestSplitParagraphs(unittest.TestCase):
    """Test _split_paragraphs helper."""

    def test_empty_string(self):
        self.assertEqual(_split_paragraphs(""), [])

    def test_none_input(self):
        self.assertEqual(_split_paragraphs(None), [])

    def test_single_paragraph(self):
        result = _split_paragraphs("This is a paragraph with enough text to count.")
        self.assertEqual(len(result), 1)

    def test_multiple_paragraphs(self):
        text = "First paragraph with content.\n\nSecond paragraph with content."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 2)

    def test_short_paragraph_excluded(self):
        text = "This is a long paragraph.\n\nShort.\n\nAnother long paragraph here."
        result = _split_paragraphs(text)
        self.assertEqual(len(result), 2)

    def test_strip_whitespace(self):
        text = "  First paragraph here.  \n\n  Second paragraph here.  "
        result = _split_paragraphs(text)
        for p in result:
            self.assertFalse(p.startswith("  "))
            self.assertFalse(p.endswith("  "))


# ---------------------------------------------------------------------------
# Helper: _content_words
# ---------------------------------------------------------------------------

class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_empty_string(self):
        self.assertEqual(_content_words(""), set())

    def test_function_words_excluded(self):
        result = _content_words("the cat is on the mat")
        self.assertNotIn("the", result)
        self.assertNotIn("is", result)
        self.assertNotIn("on", result)

    def test_content_words_included(self):
        result = _content_words("The algorithm processes data efficiently")
        self.assertIn("algorithm", result)
        self.assertIn("processes", result)
        self.assertIn("data", result)
        self.assertIn("efficiently", result)

    def test_short_words_excluded(self):
        result = _content_words("I am a big cat")
        # "am" is only 2 chars, excluded by length filter
        self.assertNotIn("am", result)
        # "big" is 3 chars but not a function word
        self.assertIn("big", result)

    def test_case_normalization(self):
        result = _content_words("Python PYTHON python")
        self.assertEqual(result, {"python"})

    def test_mixed_content(self):
        result = _content_words("The quick brown fox jumps over the lazy dog")
        self.assertIn("quick", result)
        self.assertIn("brown", result)
        self.assertIn("fox", result)
        self.assertIn("jumps", result)
        self.assertIn("lazy", result)
        self.assertIn("dog", result)
        self.assertNotIn("the", result)


# ---------------------------------------------------------------------------
# Helper: _word_overlap
# ---------------------------------------------------------------------------

class TestWordOverlap(unittest.TestCase):
    """Test _word_overlap (Jaccard similarity)."""

    def test_empty_sets(self):
        self.assertEqual(_word_overlap(set(), set()), 0.0)
        self.assertEqual(_word_overlap(set(), {"a"}), 0.0)
        self.assertEqual(_word_overlap({"a"}, set()), 0.0)

    def test_identical_sets(self):
        self.assertEqual(_word_overlap({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_sets(self):
        self.assertEqual(_word_overlap({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial_overlap(self):
        result = _word_overlap({"a", "b", "c"}, {"b", "c", "d"})
        self.assertAlmostEqual(result, 2 / 4, places=3)

    def test_subset(self):
        result = _word_overlap({"a"}, {"a", "b", "c"})
        self.assertAlmostEqual(result, 1 / 3, places=3)


# ---------------------------------------------------------------------------
# Core: compute_back_reference_density
# ---------------------------------------------------------------------------

class TestBackReferenceDensity(unittest.TestCase):
    """Test back-reference detection."""

    def test_empty_list(self):
        self.assertEqual(compute_back_reference_density([]), 0.0)

    def test_no_back_references(self):
        sentences = [
            "The algorithm processes data efficiently.",
            "New results show improved performance metrics.",
            "Further testing revealed additional optimization paths.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertEqual(result, 0.0)

    def test_in_other_words(self):
        sentences = [
            "The system uses caching for performance.",
            "In other words, it stores results for faster retrieval.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_that_is(self):
        sentences = [
            "We need an idempotent operation.",
            "That is, applying it multiple times produces the same result.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_ie_abbreviation(self):
        sentences = [
            "The function is monotonic.",
            "The output is i.e. always increasing or always decreasing.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_as_mentioned_above(self):
        sentences = [
            "The cache has a 100-item limit.",
            "As mentioned above, the limit prevents memory exhaustion.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_aforementioned(self):
        sentences = [
            "The deploy key was rotated last week.",
            "The aforementioned key is now expired.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_same_pattern(self):
        sentences = [
            "The error occurred during startup.",
            "This very same error blocked the previous release.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertGreater(result, 0.0)

    def test_all_back_references(self):
        sentences = [
            "In other words, the first approach failed.",
            "That is, we needed a different strategy.",
            "As noted before, timing was the issue.",
        ]
        result = compute_back_reference_density(sentences)
        self.assertEqual(result, 1.0)


# ---------------------------------------------------------------------------
# Core: compute_rephrasing_loop_rate
# ---------------------------------------------------------------------------

class TestRephrasingLoopRate(unittest.TestCase):
    """Test rephrasing loop detection."""

    def test_empty_list(self):
        self.assertEqual(compute_rephrasing_loop_rate([]), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_rephrasing_loop_rate(["Hello world."]), 0.0)

    def test_no_loops(self):
        sentences = [
            "The server started successfully.",
            "Database connections were established.",
            "Client requests began flowing through the system.",
        ]
        result = compute_rephrasing_loop_rate(sentences)
        self.assertEqual(result, 0.0)

    def test_obvious_rephrasing(self):
        sentences = [
            "The server handles incoming client requests efficiently.",
            "The server manages incoming client requests efficiently.",
        ]
        result = compute_rephrasing_loop_rate(sentences)
        # High overlap (server, handles/manages differ, incoming, client,
        # requests, efficiently shared), one word different → loop
        self.assertGreater(result, 0.0)

    def test_legitimate_progression(self):
        sentences = [
            "The server started up and loaded its configuration.",
            "Next it opened a connection to the database cluster.",
            "Then it began accepting requests from external clients.",
        ]
        result = compute_rephrasing_loop_rate(sentences)
        self.assertEqual(result, 0.0)


# ---------------------------------------------------------------------------
# Core: compute_idea_recursion_rate
# ---------------------------------------------------------------------------

class TestIdeaRecursionRate(unittest.TestCase):
    """Test idea recursion detection within paragraphs."""

    def test_empty_list(self):
        self.assertEqual(compute_idea_recursion_rate([]), 0.0)

    def test_short_paragraphs_skipped(self):
        paragraphs = ["Short. Hi."]
        result = compute_idea_recursion_rate(paragraphs)
        self.assertEqual(result, 0.0)

    def test_no_recursion(self):
        paragraphs = [
            "The server started up. It loaded configuration files. "
            "Then it connected to the database. Finally it began serving requests."
        ]
        result = compute_idea_recursion_rate(paragraphs)
        self.assertEqual(result, 0.0)

    def test_with_recursion(self):
        paragraphs = [
            "The server uses caching for performance improvement. "
            "Memory allocation happens during the initialization phase. "
            "Database indexing provides faster query response times. "
            "The server uses caching for performance improvement again."
        ]
        result = compute_idea_recursion_rate(paragraphs)
        # Sentence 4 echoes sentence 1 with intervening different content
        self.assertGreater(result, 0.0)


# ---------------------------------------------------------------------------
# Core: compute_forward_build_ratio
# ---------------------------------------------------------------------------

class TestForwardBuildRatio(unittest.TestCase):
    """Test forward build ratio."""

    def test_empty_list(self):
        self.assertEqual(compute_forward_build_ratio([]), 0.0)

    def test_all_forward(self):
        sentences = [
            "The server initializes its configuration module.",
            "Database connections require authentication tokens.",
            "External clients communicate through encrypted channels.",
        ]
        result = compute_forward_build_ratio(sentences)
        # Each sentence introduces new content words
        self.assertGreater(result, 0.9)

    def test_all_repetitive(self):
        sentences = [
            "The server processes incoming requests from clients.",
            "The server processes incoming requests from clients.",
            "The server processes incoming requests from clients.",
        ]
        result = compute_forward_build_ratio(sentences)
        # Exact duplicates introduce zero new words after sentence 1
        self.assertLess(result, 0.5)

    def test_single_sentence(self):
        sentences = ["The quick brown fox jumps over the lazy dog."]
        result = compute_forward_build_ratio(sentences)
        # First sentence always counts as building forward
        self.assertEqual(result, 1.0)

    def test_mixed_content(self):
        sentences = [
            "Python is a dynamically typed programming language.",
            "Python is a popular choice for web development.",
            "Ruby offers metaprogramming features through reflection.",
            "Ruby enables elegant domain specific language design.",
        ]
        result = compute_forward_build_ratio(sentences)
        # Some sentences build forward, some repeat
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)


# ---------------------------------------------------------------------------
# Core: compute_paragraph_drift_rate
# ---------------------------------------------------------------------------

class TestParagraphDriftRate(unittest.TestCase):
    """Test paragraph drift detection."""

    def test_empty_list(self):
        self.assertEqual(compute_paragraph_drift_rate([]), 0.0)

    def test_coherent_paragraph(self):
        paragraphs = [
            "The algorithm uses caching to store data. The cache stores frequently accessed data entries. "
            "Cached results expire after a configurable timeout period."
        ]
        result = compute_paragraph_drift_rate(paragraphs)
        # Sentences share content words and have logical connections
        self.assertLess(result, 0.6)

    def test_drifting_paragraph(self):
        paragraphs = [
            "Quantum computing uses entanglement for parallel processing. "
            "Butterfly migration patterns follow seasonal weather changes. "
            "Medieval architecture incorporated flying buttresses extensively."
        ]
        result = compute_paragraph_drift_rate(paragraphs)
        # Completely unrelated sentences with no connectives
        self.assertGreater(result, 0.0)

    def test_temporal_connective_prevents_drift(self):
        paragraphs = [
            "The server crashed during peak load yesterday. "
            "Then the monitoring system alerted the operations team. "
            "Next they scaled up the infrastructure capacity."
        ]
        result = compute_paragraph_drift_rate(paragraphs)
        # Temporal connectives bridge the topic shifts
        self.assertLess(result, 0.5)

    def test_causal_connective_prevents_drift(self):
        paragraphs = [
            "The database connection pool exhausted all available slots. "
            "Therefore the application began rejecting incoming requests. "
            "Because of the overload the load balancer triggered failover."
        ]
        result = compute_paragraph_drift_rate(paragraphs)
        self.assertLess(result, 0.5)


# ---------------------------------------------------------------------------
# Composite: compute_linearity_metrics
# ---------------------------------------------------------------------------

class TestLinearityMetrics(unittest.TestCase):
    """Test the full metrics computation."""

    def test_empty_text(self):
        result = compute_linearity_metrics("")
        self.assertEqual(result["back_reference_density"], 0.0)
        self.assertEqual(result["rephrasing_loop_rate"], 0.0)
        self.assertEqual(result["idea_recursion_rate"], 0.0)
        self.assertEqual(result["forward_build_ratio"], 0.0)
        self.assertEqual(result["paragraph_drift_rate"], 0.0)

    def test_none_text(self):
        result = compute_linearity_metrics(None)
        self.assertIn("back_reference_density", result)

    def test_linear_text(self):
        text = (
            "The compiler parses source code into an abstract syntax tree. "
            "Type checking validates variable declarations against scope rules. "
            "Code generation emits optimized machine instructions for the target. "
            "The linker resolves symbol references across compiled object files. "
            "Finally the executable is ready for deployment and execution."
        )
        result = compute_linearity_metrics(text)
        # Linear text should have high forward build and low back-reference
        self.assertGreater(result["forward_build_ratio"], 0.5)
        self.assertEqual(result["back_reference_density"], 0.0)

    def test_non_linear_text(self):
        text = (
            "The algorithm is fast and efficient. In other words, it processes "
            "data quickly. That is to say, the processing speed is high. The "
            "algorithm is fast and efficient.\n\n"
            "The server runs the application. The server executes the program."
        )
        result = compute_linearity_metrics(text)
        # Non-linear text should have high back-reference
        self.assertGreater(result["back_reference_density"], 0.0)

    def test_metrics_are_rounded(self):
        text = "The cat sat on the mat. The dog ran across the field."
        result = compute_linearity_metrics(text)
        for key, value in result.items():
            # Check that values are rounded to 4 decimal places
            self.assertEqual(value, round(value, 4))


# ---------------------------------------------------------------------------
# Composite: compute_linearity_index
# ---------------------------------------------------------------------------

class TestLinearityIndex(unittest.TestCase):
    """Test the composite linearity index."""

    def test_perfect_linearity(self):
        metrics = {
            "back_reference_density": 0.0,
            "rephrasing_loop_rate": 0.0,
            "idea_recursion_rate": 0.0,
            "forward_build_ratio": 1.0,
            "paragraph_drift_rate": 0.0,
        }
        result = compute_linearity_index(metrics)
        self.assertAlmostEqual(result, 1.0, places=3)

    def test_worst_linearity(self):
        metrics = {
            "back_reference_density": 1.0,
            "rephrasing_loop_rate": 1.0,
            "idea_recursion_rate": 1.0,
            "forward_build_ratio": 0.0,
            "paragraph_drift_rate": 1.0,
        }
        result = compute_linearity_index(metrics)
        self.assertAlmostEqual(result, 0.0, places=3)

    def test_mixed_metrics(self):
        metrics = {
            "back_reference_density": 0.2,
            "rephrasing_loop_rate": 0.1,
            "idea_recursion_rate": 0.15,
            "forward_build_ratio": 0.8,
            "paragraph_drift_rate": 0.1,
        }
        result = compute_linearity_index(metrics)
        self.assertGreater(result, 0.5)
        self.assertLess(result, 1.0)

    def test_missing_keys_default(self):
        metrics = {}
        result = compute_linearity_index(metrics)
        # Should use defaults (0.0 for densities, 0.5 for forward_build)
        self.assertIsInstance(result, float)

    def test_rounded_output(self):
        metrics = {
            "back_reference_density": 0.123456,
            "rephrasing_loop_rate": 0.234567,
            "idea_recursion_rate": 0.345678,
            "forward_build_ratio": 0.456789,
            "paragraph_drift_rate": 0.567890,
        }
        result = compute_linearity_index(metrics)
        self.assertEqual(result, round(result, 4))


# ---------------------------------------------------------------------------
# Classification: classify_linearity
# ---------------------------------------------------------------------------

class TestClassifyLinearity(unittest.TestCase):
    """Test linearity classification."""

    def test_arrow(self):
        self.assertEqual(classify_linearity(0.80), "arrow")
        self.assertEqual(classify_linearity(0.75), "arrow")
        self.assertEqual(classify_linearity(1.0), "arrow")

    def test_river(self):
        self.assertEqual(classify_linearity(0.55), "river")
        self.assertEqual(classify_linearity(0.65), "river")
        self.assertEqual(classify_linearity(0.74), "river")

    def test_meandering(self):
        self.assertEqual(classify_linearity(0.35), "meandering")
        self.assertEqual(classify_linearity(0.45), "meandering")
        self.assertEqual(classify_linearity(0.54), "meandering")

    def test_stagnant(self):
        self.assertEqual(classify_linearity(0.0), "stagnant")
        self.assertEqual(classify_linearity(0.20), "stagnant")
        self.assertEqual(classify_linearity(0.34), "stagnant")

    def test_boundary_values(self):
        # Exact boundaries
        self.assertEqual(classify_linearity(0.75), "arrow")
        self.assertEqual(classify_linearity(0.55), "river")
        self.assertEqual(classify_linearity(0.35), "meandering")
        self.assertEqual(classify_linearity(0.34), "stagnant")

    def test_negative_score(self):
        self.assertEqual(classify_linearity(-0.1), "stagnant")

    def test_over_one(self):
        self.assertEqual(classify_linearity(1.5), "arrow")


# ---------------------------------------------------------------------------
# Pipeline: analyze_linearity
# ---------------------------------------------------------------------------

class TestAnalyzeLinearity(unittest.TestCase):
    """Test the full analysis pipeline."""

    def test_empty_text(self):
        result = analyze_linearity("")
        self.assertIn("metrics", result)
        self.assertIn("linearity_index", result)
        self.assertIn("linearity_class", result)
        self.assertIn("sentence_count", result)
        self.assertIn("paragraph_count", result)

    def test_structure(self):
        text = "First sentence introduces the topic.\n\nSecond paragraph adds depth."
        result = analyze_linearity(text)
        self.assertIsInstance(result["metrics"], dict)
        self.assertIsInstance(result["linearity_index"], float)
        self.assertIsInstance(result["linearity_class"], str)
        self.assertIsInstance(result["sentence_count"], int)
        self.assertIsInstance(result["paragraph_count"], int)

    def test_linear_text_classifies_high(self):
        text = (
            "The compiler begins by tokenizing the source code into lexical units. "
            "Parsing transforms tokens into a hierarchical syntax tree structure. "
            "Semantic analysis checks type compatibility across expressions. "
            "Optimization passes reduce instruction count and memory usage. "
            "Code generation emits platform-specific machine instructions. "
            "The linker combines object files into a final executable binary."
        )
        result = analyze_linearity(text)
        self.assertIn(result["linearity_class"], ("arrow", "river"))
        self.assertGreater(result["linearity_index"], 0.5)

    def test_non_linear_text_classifies_low(self):
        text = (
            "The algorithm is fast. In other words, it processes quickly. "
            "That is, the speed is high. The algorithm is indeed fast. "
            "Going back to speed: the algorithm processes things fast.\n\n"
            "The server runs. That is to say, it operates. The server runs."
        )
        result = analyze_linearity(text)
        self.assertLess(result["linearity_index"], 0.8)

    def test_counts_match(self):
        text = "Sentence one.\n\nSentence two here.\n\nSentence three now."
        result = analyze_linearity(text)
        self.assertGreaterEqual(result["paragraph_count"], 1)
        self.assertGreaterEqual(result["sentence_count"], 1)


# ---------------------------------------------------------------------------
# Report: format_linearity_report
# ---------------------------------------------------------------------------

class TestFormatLinearityReport(unittest.TestCase):
    """Test the human-readable report formatter."""

    def test_report_contains_class(self):
        analysis = analyze_linearity(
            "The quick brown fox jumped over the lazy sleeping dog."
        )
        report = format_linearity_report(analysis)
        self.assertIn(analysis["linearity_class"], report)

    def test_report_contains_metrics(self):
        analysis = analyze_linearity(
            "First sentence. Second sentence with new words."
        )
        report = format_linearity_report(analysis)
        self.assertIn("Forward build ratio", report)
        self.assertIn("Back-reference density", report)
        self.assertIn("Rephrasing loop rate", report)
        self.assertIn("Idea recursion rate", report)
        self.assertIn("Paragraph drift rate", report)

    def test_report_contains_counts(self):
        text = "First paragraph sentence.\n\nSecond paragraph sentence."
        analysis = analyze_linearity(text)
        report = format_linearity_report(analysis)
        self.assertIn("sentences", report)
        self.assertIn("paragraphs", report)

    def test_report_is_multiline(self):
        analysis = analyze_linearity("Simple test sentence here.")
        report = format_linearity_report(analysis)
        lines = report.strip().split("\n")
        self.assertGreaterEqual(len(lines), 5)


# ---------------------------------------------------------------------------
# Integration: end-to-end scenarios
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    """Integration tests with realistic text samples."""

    def test_technical_documentation(self):
        text = (
            "The REST API accepts JSON payloads via POST requests. "
            "Authentication uses bearer tokens issued by the OAuth provider. "
            "Rate limiting applies per-endpoint quotas based on subscription tier. "
            "Error responses follow RFC 7807 problem detail format. "
            "Pagination uses cursor-based tokens for stable result ordering."
        )
        result = analyze_linearity(text)
        # Technical docs should be linear
        self.assertIn(result["linearity_class"], ("arrow", "river"))

    def test_repetitive_marketing_copy(self):
        text = (
            "Our product is innovative and cutting-edge. In other words, "
            "it brings new solutions. That is, we offer fresh approaches. "
            "Our innovative product delivers cutting-edge solutions. "
            "The innovative and cutting-edge product is what we offer."
        )
        result = analyze_linearity(text)
        # Repetitive copy should score lower
        self.assertLess(result["linearity_index"], 0.8)

    def test_academic_abstract(self):
        text = (
            "This study examines the relationship between sleep quality and cognitive performance. "
            "We recruited 200 participants across three age cohorts. "
            "Polysomnography data was collected over seven consecutive nights. "
            "Cognitive tests measured working memory, attention, and processing speed. "
            "Results indicate a significant correlation between REM duration and test scores. "
            "These findings suggest that sleep architecture matters more than total sleep time."
        )
        result = analyze_linearity(text)
        self.assertIn(result["linearity_class"], ("arrow", "river"))
        self.assertGreater(result["metrics"]["forward_build_ratio"], 0.5)

    def test_single_sentence_text(self):
        result = analyze_linearity("The cat sat on the mat.")
        self.assertIn("linearity_index", result)
        self.assertIn("linearity_class", result)

    def test_multiline_paragraphs(self):
        text = (
            "The database migration script handles schema evolution gracefully.\n\n"
            "Rollback procedures ensure data integrity during failed migrations.\n\n"
            "Testing validates both forward and backward migration paths."
        )
        result = analyze_linearity(text)
        self.assertEqual(result["paragraph_count"], 3)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """Test that constants are properly defined."""

    def test_function_words_is_frozenset(self):
        self.assertIsInstance(FUNCTION_WORDS, frozenset)

    def test_function_words_contains_common(self):
        self.assertIn("the", FUNCTION_WORDS)
        self.assertIn("and", FUNCTION_WORDS)
        self.assertIn("is", FUNCTION_WORDS)

    def test_back_reference_patterns_are_compiled(self):
        for pat in BACK_REFERENCE_PATTERNS:
            self.assertTrue(hasattr(pat, "search"))

    def test_temporal_connectives_compiled(self):
        self.assertTrue(hasattr(TEMPORAL_CONNECTIVES, "search"))

    def test_causal_connectives_compiled(self):
        self.assertTrue(hasattr(CAUSAL_CONNECTIVES, "search"))

    def test_weights_sum_to_one(self):
        from iamai.writer_linearity import WEIGHTS
        total = sum(WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_very_short_text(self):
        result = analyze_linearity("Hi.")
        self.assertIn("linearity_class", result)

    def test_only_function_words(self):
        text = "The and or but the and or but."
        result = compute_linearity_metrics(text)
        # Should not crash even with no content words
        self.assertIn("forward_build_ratio", result)

    def test_unicode_text(self):
        text = "The café serves naïve résumé templates. The entrée costs more."
        result = analyze_linearity(text)
        self.assertIn("linearity_index", result)

    def test_numbers_and_symbols(self):
        text = "The algorithm runs in O(n log n) time complexity. Memory usage is O(n) space."
        result = analyze_linearity(text)
        self.assertIn("linearity_index", result)

    def test_very_long_sentences(self):
        long_sentence = " ".join([f"word{i}" for i in range(200)]) + "."
        result = analyze_linearity(long_sentence)
        self.assertIn("linearity_index", result)

    def test_repeated_text(self):
        text = "The cat sat on the mat. " * 20
        result = analyze_linearity(text)
        # Repetitive text should have low linearity
        self.assertIn("linearity_class", result)

    def test_newlines_only(self):
        result = analyze_linearity("\n\n\n\n")
        self.assertIn("linearity_index", result)

    def test_single_word_paragraphs(self):
        text = "Hello.\n\nWorld.\n\nTesting."
        result = analyze_linearity(text)
        self.assertIn("paragraph_count", result)


if __name__ == "__main__":
    unittest.main()
