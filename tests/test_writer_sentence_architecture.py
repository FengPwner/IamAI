#!/usr/bin/env python3
"""Tests for writer_sentence_architecture — measuring structural variety of sentences."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_sentence_architecture import (  # noqa: E402
    _classify_architecture,
    _classify_opener,
    _is_fragment,
    _is_passive,
    _score_active_ratio,
    _score_fragment_rate,
    _score_length_variance,
    _split_sentences,
    _split_words,
    analyze_sentence_architecture,
    analyze_session_architecture,
    analyze_stroke_architecture,
    classify_trend,
    compute_active_ratio,
    compute_architecture_index,
    compute_architecture_trend,
    compute_fragment_rate,
    compute_length_variance,
    compute_opening_diversity,
    format_architecture_report,
)


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sents = _split_sentences("Hello world. How are you? Fine.")
        self.assertEqual(len(sents), 3)

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_exclamation(self):
        sents = _split_sentences("Wow! Amazing! Incredible!")
        self.assertEqual(len(sents), 3)

    def test_empty(self):
        sents = _split_sentences("")
        self.assertEqual(sents, [])

    def test_markdown_stripped(self):
        sents = _split_sentences("**Bold** text here. *Italic* too.")
        self.assertEqual(len(sents), 2)

    def test_short_noise_filtered(self):
        sents = _split_sentences("OK. This is a full sentence.")
        # "OK." is too short (2 chars) and should be filtered
        self.assertEqual(len(sents), 1)


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
# Helper: _classify_opener
# ---------------------------------------------------------------------------


class TestClassifyOpener(unittest.TestCase):
    """Test _classify_opener helper."""

    def test_article(self):
        self.assertEqual(_classify_opener("The system works."), "article")
        self.assertEqual(_classify_opener("A new approach."), "article")
        self.assertEqual(_classify_opener("An interesting idea."), "article")

    def test_pronoun(self):
        self.assertEqual(_classify_opener("We should try."), "pronoun")
        self.assertEqual(_classify_opener("This matters."), "pronoun")
        self.assertEqual(_classify_opener("They arrived."), "pronoun")

    def test_preposition(self):
        self.assertEqual(_classify_opener("In the beginning."), "preposition")
        self.assertEqual(_classify_opener("By the time."), "preposition")
        self.assertEqual(_classify_opener("After the storm."), "preposition")

    def test_adverb(self):
        self.assertEqual(_classify_opener("However, we tried."), "adverb")
        self.assertEqual(_classify_opener("Therefore, it works."), "adverb")
        self.assertEqual(_classify_opener("Clearly, this matters."), "adverb")

    def test_conjunction(self):
        self.assertEqual(_classify_opener("But we persisted."), "conjunction")
        self.assertEqual(_classify_opener("And then we won."), "conjunction")

    def test_empty(self):
        self.assertEqual(_classify_opener(""), "unknown")


# ---------------------------------------------------------------------------
# Helper: _is_passive
# ---------------------------------------------------------------------------


class TestIsPassive(unittest.TestCase):
    """Test _is_passive helper."""

    def test_passive(self):
        self.assertTrue(_is_passive("The ball was thrown by the boy."))
        self.assertTrue(_is_passive("The data is collected by the system."))
        self.assertTrue(_is_passive("Results were analyzed by the team."))

    def test_active(self):
        self.assertFalse(_is_passive("The boy threw the ball."))
        self.assertFalse(_is_passive("The system collects data."))
        self.assertFalse(_is_passive("We analyzed the results."))

    def test_ambiguous(self):
        # "is running" — present progressive, not passive
        self.assertFalse(_is_passive("The process is running."))


# ---------------------------------------------------------------------------
# Helper: _is_fragment
# ---------------------------------------------------------------------------


class TestIsFragment(unittest.TestCase):
    """Test _is_fragment helper."""

    def test_fragment(self):
        self.assertTrue(_is_fragment("A lot."))
        self.assertTrue(_is_fragment("No way."))
        self.assertTrue(_is_fragment("Very much."))

    def test_complete_short(self):
        self.assertFalse(_is_fragment("It works."))
        self.assertFalse(_is_fragment("Go now."))

    def test_long_not_fragment(self):
        self.assertFalse(_is_fragment("This is a complete sentence with many words."))
        self.assertFalse(_is_fragment("The system processes data efficiently every day."))

    def test_single_word_with_verb(self):
        self.assertFalse(_is_fragment("Go."))
        self.assertFalse(_is_fragment("Stop."))


# ---------------------------------------------------------------------------
# Signal 1: Length variance
# ---------------------------------------------------------------------------


class TestLengthVariance(unittest.TestCase):
    """Test compute_length_variance."""

    def test_uniform(self):
        sents = ["One two three.", "Four five six.", "Seven eight nine."]
        cv = compute_length_variance(sents)
        self.assertAlmostEqual(cv, 0.0, places=1)

    def test_varied(self):
        sents = [
            "Go.",
            "The quick brown fox jumps over the lazy dog near the riverbank.",
            "Stop.",
            "Meanwhile the entire system processes thousands of requests every single second.",
        ]
        cv = compute_length_variance(sents)
        self.assertGreater(cv, 0.5)

    def test_single_sentence(self):
        self.assertEqual(compute_length_variance(["Only one."]), 0.0)

    def test_empty(self):
        self.assertEqual(compute_length_variance([]), 0.0)

    def test_scoring_uniform(self):
        score = _score_length_variance(0.1)
        self.assertLess(score, 0.4)

    def test_scoring_ideal(self):
        score = _score_length_variance(0.7)
        self.assertGreater(score, 0.7)

    def test_scoring_chaotic(self):
        score = _score_length_variance(2.0)
        self.assertLess(score, 0.8)


# ---------------------------------------------------------------------------
# Signal 2: Opening diversity
# ---------------------------------------------------------------------------


class TestOpeningDiversity(unittest.TestCase):
    """Test compute_opening_diversity."""

    def test_all_same(self):
        sents = ["The dog ran.", "The cat slept.", "The bird flew.", "The fish swam."]
        div = compute_opening_diversity(sents)
        self.assertAlmostEqual(div, 0.0, places=1)

    def test_diverse(self):
        sents = [
            "The system works.",        # article
            "We tested it.",            # pronoun
            "In production, it fails.", # preposition
            "However, we fixed it.",    # adverb
            "But it broke again.",      # conjunction
        ]
        div = compute_opening_diversity(sents)
        self.assertGreater(div, 0.7)

    def test_single_sentence(self):
        self.assertEqual(compute_opening_diversity(["Just one."]), 0.0)

    def test_empty(self):
        self.assertEqual(compute_opening_diversity([]), 0.0)


# ---------------------------------------------------------------------------
# Signal 3: Active ratio
# ---------------------------------------------------------------------------


class TestActiveRatio(unittest.TestCase):
    """Test compute_active_ratio."""

    def test_all_active(self):
        sents = ["The dog chased the cat.", "We wrote the code.", "She ran fast."]
        ratio = compute_active_ratio(sents)
        self.assertEqual(ratio, 1.0)

    def test_all_passive(self):
        sents = [
            "The ball was thrown by the boy.",
            "The data is collected by the system.",
            "Results were analyzed by the team.",
        ]
        ratio = compute_active_ratio(sents)
        self.assertEqual(ratio, 0.0)

    def test_mixed(self):
        sents = [
            "The dog chased the cat.",
            "The ball was thrown by the boy.",
            "We wrote the code.",
            "Results were analyzed by the team.",
        ]
        ratio = compute_active_ratio(sents)
        self.assertAlmostEqual(ratio, 0.5)

    def test_single_sentence_neutral(self):
        self.assertEqual(compute_active_ratio(["Just one."]), 0.5)

    def test_scoring_low(self):
        score = _score_active_ratio(0.3)
        self.assertLess(score, 0.5)

    def test_scoring_ideal(self):
        score = _score_active_ratio(0.85)
        self.assertGreater(score, 0.8)


# ---------------------------------------------------------------------------
# Signal 4: Fragment rate
# ---------------------------------------------------------------------------


class TestFragmentRate(unittest.TestCase):
    """Test compute_fragment_rate."""

    def test_no_fragments(self):
        sents = [
            "The system processes data efficiently.",
            "We tested the code thoroughly.",
            "Results showed significant improvement.",
        ]
        rate = compute_fragment_rate(sents)
        self.assertEqual(rate, 0.0)

    def test_some_fragments(self):
        sents = [
            "This matters a great deal.",
            "A lot.",
            "The system works well in production.",
            "Very much.",
            "We tested it thoroughly before release.",
            "Several engineers reviewed the code carefully.",
        ]
        rate = compute_fragment_rate(sents)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 0.6)

    def test_scoring_zero(self):
        score = _score_fragment_rate(0.0)
        self.assertAlmostEqual(score, 0.5)

    def test_scoring_ideal(self):
        score = _score_fragment_rate(0.05)
        self.assertGreater(score, 0.8)

    def test_scoring_excessive(self):
        score = _score_fragment_rate(0.30)
        self.assertLess(score, 0.5)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


class TestArchitectureIndex(unittest.TestCase):
    """Test compute_architecture_index and _classify_architecture."""

    def test_perfect(self):
        # Ideal values: high variance, high diversity, good active, some fragments
        index = compute_architecture_index(0.7, 0.9, 0.85, 0.05)
        self.assertGreater(index, 0.75)

    def test_monotonous(self):
        # Poor values: no variance, no diversity, all passive, no fragments
        index = compute_architecture_index(0.05, 0.0, 0.2, 0.0)
        self.assertLess(index, 0.35)

    def test_classify_masterful(self):
        self.assertEqual(_classify_architecture(0.80), "masterful")

    def test_classify_varied(self):
        self.assertEqual(_classify_architecture(0.60), "varied")

    def test_classify_competent(self):
        self.assertEqual(_classify_architecture(0.40), "competent")

    def test_classify_uniform(self):
        self.assertEqual(_classify_architecture(0.25), "uniform")

    def test_classify_monotonous(self):
        self.assertEqual(_classify_architecture(0.10), "monotonous")


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------


class TestAnalyzeSentenceArchitecture(unittest.TestCase):
    """Test the main analyze_sentence_architecture function."""

    def test_empty_text(self):
        result = analyze_sentence_architecture("")
        self.assertEqual(result["total_sentences"], 0)
        self.assertEqual(result["architecture_class"], "monotonous")

    def test_rich_text(self):
        text = (
            "The system works. However, performance degrades under load. "
            "We tested three configurations. In production, the first two "
            "failed immediately. But the third survived. Barely. The "
            "engineers celebrated, though the victory felt hollow. By "
            "morning, the alerts had returned. Monitoring is essential. "
            "Very much so."
        )
        result = analyze_sentence_architecture(text)
        self.assertGreater(result["total_sentences"], 5)
        self.assertGreater(result["architecture_index"], 0.0)
        self.assertIn(result["architecture_class"],
                      ["masterful", "varied", "competent", "uniform", "monotonous"])

    def test_monotonous_text(self):
        text = (
            "The system processes data. The module handles requests. "
            "The service manages connections. The pipeline transforms "
            "records. The database stores results. The cache holds "
            "frequently accessed items. The API provides endpoints. "
            "The worker executes background tasks."
        )
        result = analyze_sentence_architecture(text)
        # All sentences start with "The" — low opening diversity
        self.assertLess(result["opening_diversity"], 0.3)

    def test_result_keys(self):
        result = analyze_sentence_architecture("Test sentence here.")
        expected_keys = {
            "total_sentences", "total_words", "length_cv",
            "opening_diversity", "active_ratio", "fragment_rate",
            "architecture_index", "architecture_class",
            "opening_distribution",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Stroke-level analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeArchitecture(unittest.TestCase):
    """Test analyze_stroke_architecture."""

    def test_with_text_field(self):
        stroke = {"text": "The system works well. We tested it thoroughly."}
        result = analyze_stroke_architecture(stroke)
        self.assertEqual(result["total_sentences"], 2)

    def test_with_content_field(self):
        stroke = {"content": "Hello world. How are you?"}
        result = analyze_stroke_architecture(stroke)
        self.assertEqual(result["total_sentences"], 2)

    def test_empty_stroke(self):
        stroke = {"text": ""}
        result = analyze_stroke_architecture(stroke)
        self.assertEqual(result["total_sentences"], 0)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


class TestArchitectureTrend(unittest.TestCase):
    """Test compute_architecture_trend and classify_trend."""

    def test_empty(self):
        result = compute_architecture_trend([])
        self.assertEqual(result["trend"], "no_data")

    def test_single_stroke(self):
        strokes = [{"text": "The system works well in production environments."}]
        result = compute_architecture_trend(strokes)
        self.assertEqual(result["trend"], "insufficient_data")

    def test_improving_trend(self):
        # Start with monotonous text, end with varied text
        strokes = []
        for _ in range(10):
            strokes.append({"text": "The system processes data. The module handles requests. The service works."})
        for _ in range(10):
            strokes.append({"text": (
                "However, the system performs well. In production, we tested three "
                "configurations. The first two failed. But the third survived. "
                "Barely. Engineers celebrated, though cautiously. By morning, "
                "the alerts had returned. Monitoring is essential. Very much so."
            )})
        result = compute_architecture_trend(strokes)
        self.assertIn(result["trend"], ["improving", "stable"])

    def test_classify_trend(self):
        self.assertEqual(classify_trend({"trend": "improving"}), "improving")
        self.assertEqual(classify_trend({"trend": "stable"}), "stable")
        self.assertEqual(classify_trend({}), "unknown")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test format_architecture_report."""

    def test_empty(self):
        result = {"total_sentences": 0}
        report = format_architecture_report(result)
        self.assertEqual(report, "No sentences to analyze.")

    def test_full_report(self):
        result = analyze_sentence_architecture(
            "The system works. However, it fails under load. We fixed it. "
            "In production, things got worse. But we recovered. Barely."
        )
        report = format_architecture_report(result)
        self.assertIn("Architecture:", report)
        self.assertIn("Index:", report)
        self.assertIn("Length CV:", report)
        self.assertIn("Opening diversity:", report)


