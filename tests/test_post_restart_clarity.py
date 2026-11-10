#!/usr/bin/env python3
"""Tests for post_restart_clarity — 48 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.post_restart_clarity import (  # noqa: E402
    ClarityReport,
    _bigrams,
    _compute_score,
    _jaccard,
    _score_to_verdict,
    _tokenize,
    _vocabulary_richness,
    clarity_over_time,
    clarity_report,
    signal_content_overlap,
    signal_length_variance,
    signal_repetition_rate,
    signal_topic_shift,
    signal_vocabulary_delta,
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

class TestTokenize(unittest.TestCase):
    """Tokenisation and stop-word removal."""

    def test_basic_tokenize(self):
        tokens = _tokenize("the repo accumulates files")
        self.assertEqual(tokens, ["repo", "accumulates", "files"])

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_single_char_words_dropped(self):
        tokens = _tokenize("I am a test")
        self.assertNotIn("i", tokens)
        self.assertNotIn("a", tokens)

    def test_punctuation_stripped(self):
        tokens = _tokenize("hello, world! it's fine.")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("it's", tokens)
        self.assertIn("fine", tokens)

    def test_case_insensitive(self):
        tokens = _tokenize("HELLO World HELLO")
        self.assertEqual(tokens, ["hello", "world", "hello"])

    def test_numbers_dropped(self):
        tokens = _tokenize("stroke 42 in the log")
        self.assertNotIn("42", tokens)
        self.assertIn("stroke", tokens)

    def test_all_stop_words(self):
        self.assertEqual(_tokenize("the a an is are was"), [])


class TestBigrams(unittest.TestCase):
    """Bigram generation."""

    def test_basic_bigrams(self):
        result = _bigrams(["a", "b", "c"])
        self.assertEqual(result, ["a b", "b c"])

    def test_single_token_no_bigrams(self):
        self.assertEqual(_bigrams(["only"]), [])

    def test_empty_input(self):
        self.assertEqual(_bigrams([]), [])

    def test_duplicate_bigrams(self):
        result = _bigrams(["a", "b", "a", "b"])
        self.assertEqual(result, ["a b", "b a", "a b"])


class TestVocabularyRichness(unittest.TestCase):
    """Type-token ratio calculation."""

    def test_all_unique(self):
        self.assertAlmostEqual(_vocabulary_richness(["a", "b", "c"]), 1.0)

    def test_all_same(self):
        self.assertAlmostEqual(_vocabulary_richness(["x", "x", "x"]), 1/3)

    def test_empty(self):
        self.assertAlmostEqual(_vocabulary_richness([]), 0.0)

    def test_half_unique(self):
        self.assertAlmostEqual(_vocabulary_richness(["a", "b", "a", "b"]), 0.5)


class TestJaccard(unittest.TestCase):
    """Jaccard similarity."""

    def test_identical_sets(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_sets(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial_overlap(self):
        self.assertAlmostEqual(_jaccard({"a", "b", "c"}, {"b", "c", "d"}), 0.5)

    def test_both_empty(self):
        self.assertAlmostEqual(_jaccard(set(), set()), 1.0)

    def test_one_empty(self):
        self.assertAlmostEqual(_jaccard({"a"}, set()), 0.0)


# ---------------------------------------------------------------------------
# Signal: vocabulary_delta
# ---------------------------------------------------------------------------

class TestSignalVocabularyDelta(unittest.TestCase):
    """Vocabulary richness change between pre and post."""

    def test_post_richer(self):
        pre = ["a", "a", "a", "b"]  # 2/4 = 0.5
        post = ["a", "b", "c", "d"]  # 4/4 = 1.0
        delta = signal_vocabulary_delta(pre, post)
        self.assertGreater(delta, 0)

    def test_post_poorer(self):
        pre = ["a", "b", "c", "d"]  # 1.0
        post = ["a", "a", "a", "b"]  # 0.5
        delta = signal_vocabulary_delta(pre, post)
        self.assertLess(delta, 0)

    def test_equal_richness(self):
        pre = ["a", "b", "c"]
        post = ["d", "e", "f"]
        delta = signal_vocabulary_delta(pre, post)
        self.assertAlmostEqual(delta, 0.0)

    def test_both_empty(self):
        self.assertAlmostEqual(signal_vocabulary_delta([], []), 0.0)


# ---------------------------------------------------------------------------
# Signal: content_overlap
# ---------------------------------------------------------------------------

class TestSignalContentOverlap(unittest.TestCase):
    """Content overlap via bigram Jaccard (inverted)."""

    def test_completely_different(self):
        pre = ["alpha", "beta", "gamma"]
        post = ["delta", "epsilon", "zeta"]
        score = signal_content_overlap(pre, post)
        self.assertAlmostEqual(score, 1.0)

    def test_identical_content(self):
        text = ["alpha", "beta", "gamma", "delta"]
        score = signal_content_overlap(text, text)
        self.assertAlmostEqual(score, 0.0)

    def test_partial_overlap(self):
        pre = ["alpha", "beta", "gamma"]
        post = ["beta", "gamma", "delta"]
        score = signal_content_overlap(pre, post)
        self.assertGreater(score, 0)
        self.assertLess(score, 1)

    def test_empty_inputs(self):
        self.assertAlmostEqual(signal_content_overlap([], []), 0.0)


# ---------------------------------------------------------------------------
# Signal: length_variance
# ---------------------------------------------------------------------------

class TestSignalLengthVariance(unittest.TestCase):
    """Sentence length variation."""

    def test_uniform_lengths(self):
        texts = ["word word word", "word word word", "word word word"]
        self.assertAlmostEqual(signal_length_variance(texts), 0.0)

    def test_varied_lengths(self):
        texts = ["short", "a much longer sentence here", "mid length"]
        score = signal_length_variance(texts)
        self.assertGreater(score, 0)

    def test_single_text(self):
        self.assertAlmostEqual(signal_length_variance(["only one"]), 0.0)

    def test_empty_list(self):
        self.assertAlmostEqual(signal_length_variance([]), 0.0)

    def test_capped_at_one(self):
        # extreme variation
        texts = ["one", " ".join(["word"] * 100), "two"]
        score = signal_length_variance(texts)
        self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# Signal: topic_shift
# ---------------------------------------------------------------------------

class TestSignalTopicShift(unittest.TestCase):
    """Word-set distance between pre and post."""

    def test_completely_different_topics(self):
        pre = ["alpha", "beta"]
        post = ["gamma", "delta"]
        self.assertAlmostEqual(signal_topic_shift(pre, post), 1.0)

    def test_same_topics(self):
        pre = ["alpha", "beta", "gamma"]
        post = ["alpha", "beta", "gamma"]
        self.assertAlmostEqual(signal_topic_shift(pre, post), 0.0)

    def test_empty_inputs(self):
        self.assertAlmostEqual(signal_topic_shift([], []), 0.0)


# ---------------------------------------------------------------------------
# Signal: repetition_rate
# ---------------------------------------------------------------------------

class TestSignalRepetitionRate(unittest.TestCase):
    """Fraction of post-restart texts echoing pre-stall."""

    def test_no_repetition(self):
        pre = ["the quick brown fox jumps over the lazy dog"]
        post = ["completely different words about other topics"]
        rate = signal_repetition_rate(pre, post)
        self.assertAlmostEqual(rate, 0.0)

    def test_full_repetition(self):
        text = "the quick brown fox jumps over the lazy dog near the river"
        pre = [text]
        post = [text]
        rate = signal_repetition_rate(pre, post)
        self.assertAlmostEqual(rate, 1.0)

    def test_partial_repetition(self):
        pre = ["alpha beta gamma delta epsilon zeta eta theta"]
        post = [
            "alpha beta gamma delta epsilon zeta eta theta",  # echo
            "completely different words about something else",  # new
        ]
        rate = signal_repetition_rate(pre, post)
        self.assertAlmostEqual(rate, 0.5)

    def test_empty_post(self):
        self.assertAlmostEqual(signal_repetition_rate(["pre text"], []), 0.0)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

class TestComputeScore(unittest.TestCase):
    """Score composition."""

    def test_max_score(self):
        score = _compute_score(
            vocab_delta=1.0,
            content_overlap=1.0,
            post_length_var=1.0,
            topic_shift=1.0,
            repetition_rate=0.0,
        )
        self.assertEqual(score, 100)

    def test_min_score(self):
        score = _compute_score(
            vocab_delta=-1.0,
            content_overlap=0.0,
            post_length_var=0.0,
            topic_shift=0.0,
            repetition_rate=1.0,
        )
        self.assertEqual(score, 0)

    def test_mid_score(self):
        score = _compute_score(
            vocab_delta=0.0,
            content_overlap=0.5,
            post_length_var=0.5,
            topic_shift=0.5,
            repetition_rate=0.5,
        )
        self.assertGreater(score, 20)
        self.assertLess(score, 80)

    def test_clamped_above_100(self):
        score = _compute_score(2.0, 2.0, 2.0, 2.0, -1.0)
        self.assertLessEqual(score, 100)

    def test_clamped_below_zero(self):
        score = _compute_score(-2.0, -2.0, -2.0, -2.0, 2.0)
        self.assertGreaterEqual(score, 0)


class TestScoreToVerdict(unittest.TestCase):
    """Verdict mapping."""

    def test_clarified(self):
        self.assertEqual(_score_to_verdict(80), "clarified")
        self.assertEqual(_score_to_verdict(100), "clarified")

    def test_refreshed(self):
        self.assertEqual(_score_to_verdict(60), "refreshed")
        self.assertEqual(_score_to_verdict(79), "refreshed")

    def test_unchanged(self):
        self.assertEqual(_score_to_verdict(40), "unchanged")
        self.assertEqual(_score_to_verdict(59), "unchanged")

    def test_foggy(self):
        self.assertEqual(_score_to_verdict(20), "foggy")
        self.assertEqual(_score_to_verdict(39), "foggy")

    def test_stuck(self):
        self.assertEqual(_score_to_verdict(0), "stuck")
        self.assertEqual(_score_to_verdict(19), "stuck")


# ---------------------------------------------------------------------------
# Clarity report
# ---------------------------------------------------------------------------

class TestClarityReport(unittest.TestCase):
    """Full clarity analysis."""

    def test_fresh_restart(self):
        pre = [
            "the repo accumulates files like a landfill with readme",
            "the repo accumulates files like a landfill with readme",
            "the repo accumulates files like a landfill with readme",
        ]
        post = [
            "naming things is the hardest part of software design",
            "every architecture is choosing which coupling to live with",
            "commit history documents what actually happened not what was planned",
        ]
        report = clarity_report(pre, post)
        self.assertIsInstance(report, ClarityReport)
        self.assertGreater(report.score, 40)
        self.assertIn(report.verdict, ("clarified", "refreshed", "unchanged"))

    def test_stuck_restart(self):
        text = "the repo accumulates files like a landfill with readme"
        pre = [text] * 3
        post = [text] * 3
        report = clarity_report(pre, post)
        self.assertLessEqual(report.score, 30)

    def test_to_dict(self):
        pre = ["alpha beta gamma"]
        post = ["delta epsilon zeta"]
        report = clarity_report(pre, post)
        d = report.to_dict()
        self.assertIn("score", d)
        self.assertIn("verdict", d)
        self.assertIn("signals", d)
        self.assertIn("vocabulary_delta", d["signals"])

    def test_signals_present(self):
        report = clarity_report(["hello world"], ["goodbye moon"])
        expected_keys = {"vocabulary_delta", "content_overlap", "length_variance",
                         "topic_shift", "repetition_rate"}
        self.assertEqual(set(report.signals.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Clarity over time
# ---------------------------------------------------------------------------

class TestClarityOverTime(unittest.TestCase):
    """Track clarity across multiple restarts."""

    def test_single_restart(self):
        texts = [
            "alpha beta gamma delta",
            "alpha beta gamma delta",
            "alpha beta gamma delta",
            "fresh new content about different topics",
            "exploring ideas around software architecture patterns",
            "the beauty of minimal and clean code design",
        ]
        reports = clarity_over_time(texts, restart_indices=[3], window=3)
        self.assertEqual(len(reports), 1)
        self.assertIsInstance(reports[0], ClarityReport)

    def test_multiple_restarts(self):
        texts = ["text " + str(i) for i in range(20)]
        reports = clarity_over_time(texts, restart_indices=[5, 15], window=3)
        self.assertEqual(len(reports), 2)

    def test_restart_at_start_skipped(self):
        texts = ["text " + str(i) for i in range(10)]
        reports = clarity_over_time(texts, restart_indices=[0], window=3)
        # No pre-strokes for index 0, so report list should be empty
        self.assertEqual(len(reports), 0)

    def test_empty_indices(self):
        texts = ["alpha beta gamma"] * 5
        reports = clarity_over_time(texts, restart_indices=[], window=3)
        self.assertEqual(len(reports), 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Boundary conditions and unusual inputs."""

    def test_single_word_strokes(self):
        report = clarity_report(["hello"], ["world"])
        self.assertIsInstance(report.score, int)

    def test_very_long_strokes(self):
        pre = [" ".join(["alpha"] * 1000)]
        post = [" ".join(["beta"] * 1000)]
        report = clarity_report(pre, post)
        self.assertGreater(report.score, 50)

    def test_mixed_languages(self):
        pre = ["this is english text about programming"]
        post = ["completely different words and new ideas"]
        report = clarity_report(pre, post)
        self.assertIsInstance(report.score, int)

    def test_special_characters(self):
        pre = ["hello!!! @#$ world???"]
        post = ["fresh... new--- content!!!"]
        report = clarity_report(pre, post)
        self.assertIsInstance(report.score, int)


if __name__ == "__main__":
    unittest.main()
