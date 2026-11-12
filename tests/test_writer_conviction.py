#!/usr/bin/env python3
"""Tests for writer_conviction — measuring whether writing commits to its claims."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_conviction import (  # noqa: E402
    CATEGORICAL_MARKERS,
    COMMITMENT_VERBS,
    HEDGE_PHRASES,
    HEDGE_WORDS,
    SELF_UNDERMINING,
    WEASEL_PHRASES,
    _classify_conviction,
    _count_pattern_matches,
    _get_stroke_text,
    _split_sentences,
    _split_words,
    analyze_conviction,
    analyze_stroke_conviction,
    classify_trend,
    compute_categorical_density,
    compute_conviction_metrics,
    compute_conviction_trend,
    compute_hedge_density,
    compute_self_undermining,
    compute_weasel_density,
    format_conviction_report,
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
        words = _split_words("It's a test, perhaps.")
        self.assertIn("it's", words)
        self.assertIn("perhaps", words)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_multiple_spaces(self):
        words = _split_words("hello   world")
        self.assertEqual(words, ["hello", "world"])


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sents = _split_sentences("Hello world. How are you?")
        self.assertEqual(len(sents), 2)

    def test_abbreviation(self):
        sents = _split_sentences("Dr. Smith arrived. He was late.")
        self.assertEqual(len(sents), 2)

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])


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

    def test_dict_with_body(self):
        self.assertEqual(_get_stroke_text({"body": "hello"}), "hello")

    def test_dict_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_dict_non_string(self):
        self.assertEqual(_get_stroke_text({"text": 42}), "")


# ---------------------------------------------------------------------------
# Helper: _classify_conviction
# ---------------------------------------------------------------------------


class TestClassifyConviction(unittest.TestCase):
    """Test _classify_conviction classifier."""

    def test_resolute(self):
        self.assertEqual(_classify_conviction(0.80), "resolute")
        self.assertEqual(_classify_conviction(0.75), "resolute")
        self.assertEqual(_classify_conviction(1.0), "resolute")

    def test_assertive(self):
        self.assertEqual(_classify_conviction(0.55), "assertive")
        self.assertEqual(_classify_conviction(0.65), "assertive")
        self.assertEqual(_classify_conviction(0.74), "assertive")

    def test_measured(self):
        self.assertEqual(_classify_conviction(0.35), "measured")
        self.assertEqual(_classify_conviction(0.45), "measured")
        self.assertEqual(_classify_conviction(0.54), "measured")

    def test_tentative(self):
        self.assertEqual(_classify_conviction(0.20), "tentative")
        self.assertEqual(_classify_conviction(0.30), "tentative")
        self.assertEqual(_classify_conviction(0.34), "tentative")

    def test_diffident(self):
        self.assertEqual(_classify_conviction(0.0), "diffident")
        self.assertEqual(_classify_conviction(0.10), "diffident")
        self.assertEqual(_classify_conviction(0.19), "diffident")


# ---------------------------------------------------------------------------
# Signal 1: Hedge density
# ---------------------------------------------------------------------------


class TestHedgeDensity(unittest.TestCase):
    """Test compute_hedge_density."""

    def test_empty_text(self):
        result = compute_hedge_density("")
        self.assertEqual(result["total_hedges"], 0)
        self.assertAlmostEqual(result["density"], 0.0)

    def test_clean_text(self):
        text = "The server processed the request and returned a response."
        result = compute_hedge_density(text)
        self.assertEqual(result["total_hedges"], 0)

    def test_hedge_heavy(self):
        text = (
            "Perhaps maybe it is possibly the case that the system might be "
            "arguably somewhat sort of working to some extent."
        )
        result = compute_hedge_density(text)
        self.assertGreater(result["hedge_words"], 2)
        self.assertGreater(result["density"], 0.0)

    def test_hedge_phrases(self):
        text = "It seems like the code works. It might be that tests pass. One could argue it is correct."
        result = compute_hedge_density(text)
        self.assertGreater(result["hedge_phrases"], 0)

    def test_density_bounded(self):
        text = "Perhaps maybe possibly probably arguably somewhat slightly."
        result = compute_hedge_density(text)
        self.assertGreater(result["density"], 0.0)

    def test_word_count(self):
        text = "One two three four five."
        result = compute_hedge_density(text)
        self.assertEqual(result["word_count"], 5)

    def test_in_a_way(self):
        text = "In a way, the system works, sort of."
        result = compute_hedge_density(text)
        self.assertGreater(result["total_hedges"], 0)
        self.assertGreater(result["hedge_words"], 0)


# ---------------------------------------------------------------------------
# Signal 2: Weasel density
# ---------------------------------------------------------------------------


class TestWeaselDensity(unittest.TestCase):
    """Test compute_weasel_density."""

    def test_empty_text(self):
        result = compute_weasel_density("")
        self.assertEqual(result["weasel_count"], 0)
        self.assertAlmostEqual(result["density"], 0.0)

    def test_clean_text(self):
        text = "The server processed the request and returned a response."
        result = compute_weasel_density(text)
        self.assertEqual(result["weasel_count"], 0)

    def test_weasel_heavy(self):
        text = (
            "Some people think the code works. It is generally accepted that "
            "tests pass. Many experts believe the system is stable."
        )
        result = compute_weasel_density(text)
        self.assertGreater(result["weasel_count"], 0)

    def test_they_say(self):
        text = "They say the code is good. They think it works."
        result = compute_weasel_density(text)
        self.assertGreater(result["weasel_count"], 0)

    def test_it_is_said(self):
        text = "It is said that the deployment went well. It is believed that the system is stable."
        result = compute_weasel_density(text)
        self.assertGreater(result["weasel_count"], 1)

    def test_word_count(self):
        text = "One two three."
        result = compute_weasel_density(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Signal 3: Categorical density
# ---------------------------------------------------------------------------


class TestCategoricalDensity(unittest.TestCase):
    """Test compute_categorical_density."""

    def test_empty_text(self):
        result = compute_categorical_density("")
        self.assertEqual(result["total"], 0)
        self.assertAlmostEqual(result["density"], 0.0)

    def test_committed_text(self):
        text = (
            "I believe the system works. The evidence shows that tests pass. "
            "We must deploy now. We will succeed."
        )
        result = compute_categorical_density(text)
        self.assertGreater(result["categorical_count"], 0)

    def test_commitment_verbs(self):
        text = "I choose to deploy this. We commit to quality. I insist on correctness."
        result = compute_categorical_density(text)
        self.assertGreater(result["commitment_verbs"], 0)

    def test_no_commitment(self):
        text = "The server processed the request and returned a response."
        result = compute_categorical_density(text)
        self.assertEqual(result["total"], 0)

    def test_in_fact(self):
        text = "In fact, the system works. In reality, it is the best solution."
        result = compute_categorical_density(text)
        self.assertGreater(result["categorical_count"], 0)

    def test_let_me_be_clear(self):
        text = "Let me be clear about this. Let me be direct with you."
        result = compute_categorical_density(text)
        self.assertGreater(result["categorical_count"], 0)

    def test_word_count(self):
        text = "One two three."
        result = compute_categorical_density(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Signal 4: Self-undermining
# ---------------------------------------------------------------------------


class TestSelfUndermining(unittest.TestCase):
    """Test compute_self_undermining."""

    def test_empty_text(self):
        result = compute_self_undermining("")
        self.assertEqual(result["undermining_count"], 0)
        self.assertAlmostEqual(result["density"], 0.0)

    def test_clean_text(self):
        text = "The server processed the request and returned a response."
        result = compute_self_undermining(text)
        self.assertEqual(result["undermining_count"], 0)

    def test_apologetic(self):
        text = (
            "I'm not an expert, but I think this works. This might be wrong, "
            "but the code seems fine. Just my opinion, of course."
        )
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 1)

    def test_grain_of_salt(self):
        text = "Take this with a grain of salt, but the deployment went well."
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 0)

    def test_dont_quote_me(self):
        text = "Don't quote me on this, but the system is stable."
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 0)

    def test_for_what_its_worth(self):
        text = "For what it's worth, I think the code is correct."
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 0)

    def test_could_be_corrected(self):
        text = "I stand to be corrected, but this is the right approach."
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 0)

    def test_no_offense(self):
        text = "No offense, but the previous code was terrible."
        result = compute_self_undermining(text)
        self.assertGreater(result["undermining_count"], 0)

    def test_word_count(self):
        text = "One two three."
        result = compute_self_undermining(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeConviction(unittest.TestCase):
    """Test analyze_stroke_conviction."""

    def test_empty_stroke(self):
        result = analyze_stroke_conviction("")
        self.assertEqual(result["conviction_class"], "diffident")
        self.assertAlmostEqual(result["conviction_score"], 0.0)

    def test_dict_stroke(self):
        result = analyze_stroke_conviction({"text": "I believe the system works."})
        self.assertIn("conviction_score", result)
        self.assertIn("conviction_class", result)

    def test_committed_text(self):
        text = (
            "I believe this approach is correct. The evidence shows it works. "
            "We must deploy now. I insist on thorough testing."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["conviction_score"], 0.3)
        self.assertGreater(result["categorical"]["total"], 0)

    def test_hedged_text(self):
        text = (
            "Perhaps maybe it might be that the code possibly works. "
            "It seems like it might be the case. One could argue it "
            "is somewhat functional to some extent."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["hedges"]["total_hedges"], 0)

    def test_weaselly_text(self):
        text = (
            "Some people think the code works. Many experts believe it "
            "is stable. It is generally accepted that tests pass."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["weasels"]["weasel_count"], 0)

    def test_structure_keys(self):
        result = analyze_stroke_conviction("Hello world.")
        for key in ("hedges", "weasels", "categorical", "undermining",
                     "conviction_score", "conviction_class"):
            self.assertIn(key, result)

    def test_whitespace_only(self):
        result = analyze_stroke_conviction("   \n\t  ")
        self.assertEqual(result["conviction_class"], "diffident")

    def test_dict_with_content_key(self):
        result = analyze_stroke_conviction({"content": "I believe the code works."})
        self.assertIn("conviction_score", result)

    def test_dict_with_body_key(self):
        result = analyze_stroke_conviction({"body": "We must deploy now."})
        self.assertGreater(result["categorical"]["categorical_count"], 0)


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


class TestConvictionMetrics(unittest.TestCase):
    """Test compute_conviction_metrics."""

    def test_empty_strokes(self):
        result = compute_conviction_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["conviction_class"], "diffident")

    def test_single_stroke(self):
        result = compute_conviction_metrics(["I believe the system works."])
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertIn("conviction_index", result)

    def test_window_size(self):
        strokes = [f"Sentence number {i} in the sequence." for i in range(100)]
        result = compute_conviction_metrics(strokes, window_size=10)
        self.assertEqual(result["strokes_analyzed"], 10)

    def test_class_distribution(self):
        strokes = [
            "I believe the system works. We must deploy now.",
            "Perhaps maybe it might be the case.",
            "Some people think the code is fine.",
            "The evidence shows that tests pass. We will succeed.",
            "I'm not an expert, but perhaps it works.",
        ]
        result = compute_conviction_metrics(strokes)
        self.assertIsInstance(result["class_distribution"], dict)
        self.assertGreater(len(result["class_distribution"]), 0)

    def test_aggregate_counts(self):
        strokes = [
            "I believe the code works. We must test it. In fact, it is correct.",
            "Perhaps maybe it might be that the system possibly works.",
        ]
        result = compute_conviction_metrics(strokes)
        self.assertGreater(result["total_categorical"], 0)
        self.assertGreater(result["total_hedges"], 0)

    def test_density_calculations(self):
        strokes = [
            "I believe the code works. We must deploy. Let me be clear.",
        ]
        result = compute_conviction_metrics(strokes)
        self.assertGreater(result["categorical_density"], 0.0)

    def test_hedge_density_aggregation(self):
        strokes = [
            "Perhaps the system works. Maybe it is correct.",
            "It seems like it might be functional.",
        ]
        result = compute_conviction_metrics(strokes)
        self.assertGreater(result["hedge_density"], 0.0)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestConvictionTrend(unittest.TestCase):
    """Test compute_conviction_trend and classify_trend."""

    def test_empty_strokes(self):
        self.assertEqual(compute_conviction_trend([]), [])

    def test_single_window(self):
        strokes = ["I believe the code works."] * 20
        snapshots = compute_conviction_trend(strokes, window_size=20, step=10)
        self.assertEqual(len(snapshots), 1)

    def test_multiple_windows(self):
        strokes = ["I believe the code works."] * 50
        snapshots = compute_conviction_trend(strokes, window_size=20, step=10)
        self.assertGreater(len(snapshots), 1)

    def test_classify_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"conviction_index": 0.5}]), "insufficient_data")

    def test_classify_strengthening(self):
        snapshots = [
            {"conviction_index": 0.3},
            {"conviction_index": 0.3},
            {"conviction_index": 0.5},
            {"conviction_index": 0.6},
        ]
        self.assertEqual(classify_trend(snapshots), "strengthening")

    def test_classify_weakening(self):
        snapshots = [
            {"conviction_index": 0.7},
            {"conviction_index": 0.6},
            {"conviction_index": 0.3},
            {"conviction_index": 0.2},
        ]
        self.assertEqual(classify_trend(snapshots), "weakening")

    def test_classify_stable(self):
        snapshots = [
            {"conviction_index": 0.5},
            {"conviction_index": 0.5},
            {"conviction_index": 0.5},
            {"conviction_index": 0.5},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test format_conviction_report."""

    def test_empty_report(self):
        from iamai.writer_conviction import _empty_metrics
        report = format_conviction_report(_empty_metrics())
        self.assertIn("Writer Conviction", report)
        self.assertIn("diffident", report)

    def test_populated_report(self):
        metrics = compute_conviction_metrics([
            "I believe the code works. We must deploy now.",
            "Some people think it is generally accepted that tests pass.",
        ])
        report = format_conviction_report(metrics)
        self.assertIn("Conviction index", report)
        self.assertIn("Interpretation", report)

    def test_all_classes_in_report(self):
        """Ensure each class gets an interpretation message."""
        from iamai.writer_conviction import _empty_metrics
        for cls, score in [
            ("resolute", 0.8),
            ("assertive", 0.6),
            ("measured", 0.4),
            ("tentative", 0.25),
            ("diffident", 0.1),
        ]:
            metrics = _empty_metrics()
            metrics["conviction_class"] = cls
            metrics["conviction_index"] = score
            report = format_conviction_report(metrics)
            self.assertIn("Interpretation", report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------


class TestAnalyzeConviction(unittest.TestCase):
    """Test analyze_conviction standalone function."""

    def test_missing_file(self):
        result = analyze_conviction("/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_valid_file(self):
        """Test with a temporary strokes file."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"text": "I believe the system works. We must deploy."}\n')
            f.write('{"text": "Perhaps maybe it might be the case."}\n')
            f.write('{"text": "The evidence shows it is correct."}\n')
            tmp = f.name
        try:
            result = analyze_conviction(tmp, window_size=10)
            self.assertEqual(result["strokes_analyzed"], 3)
            self.assertGreater(result["total_words"], 0)
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Pattern completeness sanity checks
# ---------------------------------------------------------------------------


class TestPatternSanity(unittest.TestCase):
    """Sanity checks that pattern lists are non-empty and compile."""

    def test_hedge_words_exist(self):
        self.assertGreater(len(HEDGE_WORDS), 0)

    def test_hedge_phrases_exist(self):
        self.assertGreater(len(HEDGE_PHRASES), 0)

    def test_weasel_phrases_exist(self):
        self.assertGreater(len(WEASEL_PHRASES), 0)

    def test_categorical_markers_exist(self):
        self.assertGreater(len(CATEGORICAL_MARKERS), 0)

    def test_commitment_verbs_exist(self):
        self.assertGreater(len(COMMITMENT_VERBS), 0)

    def test_self_undermining_exist(self):
        self.assertGreater(len(SELF_UNDERMINING), 0)

    def test_all_patterns_compile(self):
        """Ensure all patterns are valid compiled regexes."""
        import re
        all_patterns = (
            HEDGE_WORDS
            + HEDGE_PHRASES
            + WEASEL_PHRASES
            + CATEGORICAL_MARKERS
            + COMMITMENT_VERBS
            + SELF_UNDERMINING
        )
        for pat in all_patterns:
            self.assertIsInstance(pat, re.Pattern)

    def test_hedge_words_detect_common_hedges(self):
        """Spot-check common hedge words are in the list."""
        text = "perhaps maybe possibly probably arguably"
        count = _count_pattern_matches(text, HEDGE_WORDS)
        self.assertGreaterEqual(count, 4)

    def test_weasel_phrases_detect_common(self):
        """Spot-check common weasel phrases."""
        text = "Some people think it is said that many experts believe"
        count = _count_pattern_matches(text, WEASEL_PHRASES)
        self.assertGreaterEqual(count, 1)


# ---------------------------------------------------------------------------
# Integration: conviction classification
# ---------------------------------------------------------------------------


class TestConvictionIntegration(unittest.TestCase):
    """Integration tests for conviction classification."""

    def test_committed_passage(self):
        """Declarative, owned, no hedging."""
        text = (
            "I believe this approach is correct. The evidence shows it works. "
            "We must deploy now. I insist on thorough testing. We will succeed."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["categorical"]["total"], 2)
        self.assertEqual(result["hedges"]["total_hedges"], 0)
        self.assertGreater(result["conviction_score"], 0.4)

    def test_evasive_passage(self):
        """Hedged, weaselly, self-undermining."""
        text = (
            "Perhaps maybe it might be that the code possibly works. "
            "Some people think it is said that the system is arguably "
            "somewhat functional. I'm not an expert, but it seems like "
            "it could be the case that tests might pass. Just my opinion."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["hedges"]["total_hedges"], 3)
        self.assertGreater(result["weasels"]["weasel_count"], 0)
        self.assertGreater(result["undermining"]["undermining_count"], 0)

    def test_mixed_passage(self):
        """A mix of committed and evasive elements."""
        text = (
            "I believe the code works. Perhaps the tests need more coverage. "
            "We must deploy, but maybe we should wait. The evidence shows "
            "the system is stable. I could be wrong about the edge cases."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["conviction_score"], 0.0)
        self.assertIn(
            result["conviction_class"],
            ["resolute", "assertive", "measured", "tentative", "diffident"],
        )

    def test_short_text(self):
        """Short but committed text."""
        text = "I believe it."
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["categorical"]["categorical_count"], 0)

    def test_technical_neutral(self):
        """Technical text with no conviction signals either way."""
        text = "The function takes two arguments and returns a dict."
        result = analyze_stroke_conviction(text)
        self.assertEqual(result["hedges"]["total_hedges"], 0)
        self.assertEqual(result["weasels"]["weasel_count"], 0)
        self.assertEqual(result["undermining"]["undermining_count"], 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_single_word(self):
        result = analyze_stroke_conviction("Hello.")
        self.assertIn("conviction_score", result)

    def test_punctuation_only(self):
        result = analyze_stroke_conviction("...")
        # Punctuation-only text is too short for meaningful signals;
        # base categorical score gives it a moderate classification.
        self.assertIn(result["conviction_class"],
                      ["resolute", "assertive", "measured", "tentative", "diffident"])

    def test_very_long_text(self):
        text = "I believe the system works. " * 200
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["categorical"]["total"], 0)

    def test_repeated_hedge(self):
        text = "Perhaps perhaps perhaps perhaps perhaps."
        result = compute_hedge_density(text)
        self.assertGreater(result["hedge_words"], 3)

    def test_mixed_signals(self):
        text = (
            "I believe the system works, perhaps. We must deploy, "
            "but maybe we should wait. In fact, it is the best approach, "
            "though I could be wrong."
        )
        result = analyze_stroke_conviction(text)
        self.assertGreater(result["categorical"]["total"], 0)
        self.assertGreater(result["hedges"]["total_hedges"], 0)
        self.assertGreater(result["undermining"]["undermining_count"], 0)


if __name__ == "__main__":
    unittest.main()
