#!/usr/bin/env python3
"""Tests for writer_tension — 90 test cases."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_tension import (  # noqa: E402
    OPEN_LOOP_PATTERNS,
    RESOLUTION_MARKERS,
    STAKES_MARKERS,
    _classify_tension,
    _empty_metrics,
    _get_stroke_text,
    _resolution_delay_score,
    _reveal_score,
    _segment_words,
    _sentence_has_open_loop,
    _sentence_has_resolution,
    _split_sentences,
    _split_words,
    _stakes_score,
    analyze_stroke_tension,
    analyze_strokes,
    analyze_tension,
    classify_trend,
    compute_information_reveal_rate,
    compute_open_loop_density,
    compute_resolution_delay,
    compute_stakes_escalation,
    compute_tension_index,
    compute_tension_metrics,
    compute_tension_trend,
    count_open_loops,
    format_report,
    format_tension_report,
)


# ---------------------------------------------------------------------------
# Sample texts
# ---------------------------------------------------------------------------

HIGH_TENSION = (
    "What if the algorithm we trust most is the one most likely to fail? "
    "This question has haunted researchers for decades. "
    "If we assume that accuracy alone is sufficient, we miss the crucial point. "
    "The surprising result, as we will see, challenges every assumption. "
    "Imagine that a model achieves 99% accuracy but fails catastrophically "
    "on the remaining 1%. The key insight is that this 1% represents the "
    "cases that matter most. But at what cost do we pursue perfection? "
    "This raises the question of whether our metrics are fundamentally flawed. "
    "One might wonder if there is a better way to evaluate performance. "
    "The answer is both simple and profound: we must measure what matters."
)

LOW_TENSION = (
    "The temperature today is 72 degrees. "
    "The cat sat on the mat. "
    "Water boils at 100 degrees Celsius. "
    "The capital of France is Paris. "
    "Two plus two equals four. "
    "The earth revolves around the sun. "
    "Apples are a type of fruit. "
    "The sky is blue on clear days. "
    "Dogs are mammals. "
    "The library closes at nine."
)

ESCALATING_STAKES = (
    "The initial tests showed a minor discrepancy in the output values. "
    "This discrepancy was noted but considered insignificant at the time. "
    "However, the discrepancy grew larger with each subsequent run. "
    "The team began to worry that the underlying model might be flawed. "
    "This became important when the flawed outputs affected real users. "
    "The consequences were significant: thousands of incorrect predictions. "
    "Critically, the errors compounded over time, creating cascading failures. "
    "The vital question became whether the system could be fixed before "
    "the damage became irreversible. This was no longer a minor bug; "
    "it was a catastrophic failure that threatened the entire platform."
)

FLAT_STAKES = (
    "The catastrophic failure destroyed the entire database immediately. "
    "This was devastating and irreversible from the very start. "
    "The crucial issue was that no backups existed. "
    "The vital data was lost forever. "
    "This was a significant problem. "
    "The important thing was to learn from it. "
    "The team noted the lesson. "
    "They moved on to other tasks. "
    "The incident was filed. "
    "Normal operations resumed the next day."
)

MIXED_TENSION = (
    "The project began with a simple question: can machines learn to write? "
    "The team assembled data from various sources. "
    "Initial results were promising but inconclusive. "
    "This led to a deeper investigation of the training process. "
    "What follows is a detailed account of what we discovered. "
    "The model performed well on standard benchmarks. "
    "However, the key insight came from an unexpected source. "
    "A graduate student noticed a pattern in the error distribution. "
    "This pattern suggested that the model was learning shortcuts. "
    "The answer was to redesign the training objective entirely."
)


# ---------------------------------------------------------------------------
# Test: _split_words
# ---------------------------------------------------------------------------

class TestSplitWords(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_split_words("Hello world"), ["hello", "world"])

    def test_apostrophes(self):
        result = _split_words("don't won't")
        self.assertIn("don't", result)
        self.assertIn("won't", result)

    def test_empty(self):
        self.assertEqual(_split_words(""), [])

    def test_punctuation_stripped(self):
        result = _split_words("Hello, world! How are you?")
        self.assertEqual(result, ["hello", "world", "how", "are", "you"])


# ---------------------------------------------------------------------------
# Test: _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    def test_basic(self):
        result = _split_sentences("Hello world. How are you?")
        self.assertEqual(len(result), 2)

    def test_multiple_punctuation(self):
        result = _split_sentences("Really?! Yes!")
        self.assertTrue(len(result) >= 2)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_no_punctuation(self):
        result = _split_sentences("just one sentence no period")
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Test: _segment_words
# ---------------------------------------------------------------------------

class TestSegmentWords(unittest.TestCase):
    def test_exact_division(self):
        words = list(range(100))
        segs = _segment_words(words, 50)
        self.assertEqual(len(segs), 2)
        self.assertEqual(len(segs[0]), 50)

    def test_remainder(self):
        words = list(range(75))
        segs = _segment_words(words, 50)
        self.assertEqual(len(segs), 2)
        self.assertEqual(len(segs[1]), 25)

    def test_single_segment(self):
        words = list(range(10))
        segs = _segment_words(words, 50)
        self.assertEqual(len(segs), 1)


# ---------------------------------------------------------------------------
# Test: _get_stroke_text
# ---------------------------------------------------------------------------

class TestGetStrokeText(unittest.TestCase):
    def test_string_input(self):
        self.assertEqual(_get_stroke_text("hello"), "hello")

    def test_dict_text_key(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_content_key(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "hello")

    def test_empty_dict(self):
        self.assertEqual(_get_stroke_text({}), "")


# ---------------------------------------------------------------------------
# Test: count_open_loops
# ---------------------------------------------------------------------------

class TestCountOpenLoops(unittest.TestCase):
    def test_high_tension_text(self):
        count = count_open_loops(HIGH_TENSION)
        self.assertGreater(count, 5)

    def test_low_tension_text(self):
        count = count_open_loops(LOW_TENSION)
        self.assertEqual(count, 0)

    def test_question_mark(self):
        self.assertGreaterEqual(count_open_loops("Is this working?"), 1)

    def test_forward_reference(self):
        self.assertGreaterEqual(
            count_open_loops("As we will see later"), 1
        )

    def test_conditional(self):
        self.assertGreaterEqual(
            count_open_loops("If we assume that this is true"), 1
        )

    def test_anticipatory(self):
        self.assertGreaterEqual(
            count_open_loops("The surprising result is"), 1
        )

    def test_key_insight(self):
        self.assertGreaterEqual(
            count_open_loops("The key insight is that"), 1
        )

    def test_empty(self):
        self.assertEqual(count_open_loops(""), 0)


# ---------------------------------------------------------------------------
# Test: compute_open_loop_density
# ---------------------------------------------------------------------------

class TestOpenLoopDensity(unittest.TestCase):
    def test_high_tension_density(self):
        density = compute_open_loop_density(HIGH_TENSION)
        self.assertGreater(density, 3.0)

    def test_low_tension_density(self):
        density = compute_open_loop_density(LOW_TENSION)
        self.assertEqual(density, 0.0)

    def test_empty(self):
        self.assertEqual(compute_open_loop_density(""), 0.0)

    def test_short_text_with_question(self):
        density = compute_open_loop_density("Why?")
        self.assertGreater(density, 0.0)


# ---------------------------------------------------------------------------
# Test: _sentence_has_open_loop / _sentence_has_resolution
# ---------------------------------------------------------------------------

class TestSentenceHelpers(unittest.TestCase):
    def test_open_loop_question(self):
        self.assertTrue(_sentence_has_open_loop("Why does this happen?"))

    def test_open_loop_forward_ref(self):
        self.assertTrue(_sentence_has_open_loop("We will see this later"))

    def test_no_open_loop(self):
        self.assertFalse(_sentence_has_open_loop("The cat sat on the mat"))

    def test_resolution_therefore(self):
        self.assertTrue(_sentence_has_resolution("Therefore we conclude"))

    def test_resolution_the_answer(self):
        self.assertTrue(_sentence_has_resolution("The answer is simple"))

    def test_no_resolution(self):
        self.assertFalse(_sentence_has_resolution("The sky is blue"))


# ---------------------------------------------------------------------------
# Test: compute_resolution_delay
# ---------------------------------------------------------------------------

class TestResolutionDelay(unittest.TestCase):
    def test_text_with_resolution(self):
        text = (
            "What if we could fly? "
            "Scientists studied this for years. "
            "They tested many approaches. "
            "The answer is found in aerodynamics."
        )
        delay = compute_resolution_delay(text)
        self.assertGreater(delay, 0.0)
        self.assertLessEqual(delay, 4.0)

    def test_text_without_open_loops(self):
        delay = compute_resolution_delay(LOW_TENSION)
        self.assertEqual(delay, 0.0)

    def test_unresolved_loops(self):
        text = (
            "What if we could fly? "
            "The cat sat on the mat. "
            "Water boils at 100 degrees. "
            "The sky is blue. "
            "Dogs are mammals."
        )
        delay = compute_resolution_delay(text)
        self.assertEqual(delay, 20)  # max_lookback default

    def test_empty(self):
        self.assertEqual(compute_resolution_delay(""), 0.0)

    def test_immediate_resolution(self):
        text = (
            "What if we could fly? "
            "The answer is aerodynamics."
        )
        delay = compute_resolution_delay(text)
        self.assertEqual(delay, 1.0)


# ---------------------------------------------------------------------------
# Test: _resolution_delay_score
# ---------------------------------------------------------------------------

class TestResolutionDelayScore(unittest.TestCase):
    def test_zero_delay(self):
        self.assertEqual(_resolution_delay_score(0.0), 0.0)

    def test_ideal_delay(self):
        score = _resolution_delay_score(5.0)
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_short_delay(self):
        score = _resolution_delay_score(1.0)
        self.assertLess(score, 0.5)

    def test_long_delay(self):
        score = _resolution_delay_score(15.0)
        self.assertLess(score, 0.2)

    def test_moderate_delay(self):
        score = _resolution_delay_score(4.0)
        self.assertGreater(score, 0.7)


# ---------------------------------------------------------------------------
# Test: compute_stakes_escalation
# ---------------------------------------------------------------------------

class TestStakesEscalation(unittest.TestCase):
    def test_escalating(self):
        esc = compute_stakes_escalation(ESCALATING_STAKES)
        self.assertGreater(esc, 0.0)

    def test_deflating(self):
        esc = compute_stakes_escalation(FLAT_STAKES)
        self.assertLess(esc, 0.0)

    def test_short_text(self):
        esc = compute_stakes_escalation("Hello world")
        self.assertEqual(esc, 0.0)

    def test_empty(self):
        self.assertEqual(compute_stakes_escalation(""), 0.0)

    def test_range(self):
        esc = compute_stakes_escalation(HIGH_TENSION)
        self.assertGreaterEqual(esc, -1.0)
        self.assertLessEqual(esc, 1.0)


# ---------------------------------------------------------------------------
# Test: _stakes_score
# ---------------------------------------------------------------------------

class TestStakesScore(unittest.TestCase):
    def test_positive_escalation(self):
        self.assertAlmostEqual(_stakes_score(1.0), 1.0, places=3)

    def test_zero_escalation(self):
        self.assertAlmostEqual(_stakes_score(0.0), 0.5, places=3)

    def test_negative_escalation(self):
        self.assertAlmostEqual(_stakes_score(-1.0), 0.0, places=3)


# ---------------------------------------------------------------------------
# Test: compute_information_reveal_rate
# ---------------------------------------------------------------------------

class TestInformationRevealRate(unittest.TestCase):
    def test_front_loaded(self):
        # All new words at the start, repeated words later
        text = " ".join(
            ["alpha beta gamma delta epsilon"] * 1
            + ["alpha beta gamma delta epsilon"] * 5
        )
        cv = compute_information_reveal_rate(text, segment_size=5)
        self.assertGreater(cv, 0.5)

    def test_steady_reveal(self):
        # Each segment introduces roughly the same number of new words
        # Use purely alphabetic tokens so _split_words preserves uniqueness
        import string
        words = []
        for i in range(200):
            # Generate unique alpha-only words: aa, ab, ac, ..., zz, aaa, ...
            first = string.ascii_lowercase[i // 26]
            second = string.ascii_lowercase[i % 26]
            if i < 676:
                words.append(f"{first}{second}")
            else:
                third = string.ascii_lowercase[(i - 676) % 26]
                words.append(f"{first}{second}{third}")
        cv = compute_information_reveal_rate(" ".join(words), segment_size=50)
        # All unique words → each segment has ~50 new words → CV ~ 0
        self.assertLess(cv, 0.3)

    def test_short_text(self):
        cv = compute_information_reveal_rate("hello world")
        self.assertEqual(cv, 0.0)

    def test_empty(self):
        self.assertEqual(compute_information_reveal_rate(""), 0.0)


# ---------------------------------------------------------------------------
# Test: _reveal_score
# ---------------------------------------------------------------------------

class TestRevealScore(unittest.TestCase):
    def test_zero_cv(self):
        score = _reveal_score(0.0)
        self.assertEqual(score, 0.3)

    def test_ideal_cv(self):
        score = _reveal_score(0.35)
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_high_cv(self):
        score = _reveal_score(1.5)
        self.assertLess(score, 0.2)


# ---------------------------------------------------------------------------
# Test: compute_tension_index
# ---------------------------------------------------------------------------

class TestTensionIndex(unittest.TestCase):
    def test_high_tension_inputs(self):
        idx = compute_tension_index(2.0, 5.0, 0.8, 0.35)
        self.assertGreater(idx, 0.6)

    def test_low_tension_inputs(self):
        idx = compute_tension_index(0.0, 0.0, -0.8, 0.0)
        self.assertLess(idx, 0.3)

    def test_mixed_inputs(self):
        idx = compute_tension_index(1.0, 3.0, 0.0, 0.35)
        self.assertGreater(idx, 0.3)
        self.assertLess(idx, 0.8)

    def test_range(self):
        idx = compute_tension_index(10.0, 100.0, 1.0, 10.0)
        self.assertGreaterEqual(idx, 0.0)
        self.assertLessEqual(idx, 1.0)

    def test_all_zeros(self):
        idx = compute_tension_index(0.0, 0.0, 0.0, 0.0)
        self.assertLessEqual(idx, 0.3)


# ---------------------------------------------------------------------------
# Test: _classify_tension
# ---------------------------------------------------------------------------

class TestClassifyTension(unittest.TestCase):
    def test_gripping(self):
        self.assertEqual(_classify_tension(0.85), "gripping")
        self.assertEqual(_classify_tension(0.80), "gripping")

    def test_compelling(self):
        self.assertEqual(_classify_tension(0.70), "compelling")
        self.assertEqual(_classify_tension(0.65), "compelling")

    def test_steady(self):
        self.assertEqual(_classify_tension(0.55), "steady")
        self.assertEqual(_classify_tension(0.50), "steady")

    def test_flat(self):
        self.assertEqual(_classify_tension(0.40), "flat")
        self.assertEqual(_classify_tension(0.35), "flat")

    def test_stale(self):
        self.assertEqual(_classify_tension(0.20), "stale")
        self.assertEqual(_classify_tension(0.0), "stale")


# ---------------------------------------------------------------------------
# Test: analyze_stroke_tension
# ---------------------------------------------------------------------------

class TestAnalyzeStrokeTension(unittest.TestCase):
    def test_high_tension_stroke(self):
        result = analyze_stroke_tension(HIGH_TENSION)
        self.assertGreater(result["word_count"], 50)
        self.assertGreater(result["open_loop_count"], 3)
        self.assertIn(result["tension_class"],
                       ["gripping", "compelling", "steady", "flat", "stale"])

    def test_low_tension_stroke(self):
        result = analyze_stroke_tension(LOW_TENSION)
        self.assertEqual(result["open_loop_count"], 0)

    def test_string_input(self):
        result = analyze_stroke_tension("Hello world.")
        self.assertEqual(result["word_count"], 2)

    def test_dict_input(self):
        result = analyze_stroke_tension({"text": "Hello world."})
        self.assertEqual(result["word_count"], 2)

    def test_empty_input(self):
        result = analyze_stroke_tension("")
        self.assertEqual(result["word_count"], 0)
        self.assertEqual(result["tension_class"], "stale")

    def test_empty_dict(self):
        result = analyze_stroke_tension({})
        self.assertEqual(result["word_count"], 0)

    def test_result_keys(self):
        result = analyze_stroke_tension("Some text here.")
        expected_keys = {
            "word_count", "open_loop_density", "open_loop_count",
            "resolution_delay", "stakes_escalation",
            "information_reveal_rate", "tension_index", "tension_class",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Test: compute_tension_metrics (session-level)
# ---------------------------------------------------------------------------

class TestComputeTensionMetrics(unittest.TestCase):
    def test_multiple_strokes(self):
        strokes = [
            {"text": HIGH_TENSION},
            {"text": MIXED_TENSION},
            {"text": LOW_TENSION},
        ]
        result = compute_tension_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 3)
        self.assertGreater(result["total_words"], 100)
        self.assertIn(result["tension_class"],
                       ["gripping", "compelling", "steady", "flat", "stale"])

    def test_empty_strokes(self):
        result = compute_tension_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["tension_index"], 0.0)

    def test_window_size(self):
        strokes = [{"text": f"Sentence {i}."} for i in range(100)]
        result = compute_tension_metrics(strokes, window_size=20)
        self.assertEqual(result["strokes_analyzed"], 20)

    def test_class_distribution(self):
        strokes = [
            {"text": HIGH_TENSION},
            {"text": LOW_TENSION},
        ]
        result = compute_tension_metrics(strokes)
        self.assertIsInstance(result["class_distribution"], dict)

    def test_result_keys(self):
        result = compute_tension_metrics([{"text": "Hello."}])
        expected_keys = {
            "strokes_analyzed", "total_words", "tension_index",
            "tension_class", "avg_open_loop_density", "total_open_loops",
            "avg_resolution_delay", "avg_stakes_escalation",
            "avg_information_reveal_rate", "class_distribution",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Test: _empty_metrics
# ---------------------------------------------------------------------------

class TestEmptyMetrics(unittest.TestCase):
    def test_structure(self):
        result = _empty_metrics()
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["tension_index"], 0.0)
        self.assertEqual(result["tension_class"], "stale")
        self.assertEqual(result["class_distribution"], {})


# ---------------------------------------------------------------------------
# Test: compute_tension_trend
# ---------------------------------------------------------------------------

class TestTensionTrend(unittest.TestCase):
    def test_basic_trend(self):
        strokes = [{"text": HIGH_TENSION}] * 30 + [{"text": LOW_TENSION}] * 30
        snapshots = compute_tension_trend(strokes, window_size=20, step=10)
        self.assertGreater(len(snapshots), 1)
        for snap in snapshots:
            self.assertIn("window_start", snap)
            self.assertIn("tension_index", snap)

    def test_empty(self):
        self.assertEqual(compute_tension_trend([]), [])

    def test_window_start_field(self):
        strokes = [{"text": "Hello world."} for _ in range(50)]
        snapshots = compute_tension_trend(strokes, window_size=10, step=10)
        starts = [s["window_start"] for s in snapshots]
        self.assertEqual(starts, sorted(starts))


# ---------------------------------------------------------------------------
# Test: classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend(unittest.TestCase):
    def test_insufficient_data(self):
        self.assertEqual(classify_trend([]), "insufficient_data")
        self.assertEqual(classify_trend([{"tension_index": 0.5}]),
                         "insufficient_data")

    def test_building(self):
        snapshots = [
            {"tension_index": 0.3},
            {"tension_index": 0.3},
            {"tension_index": 0.5},
            {"tension_index": 0.6},
        ]
        self.assertEqual(classify_trend(snapshots), "building")

    def test_fading(self):
        snapshots = [
            {"tension_index": 0.7},
            {"tension_index": 0.7},
            {"tension_index": 0.4},
            {"tension_index": 0.3},
        ]
        self.assertEqual(classify_trend(snapshots), "fading")

    def test_stable(self):
        snapshots = [
            {"tension_index": 0.5},
            {"tension_index": 0.51},
            {"tension_index": 0.50},
            {"tension_index": 0.49},
        ]
        self.assertEqual(classify_trend(snapshots), "stable")


# ---------------------------------------------------------------------------
# Test: format_tension_report
# ---------------------------------------------------------------------------

class TestFormatTensionReport(unittest.TestCase):
    def test_report_contains_header(self):
        metrics = compute_tension_metrics([{"text": HIGH_TENSION}])
        report = format_tension_report(metrics)
        self.assertIn("=== Writer Tension ===", report)

    def test_report_contains_index(self):
        metrics = compute_tension_metrics([{"text": HIGH_TENSION}])
        report = format_tension_report(metrics)
        self.assertIn("Tension index:", report)

    def test_report_contains_interpretation(self):
        metrics = compute_tension_metrics([{"text": HIGH_TENSION}])
        report = format_tension_report(metrics)
        self.assertIn("Interpretation:", report)

    def test_report_with_class_distribution(self):
        metrics = compute_tension_metrics(
            [{"text": HIGH_TENSION}, {"text": LOW_TENSION}]
        )
        report = format_tension_report(metrics)
        self.assertIn("Class distribution:", report)

    def test_empty_report(self):
        report = format_tension_report(_empty_metrics())
        self.assertIn("Strokes analyzed: 0", report)


# ---------------------------------------------------------------------------
# Test: analyze_strokes (alias)
# ---------------------------------------------------------------------------

class TestAnalyzeStrokes(unittest.TestCase):
    def test_alias(self):
        strokes = [{"text": "Hello world."}]
        result = analyze_strokes(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)


# ---------------------------------------------------------------------------
# Test: format_report (alias)
# ---------------------------------------------------------------------------

class TestFormatReport(unittest.TestCase):
    def test_alias(self):
        metrics = _empty_metrics()
        report = format_report(metrics)
        self.assertIn("=== Writer Tension ===", report)


# ---------------------------------------------------------------------------
# Test: analyze_tension (file reader)
# ---------------------------------------------------------------------------

class TestAnalyzeTension(unittest.TestCase):
    def test_nonexistent_file(self):
        result = analyze_tension("/tmp/nonexistent_strokes_12345.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(10):
                f.write(json.dumps({
                    "text": f"Stroke number {i} contains some text about testing.",
                    "kind": "thought",
                }) + "\n")
            tmppath = f.name

        try:
            result = analyze_tension(tmppath, window_size=10)
            self.assertEqual(result["strokes_analyzed"], 10)
        finally:
            Path(tmppath).unlink()

    def test_malformed_lines(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("not valid json\n")
            f.write(json.dumps({"text": "valid line"}) + "\n")
            f.write("{broken\n")
            tmppath = f.name

        try:
            result = analyze_tension(tmppath, window_size=10)
            self.assertEqual(result["strokes_analyzed"], 1)
        finally:
            Path(tmppath).unlink()


# ---------------------------------------------------------------------------
# Test: Integration — high tension text scores higher than low tension
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def test_high_beats_low(self):
        high = compute_tension_metrics([{"text": HIGH_TENSION}])
        low = compute_tension_metrics([{"text": LOW_TENSION}])
        self.assertGreater(high["tension_index"], low["tension_index"])

    def test_escalating_beats_flat_stakes(self):
        esc = analyze_stroke_tension(ESCALATING_STAKES)
        flat = analyze_stroke_tension(FLAT_STAKES)
        self.assertGreater(esc["stakes_escalation"], flat["stakes_escalation"])

    def test_mixed_text_moderate_tension(self):
        result = analyze_stroke_tension(MIXED_TENSION)
        self.assertGreater(result["open_loop_count"], 0)
        self.assertIn(result["tension_class"],
                       ["gripping", "compelling", "steady", "flat", "stale"])

    def test_full_pipeline(self):
        strokes = [
            {"text": HIGH_TENSION, "kind": "thought"},
            {"text": MIXED_TENSION, "kind": "note"},
            {"text": ESCALATING_STAKES, "kind": "devlog"},
            {"text": LOW_TENSION, "kind": "snippet"},
        ]
        metrics = compute_tension_metrics(strokes)
        report = format_tension_report(metrics)
        trend = compute_tension_trend(strokes, window_size=2, step=2)
        trend_class = classify_trend(trend)

        self.assertIn(metrics["tension_class"],
                       ["gripping", "compelling", "steady", "flat", "stale"])
        self.assertIn(trend_class,
                       ["building", "stable", "fading", "insufficient_data"])
        self.assertIn("=== Writer Tension ===", report)
        self.assertGreater(len(report), 100)


if __name__ == "__main__":
    unittest.main()
