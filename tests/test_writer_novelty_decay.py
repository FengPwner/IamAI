#!/usr/bin/env python3
"""Tests for writer_novelty_decay — 73 test cases."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_novelty_decay import (  # noqa: E402
    _bigrams,
    _classify_decay,
    _empty_metrics,
    _extract_template,
    _linear_slope,
    _stroke_concept_novelty,
    _stroke_structural_novelty,
    _stroke_vocabulary_novelty,
    _tokenize,
    analyze_novelty_decay,
    classify_session_trajectory,
    compute_novelty_metrics,
    compute_novelty_over_sessions,
    format_novelty_report,
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

    def test_repeats_preserved(self):
        tokens = _tokenize("go go go")
        self.assertEqual(tokens, ["go", "go", "go"])

    def test_mixed_case(self):
        tokens = _tokenize("UPPER lower MiXeD")
        self.assertEqual(tokens, ["upper", "lower", "mixed"])


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


# ---------------------------------------------------------------------------
# Helper: _extract_template
# ---------------------------------------------------------------------------

class TestExtractTemplate(unittest.TestCase):
    """Test _extract_template helper."""

    def test_numbers_replaced(self):
        t = _extract_template("stroke 42 in pool of 9 modules")
        self.assertIn("<N>", t)
        self.assertNotIn("42", t)
        self.assertNotIn(" 9 ", t)

    def test_paths_replaced(self):
        t = _extract_template("see notes/conventions.md for details")
        self.assertIn("<PATH>", t)

    def test_timestamps_replaced(self):
        t = _extract_template("at 2026-11-11T20:02:00+08:00 the process")
        self.assertIn("<TS>", t)

    def test_hex_replaced(self):
        t = _extract_template("commit abc1234def5678 landed")
        self.assertIn("<HASH>", t)

    def test_plain_text_unchanged(self):
        t = _extract_template("the writer is warming up nicely")
        self.assertEqual(t, "the writer is warming up nicely")


# ---------------------------------------------------------------------------
# Helper: _linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope(unittest.TestCase):
    """Test _linear_slope helper."""

    def test_positive_slope(self):
        self.assertGreater(_linear_slope([1.0, 2.0, 3.0, 4.0]), 0)

    def test_negative_slope(self):
        self.assertLess(_linear_slope([4.0, 3.0, 2.0, 1.0]), 0)

    def test_zero_slope(self):
        self.assertAlmostEqual(_linear_slope([5.0, 5.0, 5.0, 5.0]), 0.0)

    def test_single_value(self):
        self.assertEqual(_linear_slope([3.0]), 0.0)

    def test_empty(self):
        self.assertEqual(_linear_slope([]), 0.0)

    def test_two_values(self):
        self.assertAlmostEqual(_linear_slope([1.0, 3.0]), 2.0)


# ---------------------------------------------------------------------------
# Per-stroke novelty helpers
# ---------------------------------------------------------------------------

class TestStrokeVocabularyNovelty(unittest.TestCase):
    """Test _stroke_vocabulary_novelty."""

    def test_all_new(self):
        score = _stroke_vocabulary_novelty(["hello", "world"], set())
        self.assertEqual(score, 1.0)

    def test_all_seen(self):
        score = _stroke_vocabulary_novelty(["hello", "world"],
                                           {"hello", "world"})
        self.assertEqual(score, 0.0)

    def test_half_new(self):
        score = _stroke_vocabulary_novelty(["hello", "world"],
                                           {"hello"})
        self.assertEqual(score, 0.5)

    def test_empty_tokens(self):
        score = _stroke_vocabulary_novelty([], set())
        self.assertEqual(score, 0.0)


class TestStrokeConceptNovelty(unittest.TestCase):
    """Test _stroke_concept_novelty."""

    def test_all_new(self):
        score = _stroke_concept_novelty(
            [("a", "b"), ("c", "d")], set()
        )
        self.assertEqual(score, 1.0)

    def test_all_seen(self):
        score = _stroke_concept_novelty(
            [("a", "b")], {("a", "b")}
        )
        self.assertEqual(score, 0.0)

    def test_empty_bigrams(self):
        score = _stroke_concept_novelty([], set())
        self.assertEqual(score, 0.0)


class TestStrokeStructuralNovelty(unittest.TestCase):
    """Test _stroke_structural_novelty."""

    def test_new_template(self):
        self.assertEqual(
            _stroke_structural_novelty("some text", set()), 1.0
        )

    def test_seen_template(self):
        self.assertEqual(
            _stroke_structural_novelty("some text", {"some text"}), 0.0
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassifyDecay(unittest.TestCase):
    """Test _classify_decay."""

    def test_blooming(self):
        self.assertEqual(_classify_decay(0.05), "blooming")

    def test_blooming_boundary(self):
        self.assertEqual(_classify_decay(0.03), "blooming")

    def test_steady_positive(self):
        self.assertEqual(_classify_decay(0.01), "steady")

    def test_steady_negative(self):
        self.assertEqual(_classify_decay(-0.01), "steady")

    def test_steady_boundary(self):
        self.assertEqual(_classify_decay(0.029), "steady")

    def test_plateauing(self):
        self.assertEqual(_classify_decay(-0.05), "plateauing")

    def test_plateauing_boundary(self):
        # -0.03 is exactly at the boundary; not strictly greater than -0.03
        self.assertEqual(_classify_decay(-0.03), "plateauing")

    def test_exhausted(self):
        self.assertEqual(_classify_decay(-0.10), "exhausted")

    def test_exhausted_boundary(self):
        self.assertEqual(_classify_decay(-0.08), "exhausted")


# ---------------------------------------------------------------------------
# Core metrics: compute_novelty_metrics
# ---------------------------------------------------------------------------

class TestComputeNoveltyMetrics(unittest.TestCase):
    """Test compute_novelty_metrics."""

    def _make_strokes(self, texts: list[str]) -> list[dict]:
        return [{"text": t} for t in texts]

    def test_empty_strokes(self):
        result = compute_novelty_metrics([])
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["novelty_index"], 0.0)
        self.assertEqual(result["decay_class"], "exhausted")

    def test_single_stroke(self):
        strokes = self._make_strokes(["hello world foo bar"])
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        # First stroke: everything is new
        self.assertEqual(result["vocabulary_novelty"], 1.0)
        self.assertEqual(result["concept_novelty"], 1.0)
        self.assertEqual(result["structural_novelty"], 1.0)

    def test_identical_strokes_decay(self):
        text = "the writer added another stroke to the log today"
        strokes = self._make_strokes([text] * 10)
        result = compute_novelty_metrics(strokes)
        # First stroke is fully novel; rest should have zero vocab novelty
        self.assertLess(result["vocabulary_novelty"], 0.2)
        # Sharp negative trend but not fully exhausted (first stroke
        # lifts the mean enough that the slope lands in plateauing)
        self.assertIn(result["decay_class"], ("plateauing", "exhausted"))
        self.assertLess(result["novelty_trend"], 0.0)

    def test_increasingly_novel(self):
        # Each stroke introduces completely new words
        strokes = self._make_strokes([
            "alpha beta gamma",
            "delta epsilon zeta eta",
            "theta iota kappa lambda mu",
            "nu xi omicron pi rho sigma",
            "tau upsilon phi chi psi omega",
        ])
        result = compute_novelty_metrics(strokes)
        # All words are unique across strokes → high novelty
        self.assertGreater(result["vocabulary_novelty"], 0.8)
        self.assertEqual(result["structural_novelty"], 1.0)

    def test_window_size_limits_analysis(self):
        strokes = self._make_strokes(["word"] * 100)
        result = compute_novelty_metrics(strokes, window_size=10)
        self.assertEqual(result["strokes_analyzed"], 10)

    def test_content_field_fallback(self):
        strokes = [{"content": "fallback content here now"}]
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertEqual(result["vocabulary_novelty"], 1.0)

    def test_empty_text_strokes(self):
        strokes = self._make_strokes(["", "", ""])
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 3)
        self.assertEqual(result["vocabulary_novelty"], 0.0)

    def test_per_stroke_novelty_length(self):
        strokes = self._make_strokes([
            "first stroke alpha",
            "second stroke beta",
            "third stroke gamma",
        ])
        result = compute_novelty_metrics(strokes)
        self.assertEqual(len(result["per_stroke_novelty"]), 3)

    def test_novelty_trend_type(self):
        strokes = self._make_strokes([
            "one two three",
            "four five six",
            "seven eight nine",
        ])
        result = compute_novelty_metrics(strokes)
        self.assertIsInstance(result["novelty_trend"], float)

    def test_blooming_session(self):
        # Start with repeated words, then introduce many new ones
        strokes = self._make_strokes([
            "the the the",
            "the the the",
            "alpha beta gamma delta epsilon",
            "zeta eta theta iota kappa",
            "lambda mu nu xi omicron pi rho sigma tau",
        ])
        result = compute_novelty_metrics(strokes)
        # Later strokes have all new words → positive trend
        self.assertGreater(result["novelty_trend"], 0.0)

    def test_exhausted_session(self):
        # Start with rich vocabulary, then repeat
        strokes = self._make_strokes([
            "alpha beta gamma delta epsilon zeta",
            "eta theta iota kappa lambda mu",
            "the same old words again today",
            "the same old words again today",
            "the same old words again today",
        ])
        result = compute_novelty_metrics(strokes)
        # Later strokes recycle words → negative trend
        self.assertLess(result["novelty_trend"], 0.0)


# ---------------------------------------------------------------------------
# Multi-session analysis
# ---------------------------------------------------------------------------

class TestComputeNoveltyOverSessions(unittest.TestCase):
    """Test compute_novelty_over_sessions."""

    def _make_strokes(self, n: int, unique: bool = True) -> list[dict]:
        if unique:
            return [{"text": f"stroke number {i} with unique words alpha{i}"}
                    for i in range(n)]
        return [{"text": "repeated stroke content here"} for _ in range(n)]

    def test_short_session(self):
        strokes = self._make_strokes(5)
        snapshots = compute_novelty_over_sessions(strokes, session_size=10)
        self.assertEqual(len(snapshots), 1)

    def test_multiple_windows(self):
        strokes = self._make_strokes(30)
        snapshots = compute_novelty_over_sessions(
            strokes, session_size=10, step=10
        )
        self.assertEqual(len(snapshots), 3)

    def test_window_start_recorded(self):
        strokes = self._make_strokes(25)
        snapshots = compute_novelty_over_sessions(
            strokes, session_size=10, step=5
        )
        for snap in snapshots:
            self.assertIn("window_start", snap)

    def test_empty_strokes(self):
        snapshots = compute_novelty_over_sessions([], session_size=10)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Session trajectory classification
# ---------------------------------------------------------------------------

class TestClassifySessionTrajectory(unittest.TestCase):
    """Test classify_session_trajectory."""

    def test_insufficient_data(self):
        self.assertEqual(
            classify_session_trajectory([{"novelty_trend": 0.1}]),
            "insufficient_data",
        )

    def test_recovering(self):
        snapshots = [
            {"novelty_trend": -0.05},
            {"novelty_trend": -0.02},
            {"novelty_trend": 0.01},
            {"novelty_trend": 0.04},
        ]
        self.assertEqual(
            classify_session_trajectory(snapshots), "recovering"
        )

    def test_declining(self):
        snapshots = [
            {"novelty_trend": 0.05},
            {"novelty_trend": 0.02},
            {"novelty_trend": -0.03},
            {"novelty_trend": -0.06},
        ]
        self.assertEqual(
            classify_session_trajectory(snapshots), "declining"
        )

    def test_stable(self):
        snapshots = [
            {"novelty_trend": 0.01},
            {"novelty_trend": 0.00},
            {"novelty_trend": -0.01},
            {"novelty_trend": 0.01},
        ]
        self.assertEqual(
            classify_session_trajectory(snapshots), "stable"
        )

    def test_empty(self):
        self.assertEqual(
            classify_session_trajectory([]), "insufficient_data"
        )


# ---------------------------------------------------------------------------
# Empty metrics
# ---------------------------------------------------------------------------

class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics."""

    def test_keys_present(self):
        m = _empty_metrics()
        expected = {
            "vocabulary_novelty", "concept_novelty", "structural_novelty",
            "novelty_index", "novelty_trend", "decay_class",
            "strokes_analyzed", "per_stroke_novelty",
        }
        self.assertTrue(expected.issubset(set(m.keys())))

    def test_values_zero(self):
        m = _empty_metrics()
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["novelty_index"], 0.0)
        self.assertEqual(m["decay_class"], "exhausted")
        self.assertEqual(m["per_stroke_novelty"], [])


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormatNoveltyReport(unittest.TestCase):
    """Test format_novelty_report."""

    def test_blooming_report(self):
        m = {
            "strokes_analyzed": 10,
            "novelty_index": 0.85,
            "novelty_trend": 0.05,
            "decay_class": "blooming",
            "vocabulary_novelty": 0.80,
            "concept_novelty": 0.75,
            "structural_novelty": 1.0,
            "per_stroke_novelty": [],
        }
        report = format_novelty_report(m)
        self.assertIn("blooming", report.lower())
        self.assertIn("flow", report.lower())

    def test_steady_report(self):
        m = {
            "strokes_analyzed": 10,
            "novelty_index": 0.50,
            "novelty_trend": 0.01,
            "decay_class": "steady",
            "vocabulary_novelty": 0.45,
            "concept_novelty": 0.40,
            "structural_novelty": 0.70,
            "per_stroke_novelty": [],
        }
        report = format_novelty_report(m)
        self.assertIn("stable", report.lower())

    def test_plateauing_report(self):
        m = {
            "strokes_analyzed": 10,
            "novelty_index": 0.35,
            "novelty_trend": -0.05,
            "decay_class": "plateauing",
            "vocabulary_novelty": 0.30,
            "concept_novelty": 0.25,
            "structural_novelty": 0.50,
            "per_stroke_novelty": [],
        }
        report = format_novelty_report(m)
        self.assertIn("decay", report.lower())

    def test_exhausted_report(self):
        m = {
            "strokes_analyzed": 10,
            "novelty_index": 0.10,
            "novelty_trend": -0.10,
            "decay_class": "exhausted",
            "vocabulary_novelty": 0.05,
            "concept_novelty": 0.03,
            "structural_novelty": 0.20,
            "per_stroke_novelty": [],
        }
        report = format_novelty_report(m)
        self.assertIn("exhausted", report.lower())
        self.assertIn("intervention", report.lower())


