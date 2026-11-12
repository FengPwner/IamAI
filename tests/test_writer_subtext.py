#!/usr/bin/env python3
"""Tests for writer_subtext — subtext as meaning-depth signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_subtext import (  # noqa: E402
    HEDGE_PATTERNS,
    HYPERBOLE_PATTERNS,
    IRONY_SIGNALS,
    LITOTES_PATTERNS,
    REFERENTIAL_GAP_PATTERNS,
    RHETORICAL_QUESTION_PATTERNS,
    UNDERSTATEMENT_MARKERS,
    _classify_subtext,
    _count_pattern_matches,
    _get_stroke_text,
    _split_sentences,
    _split_words,
    analyze_stroke_subtext,
    analyze_subtext,
    classify_trend,
    compute_gap_density,
    compute_indirectness_density,
    compute_irony_markers,
    compute_show_tell_ratio,
    compute_subtext_metrics,
    compute_subtext_trend,
    format_subtext_report,
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

    def test_exclamation(self):
        sents = _split_sentences("Stop! Don't move! Stay still.")
        self.assertEqual(len(sents), 3)

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
# Helper: _count_pattern_matches
# ---------------------------------------------------------------------------


class TestCountPatternMatches(unittest.TestCase):
    """Test _count_pattern_matches helper."""

    def test_single_match(self):
        import re
        pat = [re.compile(r"\bhello\b", re.I)]
        self.assertEqual(_count_pattern_matches("hello world", pat), 1)

    def test_multiple_matches(self):
        import re
        pat = [re.compile(r"\btest\b", re.I)]
        self.assertEqual(_count_pattern_matches("test test test", pat), 3)

    def test_multiple_patterns(self):
        import re
        pats = [re.compile(r"\bhello\b", re.I), re.compile(r"\bworld\b", re.I)]
        self.assertEqual(_count_pattern_matches("hello world", pats), 2)

    def test_no_match(self):
        import re
        pat = [re.compile(r"\bxyz\b", re.I)]
        self.assertEqual(_count_pattern_matches("hello world", pat), 0)


# ---------------------------------------------------------------------------
# Helper: _classify_subtext
# ---------------------------------------------------------------------------


class TestClassifySubtext(unittest.TestCase):
    """Test _classify_subtext classifier."""

    def test_layered(self):
        self.assertEqual(_classify_subtext(0.80), "layered")
        self.assertEqual(_classify_subtext(0.75), "layered")
        self.assertEqual(_classify_subtext(1.0), "layered")

    def test_suggestive(self):
        self.assertEqual(_classify_subtext(0.55), "suggestive")
        self.assertEqual(_classify_subtext(0.65), "suggestive")
        self.assertEqual(_classify_subtext(0.74), "suggestive")

    def test_literal(self):
        self.assertEqual(_classify_subtext(0.35), "literal")
        self.assertEqual(_classify_subtext(0.45), "literal")
        self.assertEqual(_classify_subtext(0.54), "literal")

    def test_flat(self):
        self.assertEqual(_classify_subtext(0.20), "flat")
        self.assertEqual(_classify_subtext(0.30), "flat")
        self.assertEqual(_classify_subtext(0.34), "flat")

    def test_opaque(self):
        self.assertEqual(_classify_subtext(0.0), "opaque")
        self.assertEqual(_classify_subtext(0.10), "opaque")
        self.assertEqual(_classify_subtext(0.19), "opaque")


# ---------------------------------------------------------------------------
# Signal 1: Indirectness density
# ---------------------------------------------------------------------------


class TestIndirectnessDensity(unittest.TestCase):
    """Test compute_indirectness_density."""

    def test_empty_text(self):
        result = compute_indirectness_density("")
        self.assertEqual(result["total_indirect"], 0)
        self.assertAlmostEqual(result["density"], 0.0, places=2)

    def test_rhetorical_questions(self):
        text = "Isn't it obvious that this approach fails? After all, who would want such a thing?"
        result = compute_indirectness_density(text)
        self.assertGreaterEqual(result["rhetorical_questions"], 2)

    def test_hedges(self):
        text = "One might argue that this is, arguably, in a sense, the best approach. Perhaps it is possible to see the merit."
        result = compute_indirectness_density(text)
        self.assertGreaterEqual(result["hedges"], 2)

    def test_litotes(self):
        text = "The result was not unlike what we expected. It was not without merit. Not exactly a trivial accomplishment."
        result = compute_indirectness_density(text)
        self.assertGreaterEqual(result["litotes"], 2)

    def test_understatement(self):
        text = "It was a bit of a disaster, to say the least. A slight issue, perhaps, rather a problem."
        result = compute_indirectness_density(text)
        self.assertGreaterEqual(result["understatement"], 1)

    def test_density_calculation(self):
        # 100 words with 5 indirect acts → density 5.0
        words = ["word"] * 95 + ["not unlike", "arguably", "perhaps it is possible to see", "after all,", "one might argue"]
        text = " ".join(words)
        result = compute_indirectness_density(text)
        self.assertGreater(result["density"], 0.0)

    def test_word_count(self):
        text = "One two three four five."
        result = compute_indirectness_density(text)
        self.assertEqual(result["word_count"], 5)

    def test_combined_signals(self):
        text = "Isn't it obvious? One might argue it was not without merit. To say the least."
        result = compute_indirectness_density(text)
        self.assertGreater(result["total_indirect"], 2)


# ---------------------------------------------------------------------------
# Signal 2: Irony markers
# ---------------------------------------------------------------------------


class TestIronyMarkers(unittest.TestCase):
    """Test compute_irony_markers."""

    def test_empty_text(self):
        result = compute_irony_markers("")
        self.assertEqual(result["total_irony"], 0)

    def test_explicit_irony(self):
        text = "Ironically, the fix introduced more bugs. Of course, it worked on the first try."
        result = compute_irony_markers(text)
        self.assertGreaterEqual(result["explicit_irony"], 2)

    def test_naturally_predictably(self):
        text = "Naturally, the server crashed at 3am. Predictably, the backup had also failed."
        result = compute_irony_markers(text)
        self.assertGreaterEqual(result["explicit_irony"], 2)

    def test_hyperbole(self):
        text = "It was absolutely ridiculous. The most terrible thing ever in history."
        result = compute_irony_markers(text)
        self.assertGreaterEqual(result["hyperbole"], 1)

    def test_sentiment_inversion(self):
        text = "It was wonderful and terrible at the same time."
        result = compute_irony_markers(text)
        self.assertGreaterEqual(result["sentiment_inversions"], 1)

    def test_irony_signal_with_sentiment(self):
        text = "Of course, it was a brilliant idea. Naturally, the result was perfect."
        result = compute_irony_markers(text)
        # Should detect both explicit irony and sentiment inversions
        self.assertGreater(result["total_irony"], 2)

    def test_word_count(self):
        text = "One two three."
        result = compute_irony_markers(text)
        self.assertEqual(result["word_count"], 3)

    def test_as_expected(self):
        text = "As expected, the deployment failed. As usual, nobody was surprised."
        result = compute_irony_markers(text)
        self.assertGreaterEqual(result["explicit_irony"], 2)


# ---------------------------------------------------------------------------
# Signal 3: Gap density
# ---------------------------------------------------------------------------


class TestGapDensity(unittest.TestCase):
    """Test compute_gap_density."""

    def test_empty_text(self):
        result = compute_gap_density("")
        self.assertEqual(result["total_gaps"], 0)

    def test_ellipses(self):
        text = "She looked at him... and then... well..."
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["ellipses"], 2)

    def test_unicode_ellipsis(self):
        text = "She hesitated… then continued…"
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["ellipses"], 2)

    def test_referential_gaps(self):
        text = "For obvious reasons, certain people were not invited. You know what I mean."
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["referential_gaps"], 2)

    def test_loaded_pauses(self):
        # Long sentence followed by short one
        text = (
            "The entire system had been designed with careful consideration of every "
            "possible edge case and failure mode that could arise in production. "
            "It failed."
        )
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["loaded_pauses"], 1)

    def test_no_loaded_pause(self):
        # Two sentences of similar length
        text = "The system was designed carefully. It worked in production."
        result = compute_gap_density(text)
        self.assertEqual(result["loaded_pauses"], 0)

    def test_vague_references(self):
        text = "They know what they did. That thing happened. For obvious reasons we cannot discuss."
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["referential_gaps"], 2)

    def test_without_naming(self):
        text = "Without naming names, certain parties were involved. Let's just say it happened."
        result = compute_gap_density(text)
        self.assertGreaterEqual(result["referential_gaps"], 2)


# ---------------------------------------------------------------------------
# Signal 4: Show vs tell ratio
# ---------------------------------------------------------------------------


class TestShowTellRatio(unittest.TestCase):
    """Test compute_show_tell_ratio."""

    def test_empty_text(self):
        result = compute_show_tell_ratio("")
        # Empty text → neutral default
        self.assertAlmostEqual(result["ratio"], 0.5, places=2)

    def test_mostly_showing(self):
        text = (
            "She walked to the door, slammed it shut, and paced across the room. "
            "Her hands trembled as she reached for the phone. She stared at the "
            "screen, then threw it onto the couch."
        )
        result = compute_show_tell_ratio(text)
        self.assertGreater(result["show_count"], result["tell_count"])
        self.assertGreater(result["ratio"], 0.6)

    def test_mostly_telling(self):
        text = (
            "She was angry. She felt frustrated and disappointed. He seemed "
            "confused and appeared anxious about the situation. They were "
            "both miserable and felt overwhelmed."
        )
        result = compute_show_tell_ratio(text)
        self.assertGreater(result["tell_count"], result["show_count"])
        self.assertLess(result["ratio"], 0.4)

    def test_mixed(self):
        text = (
            "She walked to the window and stared at the rain. She was sad. "
            "He frowned and turned away. He felt disappointed."
        )
        result = compute_show_tell_ratio(text)
        # Both show and tell should be present
        self.assertGreater(result["show_count"], 0)
        self.assertGreater(result["tell_count"], 0)

    def test_no_emotion_words(self):
        text = "The server processed the request and returned a response."
        result = compute_show_tell_ratio(text)
        self.assertEqual(result["show_count"] + result["tell_count"], 0)
        self.assertAlmostEqual(result["ratio"], 0.5, places=2)

    def test_density_calculation(self):
        text = "She walked slowly and smiled. She was happy."
        result = compute_show_tell_ratio(text)
        self.assertGreater(result["density"], 0.0)

    def test_word_count(self):
        text = "One two three."
        result = compute_show_tell_ratio(text)
        self.assertEqual(result["word_count"], 3)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeSubtext(unittest.TestCase):
    """Test analyze_stroke_subtext."""

    def test_empty_stroke(self):
        result = analyze_stroke_subtext("")
        self.assertEqual(result["subtext_class"], "opaque")
        self.assertAlmostEqual(result["subtext_score"], 0.0)

    def test_dict_stroke(self):
        result = analyze_stroke_subtext({"text": "Hello world."})
        self.assertIn("subtext_score", result)
        self.assertIn("subtext_class", result)

    def test_rich_subtext(self):
        text = (
            "Isn't it obvious? One might argue the plan was not without merit. "
            "She walked to the window, stared at the rain. He frowned. "
            "Ironically, the solution created more problems. You know what I mean."
        )
        result = analyze_stroke_subtext(text)
        self.assertGreater(result["subtext_score"], 0.2)
        self.assertIn(result["subtext_class"], ["layered", "suggestive", "literal", "flat"])

    def test_flat_text(self):
        text = "The server returned a 200 status code. The request was processed successfully."
        result = analyze_stroke_subtext(text)
        self.assertLessEqual(result["subtext_score"], 0.5)

    def test_structure_keys(self):
        result = analyze_stroke_subtext("Hello world.")
        for key in ("indirectness", "irony", "gaps", "show_tell", "subtext_score", "subtext_class"):
            self.assertIn(key, result)

    def test_whitespace_only(self):
        result = analyze_stroke_subtext("   \n\t  ")
        self.assertEqual(result["subtext_class"], "opaque")

    def test_dict_with_content_key(self):
        result = analyze_stroke_subtext({"content": "She slammed the door."})
        self.assertGreater(result["show_tell"]["show_count"], 0)

    def test_dict_with_body_key(self):
        result = analyze_stroke_subtext({"body": "It was, arguably, not unlike success."})
        self.assertGreater(result["indirectness"]["total_indirect"], 0)


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


class TestSubtextMetrics(unittest.TestCase):
    """Test compute_subtext_metrics."""

    def test_empty_strokes(self):
        result = compute_subtext_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["subtext_class"], "opaque")

    def test_single_stroke(self):
        result = compute_subtext_metrics(["Hello world."])
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertIn("subtext_index", result)

    def test_window_size(self):
        strokes = [f"Sentence number {i} in the sequence." for i in range(100)]
        result = compute_subtext_metrics(strokes, window_size=10)
        self.assertEqual(result["strokes_analyzed"], 10)

    def test_class_distribution(self):
        strokes = [
            "She walked slowly, her hands trembling.",
            "The system returned an error code.",
            "Isn't it obvious? One might argue...",
            "The data was processed successfully.",
            "He slammed the door. She was furious.",
        ]
        result = compute_subtext_metrics(strokes)
        self.assertIsInstance(result["class_distribution"], dict)
        self.assertGreater(len(result["class_distribution"]), 0)

    def test_aggregate_counts(self):
        strokes = [
            "Ironically, the fix broke everything. Not without merit, one might argue.",
            "She paced the room, trembling. For obvious reasons, certain people knew.",
        ]
        result = compute_subtext_metrics(strokes)
        self.assertGreater(result["total_irony_markers"], 0)
        self.assertGreater(result["total_indirect_acts"], 0)

    def test_show_tell_aggregation(self):
        strokes = [
            "She walked slowly and smiled at the window.",
            "He was angry and felt disappointed about the situation.",
        ]
        result = compute_subtext_metrics(strokes)
        self.assertGreater(result["total_show_words"] + result["total_tell_words"], 0)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestSubtextTrend(unittest.TestCase):
    """Test compute_subtext_trend and classify_trend."""

    def test_empty_strokes(self):
        self.assertEqual(compute_subtext_trend([]), [])

    def test_single_window(self):
        strokes = ["Hello world."] * 20
        snapshots = compute_subtext_trend(strokes, window_size=20, step=10)
        self.assertEqual(len(snapshots), 1)

    def test_multiple_windows(self):
        strokes = ["Hello world."] * 50
        snapshots = compute_subtext_trend(strokes, window_size=20, step=10)
        self.assertGreater(len(snapshots), 1)

    def test_classify_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"subtext_index": 0.5}]), "insufficient_data")

    def test_classify_deepening(self):
        snapshots = [
            {"subtext_index": 0.3},
            {"subtext_index": 0.3},
            {"subtext_index": 0.5},
            {"subtext_index": 0.6},
        ]
        self.assertEqual(classify_trend(snapshots), "deepening")

    def test_classify_flattening(self):
        snapshots = [
            {"subtext_index": 0.7},
            {"subtext_index": 0.6},
            {"subtext_index": 0.3},
            {"subtext_index": 0.2},
        ]
        self.assertEqual(classify_trend(snapshots), "flattening")

    def test_classify_stable(self):
        snapshots = [
            {"subtext_index": 0.5},
            {"subtext_index": 0.5},
            {"subtext_index": 0.5},
            {"subtext_index": 0.5},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test format_subtext_report."""

    def test_empty_report(self):
        from iamai.writer_subtext import _empty_metrics
        report = format_subtext_report(_empty_metrics())
        self.assertIn("Writer Subtext", report)
        self.assertIn("opaque", report)

    def test_populated_report(self):
        metrics = compute_subtext_metrics([
            "Isn't it obvious? One might argue it was not without merit.",
            "She walked to the door and slammed it. He was furious.",
        ])
        report = format_subtext_report(metrics)
        self.assertIn("Subtext index", report)
        self.assertIn("Interpretation", report)

    def test_all_classes_in_report(self):
        """Ensure each class gets an interpretation message."""
        from iamai.writer_subtext import _empty_metrics
        for cls, score in [("layered", 0.8), ("suggestive", 0.6), ("literal", 0.4), ("flat", 0.25), ("opaque", 0.1)]:
            metrics = _empty_metrics()
            metrics["subtext_class"] = cls
            metrics["subtext_index"] = score
            report = format_subtext_report(metrics)
            self.assertIn("Interpretation", report)


