#!/usr/bin/env python3
"""Tests for writer_cohesion — 80 test cases."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_cohesion import (  # noqa: E402
    BACKREF_PATTERNS,
    FUNCTION_WORDS,
    TRANSITION_PHRASES,
    _classify,
    _classify_opening,
    _content_words,
    _empty_metrics,
    _jaccard_similarity,
    _parallelism_score,
    _sentence_has_backref,
    _split_sentences,
    _word_count,
    analyze_strokes,
    classify_trend,
    compute_cohesion_metrics,
    compute_cohesion_trend,
    compute_lexical_chain_strength,
    compute_referential_continuity,
    compute_structural_parallelism,
    compute_transition_density,
    count_transitions,
    format_cohesion_report,
)


# ---------------------------------------------------------------------------
# Helper: sample texts
# ---------------------------------------------------------------------------

WELL_CONNECTED = (
    "The project began with a simple hypothesis. "
    "However, the initial results were inconclusive. "
    "Therefore, the team decided to extend the experiment. "
    "This extension revealed a surprising pattern. "
    "Moreover, the pattern held across multiple trials. "
    "Consequently, the team published their findings. "
    "Furthermore, the findings attracted international attention. "
    "As a result, several collaborations emerged. "
    "Nevertheless, some questions remained unanswered. "
    "In the end, the project spawned three follow-up studies."
)

DISJOINTED = (
    "Cats sleep eighteen hours a day. "
    "The stock market closed higher on Tuesday. "
    "Bananas contain potassium and vitamin B6. "
    "Quantum entanglement defies classical intuition. "
    "The Nile River flows northward through Egypt. "
    "Shakespeare wrote thirty-seven plays. "
    "Volcanic eruptions release sulfur dioxide. "
    "The Fibonacci sequence appears in sunflower spirals."
)

MIXED_TEXT = (
    "The algorithm processes data in three stages. "
    "First, it normalizes the input values. "
    "Then it applies a transformation matrix. "
    "The output is compared against expected results. "
    "Errors are logged for later analysis. "
    "Performance metrics are computed from the logs. "
    "The team reviews the metrics weekly. "
    "Adjustments are made based on trends."
)

SHORT_TEXT = "Hello world. This is short."

ONE_SENTENCE = "Just a single sentence here."

EMPTY_TEXT = ""


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences."""

    def test_basic_split(self):
        sents = _split_sentences("Hello world. How are you. I am fine.")
        self.assertGreaterEqual(len(sents), 2)

    def test_single_sentence(self):
        sents = _split_sentences("Just one sentence here.")
        self.assertEqual(len(sents), 1)

    def test_empty_input(self):
        sents = _split_sentences("")
        self.assertEqual(len(sents), 0)

    def test_exclamation(self):
        sents = _split_sentences("What a day! The sun is shining. Birds are singing.")
        self.assertGreaterEqual(len(sents), 2)

    def test_question_mark(self):
        sents = _split_sentences("Is this working? I hope so. Let us continue.")
        self.assertGreaterEqual(len(sents), 2)

    def test_filters_short(self):
        sents = _split_sentences("OK. The longer sentence stays here.")
        # "OK." is too short (< 6 chars) and should be filtered
        for s in sents:
            self.assertGreater(len(s), 5)


# ---------------------------------------------------------------------------
# Content words
# ---------------------------------------------------------------------------

class TestContentWords(unittest.TestCase):
    """Test _content_words."""

    def test_excludes_function_words(self):
        words = _content_words("The cat is on the mat")
        self.assertNotIn("the", words)
        self.assertNotIn("is", words)
        self.assertNotIn("on", words)

    def test_includes_content_words(self):
        words = _content_words("The algorithm processes data efficiently")
        self.assertIn("algorithm", words)
        self.assertIn("processes", words)
        self.assertIn("data", words)
        self.assertIn("efficiently", words)

    def test_excludes_short_tokens(self):
        words = _content_words("It is a big cat")
        # "it", "is", "a" should all be excluded
        for w in words:
            self.assertGreater(len(w), 2)

    def test_empty_input(self):
        words = _content_words("")
        self.assertEqual(len(words), 0)


# ---------------------------------------------------------------------------
# Word count
# ---------------------------------------------------------------------------