# ---------------------------------------------------------------------------
# Standalone analysis (file I/O)
# ---------------------------------------------------------------------------

class TestAnalyzeNoveltyDecay(unittest.TestCase):
    """Test analyze_novelty_decay with temp files."""

    def test_missing_file(self):
        result = analyze_novelty_decay("/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(5):
                f.write(json.dumps({
                    "text": f"stroke {i} with unique word alpha{i} beta{i}"
                }) + "\n")
            f.flush()
            result = analyze_novelty_decay(f.name, window_size=10)
        Path(f.name).unlink()
        self.assertEqual(result["strokes_analyzed"], 5)
        self.assertGreater(result["novelty_index"], 0.0)

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"text": "valid stroke here now"}\n')
            f.write("this is not json\n")
            f.write('{"text": "another valid stroke"}\n')
            f.flush()
            result = analyze_novelty_decay(f.name, window_size=10)
        Path(f.name).unlink()
        self.assertEqual(result["strokes_analyzed"], 2)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.flush()
            result = analyze_novelty_decay(f.name)
        Path(f.name).unlink()
        self.assertEqual(result["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Integration and edge-case tests."""

    def test_very_long_strokes(self):
        text = " ".join(f"word{i}" for i in range(500))
        strokes = [{"text": text}]
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 1)

    def test_unicode_content(self):
        strokes = [
            {"text": "héllo wörld café"},
            {"text": "naïve résumé über"},
        ]
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 2)

    def test_numeric_only_strokes(self):
        strokes = [
            {"text": "42 100 999"},
            {"text": "42 100 999"},
        ]
        result = compute_novelty_metrics(strokes)
        # Second stroke reuses all words → low novelty
        self.assertLess(result["vocabulary_novelty"], 0.6)

    def test_single_word_strokes(self):
        strokes = [
            {"text": "hello"},
            {"text": "world"},
            {"text": "foo"},
        ]
        result = compute_novelty_metrics(strokes)
        # Each stroke is one unique word → vocab novelty = 1.0 each
        self.assertEqual(result["vocabulary_novelty"], 1.0)
        # No bigrams possible → concept novelty = 0.0
        self.assertEqual(result["concept_novelty"], 0.0)

    def test_mixed_text_and_content_fields(self):
        strokes = [
            {"text": "alpha beta gamma"},
            {"content": "delta epsilon zeta"},
            {"text": "eta theta iota"},
        ]
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 3)

    def test_none_values_handled(self):
        strokes = [
            {"text": None},
            {"text": "some actual content here"},
        ]
        result = compute_novelty_metrics(strokes)
        self.assertEqual(result["strokes_analyzed"], 2)

    def test_report_contains_all_sections(self):
        m = compute_novelty_metrics([
            {"text": "first stroke with some words"},
            {"text": "second stroke with different words"},
        ])
        report = format_novelty_report(m)
        self.assertIn("Novelty index", report)
        self.assertIn("Novelty trend", report)
        self.assertIn("Decay class", report)
        self.assertIn("Interpretation", report)


if __name__ == "__main__":
    unittest.main()