# ---------------------------------------------------------------------------
# Standalone analysis
# ---------------------------------------------------------------------------


class TestAnalyzeSubtext(unittest.TestCase):
    """Test analyze_subtext standalone function."""

    def test_missing_file(self):
        result = analyze_subtext("/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_valid_file(self, tmp_path=None):
        """Test with a temporary strokes file."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"text": "She walked slowly. He was angry."}\n')
            f.write('{"text": "Ironically, it worked. Not without merit."}\n')
            f.write('{"text": "One might argue. After all, who would want this?"}\n')
            tmp = f.name
        try:
            result = analyze_subtext(tmp, window_size=10)
            self.assertEqual(result["strokes_analyzed"], 3)
            self.assertGreater(result["total_words"], 0)
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Pattern completeness sanity checks
# ---------------------------------------------------------------------------


class TestPatternSanity(unittest.TestCase):
    """Sanity checks that pattern lists are non-empty and compile."""

    def test_rhetorical_patterns_exist(self):
        self.assertGreater(len(RHETORICAL_QUESTION_PATTERNS), 0)

    def test_hedge_patterns_exist(self):
        self.assertGreater(len(HEDGE_PATTERNS), 0)

    def test_litotes_patterns_exist(self):
        self.assertGreater(len(LITOTES_PATTERNS), 0)

    def test_understatement_patterns_exist(self):
        self.assertGreater(len(UNDERSTATEMENT_MARKERS), 0)

    def test_irony_signals_exist(self):
        self.assertGreater(len(IRONY_SIGNALS), 0)

    def test_hyperbole_patterns_exist(self):
        self.assertGreater(len(HYPERBOLE_PATTERNS), 0)

    def test_referential_gap_patterns_exist(self):
        self.assertGreater(len(REFERENTIAL_GAP_PATTERNS), 0)

    def test_all_patterns_compile(self):
        """Ensure all patterns are valid compiled regexes."""
        import re
        all_patterns = (
            RHETORICAL_QUESTION_PATTERNS
            + HEDGE_PATTERNS
            + LITOTES_PATTERNS
            + UNDERSTATEMENT_MARKERS
            + IRONY_SIGNALS
            + HYPERBOLE_PATTERNS
            + REFERENTIAL_GAP_PATTERNS
        )
        for pat in all_patterns:
            self.assertIsInstance(pat, re.Pattern)


# ---------------------------------------------------------------------------
# Integration: layered subtext detection
# ---------------------------------------------------------------------------


class TestLayeredSubtext(unittest.TestCase):
    """Integration tests for detecting rich subtext."""

    def test_chekhov_gun_passage(self):
        """A passage with showing, gaps, and indirectness."""
        text = (
            "She placed the letter on the mantelpiece, where it had been "
            "for three weeks. Not exactly a small matter, one might argue. "
            "He glanced at it as he passed. He frowned. The clock ticked. "
            "For obvious reasons, neither of them mentioned it."
        )
        result = analyze_stroke_subtext(text)
        self.assertGreater(result["indirectness"]["total_indirect"], 0)
        self.assertGreater(result["gaps"]["referential_gaps"], 0)
        self.assertGreater(result["show_tell"]["show_count"], 0)
        self.assertGreater(result["subtext_score"], 0.25)

    def test_technical_manual_passage(self):
        """A flat, explicit technical passage."""
        text = (
            "The function accepts two parameters: a string and an integer. "
            "It returns a boolean indicating whether the string length "
            "exceeds the integer value. No exceptions are raised."
        )
        result = analyze_stroke_subtext(text)
        self.assertEqual(result["indirectness"]["total_indirect"], 0)
        self.assertEqual(result["irony"]["total_irony"], 0)
        self.assertLess(result["subtext_score"], 0.4)

    def test_ironic_passage(self):
        """A passage heavy with irony."""
        text = (
            "Naturally, the 'foolproof' deployment script deleted the "
            "production database. Of course, the backups were stored on "
            "the same server. Ironically, this was the team's most "
            "productive day — in terms of learning about disaster recovery."
        )
        result = analyze_stroke_subtext(text)
        self.assertGreater(result["irony"]["total_irony"], 2)


if __name__ == "__main__":
    unittest.main()
