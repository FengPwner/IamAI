#!/usr/bin/env python3
"""Tests for writer_concision — concision as economy signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_concision import (  # noqa: E402
    DEADWOOD_WORDS,
    FILLER_CLAUSES,
    REDUNDANCY_PATTERNS,
    _classify_concision,
    _get_stroke_text,
    _split_words,
    analyze_stroke_concision,
    classify_trend,
    compute_concision_index,
    compute_concision_metrics,
    compute_concision_trend,
    compute_deadwood_ratio,
    compute_filler_clause_density,
    compute_information_density,
    compute_redundancy_ratio,
    count_redundancy_hits,
    format_concision_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_words
# ---------------------------------------------------------------------------


class TestSplitWords(unittest.TestCase):
    """Test _split_words helper."""

    def test_basic(self):
        words = _split_words("Hello world")
        self.assertEqual(words, ["hello", "world"])

    def test_punctuation(self):
        words = _split_words("It's a test, really.")
        self.assertIn("it's", words)
        self.assertIn("really", words)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_numbers_ignored(self):
        words = _split_words("test 42 data")
        self.assertEqual(words, ["test", "data"])


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_string_input(self):
        self.assertEqual(_get_stroke_text("hello"), "hello")

    def test_dict_with_text(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_with_content(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "hello")

    def test_dict_empty(self):
        self.assertEqual(_get_stroke_text({}), "")


# ---------------------------------------------------------------------------
# Signal: redundancy
# ---------------------------------------------------------------------------


class TestRedundancy(unittest.TestCase):
    """Test redundancy detection."""

    def test_no_redundancy(self):
        text = "The system processes data efficiently."
        hits = count_redundancy_hits(text)
        self.assertEqual(len(hits), 0)

    def test_in_order_to(self):
        text = "We need to refactor in order to improve performance."
        hits = count_redundancy_hits(text)
        self.assertTrue(any("in order to" in h[0] for h in hits))

    def test_due_to_the_fact_that(self):
        text = "The test failed due to the fact that the mock was wrong."
        hits = count_redundancy_hits(text)
        self.assertTrue(any("due to the fact that" in h[0] for h in hits))

    def test_multiple_patterns(self):
        text = (
            "In order to fix the bug, we need to make use of "
            "a debugger due to the fact that the logs are unclear."
        )
        hits = count_redundancy_hits(text)
        self.assertGreaterEqual(len(hits), 3)

    def test_case_insensitive(self):
        text = "IN ORDER TO fix this, we should act."
        hits = count_redundancy_hits(text)
        self.assertTrue(any("in order to" in h[0] for h in hits))

    def test_redundancy_ratio_zero_for_clean_text(self):
        text = "Fast tests catch bugs early."
        ratio = compute_redundancy_ratio(text)
        self.assertEqual(ratio, 0.0)

    def test_redundancy_ratio_positive(self):
        text = (
            "In order to ensure that the system works, "
            "we need to make use of comprehensive testing "
            "due to the fact that bugs are expensive to fix."
        )
        ratio = compute_redundancy_ratio(text)
        self.assertGreater(ratio, 0.0)

    def test_empty_text(self):
        self.assertEqual(compute_redundancy_ratio(""), 0.0)
        self.assertEqual(count_redundancy_hits(""), [])


# ---------------------------------------------------------------------------
# Signal: deadwood
# ---------------------------------------------------------------------------


class TestDeadwood(unittest.TestCase):
    """Test deadwood word detection."""

    def test_no_deadwood(self):
        text = "The algorithm sorts the list in linear time."
        ratio = compute_deadwood_ratio(text)
        self.assertEqual(ratio, 0.0)

    def test_very(self):
        text = "The code is very fast and quite reliable."
        ratio = compute_deadwood_ratio(text)
        self.assertGreater(ratio, 0.0)

    def test_multiple_deadwood(self):
        text = (
            "It is actually very important to basically "
            "understand that the system is really quite complex."
        )
        ratio = compute_deadwood_ratio(text)
        self.assertGreater(ratio, 0.1)

    def test_empty_text(self):
        self.assertEqual(compute_deadwood_ratio(""), 0.0)

    def test_known_words(self):
        """Verify specific deadwood words are in the set."""
        for word in ["very", "really", "basically", "just", "simply"]:
            self.assertIn(word, DEADWOOD_WORDS)

    def test_non_deadwood_excluded(self):
        """Common meaningful words should not be deadwood."""
        for word in ["the", "system", "processes", "data", "test"]:
            self.assertNotIn(word, DEADWOOD_WORDS)


# ---------------------------------------------------------------------------
# Signal: filler clauses
# ---------------------------------------------------------------------------


class TestFillerClauses(unittest.TestCase):
    """Test filler clause detection."""

    def test_no_filler(self):
        text = "Tests verify correctness and prevent regressions."
        density = compute_filler_clause_density(text)
        self.assertEqual(density, 0.0)

    def test_at_end_of_day(self):
        text = "At the end of the day, we need good tests."
        density = compute_filler_clause_density(text)
        self.assertGreater(density, 0.0)

    def test_multiple_fillers(self):
        text = (
            "Needless to say, the system is important. "
            "It goes without saying that testing matters. "
            "At the end of the day, quality counts."
        )
        density = compute_filler_clause_density(text)
        self.assertGreater(density, 5.0)

    def test_empty_text(self):
        self.assertEqual(compute_filler_clause_density(""), 0.0)

    def test_case_insensitive(self):
        text = "NEEDLESS TO SAY, this works."
        density = compute_filler_clause_density(text)
        self.assertGreater(density, 0.0)


# ---------------------------------------------------------------------------
# Signal: information density
# ---------------------------------------------------------------------------


class TestInformationDensity(unittest.TestCase):
    """Test information density computation."""

    def test_dense_text(self):
        # Mostly content words
        text = "Neural networks classify images using convolutional filters."
        density = compute_information_density(text)
        self.assertGreater(density, 0.5)

    def test_sparse_text(self):
        # Mostly function words
        text = "It is a the of and to for in on at by with from."
        density = compute_information_density(text)
        self.assertLess(density, 0.3)

    def test_empty_text(self):
        self.assertEqual(compute_information_density(""), 0.0)

    def test_mixed_text(self):
        text = "The quick brown fox jumps over the lazy dog."
        density = compute_information_density(text)
        # Should be somewhere in the middle
        self.assertGreater(density, 0.3)
        self.assertLess(density, 0.8)


# ---------------------------------------------------------------------------
# Composite: concision index
# ---------------------------------------------------------------------------


class TestConcisionIndex(unittest.TestCase):
    """Test composite concision index."""

    def test_perfect_concision(self):
        # No redundancy, no deadwood, no filler, high info density
        index = compute_concision_index(0.0, 0.0, 0.0, 0.60)
        self.assertGreaterEqual(index, 0.80)

    def test_terrible_concision(self):
        # High redundancy, high deadwood, high filler, low info density
        index = compute_concision_index(0.15, 0.20, 8.0, 0.30)
        self.assertLess(index, 0.35)

    def test_moderate_concision(self):
        # Some issues
        index = compute_concision_index(0.03, 0.05, 1.0, 0.50)
        self.assertGreater(index, 0.40)
        self.assertLess(index, 0.80)

    def test_clamped_zero(self):
        # Extreme values should not produce negative index
        index = compute_concision_index(1.0, 1.0, 100.0, 0.0)
        self.assertGreaterEqual(index, 0.0)

    def test_clamped_one(self):
        # Perfect values should not exceed 1.0
        index = compute_concision_index(0.0, 0.0, 0.0, 1.0)
        self.assertLessEqual(index, 1.0)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyConcision(unittest.TestCase):
    """Test concision classification thresholds."""

    def test_precise(self):
        self.assertEqual(_classify_concision(0.80), "precise")
        self.assertEqual(_classify_concision(0.95), "precise")

    def test_clean(self):
        self.assertEqual(_classify_concision(0.65), "clean")
        self.assertEqual(_classify_concision(0.79), "clean")

    def test_wordy(self):
        self.assertEqual(_classify_concision(0.50), "wordy")
        self.assertEqual(_classify_concision(0.64), "wordy")

    def test_bloated(self):
        self.assertEqual(_classify_concision(0.35), "bloated")
        self.assertEqual(_classify_concision(0.49), "bloated")

    def test_suffocating(self):
        self.assertEqual(_classify_concision(0.0), "suffocating")
        self.assertEqual(_classify_concision(0.34), "suffocating")


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeConcision(unittest.TestCase):
    """Test single-stroke concision analysis."""

    def test_concise_stroke(self):
        text = "Tests catch bugs before production deploys them."
        result = analyze_stroke_concision(text)
        self.assertIn(result["concision_class"], ("precise", "clean"))
        self.assertEqual(result["word_count"], 7)

    def test_verbose_stroke(self):
        text = (
            "It is important to note that in order to effectively "
            "and basically correctly make use of the testing framework, "
            "it is very really quite essential to actually understand "
            "that at the end of the day, the tests themselves are "
            "the important artifacts."
        )
        result = analyze_stroke_concision(text)
        self.assertIn(result["concision_class"], ("bloated", "suffocating"))
        self.assertGreater(len(result["redundancy_hits"]), 0)
        self.assertGreater(result["deadwood_count"], 0)

    def test_empty_stroke(self):
        result = analyze_stroke_concision("")
        self.assertEqual(result["word_count"], 0)
        self.assertEqual(result["concision_class"], "suffocating")

    def test_dict_input(self):
        result = analyze_stroke_concision({"text": "Clean code reads well."})
        self.assertEqual(result["word_count"], 4)
        self.assertIn("concision_index", result)

    def test_redundancy_hits_listed(self):
        text = "In order to make use of the tool, we need to refactor."
        result = analyze_stroke_concision(text)
        self.assertGreater(len(result["redundancy_hits"]), 0)
        verbose_phrases = [h[0] for h in result["redundancy_hits"]]
        self.assertTrue(any("in order to" in p for p in verbose_phrases))


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


class TestComputeConcisionMetrics(unittest.TestCase):
    """Test session-level concision metrics."""

    def test_empty_list(self):
        metrics = compute_concision_metrics([])
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["concision_class"], "suffocating")

    def test_single_stroke(self):
        metrics = compute_concision_metrics(["Good code is self-documenting."])
        self.assertEqual(metrics["strokes_analyzed"], 1)
        self.assertIn("concision_index", metrics)

    def test_mixed_session(self):
        strokes = [
            "Fast tests catch bugs.",
            "It is important to note that in order to effectively test, "
            "one should basically always make use of assertions.",
            "Clean interfaces reduce coupling.",
            "At the end of the day, the very really important thing "
            "is to actually just write the code.",
        ]
        metrics = compute_concision_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 4)
        self.assertGreater(metrics["total_words"], 0)
        self.assertGreater(metrics["total_redundancy_hits"], 0)
        self.assertGreater(metrics["total_deadwood_words"], 0)

    def test_window_limits(self):
        strokes = [f"Stroke number {i} with some content." for i in range(100)]
        metrics = compute_concision_metrics(strokes, window_size=10)
        self.assertEqual(metrics["strokes_analyzed"], 10)

    def test_class_distribution(self):
        strokes = [
            "Clean test.",
            "Another clean test.",
            "It is very really quite important to basically note that "
            "at the end of the day the thing matters.",
        ]
        metrics = compute_concision_metrics(strokes)
        dist = metrics["class_distribution"]
        self.assertIsInstance(dist, dict)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestConcisionTrend(unittest.TestCase):
    """Test concision trend computation."""

    def test_empty_strokes(self):
        snapshots = compute_concision_trend([])
        self.assertEqual(len(snapshots), 0)

    def test_single_window(self):
        strokes = ["Clean code." for _ in range(5)]
        snapshots = compute_concision_trend(strokes, window_size=3, step=1)
        self.assertGreater(len(snapshots), 0)

    def test_classify_improving(self):
        snapshots = [
            {"concision_index": 0.40},
            {"concision_index": 0.50},
            {"concision_index": 0.60},
            {"concision_index": 0.75},
        ]
        self.assertEqual(classify_trend(snapshots), "improving")

    def test_classify_degrading(self):
        snapshots = [
            {"concision_index": 0.80},
            {"concision_index": 0.70},
            {"concision_index": 0.55},
            {"concision_index": 0.40},
        ]
        self.assertEqual(classify_trend(snapshots), "degrading")

    def test_classify_stable(self):
        snapshots = [
            {"concision_index": 0.65},
            {"concision_index": 0.66},
            {"concision_index": 0.64},
            {"concision_index": 0.65},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")

    def test_insufficient_data(self):
        self.assertEqual(classify_trend([{"concision_index": 0.5}]), "insufficient_data")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test report formatting."""

    def test_basic_report(self):
        metrics = compute_concision_metrics([
            "Clean code is self-documenting.",
            "Tests verify behavior.",
        ])
        report = format_concision_report(metrics)
        self.assertIn("Writer Concision", report)
        self.assertIn("concision_index", report.lower().replace(" ", "_"))
        self.assertIn("Interpretation:", report)

    def test_empty_report(self):
        metrics = compute_concision_metrics([])
        report = format_concision_report(metrics)
        self.assertIn("Strokes analyzed: 0", report)

    def test_all_classes_in_report(self):
        """Report with mixed strokes should show class distribution."""
        strokes = [
            "Short.",
            "It is very really quite important to basically note that "
            "at the end of the day in order to make use of the tool "
            "one has the ability to simply just run the command.",
        ]
        metrics = compute_concision_metrics(strokes)
        report = format_concision_report(metrics)
        self.assertIn("Class distribution:", report)


