#!/usr/bin/env python3
"""Tests for writer_coherence — coherence as logical connectedness signal."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_coherence import (  # noqa: E402
    ALL_TRANSITIONS,
    PRONOUNS,
    STOP_WORDS,
    TRANSITION_ADDITIVE,
    TRANSITION_CAUSAL,
    TRANSITION_CONTRASTIVE,
    TRANSITION_TEMPORAL,
    _content_words,
    _empty_metrics,
    _get_stroke_text,
    _has_antecedent,
    _score_transition_density,
    _split_sentences,
    _split_words,
    analyze_coherence,
    analyze_stroke_coherence,
    classify_coherence,
    classify_trend,
    compute_coherence_index,
    compute_coherence_metrics,
    compute_coherence_trend,
    compute_discourse_marker_diversity,
    compute_lexical_cohesion,
    compute_logical_connector_coverage,
    compute_pronoun_reference_clarity,
    compute_transition_density,
    format_coherence_report,
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
# Helper: _split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_basic(self):
        sentences = _split_sentences("First sentence. Second sentence.")
        self.assertEqual(len(sentences), 2)

    def test_single_word_filtered(self):
        sentences = _split_sentences("Hello. This is a test.")
        # "Hello." is only one word, should be filtered.
        self.assertEqual(len(sentences), 1)
        self.assertIn("test", sentences[0])

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_exclamation_and_question(self):
        sentences = _split_sentences("What happened? It crashed! The server died.")
        self.assertEqual(len(sentences), 3)


# ---------------------------------------------------------------------------
# Helper: _content_words
# ---------------------------------------------------------------------------


class TestContentWords(unittest.TestCase):
    """Test _content_words helper."""

    def test_filters_stop_words(self):
        words = ["the", "server", "is", "running", "fast"]
        result = _content_words(words)
        self.assertNotIn("the", result)
        self.assertNotIn("is", result)
        self.assertIn("server", result)
        self.assertIn("running", result)

    def test_filters_short_words(self):
        words = ["an", "or", "big", "data"]
        result = _content_words(words)
        self.assertNotIn("an", result)
        self.assertNotIn("or", result)
        self.assertIn("big", result)
        self.assertIn("data", result)

    def test_empty(self):
        self.assertEqual(_content_words([]), [])


# ---------------------------------------------------------------------------
# Helper: _has_antecedent
# ---------------------------------------------------------------------------


class TestHasAntecedent(unittest.TestCase):
    """Test _has_antecedent helper."""

    def test_it_with_content_words(self):
        self.assertTrue(_has_antecedent("it", {"server", "crashed"}))

    def test_it_empty(self):
        self.assertFalse(_has_antecedent("it", set()))

    def test_she_with_person_noun(self):
        self.assertTrue(_has_antecedent("she", {"developer", "wrote"}))

    def test_she_without_person_noun(self):
        self.assertFalse(_has_antecedent("she", {"server", "running"}))

    def test_he_with_person_noun(self):
        self.assertTrue(_has_antecedent("he", {"engineer", "fixed"}))

    def test_they_with_content(self):
        self.assertTrue(_has_antecedent("they", {"tests", "failed"}))


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

    def test_empty_stroke(self):
        self.assertEqual(_get_stroke_text({}), "")

    def test_whitespace_only(self):
        self.assertEqual(_get_stroke_text({"text": "   "}), "")


# ---------------------------------------------------------------------------
# Signal 1: Transition density
# ---------------------------------------------------------------------------


class TestTransitionDensity(unittest.TestCase):
    """Test compute_transition_density."""

    def test_no_transitions(self):
        text = "The server crashed. The database failed. Tests passed."
        density = compute_transition_density(text)
        self.assertEqual(density, 0.0)

    def test_with_transitions(self):
        text = (
            "The server crashed. However, the database survived. "
            "Therefore, we continued testing. Moreover, the results "
            "were positive."
        )
        density = compute_transition_density(text)
        self.assertGreater(density, 0.0)

    def test_empty(self):
        self.assertEqual(compute_transition_density(""), 0.0)

    def test_high_density(self):
        text = (
            "However the server crashed. Therefore we restarted. "
            "Moreover the tests passed. Furthermore the deploy succeeded. "
            "Additionally the metrics improved. Consequently we shipped."
        )
        density = compute_transition_density(text)
        self.assertGreater(density, 5.0)

    def test_score_conversion(self):
        self.assertAlmostEqual(_score_transition_density(0.0), 0.0, places=2)
        self.assertGreater(_score_transition_density(3.0), 0.5)
        self.assertGreater(_score_transition_density(6.0), 0.8)


# ---------------------------------------------------------------------------
# Signal 2: Pronoun reference clarity
# ---------------------------------------------------------------------------


class TestPronounReferenceClarity(unittest.TestCase):
    """Test compute_pronoun_reference_clarity."""

    def test_clear_pronouns(self):
        text = (
            "The server crashed at midnight. It had been running for "
            "48 hours. The database also failed. It needed a restart."
        )
        clarity = compute_pronoun_reference_clarity(text)
        self.assertGreater(clarity, 0.5)

    def test_no_pronouns(self):
        text = "The server crashed. The database failed. Tests passed."
        clarity = compute_pronoun_reference_clarity(text)
        self.assertAlmostEqual(clarity, 0.7)

    def test_single_sentence(self):
        text = "It crashed."
        clarity = compute_pronoun_reference_clarity(text)
        self.assertAlmostEqual(clarity, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_pronoun_reference_clarity(""), 0.5)


# ---------------------------------------------------------------------------
# Signal 3: Logical connector coverage
# ---------------------------------------------------------------------------


class TestLogicalConnectorCoverage(unittest.TestCase):
    """Test compute_logical_connector_coverage."""

    def test_all_linked(self):
        text = (
            "The server crashed. However the database survived. "
            "Therefore we continued. Moreover results were good."
        )
        coverage = compute_logical_connector_coverage(text)
        self.assertGreater(coverage, 0.5)

    def test_none_linked(self):
        text = (
            "The server crashed. The database failed. "
            "Tests passed. Deploy succeeded."
        )
        coverage = compute_logical_connector_coverage(text)
        self.assertEqual(coverage, 0.0)

    def test_single_sentence(self):
        coverage = compute_logical_connector_coverage("The server crashed.")
        self.assertAlmostEqual(coverage, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_logical_connector_coverage(""), 0.5)


# ---------------------------------------------------------------------------
# Signal 4: Lexical cohesion
# ---------------------------------------------------------------------------


class TestLexicalCohesion(unittest.TestCase):
    """Test compute_lexical_cohesion."""

    def test_high_cohesion(self):
        text = (
            "The server processes requests quickly. The server handles "
            "errors gracefully. The server logs all activity."
        )
        cohesion = compute_lexical_cohesion(text)
        self.assertGreater(cohesion, 0.1)

    def test_low_cohesion(self):
        text = (
            "Python ships new releases quarterly. Mountain climbing "
            "requires endurance. Quantum computing uses qubits."
        )
        cohesion = compute_lexical_cohesion(text)
        self.assertLess(cohesion, 0.3)

    def test_single_sentence(self):
        cohesion = compute_lexical_cohesion("The server crashed.")
        self.assertAlmostEqual(cohesion, 0.5)

    def test_empty(self):
        self.assertAlmostEqual(compute_lexical_cohesion(""), 0.5)


# ---------------------------------------------------------------------------
# Signal 5: Discourse marker diversity
# ---------------------------------------------------------------------------


class TestDiscourseMarkerDiversity(unittest.TestCase):
    """Test compute_discourse_marker_diversity."""

    def test_no_markers(self):
        text = "The server crashed. The database failed."
        diversity = compute_discourse_marker_diversity(text)
        self.assertAlmostEqual(diversity, 0.5)

    def test_diverse_markers(self):
        text = (
            "However the server crashed. Moreover the database failed. "
            "Therefore we restarted. Additionally tests passed."
        )
        diversity = compute_discourse_marker_diversity(text)
        self.assertGreater(diversity, 0.8)

    def test_repeated_marker(self):
        text = (
            "However the server crashed. However the database failed. "
            "However tests passed. However deploy succeeded."
        )
        diversity = compute_discourse_marker_diversity(text)
        self.assertAlmostEqual(diversity, 0.25)  # 1 unique / 4 total

    def test_empty(self):
        self.assertAlmostEqual(compute_discourse_marker_diversity(""), 0.5)


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


class TestCoherenceIndex(unittest.TestCase):
    """Test compute_coherence_index and classify_coherence."""

    def test_perfect_scores(self):
        idx = compute_coherence_index(
            transition_density=10.0,
            pronoun_reference_clarity=1.0,
            logical_connector_coverage=1.0,
            lexical_cohesion=1.0,
            discourse_marker_diversity=1.0,
        )
        self.assertGreater(idx, 0.8)
        self.assertEqual(classify_coherence(idx), "tight")

    def test_zero_scores(self):
        idx = compute_coherence_index(
            transition_density=0.0,
            pronoun_reference_clarity=0.0,
            logical_connector_coverage=0.0,
            lexical_cohesion=0.0,
            discourse_marker_diversity=0.0,
        )
        self.assertLess(idx, 0.2)
        self.assertEqual(classify_coherence(idx), "fragmented")

    def test_moderate_scores(self):
        idx = compute_coherence_index(
            transition_density=3.0,
            pronoun_reference_clarity=0.6,
            logical_connector_coverage=0.5,
            lexical_cohesion=0.3,
            discourse_marker_diversity=0.5,
        )
        self.assertGreater(idx, 0.3)
        self.assertLess(idx, 0.8)

    def test_classify_boundaries(self):
        self.assertEqual(classify_coherence(0.85), "tight")
        self.assertEqual(classify_coherence(0.70), "connected")
        self.assertEqual(classify_coherence(0.50), "adequate")
        self.assertEqual(classify_coherence(0.25), "loose")
        self.assertEqual(classify_coherence(0.10), "fragmented")
        self.assertEqual(classify_coherence(0.80), "tight")
        self.assertEqual(classify_coherence(0.60), "connected")
        self.assertEqual(classify_coherence(0.40), "adequate")
        self.assertEqual(classify_coherence(0.20), "loose")


# ---------------------------------------------------------------------------
# Metrics over strokes
# ---------------------------------------------------------------------------


class TestCoherenceMetrics(unittest.TestCase):
    """Test compute_coherence_metrics."""

    def test_empty_strokes(self):
        metrics = compute_coherence_metrics([])
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["classification"], "adequate")

    def test_with_strokes(self):
        strokes = [
            {"text": "The server crashed. However the database survived."},
            {"text": "Therefore we continued testing. Moreover results were positive."},
            {"text": "Additionally the deploy succeeded. Thus we shipped."},
        ]
        metrics = compute_coherence_metrics(strokes)
        self.assertEqual(metrics["strokes_analyzed"], 3)
        self.assertGreater(metrics["coherence_index"], 0.0)

    def test_window_size(self):
        strokes = [{"text": f"Sentence number {i} here."} for i in range(100)]
        metrics = compute_coherence_metrics(strokes, window_size=10)
        self.assertEqual(metrics["strokes_analyzed"], 10)

    def test_empty_metrics(self):
        metrics = _empty_metrics()
        self.assertEqual(metrics["strokes_analyzed"], 0)
        self.assertEqual(metrics["classification"], "adequate")
        self.assertAlmostEqual(metrics["coherence_index"], 0.5)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


class TestCoherenceTrend(unittest.TestCase):
    """Test compute_coherence_trend and classify_trend."""

    def test_short_strokes(self):
        strokes = [{"text": "Hello world."}]
        trend = compute_coherence_trend(strokes)
        self.assertEqual(len(trend), 1)

    def test_classify_improving(self):
        trend = [
            {"coherence_index": 0.3, "classification": "loose"},
            {"coherence_index": 0.4, "classification": "adequate"},
            {"coherence_index": 0.6, "classification": "connected"},
            {"coherence_index": 0.7, "classification": "connected"},
        ]
        self.assertEqual(classify_trend(trend), "improving")

    def test_classify_declining(self):
        trend = [
            {"coherence_index": 0.8, "classification": "tight"},
            {"coherence_index": 0.7, "classification": "connected"},
            {"coherence_index": 0.3, "classification": "loose"},
            {"coherence_index": 0.2, "classification": "loose"},
        ]
        self.assertEqual(classify_trend(trend), "declining")

    def test_classify_stable(self):
        trend = [
            {"coherence_index": 0.5, "classification": "adequate"},
            {"coherence_index": 0.5, "classification": "adequate"},
            {"coherence_index": 0.5, "classification": "adequate"},
            {"coherence_index": 0.5, "classification": "adequate"},
        ]
        self.assertEqual(classify_trend(trend), "stable")

    def test_classify_single(self):
        trend = [{"coherence_index": 0.5, "classification": "adequate"}]
        self.assertEqual(classify_trend(trend), "stable")


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


class TestAnalyzeStrokeCoherence(unittest.TestCase):
    """Test analyze_stroke_coherence."""

    def test_connected_stroke(self):
        stroke = {
            "text": (
                "The server crashed at midnight. However the database "
                "survived the outage. Therefore we focused on recovery. "
                "Moreover the backup was intact."
            )
        }
        result = analyze_stroke_coherence(stroke)
        self.assertEqual(result["strokes_analyzed"], 1)
        self.assertGreater(result["coherence_index"], 0.0)

    def test_disconnected_stroke(self):
        stroke = {
            "text": (
                "Python ships quarterly. Mountain climbing requires "
                "endurance. Quantum computing uses qubits."
            )
        }
        result = analyze_stroke_coherence(stroke)
        self.assertEqual(result["strokes_analyzed"], 1)
        # No transitions, low cohesion.
        self.assertLess(result["transition_density"], 1.0)

    def test_empty_stroke(self):
        result = analyze_stroke_coherence({})
        self.assertEqual(result["strokes_analyzed"], 0)

    def test_short_stroke(self):
        result = analyze_stroke_coherence({"text": ""})
        self.assertEqual(result["strokes_analyzed"], 0)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestFormatCoherenceReport(unittest.TestCase):
    """Test format_coherence_report."""

    def test_no_strokes(self):
        report = format_coherence_report(_empty_metrics())
        self.assertEqual(report, "No strokes analyzed.")

    def test_with_data(self):
        metrics = {
            "coherence_index": 0.6543,
            "classification": "connected",
            "transition_density": 4.5,
            "pronoun_reference_clarity": 0.8,
            "logical_connector_coverage": 0.75,
            "lexical_cohesion": 0.35,
            "discourse_marker_diversity": 0.6,
            "strokes_analyzed": 10,
        }
        report = format_coherence_report(metrics)
        self.assertIn("Coherence Report", report)
        self.assertIn("10 strokes", report)
        self.assertIn("connected", report)
        self.assertIn("0.6543", report)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestAnalyzeCoherence(unittest.TestCase):
    """Test analyze_coherence CLI function."""

    def test_missing_file(self):
        result = analyze_coherence("/nonexistent/path.jsonl")
        self.assertEqual(result["strokes_analyzed"], 0)
        self.assertEqual(result["classification"], "adequate")


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Test that constants are well-formed."""

    def test_all_transitions_not_empty(self):
        self.assertGreater(len(ALL_TRANSITIONS), 50)

    def test_categories_cover_all(self):
        combined = (
            TRANSITION_ADDITIVE
            + TRANSITION_CONTRASTIVE
            + TRANSITION_CAUSAL
            + TRANSITION_TEMPORAL
        )
        self.assertEqual(set(combined), set(ALL_TRANSITIONS))

    def test_pronouns_not_empty(self):
        self.assertGreater(len(PRONOUNS), 10)

    def test_stop_words_not_empty(self):
        self.assertGreater(len(STOP_WORDS), 50)

    def test_no_duplicate_transitions(self):
        self.assertEqual(len(ALL_TRANSITIONS), len(set(ALL_TRANSITIONS)))


