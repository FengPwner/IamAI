#!/usr/bin/env python3
"""Tests for writer_coherence — 65 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_coherence import (  # noqa: E402
    _bigrams,
    _classify_coherence,
    _classify_phase_arc,
    _compute_phase_scores,
    _get_stroke_text,
    _jaccard,
    _tokenize,
    _word_set,
    analyze_concept_threading,
    analyze_lexical_chaining,
    analyze_topic_stability,
    compute_coherence_metrics,
    count_active_threads,
    format_coherence_report,
)


# ---------------------------------------------------------------------------
# Helper: _tokenize
# ---------------------------------------------------------------------------

class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_basic_sentence(self):
        self.assertEqual(_tokenize("Hello World"), ["hello", "world"])

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_punctuation_stripped(self):
        tokens = _tokenize("foo, bar! baz.")
        self.assertEqual(tokens, ["foo", "bar", "baz"])

    def test_numbers_included(self):
        tokens = _tokenize("stroke 42 done")
        self.assertIn("42", tokens)

    def test_mixed_case(self):
        tokens = _tokenize("UPPER lower MiXeD")
        self.assertEqual(tokens, ["upper", "lower", "mixed"])

    def test_repeats_preserved(self):
        tokens = _tokenize("go go go")
        self.assertEqual(tokens, ["go", "go", "go"])

    def test_underscores(self):
        tokens = _tokenize("hello_world test")
        self.assertEqual(tokens, ["hello_world", "test"])


# ---------------------------------------------------------------------------
# Helper: _bigrams
# ---------------------------------------------------------------------------

class TestBigrams(unittest.TestCase):
    """Test _bigrams helper."""

    def test_basic(self):
        result = _bigrams(["a", "b", "c"])
        self.assertEqual(result, [("a", "b"), ("b", "c")])

    def test_single_token(self):
        self.assertEqual(_bigrams(["a"]), [])

    def test_empty(self):
        self.assertEqual(_bigrams([]), [])

    def test_two_tokens(self):
        self.assertEqual(_bigrams(["x", "y"]), [("x", "y")])

    def test_duplicates_preserved(self):
        result = _bigrams(["a", "b", "a", "b"])
        self.assertEqual(len(result), 3)

    def test_four_tokens(self):
        result = _bigrams(["a", "b", "c", "d"])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ("a", "b"))
        self.assertEqual(result[2], ("c", "d"))


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_text_key(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_content_key(self):
        self.assertEqual(_get_stroke_text({"content": "world"}), "world")

    def test_text_takes_precedence(self):
        self.assertEqual(
            _get_stroke_text({"text": "first", "content": "second"}),
            "first",
        )

    def test_empty_dict(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_none_text(self):
        self.assertEqual(_get_stroke_text({"text": None}), "")

    def test_integer_text(self):
        self.assertEqual(_get_stroke_text({"text": 42}), "42")


# ---------------------------------------------------------------------------
# Helper: _word_set
# ---------------------------------------------------------------------------

class TestWordSet(unittest.TestCase):
    """Test _word_set helper."""

    def test_basic(self):
        self.assertEqual(_word_set(["a", "b", "c"]), {"a", "b", "c"})

    def test_deduplication(self):
        self.assertEqual(_word_set(["a", "a", "b"]), {"a", "b"})

    def test_empty(self):
        self.assertEqual(_word_set([]), set())


# ---------------------------------------------------------------------------
# Helper: _jaccard
# ---------------------------------------------------------------------------

class TestJaccard(unittest.TestCase):
    """Test _jaccard similarity."""

    def test_identical_sets(self):
        s = {"a", "b", "c"}
        self.assertAlmostEqual(_jaccard(s, s), 1.0)

    def test_disjoint_sets(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial_overlap(self):
        # intersection = {b}, union = {a, b, c} → 1/3
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"b", "c"}), 1 / 3)

    def test_both_empty(self):
        self.assertAlmostEqual(_jaccard(set(), set()), 0.0)

    def test_one_empty(self):
        self.assertAlmostEqual(_jaccard({"a"}, set()), 0.0)

    def test_subset(self):
        # intersection = {a}, union = {a, b, c} → 1/3
        self.assertAlmostEqual(_jaccard({"a"}, {"a", "b", "c"}), 1 / 3)


# ---------------------------------------------------------------------------
# analyze_lexical_chaining
# ---------------------------------------------------------------------------

class TestLexicalChaining(unittest.TestCase):
    """Test analyze_lexical_chaining."""

    def test_identical_strokes(self):
        tokens = _tokenize("the cadence of the writing session")
        score = analyze_lexical_chaining(tokens, tokens)
        self.assertAlmostEqual(score, 1.0)

    def test_completely_different(self):
        a = _tokenize("cadence rhythm tempo")
        b = _tokenize("quantum physics entropy")
        score = analyze_lexical_chaining(a, b)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_overlap(self):
        a = _tokenize("the cadence drift was detected")
        b = _tokenize("cadence drift compensation module added")
        score = analyze_lexical_chaining(a, b)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_current(self):
        prev = _tokenize("hello world")
        self.assertAlmostEqual(analyze_lexical_chaining([], prev), 0.0)

    def test_empty_previous(self):
        curr = _tokenize("hello world")
        self.assertAlmostEqual(analyze_lexical_chaining(curr, []), 0.0)

    def test_both_empty(self):
        self.assertAlmostEqual(analyze_lexical_chaining([], []), 0.0)


# ---------------------------------------------------------------------------
# analyze_concept_threading
# ---------------------------------------------------------------------------

class TestConceptThreading(unittest.TestCase):
    """Test analyze_concept_threading."""

    def test_all_threaded(self):
        # All bigrams in current appear in lookback
        current = [("a", "b"), ("b", "c")]
        lookback = [[("a", "b"), ("b", "c"), ("c", "d")]]
        score = analyze_concept_threading(current, lookback)
        self.assertAlmostEqual(score, 1.0)

    def test_none_threaded(self):
        current = [("x", "y"), ("y", "z")]
        lookback = [[("a", "b"), ("b", "c")]]
        score = analyze_concept_threading(current, lookback)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_threading(self):
        current = [("a", "b"), ("x", "y")]
        lookback = [[("a", "b"), ("c", "d")]]
        score = analyze_concept_threading(current, lookback)
        self.assertAlmostEqual(score, 0.5)

    def test_empty_current(self):
        score = analyze_concept_threading([], [[("a", "b")]])
        self.assertAlmostEqual(score, 0.0)

    def test_empty_lookback(self):
        current = [("a", "b")]
        score = analyze_concept_threading(current, [])
        self.assertAlmostEqual(score, 0.0)

    def test_multiple_lookback_strokes(self):
        current = [("a", "b"), ("c", "d")]
        lookback = [
            [("a", "b")],
            [("e", "f")],
            [("c", "d")],
        ]
        score = analyze_concept_threading(current, lookback)
        self.assertAlmostEqual(score, 1.0)

    def test_scattered_lookback(self):
        current = [("a", "b"), ("c", "d"), ("e", "f")]
        lookback = [[("a", "b")], [("e", "f")]]
        score = analyze_concept_threading(current, lookback)
        self.assertAlmostEqual(score, 2 / 3)


# ---------------------------------------------------------------------------
# analyze_topic_stability
# ---------------------------------------------------------------------------

class TestTopicStability(unittest.TestCase):
    """Test analyze_topic_stability."""

    def test_identical_windows(self):
        window = [_tokenize("cadence drift rhythm tempo")]
        score = analyze_topic_stability(window, window)
        self.assertAlmostEqual(score, 1.0)

    def test_completely_different(self):
        w1 = [_tokenize("quantum physics entropy")]
        w2 = [_tokenize("cadence rhythm writing")]
        score = analyze_topic_stability(w1, w2)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_stability(self):
        w1 = [_tokenize("cadence drift and rhythm")]
        w2 = [_tokenize("cadence drift was detected")]
        score = analyze_topic_stability(w1, w2)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_multi_stroke_windows(self):
        w1 = [_tokenize("cadence rhythm"), _tokenize("tempo pace")]
        w2 = [_tokenize("cadence drift"), _tokenize("tempo speed")]
        score = analyze_topic_stability(w1, w2)
        self.assertGreater(score, 0.0)

    def test_empty_windows(self):
        self.assertAlmostEqual(analyze_topic_stability([], []), 0.0)

    def test_one_empty(self):
        w1 = [_tokenize("hello world")]
        self.assertAlmostEqual(analyze_topic_stability(w1, []), 0.0)


# ---------------------------------------------------------------------------
# count_active_threads
# ---------------------------------------------------------------------------

class TestCountActiveThreads(unittest.TestCase):
    """Test count_active_threads."""

    def test_no_strokes(self):
        self.assertEqual(count_active_threads([]), 0)

    def test_fewer_than_min_persistence(self):
        strokes = [
            {"text": "hello world"},
            {"text": "hello world"},
        ]
        self.assertEqual(count_active_threads(strokes, min_persistence=3), 0)

    def test_single_thread(self):
        # "hello world" appears in 3 strokes → 1 thread
        strokes = [
            {"text": "hello world foo"},
            {"text": "hello world bar"},
            {"text": "hello world baz"},
        ]
        count = count_active_threads(strokes, lookback=5, min_persistence=3)
        self.assertGreaterEqual(count, 1)

    def test_multiple_threads(self):
        strokes = [
            {"text": "cadence drift rhythm and tempo pace"},
            {"text": "cadence drift module added for tracking"},
            {"text": "rhythm and tempo detection improvements"},
            {"text": "cadence drift and rhythm monitoring system"},
        ]
        count = count_active_threads(strokes, lookback=5, min_persistence=3)
        self.assertGreaterEqual(count, 1)

    def test_lookback_window(self):
        # Bigram appears twice but outside lookback window
        strokes = [
            {"text": "alpha beta gamma"},
            {"text": "delta epsilon zeta"},
            {"text": "eta theta iota"},
            {"text": "kappa lambda mu"},
            {"text": "alpha beta nu"},
        ]
        # With small lookback, early occurrence may not be in window
        count_small = count_active_threads(
            strokes, lookback=2, min_persistence=2,
        )
        count_large = count_active_threads(
            strokes, lookback=6, min_persistence=2,
        )
        # Large lookback should find the thread, small might not
        self.assertGreaterEqual(count_large, count_small)

    def test_text_extraction(self):
        strokes = [
            {"content": "hello world test"},
            {"text": "hello world again"},
            {"text": "hello world more"},
        ]
        count = count_active_threads(strokes, lookback=5, min_persistence=3)
        self.assertGreaterEqual(count, 1)


# ---------------------------------------------------------------------------
# _classify_coherence
# ---------------------------------------------------------------------------

class TestClassifyCoherence(unittest.TestCase):
    """Test _classify_coherence."""

    def test_narrative(self):
        self.assertEqual(_classify_coherence(0.60), "narrative")
        self.assertEqual(_classify_coherence(0.85), "narrative")
        self.assertEqual(_classify_coherence(1.0), "narrative")

    def test_meandering(self):
        self.assertEqual(_classify_coherence(0.40), "meandering")
        self.assertEqual(_classify_coherence(0.50), "meandering")
        self.assertEqual(_classify_coherence(0.59), "meandering")

    def test_fragmented(self):
        self.assertEqual(_classify_coherence(0.20), "fragmented")
        self.assertEqual(_classify_coherence(0.30), "fragmented")
        self.assertEqual(_classify_coherence(0.39), "fragmented")

    def test_disjointed(self):
        self.assertEqual(_classify_coherence(0.0), "disjointed")
        self.assertEqual(_classify_coherence(0.10), "disjointed")
        self.assertEqual(_classify_coherence(0.19), "disjointed")

    def test_boundaries(self):
        # Exact boundary values
        self.assertEqual(_classify_coherence(0.60), "narrative")
        self.assertEqual(_classify_coherence(0.40), "meandering")
        self.assertEqual(_classify_coherence(0.20), "fragmented")


# ---------------------------------------------------------------------------
# _classify_phase_arc
# ---------------------------------------------------------------------------

class TestClassifyPhaseArc(unittest.TestCase):
    """Test _classify_phase_arc."""

    def test_steady(self):
        scores = [0.4, 0.4, 0.4, 0.4]
        self.assertEqual(_classify_phase_arc(scores), "steady")

    def test_rising(self):
        scores = [0.2, 0.3, 0.4, 0.5]
        self.assertEqual(_classify_phase_arc(scores), "rising")

    def test_falling(self):
        scores = [0.5, 0.4, 0.3, 0.2]
        self.assertEqual(_classify_phase_arc(scores), "falling")

    def test_oscillating(self):
        scores = [0.5, 0.2, 0.6, 0.1]
        self.assertEqual(_classify_phase_arc(scores), "oscillating")

    def test_slight_rise_is_steady(self):
        # Difference of 0.04 is below the 0.05 threshold
        scores = [0.40, 0.41, 0.42, 0.44]
        self.assertEqual(_classify_phase_arc(scores), "steady")

    def test_near_boundary(self):
        # Exactly 0.05 rise → rising
        scores = [0.30, 0.31, 0.33, 0.36]
        self.assertEqual(_classify_phase_arc(scores), "rising")


# ---------------------------------------------------------------------------
# _compute_phase_scores
# ---------------------------------------------------------------------------

class TestComputePhaseScores(unittest.TestCase):
    """Test _compute_phase_scores."""

    def test_empty(self):
        self.assertEqual(_compute_phase_scores([], [], []), [0.0, 0.0, 0.0, 0.0])

    def test_single_pair(self):
        scores = _compute_phase_scores([0.6], [0.4], [0.5])
        self.assertAlmostEqual(scores[0], 0.5)
        self.assertEqual(scores[1], 0.0)

    def test_four_pairs(self):
        lex = [0.1, 0.2, 0.3, 0.4]
        con = [0.1, 0.2, 0.3, 0.4]
        stab = [0.1, 0.2, 0.3, 0.4]
        scores = _compute_phase_scores(lex, con, stab)
        # Each quartile should have exactly one value
        self.assertEqual(len(scores), 4)

    def test_eight_pairs(self):
        lex = [0.1] * 8
        con = [0.2] * 8
        stab = [0.3] * 8
        scores = _compute_phase_scores(lex, con, stab)
        expected = (0.1 + 0.2 + 0.3) / 3.0
        for s in scores:
            self.assertAlmostEqual(s, expected)


# ---------------------------------------------------------------------------
# compute_coherence_metrics
# ---------------------------------------------------------------------------

class TestComputeCoherenceMetrics(unittest.TestCase):
    """Test compute_coherence_metrics session-level analysis."""

    def test_empty_strokes(self):
        m = compute_coherence_metrics([])
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["coherence_index"], 0.0)
        self.assertEqual(m["coherence_class"], "disjointed")
        self.assertEqual(m["thread_count"], 0)

    def test_single_stroke(self):
        m = compute_coherence_metrics([{"text": "hello world"}])
        self.assertEqual(m["strokes_analyzed"], 1)
        self.assertEqual(m["coherence_index"], 0.0)
        self.assertEqual(m["coherence_class"], "disjointed")

    def test_two_identical_strokes(self):
        strokes = [
            {"text": "the cadence drift module detects rhythm changes"},
            {"text": "the cadence drift module detects rhythm changes"},
        ]
        m = compute_coherence_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 2)
        # Identical strokes should have high lexical chaining
        self.assertGreater(m["lexical_chaining"], 0.5)

    def test_coherent_session(self):
        strokes = [
            {"text": "cadence drift detection measures rhythm deviation"},
            {"text": "cadence drift compensation adjusts the writing pace"},
            {"text": "the drift detection module monitors cadence changes"},
            {"text": "cadence compensation improves rhythm stability"},
            {"text": "rhythm stability is measured by drift detection"},
            {"text": "the cadence drift module provides stability metrics"},
            {"text": "detection of cadence drift enables better pacing"},
            {"text": "pacing improvements come from drift compensation data"},
        ]
        m = compute_coherence_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 8)
        self.assertGreater(m["coherence_index"], 0.0)
        self.assertIn(m["coherence_class"], [
            "narrative", "meandering", "fragmented", "disjointed",
        ])
        self.assertEqual(len(m["phase_scores"]), 4)
        self.assertIn(m["phase_arc"], ["steady", "rising", "falling", "oscillating"])

    def test_incoherent_session(self):
        strokes = [
            {"text": "quantum entanglement creates spooky action at distance"},
            {"text": "banana bread recipe requires ripe bananas and flour"},
            {"text": "mars rovers use solar panels for energy generation"},
            {"text": "ballet dancers practice pliés at the barre daily"},
            {"text": "coral reefs face bleaching from ocean temperature rise"},
            {"text": "medieval castles used moats for defensive purposes"},
            {"text": "jazz improvisation builds on chord progressions freely"},
            {"text": "volcanic eruptions release ash into the atmosphere"},
        ]
        m = compute_coherence_metrics(strokes)
        self.assertEqual(m["strokes_analyzed"], 8)
        # Unrelated topics should have low coherence
        self.assertLess(m["coherence_index"], 0.3)

    def test_metrics_keys(self):
        strokes = [
            {"text": "hello world test"},
            {"text": "hello world again"},
        ]
        m = compute_coherence_metrics(strokes)
        expected_keys = {
            "strokes_analyzed", "lexical_chaining", "concept_threading",
            "topic_stability", "coherence_index", "coherence_class",
            "thread_count", "phase_scores", "phase_arc",
        }
        self.assertEqual(set(m.keys()), expected_keys)

    def test_lookback_parameter(self):
        strokes = [
            {"text": "cadence drift rhythm"},
            {"text": "cadence drift tempo"},
            {"text": "cadence drift pace"},
            {"text": "cadence drift speed"},
        ]
        m1 = compute_coherence_metrics(strokes, lookback=2)
        m2 = compute_coherence_metrics(strokes, lookback=4)
        # Different lookback should produce different concept threading
        # (though may coincidentally be equal for some inputs)
        self.assertIsInstance(m1["concept_threading"], float)
        self.assertIsInstance(m2["concept_threading"], float)


# ---------------------------------------------------------------------------
# format_coherence_report
# ---------------------------------------------------------------------------

class TestFormatCoherenceReport(unittest.TestCase):
    """Test format_coherence_report."""

    def test_empty_metrics(self):
        m = compute_coherence_metrics([])
        report = format_coherence_report(m)
        self.assertIn("writer coherence", report)
        self.assertIn("strokes analyzed: 0", report)
        self.assertIn("disjointed", report)

    def test_with_data(self):
        strokes = [
            {"text": "cadence drift detection module added"},
            {"text": "cadence drift compensation adjusts pace"},
            {"text": "the drift module monitors changes"},
        ]
        m = compute_coherence_metrics(strokes)
        report = format_coherence_report(m)
        self.assertIn("writer coherence", report)
        self.assertIn("strokes analyzed: 3", report)
        self.assertIn("### signals", report)
        self.assertIn("### interpretation", report)
        self.assertIn("### phase analysis", report)

    def test_report_contains_all_sections(self):
        m = compute_coherence_metrics([
            {"text": "hello world test module"},
            {"text": "hello world again test"},
        ])
        report = format_coherence_report(m)
        for section in ["signals", "phase analysis", "interpretation"]:
            self.assertIn(section, report)

    def test_interpretation_narrative(self):
        m = {
            "coherence_class": "narrative",
            "thread_count": 5,
            "phase_arc": "steady",
            "strokes_analyzed": 20,
            "coherence_index": 0.7,
            "lexical_chaining": 0.6,
            "concept_threading": 0.7,
            "topic_stability": 0.8,
            "phase_scores": [0.6, 0.7, 0.7, 0.8],
        }
        report = format_coherence_report(m)
        self.assertIn("connective tissue", report)
        self.assertIn("steady", report)

    def test_interpretation_fragmented(self):
        m = {
            "coherence_class": "fragmented",
            "thread_count": 0,
            "phase_arc": "falling",
            "strokes_analyzed": 10,
            "coherence_index": 0.25,
            "lexical_chaining": 0.2,
            "concept_threading": 0.2,
            "topic_stability": 0.3,
            "phase_scores": [0.4, 0.3, 0.2, 0.1],
        }
        report = format_coherence_report(m)
        self.assertIn("jumps between topics", report)
        self.assertIn("no persistent concept threads", report)
        self.assertIn("lost coherence", report)


# ---------------------------------------------------------------------------
# Integration: coherent vs incoherent comparison
# ---------------------------------------------------------------------------

class TestCoherenceIntegration(unittest.TestCase):
    """Integration tests comparing coherent and incoherent sessions."""

    def test_coherent_scores_higher_than_incoherent(self):
        coherent = [
            {"text": "cadence drift detection measures rhythm"},
            {"text": "cadence drift compensation adjusts pace"},
            {"text": "the drift detection module monitors cadence"},
            {"text": "cadence compensation improves rhythm stability"},
            {"text": "rhythm stability is measured by the drift module"},
            {"text": "the cadence drift provides stability metrics"},
        ]
        incoherent = [
            {"text": "quantum entanglement spooky action distance"},
            {"text": "banana bread recipe ripe bananas flour"},
            {"text": "mars rovers solar panels energy generation"},
            {"text": "ballet dancers practice pliés barre daily"},
            {"text": "coral reefs bleaching ocean temperature rise"},
            {"text": "medieval castles moats defensive purposes"},
        ]

        m_coh = compute_coherence_metrics(coherent)
        m_inc = compute_coherence_metrics(incoherent)

        self.assertGreater(
            m_coh["coherence_index"],
            m_inc["coherence_index"],
            "Coherent session should score higher than incoherent",
        )

    def test_thread_count_higher_for_coherent(self):
        coherent = [
            {"text": "cadence drift detection module rhythm"},
            {"text": "cadence drift compensation module pace"},
            {"text": "cadence drift detection compensation rhythm"},
            {"text": "the drift module detection compensation"},
        ]
        incoherent = [
            {"text": "quantum physics entanglement"},
            {"text": "banana bread recipe"},
            {"text": "mars rovers solar"},
            {"text": "ballet dancers practice"},
        ]

        m_coh = compute_coherence_metrics(coherent)
        m_inc = compute_coherence_metrics(incoherent)

        self.assertGreaterEqual(
            m_coh["thread_count"],
            m_inc["thread_count"],
            "Coherent session should have at least as many threads",
        )

    def test_report_roundtrip(self):
        """Metrics produce a valid report string."""
        strokes = [
            {"text": "hello world test one"},
            {"text": "hello world test two"},
            {"text": "hello world test three"},
        ]
        m = compute_coherence_metrics(strokes)
        report = format_coherence_report(m)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 50)


if __name__ == "__main__":
    unittest.main()