# ---------------------------------------------------------------------------
# Integration: end-to-end
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    """End-to-end integration tests."""

    def test_precise_writing_detected(self):
        """Hemingway-esque prose should score high."""
        text = "The code ran. Tests passed. The bug was in the parser."
        result = analyze_stroke_concision(text)
        self.assertGreaterEqual(result["concision_index"], 0.50)

    def test_bloated_writing_detected(self):
        """Corporate memo style should score low."""
        text = (
            "It is important to note that, at the end of the day, "
            "in order to effectively and basically successfully "
            "make use of the very comprehensive testing framework, "
            "it is essentially quite critical to actually understand "
            "that, due to the fact that the system is incredibly complex, "
            "we need to take into consideration the fact that "
            "for all intents and purposes the tests are very really "
            "quite important."
        )
        result = analyze_stroke_concision(text)
        self.assertLess(result["concision_index"], 0.50)
        self.assertIn(result["concision_class"], ("bloated", "suffocating"))

    def test_session_with_improving_trend(self):
        """Session that starts verbose and gets tighter."""
        verbose = [
            "It is very important to basically note that the system is "
            "quite really complex and actually needs testing.",
        ] * 10
        concise = [
            "Tests verify the parser handles edge cases.",
        ] * 10
        strokes = verbose + concise
        snapshots = compute_concision_trend(strokes, window_size=8, step=5)
        trend = classify_trend(snapshots)
        self.assertIn(trend, ("improving", "stable"))

    def test_orthogonal_to_readability(self):
        """Concise text can be hard to read (technical jargon)."""
        text = "Polymorphic dispatch resolves vtable indirection overhead."
        result = analyze_stroke_concision(text)
        # Should be concise (no waste) even though vocabulary is technical
        self.assertGreater(result["concision_index"], 0.50)


if __name__ == "__main__":
    unittest.main()
