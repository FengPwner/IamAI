#!/usr/bin/env python3
"""Tests for writer_restraint — restraint as trust-the-reader signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_restraint import (  # noqa: E402
    QUALIFIER_WORDS,
    READER_DISTRUST_PHRASES,
    _content_words,
    _get_stroke_text,
    _jaccard,
    _split_sentences,
    _split_words,
    analyze_session_restraint,
    analyze_stroke_restraint,
    classify_restraint,
    classify_trend,
    compute_parenthetical_density,
    compute_qualifier_stack_density,
    compute_reader_distrust_density,
    compute_restraint_index,
    compute_restraint_metrics,
    compute_restraint_trend,
    compute_restatement_ratio,
    count_distrust_hits,
    count_parentheticals,
    count_qualifier_stacks,
    format_restraint_report,
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

    def test_numbers_dropped(self):
        words = _split_words("test 42 data")
        self.assertNotIn("42", words)

    def test_case_folded(self):
        words = _split_words("HELLO World")
        self.assertEqual(words, ["hello", "world"])


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sents = _split_sentences("First sentence. Second sentence.")
        self.assertEqual(len(sents), 2)

    def test_exclamation(self):
        sents = _split_sentences("Wow! Really? Yes.")
        self.assertEqual(len(sents), 3)

    def test_single(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])


# ---------------------------------------------------------------------------
# Helper: _content_words
# ---------------------------------------------------------------------------


class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_drops_articles(self):
        cw = _content_words(["the", "cat", "sat", "on", "a", "mat"])
        self.assertNotIn("the", cw)
        self.assertNotIn("a", cw)
        self.assertIn("cat", cw)

    def test_drops_pronouns(self):
        cw = _content_words(["i", "think", "it", "works"])
        self.assertNotIn("i", cw)
        self.assertNotIn("it", cw)
        self.assertIn("think", cw)

    def test_single_chars_dropped(self):
        cw = _content_words(["a", "x", "test"])
        self.assertNotIn("a", cw)
        self.assertIn("test", cw)


# ---------------------------------------------------------------------------
# Helper: _jaccard
# ---------------------------------------------------------------------------


class TestJaccard(unittest.TestCase):
    """Test _jaccard similarity."""

    def test_identical(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial(self):
        val = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        self.assertAlmostEqual(val, 2 / 4)

    def test_empty(self):
        self.assertAlmostEqual(_jaccard(set(), set()), 0.0)


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text."""

    def test_text_field(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_body_field(self):
        self.assertEqual(_get_stroke_text({"body": "hi"}), "hi")

    def test_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_none(self):
        self.assertEqual(_get_stroke_text({"text": None}), "")


# ---------------------------------------------------------------------------
# Signal 1: Reader distrust density
# ---------------------------------------------------------------------------


class TestReaderDistrust(unittest.TestCase):
    """Test reader distrust detection."""

    def test_no_distrust(self):
        text = "The server crashed at 14:32. Logs showed a null pointer."
        self.assertEqual(count_distrust_hits(text), 0)

    def test_basically(self):
        text = "Basically, the system restarts every night."
        self.assertEqual(count_distrust_hits(text), 1)

    def test_in_other_words(self):
        text = "The process died. In other words, it stopped running."
        self.assertEqual(count_distrust_hits(text), 1)

    def test_multiple(self):
        text = (
            "Basically, the server crashed. "
            "In other words, it stopped. "
            "Essentially, nothing was running."
        )
        self.assertEqual(count_distrust_hits(text), 3)

    def test_case_insensitive(self):
        text = "BASICALLY the thing works."
        self.assertEqual(count_distrust_hits(text), 1)

    def test_density_zero_for_short(self):
        self.assertEqual(compute_reader_distrust_density("hi"), 0.0)

    def test_density_computed(self):
        text = "Basically " + " ".join(["word"] * 19)
        density = compute_reader_distrust_density(text)
        self.assertGreater(density, 0)


# ---------------------------------------------------------------------------
# Signal 2: Qualifier stacking
# ---------------------------------------------------------------------------


class TestQualifierStacking(unittest.TestCase):
    """Test qualifier stacking detection."""

    def test_no_stack(self):
        words = ["the", "server", "crashed", "at", "noon"]
        self.assertEqual(count_qualifier_stacks(words), 0)

    def test_single_qualifier(self):
        words = ["somewhat", "broken", "server", "today", "morning"]
        self.assertEqual(count_qualifier_stacks(words), 0)

    def test_two_qualifiers(self):
        words = ["somewhat", "fairly", "broken", "server", "today"]
        self.assertEqual(count_qualifier_stacks(words), 1)

    def test_three_qualifiers(self):
        words = ["somewhat", "fairly", "quite", "broken", "server"]
        stacks = count_qualifier_stacks(words)
        self.assertGreaterEqual(stacks, 1)

    def test_short_text(self):
        self.assertEqual(count_qualifier_stacks(["a", "b"]), 0)

    def test_density_zero_for_short(self):
        self.assertEqual(compute_qualifier_stack_density("hi"), 0.0)

    def test_density_computed(self):
        text = "somewhat fairly quite possibly maybe broken system " + " ".join(
            ["word"] * 20
        )
        density = compute_qualifier_stack_density(text)
        self.assertGreater(density, 0)


# ---------------------------------------------------------------------------
# Signal 3: Restatement ratio
# ---------------------------------------------------------------------------


class TestRestatementRatio(unittest.TestCase):
    """Test restatement detection via Jaccard overlap."""

    def test_no_restatement(self):
        text = (
            "The server crashed at noon. "
            "We restarted it at 12:05. "
            "Users reported normal access by 12:10."
        )
        ratio = compute_restatement_ratio(text)
        self.assertAlmostEqual(ratio, 0.0)

    def test_full_restatement(self):
        text = (
            "The server crashed at noon today. "
            "The server crashed at noon today."
        )
        ratio = compute_restatement_ratio(text)
        self.assertGreater(ratio, 0.5)

    def test_single_sentence(self):
        self.assertEqual(compute_restatement_ratio("Just one sentence."), 0.0)

    def test_partial_overlap(self):
        text = (
            "The server crashed at noon in the datacenter. "
            "The datacenter server crashed at noon."
        )
        ratio = compute_restatement_ratio(text)
        self.assertGreater(ratio, 0.3)


# ---------------------------------------------------------------------------
# Signal 4: Parenthetical density
# ---------------------------------------------------------------------------


class TestParentheticals(unittest.TestCase):
    """Test parenthetical detection."""

    def test_none(self):
        self.assertEqual(count_parentheticals("No asides here."), 0)

    def test_parentheses(self):
        self.assertEqual(count_parentheticals("The server (a Linux box) crashed."), 1)

    def test_em_dash(self):
        self.assertEqual(count_parentheticals("The server — a Linux box — crashed."), 1)

    def test_multiple(self):
        text = "One (first aside) and two (second aside) and three — third aside — done."
        self.assertEqual(count_parentheticals(text), 3)

    def test_density_zero_for_short(self):
        self.assertEqual(compute_parenthetical_density("hi"), 0.0)

    def test_density_computed(self):
        text = "The server (Linux) crashed (again) at (noon) " + " ".join(
            ["word"] * 20
        )
        density = compute_parenthetical_density(text)
        self.assertGreater(density, 0)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


class TestRestraintIndex(unittest.TestCase):
    """Test composite restraint index."""

    def test_perfect_restraint(self):
        index = compute_restraint_index(0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(index, 1.0)

    def test_worst_restraint(self):
        index = compute_restraint_index(3.0, 4.0, 1.0, 5.0)
        self.assertAlmostEqual(index, 0.0)

    def test_midrange(self):
        index = compute_restraint_index(1.5, 2.0, 0.5, 2.5)
        self.assertGreater(index, 0.0)
        self.assertLess(index, 1.0)

    def test_clamped_high(self):
        index = compute_restraint_index(0.0, 0.0, 0.0, 0.0)
        self.assertLessEqual(index, 1.0)

    def test_clamped_low(self):
        index = compute_restraint_index(99.0, 99.0, 1.0, 99.0)
        self.assertGreaterEqual(index, 0.0)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyRestraint(unittest.TestCase):
    """Test restraint classification."""

    def test_restrained(self):
        self.assertEqual(classify_restraint(0.85), "restrained")

    def test_measured(self):
        self.assertEqual(classify_restraint(0.70), "measured")

    def test_over_eager(self):
        self.assertEqual(classify_restraint(0.55), "over-eager")

    def test_anxious(self):
        self.assertEqual(classify_restraint(0.40), "anxious")

    def test_smothering(self):
        self.assertEqual(classify_restraint(0.20), "smothering")

    def test_boundary_restrained(self):
        self.assertEqual(classify_restraint(0.80), "restrained")

    def test_boundary_measured(self):
        self.assertEqual(classify_restraint(0.65), "measured")


# ---------------------------------------------------------------------------
# Full analysis
# ---------------------------------------------------------------------------


class TestComputeRestraintMetrics(unittest.TestCase):
    """Test full metrics computation."""

    def test_clean_text(self):
        text = "The server crashed at 14:32. We restarted at 14:35. Users recovered by 14:40."
        metrics = compute_restraint_metrics(text)
        self.assertIn("reader_distrust_density", metrics)
        self.assertIn("qualifier_stack_density", metrics)
        self.assertIn("restatement_ratio", metrics)
        self.assertIn("parenthetical_density", metrics)
        self.assertAlmostEqual(metrics["reader_distrust_density"], 0.0)

    def test_unrestrained_text(self):
        text = (
            "Basically, the server crashed. In other words, it stopped working. "
            "Essentially, the server was no longer operational. "
            "The somewhat fairly quite broken server (our main Linux box) "
            "had — as you might expect — stopped responding."
        )
        metrics = compute_restraint_metrics(text)
        self.assertGreater(metrics["reader_distrust_density"], 0)
        self.assertGreater(metrics["parenthetical_density"], 0)


class TestAnalyzeStrokeRestraint(unittest.TestCase):
    """Test per-stroke analysis."""

    def test_empty_stroke(self):
        result = analyze_stroke_restraint({"text": ""})
        self.assertEqual(result["restraint_class"], "restrained")
        self.assertEqual(result["restraint_index"], 1.0)

    def test_normal_stroke(self):
        result = analyze_stroke_restraint({
            "text": "The server crashed at 14:32. Logs showed null pointer in main()."
        })
        self.assertIn("restraint_index", result)
        self.assertIn("restraint_class", result)
        self.assertGreater(result["restraint_index"], 0.5)

    def test_body_field(self):
        result = analyze_stroke_restraint({
            "body": "Clean direct prose with no over-explanation."
        })
        self.assertIn("restraint_index", result)


class TestAnalyzeSessionRestraint(unittest.TestCase):
    """Test session-level analysis."""

    def test_empty_session(self):
        result = analyze_session_restraint([])
        self.assertEqual(result["n_strokes"], 0)
        self.assertEqual(result["restraint_class"], "restrained")

    def test_multi_stroke(self):
        strokes = [
            {"text": "The server crashed at noon."},
            {"text": "We restarted at 12:05."},
            {"text": "Users recovered by 12:10."},
        ]
        result = analyze_session_restraint(strokes)
        self.assertEqual(result["n_strokes"], 3)
        self.assertIn("restraint_index", result)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestRestraintTrend(unittest.TestCase):
    """Test trend computation."""

    def test_empty(self):
        trend = compute_restraint_trend([])
        self.assertEqual(trend["trend"], "no_data")

    def test_stable(self):
        strokes = [{"text": "Direct prose."}] * 10
        trend = compute_restraint_trend(strokes)
        self.assertEqual(trend["trend"], "stable")
        self.assertAlmostEqual(trend["delta"], 0.0)


class TestClassifyTrend(unittest.TestCase):
    """Test trend classification."""

    def test_improving(self):
        self.assertEqual(classify_trend(0.10), "improving")

    def test_worsening(self):
        self.assertEqual(classify_trend(-0.10), "worsening")

    def test_stable(self):
        self.assertEqual(classify_trend(0.0), "stable")

    def test_boundary_improving(self):
        self.assertEqual(classify_trend(0.06), "improving")

    def test_boundary_worsening(self):
        self.assertEqual(classify_trend(-0.06), "worsening")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test human-readable report."""

    def test_contains_class(self):
        report = format_restraint_report({
            "restraint_class": "measured",
            "restraint_index": 0.72,
            "reader_distrust_density": 0.5,
            "qualifier_stack_density": 0.3,
            "restatement_ratio": 0.1,
            "parenthetical_density": 0.8,
        })
        self.assertIn("measured", report)
        self.assertIn("0.72", report)

    def test_contains_all_signals(self):
        report = format_restraint_report({
            "restraint_class": "restrained",
            "restraint_index": 0.90,
            "reader_distrust_density": 0.0,
            "qualifier_stack_density": 0.0,
            "restatement_ratio": 0.0,
            "parenthetical_density": 0.0,
        })
        self.assertIn("reader distrust", report)
        self.assertIn("qualifier stacks", report)
        self.assertIn("restatement", report)
        self.assertIn("parentheticals", report)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Verify constant data structures."""

    def test_distrust_patterns_not_empty(self):
        self.assertGreater(len(READER_DISTRUST_PHRASES), 0)

    def test_qualifier_words_not_empty(self):
        self.assertGreater(len(QUALIFIER_WORDS), 10)

    def test_qualifier_words_lowercase(self):
        for w in QUALIFIER_WORDS:
            self.assertEqual(w, w.lower())


if __name__ == "__main__":
    unittest.main()
