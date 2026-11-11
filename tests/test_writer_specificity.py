#!/usr/bin/env python3
"""Tests for writer_specificity — specificity as concreteness signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_specificity import (  # noqa: E402
    ABSTRACT_NOUNS,
    VAGUE_TIME_REFS,
    VAGUENESS_MARKERS,
    _count_sentences,
    _empty_metrics,
    _get_stroke_text,
    _score_entity_density,
    _score_vagueness,
    _split_words,
    analyze_specificity,
    analyze_stroke_specificity,
    classify_specificity,
    classify_trend,
    compute_concrete_word_ratio,
    compute_named_entity_density,
    compute_numerical_precision,
    compute_specificity_index,
    compute_specificity_metrics,
    compute_specificity_trend,
    compute_temporal_specificity,
    compute_vagueness_density,
    format_specificity_report,
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
    """Test _get_stroke_text extraction."""

    def test_text_key(self):
        self.assertEqual(_get_stroke_text({"text": "hello"}), "hello")

    def test_content_key(self):
        self.assertEqual(_get_stroke_text({"content": "hello"}), "hello")

    def test_body_key(self):
        self.assertEqual(_get_stroke_text({"body": "hello"}), "hello")

    def test_empty_stroke(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_whitespace_only(self):
        self.assertEqual(_get_stroke_text({"text": "   "}), "")

    def test_priority(self):
        """text > content > body."""
        stroke = {"text": "a", "content": "b", "body": "c"}
        self.assertEqual(_get_stroke_text(stroke), "a")


# ---------------------------------------------------------------------------
# Helper: _count_sentences
# ---------------------------------------------------------------------------


class TestCountSentences(unittest.TestCase):
    """Test sentence counting."""

    def test_single(self):
        self.assertEqual(_count_sentences("Hello world."), 1)

    def test_multiple(self):
        self.assertEqual(_count_sentences("One. Two. Three."), 3)

    def test_empty(self):
        self.assertEqual(_count_sentences(""), 1)

    def test_exclamation(self):
        self.assertEqual(_count_sentences("Wow! Yes!"), 2)


# ---------------------------------------------------------------------------
# Helper: _score_vagueness
# ---------------------------------------------------------------------------


class TestScoreVagueness(unittest.TestCase):
    """Test vagueness density to score conversion."""

    def test_zero_density(self):
        self.assertAlmostEqual(_score_vagueness(0.0), 1.0)

    def test_high_density(self):
        score = _score_vagueness(10.0)
        self.assertLess(score, 0.2)

    def test_monotonic(self):
        self.assertGreater(_score_vagueness(1.0), _score_vagueness(5.0))


# ---------------------------------------------------------------------------
# Helper: _score_entity_density
# ---------------------------------------------------------------------------


class TestScoreEntityDensity(unittest.TestCase):
    """Test entity density to score conversion."""

    def test_zero_density(self):
        self.assertAlmostEqual(_score_entity_density(0.0), 0.0)

    def test_high_density(self):
        score = _score_entity_density(10.0)
        self.assertGreater(score, 0.9)

    def test_monotonic(self):
        self.assertLess(_score_entity_density(1.0), _score_entity_density(5.0))


# ---------------------------------------------------------------------------
# Signal 1: Vagueness density
# ---------------------------------------------------------------------------


class TestVaguenessDensity(unittest.TestCase):
    """Test vagueness marker detection."""

    def test_no_vagueness(self):
        text = "The server crashed at 14:32 with exit code 137."
        density = compute_vagueness_density(text)
        self.assertEqual(density, 0.0)

    def test_high_vagueness(self):
        text = (
            "There are various things and stuff and many aspects "
            "and several factors and certain issues and some matters "
            "and quite a few elements and a lot of considerations."
        )
        density = compute_vagueness_density(text)
        self.assertGreater(density, 10.0)

    def test_moderate_vagueness(self):
        text = (
            "Several tests failed, and there are various reasons. "
            "Some of the modules need work. Many functions are slow."
        )
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)
        self.assertLess(density, 30.0)

    def test_empty_text(self):
        self.assertEqual(compute_vagueness_density(""), 0.0)

    def test_etc_marker(self):
        text = "We tested the API, the database, the cache, etc."
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)

    def test_sort_of(self):
        text = "It sort of works but kind of breaks sometimes."
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)

    def test_pretty_much(self):
        text = "We're pretty much done, more or less."
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)

    def test_and_so_on(self):
        text = "We fixed the tests, the linter, the docs, and so on."
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)

    def test_or_whatever(self):
        text = "Deploy to staging or whatever."
        density = compute_vagueness_density(text)
        self.assertGreater(density, 0.0)


# ---------------------------------------------------------------------------
# Signal 2: Numerical precision
# ---------------------------------------------------------------------------


class TestNumericalPrecision(unittest.TestCase):
    """Test numerical precision ratio."""

    def test_all_numbers(self):
        text = "47 tests passed, 3 failed, 12 skipped in 2.3 seconds."
        precision = compute_numerical_precision(text)
        self.assertGreater(precision, 0.7)

    def test_all_vague_quantities(self):
        text = "Many tests passed, several failed, some skipped."
        precision = compute_numerical_precision(text)
        self.assertLess(precision, 0.3)

    def test_mixed(self):
        text = "47 tests passed, many failed, 3 skipped."
        precision = compute_numerical_precision(text)
        self.assertGreater(precision, 0.3)
        self.assertLess(precision, 0.8)

    def test_no_quantities(self):
        text = "The weather is nice today."
        precision = compute_numerical_precision(text)
        self.assertAlmostEqual(precision, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_numerical_precision(""), 0.5)

    def test_percentage(self):
        text = "Coverage is 87% on the main branch."
        precision = compute_numerical_precision(text)
        self.assertGreater(precision, 0.8)


# ---------------------------------------------------------------------------
# Signal 3: Named entity density
# ---------------------------------------------------------------------------


class TestNamedEntityDensity(unittest.TestCase):
    """Test named entity (proper noun) density."""

    def test_no_entities(self):
        text = "the quick brown fox jumps over the lazy dog."
        density = compute_named_entity_density(text)
        self.assertEqual(density, 0.0)

    def test_with_entities(self):
        text = "We deployed to GitHub using Python on Linux."
        density = compute_named_entity_density(text)
        self.assertGreater(density, 0.0)

    def test_multiple_entities(self):
        text = (
            "Alice pushed to GitHub from her MacBook using Python "
            "and Docker on Friday."
        )
        density = compute_named_entity_density(text)
        self.assertGreater(density, 0.0)

    def test_empty(self):
        self.assertEqual(compute_named_entity_density(""), 0.0)

    def test_sentence_start_not_counted(self):
        text = "The server crashed. The database is down."
        density = compute_named_entity_density(text)
        # "The" at sentence start should not be counted
        self.assertEqual(density, 0.0)


# ---------------------------------------------------------------------------
# Signal 4: Concrete word ratio
# ---------------------------------------------------------------------------


class TestConcreteWordRatio(unittest.TestCase):
    """Test concrete vs abstract word ratio."""

    def test_concrete_text(self):
        text = "The keyboard on the desk has a red cable."
        ratio = compute_concrete_word_ratio(text)
        self.assertGreater(ratio, 0.8)

    def test_abstract_text(self):
        text = (
            "The methodology and framework and approach and strategy "
            "and paradigm and perspective and principle and concept "
            "all contribute to the understanding."
        )
        ratio = compute_concrete_word_ratio(text)
        self.assertLess(ratio, 0.7)

    def test_empty(self):
        self.assertAlmostEqual(compute_concrete_word_ratio(""), 0.5)

    def test_mixed(self):
        text = (
            "The server on the rack processes the request from the "
            "client using a cable and a switch that improves the "
            "log output on the monitor."
        )
        ratio = compute_concrete_word_ratio(text)
        self.assertGreater(ratio, 0.0)


# ---------------------------------------------------------------------------
# Signal 5: Temporal specificity
# ---------------------------------------------------------------------------


class TestTemporalSpecificity(unittest.TestCase):
    """Test temporal precision."""

    def test_precise_time(self):
        text = "Deployed at 14:32 on 2026-10-15 to production."
        specificity = compute_temporal_specificity(text)
        self.assertGreater(specificity, 0.8)

    def test_vague_time(self):
        text = "We deployed recently and will update eventually."
        specificity = compute_temporal_specificity(text)
        self.assertLess(specificity, 0.3)

    def test_no_time_refs(self):
        text = "The sky is blue."
        self.assertAlmostEqual(compute_temporal_specificity(text), 0.5)

    def test_mixed_time(self):
        text = "At 14:32 we noticed the issue. It had happened recently."
        specificity = compute_temporal_specificity(text)
        self.assertGreater(specificity, 0.0)
        self.assertLess(specificity, 1.0)

    def test_date_format(self):
        text = "On October 15th we shipped version 2."
        specificity = compute_temporal_specificity(text)
        self.assertGreater(specificity, 0.5)

    def test_quarter_format(self):
        text = "Q3 2026 was our best quarter."
        specificity = compute_temporal_specificity(text)
        self.assertGreater(specificity, 0.5)

    def test_year_only(self):
        text = "In 2026 we changed everything."
        specificity = compute_temporal_specificity(text)
        self.assertGreater(specificity, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_temporal_specificity(""), 0.5)


# ---------------------------------------------------------------------------
# Composite: specificity index
# ---------------------------------------------------------------------------


class TestSpecificityIndex(unittest.TestCase):
    """Test composite specificity index."""

    def test_perfect_specificity(self):
        idx = compute_specificity_index(
            vagueness_density=0.0,
            numerical_precision=1.0,
            named_entity_density=10.0,
            concrete_word_ratio=1.0,
            temporal_specificity=1.0,
        )
        self.assertGreater(idx, 0.85)

    def test_terrible_specificity(self):
        idx = compute_specificity_index(
            vagueness_density=15.0,
            numerical_precision=0.0,
            named_entity_density=0.0,
            concrete_word_ratio=0.2,
            temporal_specificity=0.0,
        )
        self.assertLess(idx, 0.25)

    def test_moderate_specificity(self):
        idx = compute_specificity_index(
            vagueness_density=3.0,
            numerical_precision=0.5,
            named_entity_density=3.0,
            concrete_word_ratio=0.6,
            temporal_specificity=0.5,
        )
        self.assertGreater(idx, 0.3)
        self.assertLess(idx, 0.8)

    def test_weights_sum_to_one(self):
        # Verify weights: 0.30 + 0.25 + 0.20 + 0.15 + 0.10 = 1.00
        # When all scores are 1.0, index should be 1.0
        idx = compute_specificity_index(
            vagueness_density=0.0,  # _score_vagueness(0) = 1.0
            numerical_precision=1.0,
            named_entity_density=100.0,  # _score_entity_density → ~1.0
            concrete_word_ratio=1.0,
            temporal_specificity=1.0,
        )
        self.assertAlmostEqual(idx, 1.0, places=1)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifySpecificity(unittest.TestCase):
    """Test specificity classification."""

    def test_precise(self):
        self.assertEqual(classify_specificity(0.85), "precise")
        self.assertEqual(classify_specificity(0.80), "precise")

    def test_grounded(self):
        self.assertEqual(classify_specificity(0.65), "grounded")
        self.assertEqual(classify_specificity(0.60), "grounded")

    def test_serviceable(self):
        self.assertEqual(classify_specificity(0.45), "serviceable")
        self.assertEqual(classify_specificity(0.40), "serviceable")

    def test_vague(self):
        self.assertEqual(classify_specificity(0.25), "vague")
        self.assertEqual(classify_specificity(0.20), "vague")

    def test_foggy(self):
        self.assertEqual(classify_specificity(0.15), "foggy")
        self.assertEqual(classify_specificity(0.0), "foggy")


# ---------------------------------------------------------------------------
# Batch metrics
# ---------------------------------------------------------------------------


class TestSpecificityMetrics(unittest.TestCase):
    """Test batch specificity computation."""

    def test_with_strokes(self):
        strokes = [
            {"text": "47 tests passed on GitHub at 14:32 on 2026-10-15."},
            {"text": "The Python module crashed with exit code 137."},
            {"text": "Alice deployed Docker to Linux on October 15th."},
        ]
        metrics = compute_specificity_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 3)
        self.assertIn("specificity_index", metrics)
        self.assertIn("classification", metrics)

    def test_empty_strokes(self):
        metrics = compute_specificity_metrics([])
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["classification"], "serviceable")

    def test_window_size(self):
        strokes = [{"text": f"stroke {i} content."} for i in range(100)]
        metrics = compute_specificity_metrics(strokes, window_size=20)
        self.assertLessEqual(metrics["strokes_analyzed"], 20)

    def test_strokes_without_text(self):
        strokes = [{"kind": "devlog"}, {"kind": "note"}]
        metrics = compute_specificity_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeSpecificity(unittest.TestCase):
    """Test per-stroke specificity analysis."""

    def test_specific_stroke(self):
        stroke = {
            "text": (
                "At 14:32 on 2026-10-15, Python crashed with "
                "exit code 137 on the Linux server."
            )
        }
        result = analyze_stroke_specificity(stroke)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertIn(result["classification"], [
            "precise", "grounded", "serviceable", "vague", "foggy"
        ])

    def test_vague_stroke(self):
        stroke = {
            "text": (
                "There are various things and many issues and "
                "several factors and some considerations."
            )
        }
        result = analyze_stroke_specificity(stroke)
        self.assertIn(result["classification"], ["vague", "foggy", "serviceable"])

    def test_empty_stroke(self):
        result = analyze_stroke_specificity({})
        self.assertEqual(result["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


class TestSpecificityTrend(unittest.TestCase):
    """Test specificity trend computation."""

    def test_short_sequence(self):
        strokes = [{"text": "test content."}]
        trend = compute_specificity_trend(strokes)
        self.assertEqual(len(trend), 1)

    def test_longer_sequence(self):
        strokes = [
            {"text": f"stroke {i} with some content here."} for i in range(20)
        ]
        trend = compute_specificity_trend(strokes, window_size=5)
        self.assertGreater(len(trend), 1)

    def test_each_entry_has_keys(self):
        strokes = [{"text": "test."} for _ in range(10)]
        trend = compute_specificity_trend(strokes, window_size=3)
        for entry in trend:
            self.assertIn("window_start", entry)
            self.assertIn("window_end", entry)
            self.assertIn("specificity_index", entry)
            self.assertIn("classification", entry)


# ---------------------------------------------------------------------------
# Trend classification
# ---------------------------------------------------------------------------


class TestClassifyTrend(unittest.TestCase):
    """Test trend direction classification."""

    def test_stable(self):
        trend = [
            {"specificity_index": 0.5, "classification": "serviceable"},
            {"specificity_index": 0.52, "classification": "serviceable"},
            {"specificity_index": 0.48, "classification": "serviceable"},
            {"specificity_index": 0.51, "classification": "serviceable"},
        ]
        self.assertEqual(classify_trend(trend), "stable")

    def test_improving(self):
        trend = [
            {"specificity_index": 0.3, "classification": "serviceable"},
            {"specificity_index": 0.35, "classification": "serviceable"},
            {"specificity_index": 0.6, "classification": "grounded"},
            {"specificity_index": 0.7, "classification": "grounded"},
        ]
        self.assertEqual(classify_trend(trend), "improving")

    def test_declining(self):
        trend = [
            {"specificity_index": 0.7, "classification": "grounded"},
            {"specificity_index": 0.65, "classification": "grounded"},
            {"specificity_index": 0.3, "classification": "serviceable"},
            {"specificity_index": 0.25, "classification": "vague"},
        ]
        self.assertEqual(classify_trend(trend), "declining")

    def test_single_entry(self):
        trend = [{"specificity_index": 0.5, "classification": "serviceable"}]
        self.assertEqual(classify_trend(trend), "stable")

    def test_empty(self):
        self.assertEqual(classify_trend([]), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


class TestFormatReport(unittest.TestCase):
    """Test report formatting."""

    def test_normal_report(self):
        metrics = compute_specificity_metrics(
            [{"text": "The Python server crashed at 14:32."}]
        )
        report = format_specificity_report(metrics)
        self.assertIn("Specificity Report", report)
        self.assertIn("Specificity Index", report)
        self.assertIn("Vagueness Density", report)

    def test_empty_report(self):
        report = format_specificity_report(_empty_metrics())
        self.assertEqual(report, "No strokes analyzed.")


# ---------------------------------------------------------------------------
# Empty metrics
# ---------------------------------------------------------------------------


class TestEmptyMetrics(unittest.TestCase):
    """Test empty metrics defaults."""

    def test_keys(self):
        m = _empty_metrics()
        expected_keys = {
            "vagueness_density",
            "numerical_precision",
            "named_entity_density",
            "concrete_word_ratio",
            "temporal_specificity",
            "specificity_index",
            "classification",
            "strokes_analyzed",
        }
        self.assertEqual(set(m.keys()), expected_keys)

    def test_values(self):
        m = _empty_metrics()
        self.assertEqual(m["strokes_analyzed"], 0)
        self.assertEqual(m["classification"], "serviceable")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestAnalyzeSpecificity(unittest.TestCase):
    """Test CLI entry point."""

    def test_missing_file(self):
        metrics = analyze_specificity("/nonexistent/path.jsonl")
        self.assertEqual(metrics["strokes_analyzed"], 0)

    def test_with_real_file(self, tmp_path=None):
        """Test with a temporary JSONL file."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"text": "47 tests passed on GitHub at 14:32."}\n')
            f.write('{"text": "Python crashed with exit code 137."}\n')
            f.name
            path = f.name

        metrics = analyze_specificity(path)
        self.assertEqual(metrics["strokes_analyzed"], 2)

        # Cleanup
        import os
        os.unlink(path)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Test that constants are well-formed."""

    def test_vagueness_markers_not_empty(self):
        self.assertGreater(len(VAGUENESS_MARKERS), 20)

    def test_abstract_nouns_not_empty(self):
        self.assertGreater(len(ABSTRACT_NOUNS), 10)

    def test_vague_time_refs_not_empty(self):
        self.assertGreater(len(VAGUE_TIME_REFS), 5)

    def test_vagueness_markers_lowercase(self):
        for marker in VAGUENESS_MARKERS:
            self.assertEqual(marker, marker.lower(), f"{marker!r} not lowercase")

    def test_abstract_nouns_lowercase(self):
        for noun in ABSTRACT_NOUNS:
            self.assertEqual(noun, noun.lower(), f"{noun!r} not lowercase")


# ---------------------------------------------------------------------------
# Integration: end-to-end with realistic text
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    """End-to-end tests with realistic writing samples."""

    def test_technical_writing_is_specific(self):
        """Technical writing with numbers and proper nouns scores high."""
        text = (
            "At 14:32 on 2026-10-15, the Python 3.12 test suite "
            "completed: 847 passed, 3 failed, 12 skipped. The 3 "
            "failures were in test_push_retry.py (timeout after "
            "30s), test_rebase_safe.py (assertion error on line 42), "
            "and test_ssh_key_rescue.py (missing deploy key at "
            "/tmp/ssh_deploy_key). Alice fixed the first two by "
            "2026-10-16."
        )
        metrics = compute_specificity_metrics([{"text": text}])
        self.assertIn(metrics["classification"], ["precise", "grounded"])

    def test_vague_writing_scores_low(self):
        """Vague, hand-wavy text scores low."""
        text = (
            "There are various things going on with the project. "
            "Many issues have been identified and several factors "
            "need consideration. Some aspects of the approach are "
            "somewhat problematic. We should address these matters "
            "at some point. The methodology needs improvement and "
            "various considerations apply."
        )
        metrics = compute_specificity_metrics([{"text": text}])
        self.assertIn(metrics["classification"], ["vague", "foggy", "serviceable"])

    def test_specific_higher_than_vague(self):
        """Specific text should score higher than vague text."""
        specific = {
            "text": "47 tests failed at 14:32 on GitHub Actions."
        }
        vague = {
            "text": "Many tests failed recently on the platform."
        }
        s_metrics = analyze_stroke_specificity(specific)
        v_metrics = analyze_stroke_specificity(vague)
        self.assertGreater(
            s_metrics["specificity_index"], v_metrics["specificity_index"]
        )


if __name__ == "__main__":
    unittest.main()