# ---------------------------------------------------------------------------
# Integration: coherent vs incoherent text
# ---------------------------------------------------------------------------


class TestIntegration(unittest.TestCase):
    """Integration tests comparing coherent and incoherent text."""

    COHERENT = (
        "The deployment pipeline failed at stage three. However, the "
        "error was caught by the monitoring system. Therefore, the team "
        "was notified within seconds. Moreover, the rollback mechanism "
        "activated automatically. Consequently, no user data was lost. "
        "Additionally, the incident report was generated. Furthermore, "
        "the team scheduled a postmortem meeting."
    )

    INCOHERENT = (
        "The deployment pipeline failed. Mountain ranges stretch across "
        "continents. Python ships quarterly releases. Coffee consumption "
        "has increased globally. Quantum entanglement defies intuition. "
        "The ocean depth reaches eleven kilometers. Solar panels convert "
        "photons to electricity."
    )

    def test_coherent_higher_index(self):
        coh_metrics = compute_coherence_metrics(
            [{"text": self.COHERENT}]
        )
        inc_metrics = compute_coherence_metrics(
            [{"text": self.INCOHERENT}]
        )
        self.assertGreater(
            coh_metrics["coherence_index"],
            inc_metrics["coherence_index"],
        )

    def test_coherent_more_transitions(self):
        coh_td = compute_transition_density(self.COHERENT)
        inc_td = compute_transition_density(self.INCOHERENT)
        self.assertGreater(coh_td, inc_td)

    def test_coherent_more_coverage(self):
        coh_lc = compute_logical_connector_coverage(self.COHERENT)
        inc_lc = compute_logical_connector_coverage(self.INCOHERENT)
        self.assertGreater(coh_lc, inc_lc)

    def test_incoherent_lower_cohesion(self):
        coh_lx = compute_lexical_cohesion(self.COHERENT)
        inc_lx = compute_lexical_cohesion(self.INCOHERENT)
        self.assertGreaterEqual(coh_lx, inc_lx)

    def test_coherent_classified_higher(self):
        coh_class = classify_coherence(
            compute_coherence_index(
                compute_transition_density(self.COHERENT),
                compute_pronoun_reference_clarity(self.COHERENT),
                compute_logical_connector_coverage(self.COHERENT),
                compute_lexical_cohesion(self.COHERENT),
                compute_discourse_marker_diversity(self.COHERENT),
            )
        )
        inc_class = classify_coherence(
            compute_coherence_index(
                compute_transition_density(self.INCOHERENT),
                compute_pronoun_reference_clarity(self.INCOHERENT),
                compute_logical_connector_coverage(self.INCOHERENT),
                compute_lexical_cohesion(self.INCOHERENT),
                compute_discourse_marker_diversity(self.INCOHERENT),
            )
        )
        order = ["fragmented", "loose", "adequate", "connected", "tight"]
        self.assertGreater(
            order.index(coh_class),
            order.index(inc_class),
        )


if __name__ == "__main__":
    unittest.main()
