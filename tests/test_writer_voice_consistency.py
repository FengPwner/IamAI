#!/usr/bin/env python3
"""Tests for writer_voice_consistency — voice stability as identity signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_voice_consistency import (  # noqa: E402
    BOOSTERS,
    FORMAL_MARKERS,
    FORMAL_NOMINALIZATIONS,
    HEDGES,
    IMPERATIVE_STARTERS,
    INFORMAL_COLLOQUIAL,
    INFORMAL_CONTRACTIONS,
    INFORMAL_INTERJECTIONS,
    READER_REF_PATTERNS,
    SELF_REF_PATTERNS,
    _count_formal,
    _count_informal,
    _count_pattern,
    _detect_pov,
    _empty_metrics,
    _get_stroke_text,
    _is_imperative,
    _split_sentences,
    _split_words,
    analyze_stroke_voice_consistency,
    analyze_voice_consistency,
    classify_trend,
    classify_voice_consistency,
    compute_hedging_consistency,
    compute_imperative_consistency,
    compute_pov_consistency,
    compute_register_consistency,
    compute_self_reference_stability,
    compute_voice_consistency_index,
    compute_voice_consistency_metrics,
    compute_voice_consistency_trend,
    format_voice_consistency_report,
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


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sentences = _split_sentences("First sentence. Second sentence.")
        self.assertEqual(len(sentences), 2)

    def test_single_word_filtered(self):
        sentences = _split_sentences("Hello. This is a test.")
        self.assertEqual(len(sentences), 1)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_exclamation_and_question(self):
        sentences = _split_sentences("What happened? It crashed! The server died.")
        self.assertEqual(len(sentences), 3)


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_text_key(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_content_key(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "hello")

    def test_body_key(self):
        self.assertEqual(_get_stroke_text({"body": "hello"}), "hello")

    def test_empty(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_whitespace_only(self):
        self.assertEqual(_get_stroke_text({"text": "   "}), "")

    def test_non_string(self):
        self.assertEqual(_get_stroke_text({"text": 42}), "")


# ---------------------------------------------------------------------------
# Helper: _count_pattern
# ---------------------------------------------------------------------------


class TestCountPattern(unittest.TestCase):
    """Test _count_pattern helper."""

    def test_basic(self):
        self.assertEqual(_count_pattern("hello world hello", ["hello"]), 2)

    def test_word_boundary(self):
        self.assertEqual(_count_pattern("helloworld hello", ["hello"]), 1)

    def test_empty(self):
        self.assertEqual(_count_pattern("", ["hello"]), 0)

    def test_multiple_patterns(self):
        self.assertEqual(
            _count_pattern("hello world foo bar", ["hello", "foo"]), 2
        )


# ---------------------------------------------------------------------------
# Helper: _detect_pov
# ---------------------------------------------------------------------------


class TestDetectPOV(unittest.TestCase):
    """Test _detect_pov helper."""

    def test_first_person(self):
        self.assertEqual(_detect_pov("i think the server crashed"), "first")

    def test_first_person_plural(self):
        self.assertEqual(_detect_pov("we deployed the fix"), "first")

    def test_second_person(self):
        self.assertEqual(_detect_pov("you should check the logs"), "second")

    def test_third_person(self):
        self.assertEqual(_detect_pov("he fixed the server at noon"), "third")

    def test_no_person(self):
        self.assertIsNone(_detect_pov("deployed successfully"))

    def test_first_and_second(self):
        # First person takes priority (narrator is present).
        self.assertEqual(
            _detect_pov("i think you should check the logs"), "first"
        )

    def test_third_person_plural(self):
        self.assertEqual(_detect_pov("they fixed the bug"), "third")


# ---------------------------------------------------------------------------
# Helper: _is_imperative
# ---------------------------------------------------------------------------


class TestIsImperative(unittest.TestCase):
    """Test _is_imperative helper."""

    def test_imperative_consider(self):
        self.assertTrue(_is_imperative("Consider the implications."))

    def test_imperative_note(self):
        self.assertTrue(_is_imperative("Note that this is important."))

    def test_imperative_avoid(self):
        self.assertTrue(_is_imperative("Avoid using global state."))

    def test_declarative(self):
        self.assertFalse(_is_imperative("The server crashed at noon."))

    def test_declarative_the(self):
        self.assertFalse(_is_imperative("The implementation is correct."))

    def test_empty(self):
        self.assertFalse(_is_imperative(""))


# ---------------------------------------------------------------------------
# Helper: _count_formal / _count_informal
# ---------------------------------------------------------------------------


class TestRegisterCounts(unittest.TestCase):
    """Test formal and informal counting helpers."""

    def test_formal_markers(self):
        text = "furthermore the implementation was consequently analyzed"
        count = _count_formal(text)
        self.assertGreaterEqual(count, 3)

    def test_formal_nominalizations(self):
        text = "the implementation and analysis were thorough"
        count = _count_formal(text)
        self.assertGreaterEqual(count, 2)

    def test_informal_contractions(self):
        text = "it's won't don't"
        count = _count_informal(text)
        self.assertGreaterEqual(count, 3)

    def test_informal_colloquial(self):
        text = "that's pretty cool stuff"
        count = _count_informal(text)
        self.assertGreaterEqual(count, 2)

    def test_informal_interjections(self):
        text = "wow oops yikes"
        count = _count_informal(text)
        self.assertGreaterEqual(count, 3)

    def test_mixed(self):
        text = "furthermore it's cool"
        formal = _count_formal(text)
        informal = _count_informal(text)
        self.assertGreaterEqual(formal, 1)
        self.assertGreaterEqual(informal, 1)


# ---------------------------------------------------------------------------
# Signal 1: POV consistency
# ---------------------------------------------------------------------------


class TestPOVConsistency(unittest.TestCase):
    """Test compute_pov_consistency."""

    def test_consistent_first_person(self):
        text = (
            "I wrote the module. I tested it thoroughly. "
            "I found three bugs. My code compiles."
        )
        score = compute_pov_consistency(text)
        self.assertGreaterEqual(score, 0.8)

    def test_consistent_third_person(self):
        text = (
            "The server crashed at noon. It had been running for 48 hours. "
            "The logs showed a memory leak. They traced it to the parser."
        )
        score = compute_pov_consistency(text)
        self.assertGreaterEqual(score, 0.75)

    def test_inconsistent_pov(self):
        text = (
            "I wrote the module. You should test it. "
            "The server crashed. We fixed the bug. "
            "They reviewed the code. You need to deploy."
        )
        score = compute_pov_consistency(text)
        self.assertLess(score, 0.7)

    def test_empty(self):
        score = compute_pov_consistency("")
        self.assertEqual(score, 0.5)

    def test_no_pov_detected(self):
        text = "Deployed successfully. Running smoothly. Compiles clean."
        score = compute_pov_consistency(text)
        self.assertEqual(score, 0.5)


# ---------------------------------------------------------------------------
# Signal 2: Register consistency
# ---------------------------------------------------------------------------


class TestRegisterConsistency(unittest.TestCase):
    """Test compute_register_consistency."""

    def test_purely_formal(self):
        text = (
            "Furthermore, the implementation was analyzed thoroughly. "
            "Consequently, the evaluation demonstrated significant improvement. "
            "The assessment and investigation confirmed the hypothesis."
        )
        score = compute_register_consistency(text)
        self.assertGreaterEqual(score, 0.9)

    def test_purely_informal(self):
        text = (
            "It's pretty cool stuff. Don't worry about it, won't crash. "
            "Wow, that's awesome. Kinda weird but totally fine."
        )
        score = compute_register_consistency(text)
        self.assertGreaterEqual(score, 0.9)

    def test_mixed_register(self):
        text = (
            "Furthermore, the implementation was analyzed. "
            "It's pretty cool stuff. Consequently, the evaluation. "
            "Wow, that's awesome. The investigation confirmed."
        )
        score = compute_register_consistency(text)
        self.assertLess(score, 0.7)

    def test_no_markers(self):
        text = "The server runs at port 8080. The database has 42 tables."
        score = compute_register_consistency(text)
        self.assertEqual(score, 0.7)  # neutral

    def test_empty(self):
        score = compute_register_consistency("")
        self.assertEqual(score, 0.7)


# ---------------------------------------------------------------------------
# Signal 3: Hedging consistency
# ---------------------------------------------------------------------------


class TestHedgingConsistency(unittest.TestCase):
    """Test compute_hedging_consistency."""

    def test_consistently_hedged(self):
        text = (
            "It seems the server might be overloaded. Perhaps the memory "
            "could be insufficient. It appears the parser may be leaking."
        )
        score = compute_hedging_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_consistently_boosted(self):
        text = (
            "The server will definitely crash. Clearly the memory is "
            "insufficient. Obviously the parser must be fixed. The bug "
            "will always cause failures."
        )
        score = compute_hedging_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_oscillating(self):
        text = (
            "Perhaps the server might be overloaded. Clearly it will "
            "definitely crash. Maybe the memory could be insufficient. "
            "Obviously the parser must absolutely be fixed. Possibly "
            "the network might fail. Certainly the database will crash."
        )
        score = compute_hedging_consistency(text)
        self.assertLess(score, 0.7)

    def test_single_sentence(self):
        text = "This is a single sentence."
        score = compute_hedging_consistency(text)
        self.assertEqual(score, 0.5)

    def test_no_hedges_or_boosters(self):
        text = (
            "The server runs at port 8080. The database stores records. "
            "The API responds in JSON format. The cache expires hourly."
        )
        score = compute_hedging_consistency(text)
        # No hedges or boosters → all stances are 0.0 → zero variance
        # → perfectly consistent (no oscillation).
        self.assertEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Signal 4: Imperative consistency
# ---------------------------------------------------------------------------


class TestImperativeConsistency(unittest.TestCase):
    """Test compute_imperative_consistency."""

    def test_consistently_imperative(self):
        text = (
            "Consider the implications. Note that this matters. "
            "Remember to test thoroughly. Avoid global state. "
            "Check the logs carefully. Verify the output."
        )
        score = compute_imperative_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_consistently_declarative(self):
        text = (
            "The server crashed at noon. The logs showed an error. "
            "The parser had a memory leak. The team fixed the bug. "
            "The deploy succeeded at midnight. The system recovered."
        )
        score = compute_imperative_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_mixed_imperative_declarative(self):
        text = (
            "Consider the implications. The server crashed at noon. "
            "Note that this matters. The logs showed an error. "
            "Remember to test. The parser had a bug. "
            "Avoid global state. The team fixed it. "
            "Check the logs. The system recovered. "
            "Verify the output. The deploy succeeded."
        )
        score = compute_imperative_consistency(text)
        # First half has more imperatives, second half has more declaratives
        # This should still be somewhat consistent since they alternate
        self.assertIsInstance(score, float)

    def test_short_text(self):
        text = "Consider this. Note that."
        score = compute_imperative_consistency(text)
        self.assertEqual(score, 0.5)  # too short

    def test_empty(self):
        score = compute_imperative_consistency("")
        self.assertEqual(score, 0.5)


# ---------------------------------------------------------------------------
# Signal 5: Self-reference stability
# ---------------------------------------------------------------------------


class TestSelfReferenceStability(unittest.TestCase):
    """Test compute_self_reference_stability."""

    def test_consistent_i(self):
        text = (
            "I wrote the module and I tested it. I think the parser "
            "needs work. I found three bugs in my implementation."
        )
        score = compute_self_reference_stability(text)
        self.assertGreaterEqual(score, 0.8)

    def test_consistent_we(self):
        text = (
            "We deployed the fix. Our team reviewed the code. "
            "We found the bug in our parser."
        )
        score = compute_self_reference_stability(text)
        self.assertGreaterEqual(score, 0.7)

    def test_mixed_self_reference(self):
        text = (
            "I wrote the module. We deployed the fix. The author "
            "recommends testing. This paper presents the analysis. "
            "I tested the parser. We reviewed the code."
        )
        score = compute_self_reference_stability(text)
        self.assertLess(score, 0.7)

    def test_no_self_reference(self):
        text = "The server crashed at noon. The database stores records."
        score = compute_self_reference_stability(text)
        self.assertEqual(score, 0.7)  # neutral

    def test_empty(self):
        score = compute_self_reference_stability("")
        self.assertEqual(score, 0.7)


# ---------------------------------------------------------------------------
# Composite: compute_voice_consistency_index
# ---------------------------------------------------------------------------


class TestVoiceConsistencyIndex(unittest.TestCase):
    """Test composite index computation."""

    def test_all_high(self):
        idx = compute_voice_consistency_index(0.9, 0.9, 0.9, 0.9, 0.9)
        self.assertAlmostEqual(idx, 0.9, places=3)

    def test_all_low(self):
        idx = compute_voice_consistency_index(0.1, 0.1, 0.1, 0.1, 0.1)
        self.assertAlmostEqual(idx, 0.1, places=3)

    def test_mixed(self):
        idx = compute_voice_consistency_index(1.0, 0.0, 0.5, 0.5, 0.5)
        expected = 1.0 * 0.25 + 0.0 * 0.25 + 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.15
        self.assertAlmostEqual(idx, expected, places=3)

    def test_weights_sum_to_one(self):
        idx = compute_voice_consistency_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(idx, 1.0, places=4)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyVoiceConsistency(unittest.TestCase):
    """Test classify_voice_consistency."""

    def test_unified(self):
        self.assertEqual(classify_voice_consistency(0.85), "unified")
        self.assertEqual(classify_voice_consistency(0.80), "unified")

    def test_consistent(self):
        self.assertEqual(classify_voice_consistency(0.70), "consistent")
        self.assertEqual(classify_voice_consistency(0.60), "consistent")

    def test_mixed(self):
        self.assertEqual(classify_voice_consistency(0.50), "mixed")
        self.assertEqual(classify_voice_consistency(0.40), "mixed")

    def test_wavering(self):
        self.assertEqual(classify_voice_consistency(0.30), "wavering")
        self.assertEqual(classify_voice_consistency(0.20), "wavering")

    def test_fractured(self):
        self.assertEqual(classify_voice_consistency(0.15), "fractured")
        self.assertEqual(classify_voice_consistency(0.0), "fractured")


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


class TestVoiceConsistencyMetrics(unittest.TestCase):
    """Test compute_voice_consistency_metrics."""

    def test_with_strokes(self):
        strokes = [
            {"text": "I wrote the module and tested it thoroughly."},
            {"text": "I found three bugs in the parser implementation."},
            {"text": "I think the server needs more memory allocation."},
            {"text": "I reviewed the logs and traced the memory leak."},
        ]
        metrics = compute_voice_consistency_metrics(strokes)
        self.assertGreater(metrics["strokes_analyzed"], 0)
        self.assertIn("voice_consistency_index", metrics)
        self.assertIn("classification", metrics)

    def test_empty_strokes(self):
        metrics = compute_voice_consistency_metrics([])
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["classification"], "mixed")

    def test_window_size(self):
        strokes = [{"text": f"Sentence {i} about the server."} for i in range(100)]
        metrics = compute_voice_consistency_metrics(strokes, window_size=20)
        self.assertLessEqual(metrics["strokes_analyzed"], 20)


# ---------------------------------------------------------------------------
# Empty metrics
# ---------------------------------------------------------------------------


class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics."""

    def test_keys(self):
        m = _empty_metrics()
        expected_keys = {
            "pov_consistency",
            "register_consistency",
            "hedging_consistency",
            "imperative_consistency",
            "self_reference_stability",
            "voice_consistency_index",
            "classification",
            "strokes_analyzed",
        }
        self.assertEqual(set(m.keys()), expected_keys)

    def test_values(self):
        m = _empty_metrics()
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["classification"], "mixed")


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


