#!/usr/bin/env python3
"""Tests for writer_temporal_awareness — temporal awareness as time-consciousness signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_temporal_awareness import (  # noqa: E402
    ALL_TEMPORAL_MARKERS,
    CLOCK_TIME_RE,
    DURATION_PATTERNS,
    FLASHBACK_MARKERS,
    FUTURE_INDICATORS,
    ISO_DATE_RE,
    NAMED_MONTHS,
    PAST_TENSE_VERBS,
    PRESENT_TENSE_VERBS,
    TEMPORAL_FREQUENCY,
    TEMPORAL_POINT,
    TEMPORAL_SEQUENCE,
    _count_temporal_markers,
    _detect_tense,
    _extract_timestamp,
    _get_stroke_text,
    _has_duration,
    _has_flashback_marker,
    _has_temporal_anchor,
    _split_sentences,
    _split_words,
    _word_count,
    analyze_stroke_temporal_awareness,
    analyze_temporal_awareness,
    classify_temporal_awareness,
    classify_trend,
    compute_duration_awareness,
    compute_temporal_anchoring,
    compute_temporal_awareness_index,
    compute_temporal_awareness_metrics,
    compute_temporal_awareness_trend,
    compute_temporal_marker_density,
    compute_temporal_progression,
    compute_tense_consistency,
    format_temporal_awareness_report,
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

    def test_numbers_excluded(self):
        words = _split_words("test 42 data")
        self.assertEqual(words, ["test", "data"])

    def test_mixed_case(self):
        words = _split_words("Hello WORLD")
        self.assertEqual(words, ["hello", "world"])


# ---------------------------------------------------------------------------
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sentences = _split_sentences("First sentence. Second sentence.")
        self.assertEqual(len(sentences), 2)

    def test_question_marks(self):
        sentences = _split_sentences("Is this it? Yes it is.")
        self.assertEqual(len(sentences), 2)

    def test_abbreviation(self):
        sentences = _split_sentences("Dr. Smith went home. He was tired.")
        self.assertEqual(len(sentences), 2)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        sentences = _split_sentences("Just one sentence.")
        self.assertEqual(len(sentences), 1)


# ---------------------------------------------------------------------------
# Helper: _word_count
# ---------------------------------------------------------------------------


class TestWordCount(unittest.TestCase):
    """Test _word_count helper."""

    def test_basic(self):
        self.assertEqual(_word_count("one two three"), 3)

    def test_empty(self):
        self.assertEqual(_word_count(""), 0)

    def test_with_numbers(self):
        self.assertEqual(_word_count("test 42 data"), 2)


# ---------------------------------------------------------------------------
# Helper: _detect_tense
# ---------------------------------------------------------------------------


class TestDetectTense(unittest.TestCase):
    """Test _detect_tense helper."""

    def test_past_tense(self):
        self.assertEqual(
            _detect_tense("The server crashed and the deploy key expired."),
            "past",
        )

    def test_present_tense(self):
        self.assertEqual(
            _detect_tense("The server is running and the tests pass."),
            "present",
        )

    def test_future_tense(self):
        self.assertEqual(
            _detect_tense("The server will be deployed tomorrow."),
            "future",
        )

    def test_ambiguous(self):
        self.assertEqual(_detect_tense("Hello world"), "ambiguous")

    def test_mixed_dominant_past(self):
        result = _detect_tense("The deploy key expired and tests failed.")
        self.assertEqual(result, "past")

    def test_going_to_future(self):
        result = _detect_tense("We are going to deploy the fix.")
        self.assertIn(result, ["future", "present"])


# ---------------------------------------------------------------------------
# Helper: _has_temporal_anchor
# ---------------------------------------------------------------------------


class TestHasTemporalAnchor(unittest.TestCase):
    """Test _has_temporal_anchor helper."""

    def test_iso_date(self):
        self.assertTrue(_has_temporal_anchor("Deployed on 2026-11-12."))

    def test_iso_datetime(self):
        self.assertTrue(
            _has_temporal_anchor("Crashed at 2026-11-12T14:32:07Z.")
        )

    def test_clock_time(self):
        self.assertTrue(_has_temporal_anchor("The server crashed at 14:32."))

    def test_named_period(self):
        self.assertTrue(_has_temporal_anchor("Last week we deployed."))

    def test_this_morning(self):
        self.assertTrue(_has_temporal_anchor("This morning the tests ran."))

    def test_named_month(self):
        self.assertTrue(_has_temporal_anchor("In October we shipped."))

    def test_relative_time(self):
        self.assertTrue(_has_temporal_anchor("Three days ago the key expired."))

    def test_no_anchor(self):
        self.assertFalse(_has_temporal_anchor("The server crashed."))

    def test_generic_word(self):
        self.assertFalse(_has_temporal_anchor("Things happened recently."))


# ---------------------------------------------------------------------------
# Helper: _extract_timestamp
# ---------------------------------------------------------------------------


class TestExtractTimestamp(unittest.TestCase):
    """Test _extract_timestamp helper."""

    def test_iso_date(self):
        ts = _extract_timestamp("Deployed on 2026-11-12.")
        self.assertIsNotNone(ts)
        self.assertAlmostEqual(ts, 20261112.0, delta=1.0)

    def test_clock_time(self):
        ts = _extract_timestamp("Crashed at 14:32.")
        self.assertIsNotNone(ts)
        self.assertEqual(ts, 14 * 3600 + 32 * 60)

    def test_no_timestamp(self):
        ts = _extract_timestamp("The server crashed.")
        self.assertIsNone(ts)

    def test_ordering(self):
        ts1 = _extract_timestamp("Started at 2026-11-11.")
        ts2 = _extract_timestamp("Finished at 2026-11-12.")
        self.assertIsNotNone(ts1)
        self.assertIsNotNone(ts2)
        self.assertGreater(ts2, ts1)


# ---------------------------------------------------------------------------
# Helper: _has_flashback_marker
# ---------------------------------------------------------------------------


class TestHasFlashbackMarker(unittest.TestCase):
    """Test _has_flashback_marker helper."""

    def test_previously(self):
        self.assertTrue(_has_flashback_marker("Previously, the key was valid."))

    def test_earlier(self):
        self.assertTrue(_has_flashback_marker("Earlier today we tested."))

    def test_no_marker(self):
        self.assertFalse(_has_flashback_marker("The key expired."))


# ---------------------------------------------------------------------------
# Helper: _has_duration
# ---------------------------------------------------------------------------


class TestHasDuration(unittest.TestCase):
    """Test _has_duration helper."""

    def test_for_hours(self):
        self.assertTrue(_has_duration("The server ran for 48 hours."))

    def test_three_days(self):
        self.assertTrue(_has_duration("Deployed three days ago."))

    def test_seconds(self):
        self.assertTrue(_has_duration("Completed in 2.5 seconds."))

    def test_a_while(self):
        self.assertTrue(_has_duration("It took a while."))

    def test_last_week(self):
        self.assertTrue(_has_duration("Over the last 7 days."))

    def test_no_duration(self):
        self.assertFalse(_has_duration("The server crashed."))


# ---------------------------------------------------------------------------
# Helper: _count_temporal_markers
# ---------------------------------------------------------------------------


class TestCountTemporalMarkers(unittest.TestCase):
    """Test _count_temporal_markers helper."""

    def test_no_markers(self):
        self.assertEqual(_count_temporal_markers("The server crashed."), 0)

    def test_single_marker(self):
        self.assertEqual(_count_temporal_markers("Then the server crashed."), 1)

    def test_multiple_markers(self):
        text = "Then the server crashed. After the restart, it was fine."
        count = _count_temporal_markers(text)
        self.assertGreaterEqual(count, 2)

    def test_case_insensitive(self):
        self.assertEqual(_count_temporal_markers("NOW it works."), 1)


# ---------------------------------------------------------------------------
# Signal 1: Tense consistency
# ---------------------------------------------------------------------------


class TestTenseConsistency(unittest.TestCase):
    """Test compute_tense_consistency."""

    def test_consistent_past(self):
        text = (
            "The server crashed. The deploy key expired. "
            "Tests failed at 14:32. The team investigated."
        )
        score = compute_tense_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_consistent_present(self):
        text = (
            "The server is running. The tests pass. "
            "The deploy key is valid. Everything works."
        )
        score = compute_tense_consistency(text)
        self.assertGreaterEqual(score, 0.7)

    def test_inconsistent_tense(self):
        text = (
            "The server crashed. Now the tests pass. "
            "The key was expired. The deploy is running. "
            "It had failed. The team makes a fix."
        )
        score = compute_tense_consistency(text)
        self.assertLessEqual(score, 0.8)

    def test_legitimate_shift(self):
        text = (
            "The server crashed yesterday. Currently it is running. "
            "Previously the key had expired."
        )
        score = compute_tense_consistency(text)
        self.assertGreaterEqual(score, 0.5)

    def test_single_sentence(self):
        score = compute_tense_consistency("The server crashed.")
        self.assertEqual(score, 1.0)

    def test_empty(self):
        score = compute_tense_consistency("")
        self.assertEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Signal 2: Temporal anchoring
# ---------------------------------------------------------------------------


class TestTemporalAnchoring(unittest.TestCase):
    """Test compute_temporal_anchoring."""

    def test_fully_anchored(self):
        text = (
            "On 2026-11-12 the server crashed. "
            "At 14:32 the deploy key expired. "
            "Last week we had tested successfully."
        )
        score = compute_temporal_anchoring(text)
        self.assertGreaterEqual(score, 0.8)

    def test_no_anchoring(self):
        text = (
            "The server crashed. The deploy key expired. "
            "Tests failed. The team investigated."
        )
        score = compute_temporal_anchoring(text)
        self.assertLessEqual(score, 0.2)

    def test_partial_anchoring(self):
        text = (
            "On 2026-11-12 the server crashed. "
            "The deploy key expired. The team investigated."
        )
        score = compute_temporal_anchoring(text)
        self.assertGreater(score, 0.2)
        self.assertLess(score, 0.8)

    def test_empty(self):
        score = compute_temporal_anchoring("")
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------------
# Signal 3: Temporal progression
# ---------------------------------------------------------------------------


class TestTemporalProgression(unittest.TestCase):
    """Test compute_temporal_progression."""

    def test_forward_progression(self):
        text = (
            "Started at 2026-11-10. "
            "Deployed at 2026-11-11. "
            "Shipped at 2026-11-12."
        )
        score = compute_temporal_progression(text)
        self.assertGreaterEqual(score, 0.8)

    def test_backward_without_marker(self):
        text = (
            "Shipped at 2026-11-12. "
            "Deployed at 2026-11-11. "
            "Started at 2026-11-10."
        )
        score = compute_temporal_progression(text)
        self.assertLessEqual(score, 0.5)

    def test_backward_with_flashback(self):
        text = (
            "Shipped at 2026-11-12. "
            "Previously, at 2026-11-11, the deploy had succeeded."
        )
        score = compute_temporal_progression(text)
        self.assertGreaterEqual(score, 0.5)

    def test_no_timestamps(self):
        text = "The server crashed. The deploy key expired."
        score = compute_temporal_progression(text)
        self.assertEqual(score, 0.5)

    def test_single_sentence(self):
        score = compute_temporal_progression("Started at 2026-11-12.")
        self.assertEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Signal 4: Duration awareness
# ---------------------------------------------------------------------------


class TestDurationAwareness(unittest.TestCase):
    """Test compute_duration_awareness."""

    def test_with_durations(self):
        text = (
            "The server ran for 48 hours before crashing. "
            "The deploy took 2.5 seconds. "
            "Recovery happened three days later. "
            "The team worked over the past 12 hours. "
            "The fix took a while. "
            "The outage lasted for 3 hours."
        )
        score = compute_duration_awareness(text)
        self.assertGreater(score, 0.5)

    def test_no_durations(self):
        text = "The server crashed. The deploy key expired. Tests failed."
        score = compute_duration_awareness(text)
        self.assertEqual(score, 0.0)

    def test_single_duration(self):
        text = (
            "The server crashed. The deploy key expired. "
            "The outage lasted for 3 hours. Tests were re-run."
        )
        score = compute_duration_awareness(text)
        self.assertGreater(score, 0.0)

    def test_empty(self):
        score = compute_duration_awareness("")
        self.assertEqual(score, 0.0)

    def test_short_text(self):
        score = compute_duration_awareness("Hello world")
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------------
# Signal 5: Temporal marker density
# ---------------------------------------------------------------------------


class TestTemporalMarkerDensity(unittest.TestCase):
    """Test compute_temporal_marker_density."""

    def test_high_density(self):
        text = (
            "Then the server crashed. After the restart, "
            "meanwhile the tests ran. Currently everything works. "
            "Previously the key had expired. Now it is valid. "
            "Before the deploy, always check the key. "
            "Finally the system stabilized."
        )
        score = compute_temporal_marker_density(text)
        self.assertGreater(score, 0.5)

    def test_no_markers(self):
        text = "The server crashed. The deploy key expired. Tests failed."
        score = compute_temporal_marker_density(text)
        self.assertEqual(score, 0.0)

    def test_empty(self):
        score = compute_temporal_marker_density("")
        self.assertEqual(score, 0.0)

    def test_capped_at_one(self):
        # Fill with many temporal markers in few words
        markers = " ".join(ALL_TEMPORAL_MARKERS[:20])
        score = compute_temporal_marker_density(markers)
        self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


class TestComputeTemporalAwarenessIndex(unittest.TestCase):
    """Test compute_temporal_awareness_index."""

    def test_all_high(self):
        idx = compute_temporal_awareness_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(idx, 1.0)

    def test_all_zero(self):
        idx = compute_temporal_awareness_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(idx, 0.0)

    def test_weighted(self):
        # Only temporal anchoring (weight 0.30) = 1.0, rest = 0.0
        idx = compute_temporal_awareness_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(idx, 0.30)

    def test_mixed(self):
        idx = compute_temporal_awareness_index(0.8, 0.6, 0.7, 0.4, 0.5)
        expected = 0.8 * 0.20 + 0.6 * 0.30 + 0.7 * 0.20 + 0.4 * 0.15 + 0.5 * 0.15
        self.assertAlmostEqual(idx, round(expected, 4))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyTemporalAwareness(unittest.TestCase):
    """Test classify_temporal_awareness."""

    def test_chronological(self):
        self.assertEqual(classify_temporal_awareness(0.85), "chronological")
        self.assertEqual(classify_temporal_awareness(0.80), "chronological")

    def test_grounded(self):
        self.assertEqual(classify_temporal_awareness(0.75), "grounded")
        self.assertEqual(classify_temporal_awareness(0.60), "grounded")

    def test_adequate(self):
        self.assertEqual(classify_temporal_awareness(0.55), "adequate")
        self.assertEqual(classify_temporal_awareness(0.40), "adequate")

    def test_vague(self):
        self.assertEqual(classify_temporal_awareness(0.35), "vague")
        self.assertEqual(classify_temporal_awareness(0.20), "vague")

    def test_timeless(self):
        self.assertEqual(classify_temporal_awareness(0.15), "timeless")
        self.assertEqual(classify_temporal_awareness(0.0), "timeless")


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------


class TestComputeTemporalAwarenessMetrics(unittest.TestCase):
    """Test compute_temporal_awareness_metrics."""

    def test_with_temporal_strokes(self):
        strokes = [
            {"text": f"On 2026-11-{10 + i} the server was deployed. "
                      f"Then it ran for {i + 1} hours. "
                      f"Currently everything works."}
            for i in range(5)
        ]
        metrics = compute_temporal_awareness_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 5)
        self.assertIn("temporal_awareness_index", metrics)
        self.assertIn("classification", metrics)
        self.assertGreater(metrics["temporal_anchoring"], 0.0)

    def test_with_vague_strokes(self):
        strokes = [
            {"text": "The server crashed. Things broke. Problems occurred."}
            for _ in range(5)
        ]
        metrics = compute_temporal_awareness_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 5)
        self.assertLessEqual(metrics["temporal_anchoring"], 0.2)

    def test_empty_strokes(self):
        metrics = compute_temporal_awareness_metrics([])
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["classification"], "vague")

    def test_window_size(self):
        strokes = [
            {"text": f"On 2026-11-{10 + i} the server was deployed."}
            for i in range(100)
        ]
        metrics = compute_temporal_awareness_metrics(strokes, window_size=20)
        self.assertEqual(metrics["strokes_analyzed"], 20)

    def test_textless_strokes(self):
        strokes = [{"seq": 1}, {"seq": 2}]
        metrics = compute_temporal_awareness_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


class TestComputeTemporalAwarenessTrend(unittest.TestCase):
    """Test compute_temporal_awareness_trend."""

    def test_short_input(self):
        strokes = [{"text": "On 2026-11-12 the server crashed."}]
        trend = compute_temporal_awareness_trend(strokes)
        self.assertEqual(len(trend), 1)

    def test_windowed_trend(self):
        strokes = [
            {"text": f"On 2026-11-{10 + (i % 28)} the server was deployed. "
                      f"Then it ran for {i} hours."}
            for i in range(100)
        ]
        trend = compute_temporal_awareness_trend(strokes, window_size=20)
        self.assertGreater(len(trend), 1)
        for t in trend:
            self.assertIn("temporal_awareness_index", t)
            self.assertIn("classification", t)


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend."""

    def test_stable(self):
        trend = [
            {"temporal_awareness_index": 0.5},
            {"temporal_awareness_index": 0.5},
        ]
        self.assertEqual(classify_trend(trend), "stable")

    def test_improving(self):
        trend = [
            {"temporal_awareness_index": 0.3},
            {"temporal_awareness_index": 0.3},
            {"temporal_awareness_index": 0.8},
            {"temporal_awareness_index": 0.8},
        ]
        self.assertEqual(classify_trend(trend), "improving")

    def test_declining(self):
        trend = [
            {"temporal_awareness_index": 0.8},
            {"temporal_awareness_index": 0.8},
            {"temporal_awareness_index": 0.3},
            {"temporal_awareness_index": 0.3},
        ]
        self.assertEqual(classify_trend(trend), "declining")

    def test_single_entry(self):
        trend = [{"temporal_awareness_index": 0.5}]
        self.assertEqual(classify_trend(trend), "stable")


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeTemporalAwareness(unittest.TestCase):
    """Test analyze_stroke_temporal_awareness."""

    def test_temporal_stroke(self):
        stroke = {
            "text": "On 2026-11-12 at 14:32 the server crashed. "
                    "Previously the key had been valid for 48 hours. "
                    "Then the team investigated."
        }
        metrics = analyze_stroke_temporal_awareness(stroke)
        self.assertEqual(metrics["strokes_analyzed"], 1)
        self.assertGreater(metrics["temporal_anchoring"], 0.0)
        self.assertGreater(metrics["temporal_marker_density"], 0.0)

    def test_vague_stroke(self):
        stroke = {"text": "Things happened. Problems occurred. Stuff broke."}
        metrics = analyze_stroke_temporal_awareness(stroke)
        self.assertEqual(metrics["strokes_analyzed"], 1)
        self.assertEqual(metrics["temporal_anchoring"], 0.0)

    def test_empty_stroke(self):
        stroke = {"text": ""}
        metrics = analyze_stroke_temporal_awareness(stroke)
        self.assertEqual(metrics["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestFormatTemporalAwarenessReport(unittest.TestCase):
    """Test format_temporal_awareness_report."""

    def test_with_metrics(self):
        metrics = {
            "temporal_awareness_index": 0.65,
            "classification": "grounded",
            "tense_consistency": 0.8,
            "temporal_anchoring": 0.7,
            "temporal_progression": 0.6,
            "duration_awareness": 0.4,
            "temporal_marker_density": 0.5,
            "strokes_analyzed": 50,
        }
        report = format_temporal_awareness_report(metrics)
        self.assertIn("Temporal Awareness Report", report)
        self.assertIn("grounded", report)
        self.assertIn("50 strokes", report)

    def test_empty_metrics(self):
        metrics = {
            "temporal_awareness_index": 0.25,
            "classification": "vague",
            "tense_consistency": 1.0,
            "temporal_anchoring": 0.0,
            "temporal_progression": 0.5,
            "duration_awareness": 0.0,
            "temporal_marker_density": 0.0,
            "strokes_analyzed": 0,
        }
        report = format_temporal_awareness_report(metrics)
        self.assertEqual(report, "No strokes analyzed.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestAnalyzeTemporalAwareness(unittest.TestCase):
    """Test analyze_temporal_awareness CLI."""

    def test_nonexistent_file(self):
        metrics = analyze_temporal_awareness("/nonexistent/path.jsonl")
        self.assertEqual(metrics["strokes_analyzed"], 0)

    def test_real_file(self):
        strokes_path = REPO / "data" / "strokes.jsonl"
        if strokes_path.exists():
            metrics = analyze_temporal_awareness(str(strokes_path), window_size=10)
            self.assertIn("temporal_awareness_index", metrics)
            self.assertIn("classification", metrics)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Test that constant lists are non-empty and well-formed."""

    def test_temporal_point_nonempty(self):
        self.assertGreater(len(TEMPORAL_POINT), 0)

    def test_temporal_sequence_nonempty(self):
        self.assertGreater(len(TEMPORAL_SEQUENCE), 0)

    def test_temporal_frequency_nonempty(self):
        self.assertGreater(len(TEMPORAL_FREQUENCY), 0)

    def test_all_markers_combined(self):
        combined = set(TEMPORAL_POINT) | set(TEMPORAL_SEQUENCE) | set(TEMPORAL_FREQUENCY)
        self.assertEqual(len(ALL_TEMPORAL_MARKERS), len(combined))

    def test_flashback_markers_nonempty(self):
        self.assertGreater(len(FLASHBACK_MARKERS), 0)

    def test_past_tense_verbs_nonempty(self):
        self.assertGreater(len(PAST_TENSE_VERBS), 0)

    def test_present_tense_verbs_nonempty(self):
        self.assertGreater(len(PRESENT_TENSE_VERBS), 0)

    def test_future_indicators_nonempty(self):
        self.assertGreater(len(FUTURE_INDICATORS), 0)

    def test_named_months_count(self):
        self.assertEqual(len(NAMED_MONTHS), 24)  # 12 full + 12 abbreviations

    def test_duration_patterns_nonempty(self):
        self.assertGreater(len(DURATION_PATTERNS), 0)

    def test_iso_date_regex(self):
        self.assertTrue(ISO_DATE_RE.search("2026-11-12"))
        self.assertTrue(ISO_DATE_RE.search("2026-11-12T14:32:07Z"))
        self.assertIsNone(ISO_DATE_RE.search("not a date"))

    def test_clock_time_regex(self):
        self.assertTrue(CLOCK_TIME_RE.search("14:32"))
        self.assertTrue(CLOCK_TIME_RE.search("9:00 AM"))
        self.assertIsNone(CLOCK_TIME_RE.search("not a time"))


# ---------------------------------------------------------------------------
# Helper: _get_stroke_text
# ---------------------------------------------------------------------------


class TestGetStrokeText(unittest.TestCase):
    """Test _get_stroke_text helper."""

    def test_dict_with_text(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_dict_without_text(self):
        self.assertEqual(_get_stroke_text({"seq": 1}), "")

    def test_empty_dict(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_non_dict(self):
        self.assertEqual(_get_stroke_text("not a dict"), "")


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline(unittest.TestCase):
    """Integration test for the full temporal awareness pipeline."""

    def test_chronological_writing(self):
        strokes = [
            {"text": "On 2026-11-10 the deploy key was generated. "
                      "Then the team configured the server."},
            {"text": "On 2026-11-11 the server was deployed. "
                      "After the restart, tests passed for 2 hours."},
            {"text": "On 2026-11-12 the deploy key expired at 14:32. "
                      "The server crashed. Currently the team is investigating."},
        ]
        metrics = compute_temporal_awareness_metrics(strokes)
        self.assertGreater(metrics["temporal_anchoring"], 0.3)
        self.assertIn(metrics["classification"],
                      ["chronological", "grounded", "adequate"])

    def test_timeless_writing(self):
        strokes = [
            {"text": "Servers crash. Deploy keys expire. Things break."},
            {"text": "Problems occur. Systems fail. Errors happen."},
            {"text": "Bugs exist. Tests fail. Code breaks."},
        ]
        metrics = compute_temporal_awareness_metrics(strokes)
        self.assertLessEqual(metrics["temporal_anchoring"], 0.2)
        self.assertIn(metrics["classification"], ["timeless", "vague"])


if __name__ == "__main__":
    unittest.main()