# ---------------------------------------------------------------------------
# Session-level analysis
# ---------------------------------------------------------------------------


class TestSessionAnalysis(unittest.TestCase):
    """Test analyze_session_architecture."""

    def test_missing_file(self):
        result = analyze_session_architecture("/nonexistent/path.jsonl", writer="qwen")
        self.assertIn("error", result)

    def test_with_strokes_file(self):
        # Create a temporary strokes file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(5):
                stroke = {
                    "writer": "qwen",
                    "kind": "note",
                    "text": f"Stroke {i}. The system works well. However, we tested it. In production, things vary.",
                }
                f.write(json.dumps(stroke) + "\n")
            tmppath = f.name

        try:
            result = analyze_session_architecture(tmppath, writer="qwen")
            self.assertEqual(result["strokes_analyzed"], 5)
            self.assertIn("architecture_index", result)
            self.assertIn("architecture_class", result)
        finally:
            Path(tmppath).unlink()

    def test_no_matching_writer(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            stroke = {"writer": "other", "text": "Hello."}
            f.write(json.dumps(stroke) + "\n")
            tmppath = f.name

        try:
            result = analyze_session_architecture(tmppath, writer="qwen")
            self.assertIn("error", result)
        finally:
            Path(tmppath).unlink()


if __name__ == "__main__":
    unittest.main()