class TestVoiceConsistencyTrend(unittest.TestCase):
    """Test compute_voice_consistency_trend."""

    def test_short_text(self):
        strokes = [{"text": f"Sentence {i} about the server."} for i in range(5)]
        trend = compute_voice_consistency_trend(strokes, window_size=50)
        self.assertEqual(len(trend), 1)

    def test_longer_text(self):
        strokes = [
            {"text": f"I wrote sentence {i} about the server and tested it."}
            for i in range(100)
        ]
        trend = compute_voice_consistency_trend(strokes, window_size=20)
        self.assertGreater(len(trend), 1)

    def test_trend_structure(self):
        strokes = [{"text": "I wrote the server module."} for _ in range(10)]
        trend = compute_voice_consistency_trend(strokes, window_size=5)
        for entry in trend:
            self.assertIn("window_start", entry)
            self.assertIn("window_end", entry)
            self.assertIn("voice_consistency_index", entry)
            self.assertIn("classification", entry)


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend."""

    def test_stable_single(self):
        self.assertEqual(
            classify_trend([{"voice_consistency_index": 0.7}]), "stable"
        )

    def test_improving(self):
        trend = [
            {"voice_consistency_index": 0.3},
            {"voice_consistency_index": 0.3},
            {"voice_consistency_index": 0.8},
            {"voice_consistency_index": 0.8},
        ]
        self.assertEqual(classify_trend(trend), "improving")

    def test_declining(self):
        trend = [
            {"voice_consistency_index": 0.8},
            {"voice_consistency_index": 0.8},
            {"voice_consistency_index": 0.3},
            {"voice_consistency_index": 0.3},
        ]
        self.assertEqual(classify_trend(trend), "declining")

    def test_stable(self):
        trend = [
            {"voice_consistency_index": 0.65},
            {"voice_consistency_index": 0.65},
            {"voice_consistency_index": 0.65},
            {"voice_consistency_index": 0.65},
        ]
        self.assertEqual(classify_trend(trend), "stable")

    def test_empty(self):
        self.assertEqual(classify_trend([]), "stable")


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeVoiceConsistency(unittest.TestCase):
    """Test analyze_stroke_voice_consistency."""

    def test_normal_stroke(self):
        stroke = {
            "text": "I wrote the module and tested it. I found three bugs."
        }
        result = analyze_stroke_voice_consistency(stroke)
        self.assertIn("voice_consistency_index", result)
        self.assertEqual(result["strokes_analyzed"], 1)

    def test_empty_stroke(self):
        result = analyze_stroke_voice_consistency({})
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_whitespace_stroke(self):
        result = analyze_stroke_voice_consistency({"text": "   "})
        self.assertEqual(result["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test format_voice_consistency_report."""

    def test_normal_report(self):
        metrics = compute_voice_consistency_metrics(
            [{"text": "I wrote the module and tested it thoroughly."}]
        )
        report = format_voice_consistency_report(metrics)
        self.assertIn("Voice Consistency Report", report)
        self.assertIn("Voice Consistency Index", report)
        self.assertIn("POV Consistency", report)
        self.assertIn("Register Consistency", report)

    def test_empty_report(self):
        report = format_voice_consistency_report(_empty_metrics())
        self.assertEqual(report, "No strokes analyzed.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestAnalyzeVoiceConsistency(unittest.TestCase):
    """Test analyze_voice_consistency CLI."""

    def test_missing_file(self):
        result = analyze_voice_consistency(
            strokes_path="/nonexistent/path/strokes.jsonl"
        )
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_empty_strokes_list(self):
        # With an existing but irrelevant path
        result = analyze_voice_consistency(strokes_path="/dev/null")
        self.assertEqual(result["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for voice consistency."""

    def test_single_word_sentences(self):
        text = "Hello. World. Test."
        # All single-word sentences get filtered by _split_sentences.
        score = compute_pov_consistency(text)
        self.assertEqual(score, 0.5)  # neutral

    def test_all_hedges(self):
        text = "Perhaps maybe possibly it seems it appears arguably."
        score = compute_hedging_consistency(text)
        self.assertGreaterEqual(score, 0.5)

    def test_all_boosters(self):
        text = (
            "Clearly obviously undoubtedly certainly definitely. "
            "The server must will always never crash."
        )
        score = compute_hedging_consistency(text)
        self.assertGreaterEqual(score, 0.5)

    def test_very_long_text(self):
        text = "I wrote the module. " * 500
        score = compute_pov_consistency(text)
        self.assertGreaterEqual(score, 0.9)

    def test_unicode_handling(self):
        text = "The café résumé has naïve über-architects."
        score = compute_register_consistency(text)
        self.assertIsInstance(score, float)

    def test_repeated_markers(self):
        text = "however however however however however."
        # Should not crash.
        score = compute_register_consistency(text)
        self.assertIsInstance(score, float)


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    """Integration test: full pipeline from text to classification."""

    def test_unified_voice(self):
        text = (
            "I wrote the deployment script last Tuesday. I tested it "
            "against three environments. I found a race condition in the "
            "parser. I fixed the bug and redeployed. I monitored the "
            "logs for forty-eight hours."
        )
        pov = compute_pov_consistency(text)
        reg = compute_register_consistency(text)
        hed = compute_hedging_consistency(text)
        imp = compute_imperative_consistency(text)
        srs = compute_self_reference_stability(text)
        idx = compute_voice_consistency_index(pov, reg, hed, imp, srs)
        label = classify_voice_consistency(idx)
        # Consistent first-person, neutral register, no hedging/boosting
        # oscillation, no imperatives, stable self-reference.
        self.assertIn(label, ("unified", "consistent"))

    def test_fractured_voice(self):
        text = (
            "I wrote the module. You should test it. Furthermore, the "
            "implementation was analyzed. Wow, that's pretty cool stuff. "
            "Perhaps the server might be overloaded. Clearly it will "
            "definitely crash. Consider the implications. The author "
            "recommends thorough investigation. It's kinda weird."
        )
        pov = compute_pov_consistency(text)
        reg = compute_register_consistency(text)
        hed = compute_hedging_consistency(text)
        imp = compute_imperative_consistency(text)
        srs = compute_self_reference_stability(text)
        idx = compute_voice_consistency_index(pov, reg, hed, imp, srs)
        # Mixed POV, mixed register, oscillating hedging, mixed imperative,
        # mixed self-reference.
        self.assertLess(idx, 0.70)


if __name__ == "__main__":
    unittest.main()