class TestWordCount(unittest.TestCase):
    """Test _word_count."""

    def test_basic(self):
        self.assertEqual(_word_count("hello world foo"), 3)

    def test_empty(self):
        self.assertEqual(_word_count(""), 0)

    def test_single_word(self):
        self.assertEqual(_word_count("hello"), 1)


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------

class TestJaccardSimilarity(unittest.TestCase):
    """Test _jaccard_similarity."""

    def test_identical_sets(self):
        s = {"a", "b", "c"}
        self.assertAlmostEqual(_jaccard_similarity(s, s), 1.0)

    def test_disjoint_sets(self):
        self.assertAlmostEqual(_jaccard_similarity({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        # intersection = 2, union = 4
        self.assertAlmostEqual(_jaccard_similarity(a, b), 0.5)

    def test_empty_set(self):
        self.assertAlmostEqual(_jaccard_similarity(set(), {"a"}), 0.0)

    def test_both_empty(self):
        self.assertAlmostEqual(_jaccard_similarity(set(), set()), 0.0)


# ---------------------------------------------------------------------------
# Transition counting
# ---------------------------------------------------------------------------

class TestCountTransitions(unittest.TestCase):
    """Test count_transitions."""

    def test_single_transition(self):
        self.assertGreaterEqual(count_transitions("However, the result was clear."), 1)

    def test_multiple_transitions(self):
        text = "However, the cat sat. Therefore, the dog ran. Moreover, the bird flew."
        self.assertGreaterEqual(count_transitions(text), 3)

    def test_no_transitions(self):
        text = "The cat sat on the mat. The dog ran in the park."
        self.assertEqual(count_transitions(text), 0)

    def test_case_insensitive(self):
        self.assertGreaterEqual(count_transitions("however the result"), 1)
        self.assertGreaterEqual(count_transitions("HOWEVER the result"), 1)

    def test_multi_word_phrase(self):
        text = "In contrast, the results were different."
        self.assertGreaterEqual(count_transitions(text), 1)

    def test_for_example(self):
        text = "For example, consider the case of recursion."
        self.assertGreaterEqual(count_transitions(text), 1)


# ---------------------------------------------------------------------------
# Transition density
# ---------------------------------------------------------------------------

class TestTransitionDensity(unittest.TestCase):
    """Test compute_transition_density."""

    def test_well_connected_higher_than_disjointed(self):
        connected = compute_transition_density(WELL_CONNECTED)
        disconnected = compute_transition_density(DISJOINTED)
        self.assertGreater(connected, disconnected)

    def test_empty_text(self):
        self.assertEqual(compute_transition_density(""), 0.0)

    def test_no_transitions(self):
        self.assertEqual(compute_transition_density("Cats sleep all day. Dogs play all night."), 0.0)

    def test_normalized_cap(self):
        # Even with extreme transitions, should not exceed 1.0
        text = " ".join(["However therefore moreover furthermore consequently"] * 10)
        self.assertLessEqual(compute_transition_density(text), 1.0)


# ---------------------------------------------------------------------------
# Referential continuity
# ---------------------------------------------------------------------------

class TestReferentialContinuity(unittest.TestCase):
    """Test compute_referential_continuity."""

    def test_pronoun_heavy(self):
        text = "The cat appeared. It sat down. Then it slept. It dreamed of fish."
        result = compute_referential_continuity(text)
        self.assertGreater(result, 0.5)

    def test_no_references(self):
        result = compute_referential_continuity(DISJOINTED)
        # Disjointed text has low referential continuity
        self.assertLess(result, 0.5)

    def test_demonstrative(self):
        text = "The project launched. This initiative changed everything. That decision proved wise."
        result = compute_referential_continuity(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        self.assertEqual(compute_referential_continuity(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_referential_continuity("One sentence only."), 0.0)

    def test_well_connected_vs_disjointed(self):
        connected = compute_referential_continuity(WELL_CONNECTED)
        disconnected = compute_referential_continuity(DISJOINTED)
        self.assertGreater(connected, disconnected)


class TestSentenceHasBackref(unittest.TestCase):
    """Test _sentence_has_backref."""

    def test_pronoun_it(self):
        self.assertTrue(_sentence_has_backref("It was a good day."))

    def test_demonstrative_this(self):
        self.assertTrue(_sentence_has_backref("This approach works well."))

    def test_demonstrative_that(self):
        self.assertTrue(_sentence_has_backref("That idea changed everything."))

    def test_the_former(self):
        self.assertTrue(_sentence_has_backref("The former option is better."))

    def test_no_backref(self):
        self.assertFalse(_sentence_has_backref("Cats sleep all day."))

    def test_possessive_their(self):
        self.assertTrue(_sentence_has_backref("Their results were impressive."))


# ---------------------------------------------------------------------------
# Lexical chain strength
# ---------------------------------------------------------------------------

class TestLexicalChainStrength(unittest.TestCase):
    """Test compute_lexical_chain_strength."""

    def test_thematic_text(self):
        # Sentences about the same topic should have higher lexical overlap
        text = (
            "The algorithm processes input data quickly. "
            "The algorithm processes output data efficiently. "
            "The algorithm processes error data carefully."
        )
        result = compute_lexical_chain_strength(text)
        self.assertGreater(result, 0.2)

    def test_disjointed_text(self):
        result = compute_lexical_chain_strength(DISJOINTED)
        self.assertLess(result, 0.3)

    def test_empty_text(self):
        self.assertEqual(compute_lexical_chain_strength(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_lexical_chain_strength("One sentence."), 0.0)

    def test_returns_float(self):
        result = compute_lexical_chain_strength(WELL_CONNECTED)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# Structural parallelism
# ---------------------------------------------------------------------------

class TestStructuralParallelism(unittest.TestCase):
    """Test compute_structural_parallelism."""

    def test_parallel_openings(self):
        text = (
            "He walked to the store. "
            "He bought some bread. "
            "He returned home slowly. "
            "He sat at the table."
        )
        result = compute_structural_parallelism(text)
        self.assertGreater(result, 0.5)

    def test_varied_openings(self):
        text = (
            "However the day was long. "
            "The cat sat on the mat. "
            "In the morning she walked carefully. "
            "They arrived at noon precisely."
        )
        result = compute_structural_parallelism(text)
        # All different opening patterns → low parallelism
        self.assertLessEqual(result, 0.5)

    def test_empty_text(self):
        self.assertEqual(compute_structural_parallelism(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(compute_structural_parallelism("One."), 0.0)


class TestParallelismScore(unittest.TestCase):
    """Test _parallelism_score."""

    def test_ideal_parallelism(self):
        # 0.5 is ideal
        self.assertAlmostEqual(_parallelism_score(0.5), 1.0)

    def test_zero_parallelism(self):
        self.assertAlmostEqual(_parallelism_score(0.0), 0.0)

    def test_full_parallelism(self):
        self.assertAlmostEqual(_parallelism_score(1.0), 0.0)

    def test_quarter_parallelism(self):
        self.assertAlmostEqual(_parallelism_score(0.25), 0.5)

    def test_three_quarter(self):
        self.assertAlmostEqual(_parallelism_score(0.75), 0.5)


# ---------------------------------------------------------------------------
# Opening classification
# ---------------------------------------------------------------------------

class TestClassifyOpening(unittest.TestCase):
    """Test _classify_opening."""

    def test_connective(self):
        result = _classify_opening("However the day was long.")
        self.assertEqual(result, 0)

    def test_prepositional(self):
        result = _classify_opening("In the morning she walked.")
        self.assertEqual(result, 1)

    def test_subordinate(self):
        result = _classify_opening("If the rain stops we will go.")
        self.assertEqual(result, 2)

    def test_pronoun_first(self):
        result = _classify_opening("They arrived at noon.")
        self.assertEqual(result, 3)

    def test_demonstrative_first(self):
        result = _classify_opening("This approach works well.")
        self.assertEqual(result, 4)

    def test_subject_first(self):
        result = _classify_opening("The cat sat on the mat.")
        self.assertEqual(result, 5)

    def test_unknown_returns_negative(self):
        result = _classify_opening("42 is the answer.")
        self.assertEqual(result, -1)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """Test _classify."""

    def test_seamless(self):
        self.assertEqual(_classify(0.80), "seamless")
        self.assertEqual(_classify(0.75), "seamless")

    def test_connected(self):
        self.assertEqual(_classify(0.60), "connected")
        self.assertEqual(_classify(0.74), "connected")

    def test_choppy(self):
        self.assertEqual(_classify(0.45), "choppy")
        self.assertEqual(_classify(0.59), "choppy")

    def test_fragmented(self):
        self.assertEqual(_classify(0.30), "fragmented")
        self.assertEqual(_classify(0.44), "fragmented")

    def test_disjointed(self):
        self.assertEqual(_classify(0.29), "disjointed")
        self.assertEqual(_classify(0.0), "disjointed")


# ---------------------------------------------------------------------------
# Composite metrics
# ---------------------------------------------------------------------------

class TestComputeCohesionMetrics(unittest.TestCase):
    """Test compute_cohesion_metrics."""

    def test_well_connected_scores(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        self.assertGreater(metrics["cohesion_index"], 0.3)
        self.assertIn(metrics["cohesion_class"],
                       ["seamless", "connected", "choppy", "fragmented", "disjointed"])

    def test_disjointed_scores(self):
        metrics = compute_cohesion_metrics(DISJOINTED)
        self.assertLess(metrics["cohesion_index"], 0.5)

    def test_well_connected_beats_disjointed(self):
        connected = compute_cohesion_metrics(WELL_CONNECTED)
        disjointed = compute_cohesion_metrics(DISJOINTED)
        self.assertGreater(connected["cohesion_index"], disjointed["cohesion_index"])

    def test_empty_text(self):
        metrics = compute_cohesion_metrics("")
        self.assertEqual(metrics["cohesion_index"], 0.0)
        self.assertEqual(metrics["cohesion_class"], "disjointed")

    def test_single_sentence(self):
        metrics = compute_cohesion_metrics("Just one sentence.")
        self.assertEqual(metrics["cohesion_index"], 0.0)

    def test_all_keys_present(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        expected_keys = {
            "transition_density", "referential_continuity",
            "lexical_chain_strength", "structural_parallelism",
            "parallelism_score", "cohesion_index", "cohesion_class",
            "sentence_count", "word_count",
        }
        self.assertEqual(set(metrics.keys()), expected_keys)

    def test_sentence_count(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        self.assertGreaterEqual(metrics["sentence_count"], 5)

    def test_word_count(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        self.assertGreater(metrics["word_count"], 20)

    def test_mixed_text(self):
        metrics = compute_cohesion_metrics(MIXED_TEXT)
        self.assertGreater(metrics["cohesion_index"], 0.05)

    def test_metrics_are_rounded(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        for key in ["transition_density", "referential_continuity",
                     "lexical_chain_strength", "cohesion_index"]:
            # Check that values have at most 4 decimal places
            val = metrics[key]
            self.assertAlmostEqual(val, round(val, 4))


# ---------------------------------------------------------------------------
# Empty metrics
# ---------------------------------------------------------------------------

class TestEmptyMetrics(unittest.TestCase):
    """Test _empty_metrics."""

    def test_all_zero(self):
        m = _empty_metrics()
        self.assertEqual(m["cohesion_index"], 0.0)
        self.assertEqual(m["transition_density"], 0.0)
        self.assertEqual(m["referential_continuity"], 0.0)
        self.assertEqual(m["lexical_chain_strength"], 0.0)
        self.assertEqual(m["structural_parallelism"], 0.0)
        self.assertEqual(m["sentence_count"], 0)
        self.assertEqual(m["word_count"], 0)

    def test_class_is_disjointed(self):
        m = _empty_metrics()
        self.assertEqual(m["cohesion_class"], "disjointed")


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestComputeCohesionTrend(unittest.TestCase):
    """Test compute_cohesion_trend."""

    def test_insufficient_data(self):
        result = compute_cohesion_trend("Short text.", segments=4)
        self.assertEqual(result["trend"], "insufficient_data")

    def test_returns_segment_scores(self):
        long_text = (
            "The project began with careful planning. "
            "However, the initial timeline was too aggressive. "
            "Therefore, the team extended the deadline. "
            "This extension allowed for more thorough testing. "
            "Moreover, the additional time revealed hidden bugs. "
            "Consequently, the release was delayed by two weeks. "
            "Furthermore, the delay improved overall quality. "
            "As a result, customer satisfaction increased. "
            "Nevertheless, the team learned important lessons. "
            "In the end, the project was considered a success. "
            "The retrospective identified three key improvements. "
            "However, not all suggestions were implemented immediately. "
            "Therefore, a follow-up sprint was planned. "
            "This sprint focused on technical debt reduction. "
            "Moreover, the team adopted new coding standards. "
            "Consequently, future projects benefited from these changes."
        )
        result = compute_cohesion_trend(long_text, segments=3)
        self.assertIn(result["trend"], ["improving", "stable", "declining", "insufficient_data"])
        self.assertEqual(len(result["segment_scores"]), 3)

    def test_first_second_half(self):
        long_text = ". ".join([
            "The first sentence of the paragraph introduces a topic",
            "However this second sentence adds a contrasting view",
            "Therefore the third sentence draws a conclusion",
            "Moreover the fourth sentence extends the argument further",
            "Furthermore the fifth sentence provides additional evidence",
            "Consequently the sixth sentence wraps up the discussion nicely"
        ]) + "."
        result = compute_cohesion_trend(long_text, segments=2)
        self.assertIn("first_half_avg", result)
        self.assertIn("second_half_avg", result)

    def test_empty_text(self):
        result = compute_cohesion_trend("", segments=4)
        self.assertEqual(result["trend"], "insufficient_data")


class TestClassifyTrend(unittest.TestCase):
    """Test classify_trend."""

    def test_improving(self):
        first = {"cohesion_index": 0.30}
        second = {"cohesion_index": 0.50}
        self.assertEqual(classify_trend(first, second), "improving")

    def test_declining(self):
        first = {"cohesion_index": 0.60}
        second = {"cohesion_index": 0.40}
        self.assertEqual(classify_trend(first, second), "declining")

    def test_stable(self):
        first = {"cohesion_index": 0.50}
        second = {"cohesion_index": 0.52}
        self.assertEqual(classify_trend(first, second), "stable")

    def test_small_delta_stable(self):
        first = {"cohesion_index": 0.50}
        second = {"cohesion_index": 0.54}
        # delta = 0.04, not > 0.05, so stable
        self.assertEqual(classify_trend(first, second), "stable")

    def test_missing_key(self):
        first = {}
        second = {}
        self.assertEqual(classify_trend(first, second), "stable")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormatCohesionReport(unittest.TestCase):
    """Test format_cohesion_report."""

    def test_contains_class(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        report = format_cohesion_report(metrics)
        self.assertIn(metrics["cohesion_class"].upper(), report)

    def test_contains_index(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        report = format_cohesion_report(metrics)
        self.assertIn(f"{metrics['cohesion_index']:.2f}", report)

    def test_contains_all_signals(self):
        metrics = compute_cohesion_metrics(MIXED_TEXT)
        report = format_cohesion_report(metrics)
        self.assertIn("Transition density", report)
        self.assertIn("Referential continuity", report)
        self.assertIn("Lexical chain strength", report)
        self.assertIn("Structural parallelism", report)

    def test_multiline(self):
        metrics = compute_cohesion_metrics(WELL_CONNECTED)
        report = format_cohesion_report(metrics)
        lines = report.split("\n")
        self.assertGreaterEqual(len(lines), 5)


# ---------------------------------------------------------------------------
# Stroke analysis
# ---------------------------------------------------------------------------

class TestAnalyzeStrokes(unittest.TestCase):
    """Test analyze_strokes."""

    def test_nonexistent_file(self):
        results = analyze_strokes("/tmp/nonexistent_strokes_12345.jsonl")
        self.assertEqual(results, [])

    def test_with_temp_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            strokes = [
                {"id": "1", "type": "note", "content": WELL_CONNECTED},
                {"id": "2", "type": "thought", "content": DISJOINTED},
                {"id": "3", "type": "devlog", "content": MIXED_TEXT},
            ]
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            tmp_path = f.name

        results = analyze_strokes(tmp_path, last_n=10)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["stroke_type"], "note")
        self.assertEqual(results[1]["stroke_type"], "thought")
        Path(tmp_path).unlink()

    def test_last_n_limit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(20):
                f.write(json.dumps({"id": str(i), "type": "note",
                                     "content": WELL_CONNECTED}) + "\n")
            tmp_path = f.name

        results = analyze_strokes(tmp_path, last_n=5)
        self.assertEqual(len(results), 5)
        Path(tmp_path).unlink()

    def test_skips_empty_content(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"id": "1", "type": "note", "content": ""}) + "\n")
            f.write(json.dumps({"id": "2", "type": "note", "content": WELL_CONNECTED}) + "\n")
            tmp_path = f.name

        results = analyze_strokes(tmp_path, last_n=10)
        self.assertEqual(len(results), 1)
        Path(tmp_path).unlink()

    def test_skips_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not valid json\n")
            f.write(json.dumps({"id": "2", "type": "note", "content": WELL_CONNECTED}) + "\n")
            tmp_path = f.name

        results = analyze_strokes(tmp_path, last_n=10)
        self.assertEqual(len(results), 1)
        Path(tmp_path).unlink()


# ---------------------------------------------------------------------------
# Constants integrity
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """Test module-level constants."""

    def test_transition_phrases_are_compiled(self):
        for p in TRANSITION_PHRASES:
            self.assertIsInstance(p, type(re.compile("")))

    def test_backref_patterns_are_compiled(self):
        for p in BACKREF_PATTERNS:
            self.assertIsInstance(p, type(re.compile("")))

    def test_function_words_is_set(self):
        self.assertIsInstance(FUNCTION_WORDS, set)

    def test_function_words_are_lowercase(self):
        for word in FUNCTION_WORDS:
            self.assertEqual(word, word.lower())

    def test_transition_count(self):
        self.assertGreater(len(TRANSITION_PHRASES), 20)

    def test_backref_count(self):
        self.assertGreater(len(BACKREF_PATTERNS), 10)


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and integration scenarios."""

    def test_very_long_text(self):
        long_text = (WELL_CONNECTED + " ") * 50
        metrics = compute_cohesion_metrics(long_text)
        self.assertGreater(metrics["cohesion_index"], 0.0)
        self.assertGreater(metrics["word_count"], 1000)

    def test_repeated_sentence(self):
        repeated = "The cat sat on the mat. " * 20
        metrics = compute_cohesion_metrics(repeated)
        # Repeated text has high lexical chain but low transitions
        self.assertGreater(metrics["lexical_chain_strength"], 0.0)

    def test_all_transitions(self):
        text = ("However therefore moreover furthermore consequently thus hence. "
                "The quick brown fox jumps over the lazy dog nearby.")
        metrics = compute_cohesion_metrics(text)
        self.assertGreater(metrics["transition_density"], 0.5)

    def test_unicode_text(self):
        text = "The café served espresso. However, the crème brûlée was better."
        metrics = compute_cohesion_metrics(text)
        self.assertIsInstance(metrics["cohesion_index"], float)

    def test_newlines_preserved_in_split(self):
        text = "First sentence here.\nSecond sentence follows.\nThird sentence concludes."
        sents = _split_sentences(text)
        self.assertGreaterEqual(len(sents), 2)

    def test_cohesion_index_bounded(self):
        for text in [WELL_CONNECTED, DISJOINTED, MIXED_TEXT, SHORT_TEXT]:
            metrics = compute_cohesion_metrics(text)
            self.assertGreaterEqual(metrics["cohesion_index"], 0.0)
            self.assertLessEqual(metrics["cohesion_index"], 1.0)


# ---------------------------------------------------------------------------
# Orthogonality checks
# ---------------------------------------------------------------------------

class TestOrthogonality(unittest.TestCase):
    """Verify cohesion is distinct from other metrics conceptually."""

    def test_high_cohesion_does_not_imply_specificity(self):
        # Text with high cohesion (good transitions) but vague content
        vague_connected = (
            "Something happened today. "
            "However, it was hard to describe. "
            "Therefore, we moved on. "
            "This decision seemed reasonable. "
            "Moreover, everyone agreed. "
            "Consequently, nothing more was said."
        )
        metrics = compute_cohesion_metrics(vague_connected)
        # Cohesion should be reasonable despite vague content
        self.assertGreater(metrics["cohesion_index"], 0.2)

    def test_specific_text_can_have_low_cohesion(self):
        # Very specific facts, no connections
        specific_disjointed = (
            "Mount Everest is 8,849 meters tall. "
            "The Eiffel Tower was built in 1889. "
            "Water boils at 100 degrees Celsius. "
            "Tokyo has a population of 13.96 million. "
            "The speed of light is 299,792,458 meters per second."
        )
        metrics = compute_cohesion_metrics(specific_disjointed)
        # Low cohesion despite high specificity of content
        self.assertLess(metrics["cohesion_index"], 0.5)


if __name__ == "__main__":
    unittest.main()
